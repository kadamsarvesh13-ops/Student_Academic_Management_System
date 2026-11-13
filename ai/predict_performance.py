"""Apply the trained model to current students."""

from __future__ import annotations

import joblib
import pandas as pd

from ai.train_model import FEATURES, model_path, train_model
from database.db import df_query, query
from modules.attendance import overall_attendance
from modules.marks_management import course_results_df, max_marks

INSUFFICIENT = "Insufficient data"


def load_bundle(auto_train: bool = True) -> dict | None:
    path = model_path()
    if not path.exists():
        if not auto_train:
            return None
        try:
            train_model()
        except ValueError:
            return None
    # The file is produced by train_model() on this server; do not load untrusted models.
    return joblib.load(path)


def student_features(student_id: str) -> dict:
    """Compute the five model inputs from live records (None if unavailable)."""
    limits = max_marks()
    res = course_results_df(student_id)
    internal = (res["internal"] / limits["Internal"] * 100).dropna()
    prac = res[res["has_practical"] == 1]
    practical = (prac["practical"] / limits["Practical"] * 100).dropna()
    sub = df_query(
        "SELECT COUNT(a.assignment_id) AS total, COALESCE(SUM(s.submitted),0) AS done "
        "FROM enrollments e JOIN assignments a ON a.course_id=e.course_id "
        "LEFT JOIN submissions s ON s.assignment_id=a.assignment_id AND s.student_id=e.student_id "
        "WHERE e.student_id=?", (student_id,)).iloc[0]
    prev = query("SELECT previous_percentage FROM students WHERE student_id=?", (student_id,))
    return {
        "attendance_pct": overall_attendance(student_id),
        "internal_pct": round(float(internal.mean()), 2) if len(internal) else None,
        "previous_pct": prev[0]["previous_percentage"] if prev else None,
        "assignment_pct": round(float(sub["done"] / sub["total"] * 100), 2) if sub["total"] else None,
        "practical_pct": round(float(practical.mean()), 2) if len(practical) else None,
    }


def predict_student(student_id: str, bundle: dict | None = None) -> dict:
    """Predict one student. Needs attendance and internal marks at minimum;
    other missing inputs are filled with the training-data median."""
    bundle = bundle or load_bundle()
    feats = student_features(student_id)
    if bundle is None:
        return {"student_id": student_id, "prediction": INSUFFICIENT, "confidence": None,
                "features": feats, "note": "Model not trained yet."}
    if feats["attendance_pct"] is None or feats["internal_pct"] is None:
        return {"student_id": student_id, "prediction": INSUFFICIENT, "confidence": None,
                "features": feats, "note": "Needs recorded attendance and internal marks."}
    filled = {k: (feats[k] if feats[k] is not None else bundle["medians"][k]) for k in FEATURES}
    X = pd.DataFrame([filled], columns=FEATURES)
    model = bundle["model"]
    proba = model.predict_proba(X)[0]
    best = int(proba.argmax())
    return {"student_id": student_id, "prediction": str(model.classes_[best]),
            "confidence": round(float(proba[best]) * 100, 1), "features": feats, "note": ""}


def predict_all(department: str | None = None, faculty_id: str | None = None) -> pd.DataFrame:
    """Predictions for every student (optionally limited to a faculty's courses)."""
    sql = "SELECT DISTINCT s.student_id, s.name, s.department, s.semester FROM students s"
    params: tuple = ()
    if faculty_id:
        sql += (" JOIN enrollments e ON e.student_id=s.student_id JOIN courses c "
                "ON c.course_id=e.course_id WHERE c.faculty_id=?")
        params = (faculty_id,)
    students = df_query(sql + " ORDER BY s.student_id", params)
    if department:
        students = students[students["department"] == department]
    bundle = load_bundle()
    rows = []
    for s in students.itertuples():
        p = predict_student(s.student_id, bundle)
        f = p["features"]
        rows.append({"student_id": s.student_id, "name": s.name, "department": s.department,
                     "semester": s.semester, "attendance_pct": f["attendance_pct"],
                     "internal_pct": f["internal_pct"], "previous_pct": f["previous_pct"],
                     "assignment_pct": f["assignment_pct"], "practical_pct": f["practical_pct"],
                     "prediction": p["prediction"], "confidence": p["confidence"]})
    return pd.DataFrame(rows)
