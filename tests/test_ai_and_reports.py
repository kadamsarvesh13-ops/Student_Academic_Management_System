"""ML model, chatbot privacy, recommendations and report exports."""

import io

import numpy as np
import pytest
from openpyxl import load_workbook

from ai.chatbot import answer
from ai.predict_performance import INSUFFICIENT, predict_all, predict_student
from ai.train_model import FEATURES, MIN_RECORDS, train_model
from database.db import transaction
from modules.attendance import mark_attendance
from modules.marks_management import save_marks, semester_result
from modules.performance import recommendations
from modules.reports import attendance_report, course_report, department_report, marks_report
from utils.excel_export import dfs_to_excel
from utils.pdf_generator import result_sheet_pdf, table_pdf


def _history(n=300, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(n):
        base = rng.uniform(30, 95)
        f = np.clip(base + rng.normal(0, 6, 5), 0, 100)
        score = f.mean()
        outcome = "At Risk" if score < 55 else ("Good" if score >= 75 else "Average")
        rows.append((*[float(x) for x in f], outcome))
    with transaction() as conn:
        conn.executemany("INSERT INTO historical_records(attendance_pct, internal_pct, previous_pct, "
                         "assignment_pct, practical_pct, outcome) VALUES(?,?,?,?,?,?)", rows)


def _record_for(world, sid, att_present, marks):
    import datetime as dt
    d = dt.date(2026, 1, 5)
    for i in range(20):
        mark_attendance(world["course"], d + dt.timedelta(days=i),
                        {sid: "Present" if i < att_present else "Absent"})
    i, p, e = marks
    save_marks(sid, world["course"], "Internal", i)
    save_marks(sid, world["course"], "Practical", p)
    save_marks(sid, world["course"], "External", e)


def test_training_needs_enough_history(db):
    with pytest.raises(ValueError, match="historical"):
        train_model()


def test_model_trains_on_history_and_reports_held_out_accuracy(db):
    _history(300)
    m = train_model()
    assert m["accuracy"] > 0.7 and m["test_rows"] > 0 and set(m["importances"]) == set(FEATURES)
    assert MIN_RECORDS <= m["train_rows"] + m["test_rows"]


def test_predictions_follow_the_data(world):
    _history(400)
    train_model()
    strong, weak, new = world["students"]
    _record_for(world, strong, 19, (28, 19, 48))
    _record_for(world, weak, 8, (8, 4, 12))
    assert predict_student(strong)["prediction"] == "Good"
    assert predict_student(weak)["prediction"] == "At Risk"
    # a student with no attendance/marks yet is not guessed at
    assert predict_student(new)["prediction"] == INSUFFICIENT
    df = predict_all().set_index("student_id")
    assert df.loc[weak, "prediction"] == "At Risk" and len(df) == 3


def test_prediction_without_model_is_safe(world):
    assert predict_student(world["students"][0])["prediction"] == INSUFFICIENT


# ----- chatbot privacy -----
def test_chatbot_only_reads_logged_in_students_records(world):
    mine, other, _ = world["students"]
    _record_for(world, mine, 18, (20, 10, 30))   # 90% attendance
    _record_for(world, other, 6, (5, 2, 10))     # 30% attendance
    assert "90.0%" in answer(mine, "What is my attendance percentage?")
    assert "30.0%" not in answer(mine, "What is my attendance percentage?")
    # asking about someone else's ID is refused and leaks nothing
    reply = answer(mine, f"What is the attendance of {other}?")
    assert "only share your own" in reply and "30" not in reply
    assert "only share your own" in answer(mine, f"marks for {other.lower()}")
    # naming your own ID is fine
    assert "90.0%" in answer(mine, f"attendance for {mine}")


def test_chatbot_handles_all_documented_questions(world):
    sid = world["students"][0]
    _record_for(world, sid, 12, (20, 10, 30))
    for q in ["What is my attendance percentage?", "What are my examination marks?",
              "Which subjects have low attendance?", "What is my semester result?",
              "Which assignments are pending?", "What should I focus on?", "", "gibberish"]:
        assert isinstance(answer(sid, q), str) and answer(sid, q)
    assert "Artificial Intelligence" in answer(sid, "Which subjects have low attendance?")


def test_recommendations_prioritise_weakest_subject(world):
    sid = world["students"][0]
    _record_for(world, sid, 10, (6, 4, 12))  # weak AI301
    rec = recommendations(sid)
    assert rec["attention"][0]["course_code"] == "AI301"
    assert rec["plan"] and "AI301" in rec["plan"][0]


# ----- reports -----
def test_reports_and_exports(world):
    sid = world["students"][0]
    _record_for(world, sid, 17, (27, 18, 45))
    assert len(attendance_report(student_id=sid)) == 2
    assert len(attendance_report(course_id=world["course"])) == 3
    assert len(marks_report(course_id=world["course"])) == 3
    assert len(course_report(world["course"])) == 3
    assert len(department_report("AIML")) == 3

    xlsx = dfs_to_excel({"Attendance": attendance_report(course_id=world["course"])})
    ws = load_workbook(io.BytesIO(xlsx))["Attendance"]
    assert ws.max_row == 4 and ws["A1"].value == "student_id"

    pdf = table_pdf("Marks", marks_report(course_id=world["course"]), "AIML")
    assert pdf.startswith(b"%PDF")
    assert result_sheet_pdf(semester_result(sid)).startswith(b"%PDF")
    assert table_pdf("Empty", marks_report(course_id=world["course"]).iloc[0:0]).startswith(b"%PDF")
