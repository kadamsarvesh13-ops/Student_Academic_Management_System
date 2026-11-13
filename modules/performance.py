"""Module 6 - Analytics, AI analytics page and recommendation engine."""

from __future__ import annotations

import pandas as pd

from authentication.security import require_role
from database.db import attendance_threshold, df_query, query, query_one
from modules.attendance import overall_attendance, student_attendance_summary
from modules.marks_management import course_results_df


# ---------------------------------------------------------------- analytics
def _complete_results(faculty_id: str | None = None) -> pd.DataFrame:
    df = course_results_df()
    df = df[df["complete"]]
    if faculty_id:
        ids = [r["course_id"] for r in query("SELECT course_id FROM courses WHERE faculty_id=?", (faculty_id,))]
        df = df[df["course_id"].isin(ids)]
    return df


def overview_stats() -> dict:
    att = query_one("SELECT COUNT(*) AS t, COALESCE(SUM(status='Present'),0) AS p FROM attendance")
    res = _complete_results()
    return {
        "students": query_one("SELECT COUNT(*) AS n FROM students")["n"],
        "active_courses": query_one("SELECT COUNT(*) AS n FROM courses WHERE is_active=1")["n"],
        "avg_attendance": round(att["p"] / att["t"] * 100, 1) if att["t"] else None,
        "avg_performance": round(float(res["percentage"].mean()), 1) if len(res) else None,
    }


def attendance_by_course(faculty_id: str | None = None) -> pd.DataFrame:
    sql = ("SELECT c.course_code, c.course_name, COUNT(a.attendance_id) AS total, "
           "COALESCE(SUM(a.status='Present'),0) AS present FROM courses c "
           "LEFT JOIN attendance a ON a.course_id=c.course_id WHERE c.is_active=1")
    params: tuple = ()
    if faculty_id:
        sql += " AND c.faculty_id=?"
        params = (faculty_id,)
    df = df_query(sql + " GROUP BY c.course_id ORDER BY c.course_code", params)
    df["percentage"] = [round(p / t * 100, 1) if t else None for p, t in zip(df["present"], df["total"])]
    return df


def course_performance(faculty_id: str | None = None) -> pd.DataFrame:
    df = _complete_results(faculty_id)
    if df.empty:
        return pd.DataFrame(columns=["course_code", "course_name", "avg_percentage", "pass_percentage", "students"])
    g = df.groupby(["course_code", "course_name"])
    out = g.agg(avg_percentage=("percentage", "mean"),
                pass_percentage=("grade", lambda s: (s != "F").mean() * 100),
                students=("student_id", "nunique")).round(1).reset_index()
    return out


def student_overall(faculty_id: str | None = None) -> pd.DataFrame:
    df = _complete_results(faculty_id)
    if df.empty:
        return pd.DataFrame(columns=["student_id", "name", "department", "semester", "percentage", "sgpa"])
    rows = []
    for sid, g in df.groupby("student_id"):
        sgpa = (g["grade_points"] * g["credits"]).sum() / g["credits"].sum()
        rows.append({"student_id": sid, "name": g["name"].iloc[0], "department": g["department"].iloc[0],
                     "semester": int(g["student_semester"].iloc[0]),
                     "percentage": round(g["total"].sum() / g["max_total"].sum() * 100, 2),
                     "sgpa": round(float(sgpa), 2)})
    return pd.DataFrame(rows)


def top_students(n: int = 10, faculty_id: str | None = None) -> pd.DataFrame:
    return student_overall(faculty_id).sort_values(["percentage", "sgpa"], ascending=False).head(n).reset_index(drop=True)


def pass_fail(faculty_id: str | None = None) -> pd.DataFrame:
    df = _complete_results(faculty_id)
    if df.empty:
        return pd.DataFrame({"result": ["Pass", "Fail"], "count": [0, 0]})
    failed = int((df["grade"] == "F").sum())
    return pd.DataFrame({"result": ["Pass", "Fail"], "count": [len(df) - failed, failed]})


def semester_performance(faculty_id: str | None = None) -> pd.DataFrame:
    df = _complete_results(faculty_id)
    if df.empty:
        return pd.DataFrame(columns=["course_semester", "avg_percentage"])
    return (df.groupby("course_semester")["percentage"].mean().round(1)
            .reset_index().rename(columns={"percentage": "avg_percentage"}))


# ---------------------------------------------------------- recommendations
def recommendations(student_id: str) -> dict:
    """Rule-based study advice from the student's own marks and attendance."""
    th = attendance_threshold()
    att = student_attendance_summary(student_id).set_index("course_code")
    res = course_results_df(student_id).set_index("course_code")
    items = []
    for code in res.index:
        pct = res.loc[code, "percentage"]
        pct = None if pd.isna(pct) else float(pct)
        a_row = att.loc[code]
        a_pct = float(a_row["percentage"]) if a_row["total"] > 0 else None
        marks_gap = max(0.0, 60 - pct) if pct is not None else 0.0
        att_gap = max(0.0, th - a_pct) if a_pct is not None else 0.0
        items.append({"course_code": code, "course_name": res.loc[code, "course_name"],
                      "percentage": pct, "attendance": a_pct, "needed": a_row["needed"],
                      "score": marks_gap + att_gap})
    items.sort(key=lambda x: x["score"], reverse=True)
    attention = [i for i in items if i["score"] > 0]
    plan = []
    for rank, i in enumerate(attention, 1):
        parts = []
        if i["percentage"] is not None and i["percentage"] < 60:
            parts.append(f"raise your score from {i['percentage']:.0f}% (revise weak topics, solve past papers)")
        if i["attendance"] is not None and i["attendance"] < th:
            n = f"attend the next {i['needed']} lecture(s)" if i["needed"] is not None else "speak to your faculty"
            parts.append(f"{n} to reach {th:.0f}% attendance (now {i['attendance']:.0f}%)")
        plan.append(f"{rank}. {i['course_code']} - {i['course_name']}: " + " and ".join(parts) + ".")
    return {"attention": attention, "plan": plan, "all": items}


# ----------------------------------------------------------- Streamlit UI
def render(user: dict) -> None:
    """Analytics for admin and faculty (faculty see only their own courses)."""
    import plotly.express as px
    import streamlit as st

    from utils.helpers import page_header, show_fig

    require_role(user, "admin", "faculty")
    fid = user["ref_id"] if user["role"] == "faculty" else None
    page_header("Academic Analytics", "Attendance, marks and pass/fail trends.")
    att = attendance_by_course(fid)
    perf = course_performance(fid)
    c1, c2 = st.columns(2)
    with c1:
        if att["total"].sum():
            show_fig(px.bar(att, x="course_code", y="percentage", title="Attendance comparison by subject"))
        else:
            st.info("No attendance recorded yet.")
    with c2:
        if len(perf):
            show_fig(px.bar(perf, x="course_code", y="avg_percentage", title="Average marks % by subject"))
        else:
            st.info("No completed results yet.")
    c3, c4 = st.columns(2)
    with c3:
        pf = pass_fail(fid)
        if pf["count"].sum():
            show_fig(px.pie(pf, names="result", values="count", title="Pass / fail", hole=0.5,
                            color="result", color_discrete_map={"Pass": "#1f6feb", "Fail": "#d1242f"}))
    with c4:
        sp = semester_performance(fid)
        if len(sp):
            show_fig(px.line(sp, x="course_semester", y="avg_percentage", markers=True,
                             title="Semester-wise performance"))
    st.subheader("Top-performing students")
    st.dataframe(top_students(10, fid), hide_index=True)
    st.subheader("Subject performance")
    st.dataframe(perf, hide_index=True)


def render_ai(user: dict) -> None:
    import plotly.express as px
    import streamlit as st

    from ai.predict_performance import load_bundle, predict_all
    from ai.train_model import train_model
    from utils.helpers import page_header, show_fig

    require_role(user, "admin", "faculty")
    fid = user["ref_id"] if user["role"] == "faculty" else None
    page_header("AI Analytics", "Random Forest prediction of students who may need support.")
    bundle = load_bundle()
    if bundle is None:
        st.warning("The model is not trained yet - it needs historical cohort records.")
    else:
        m = bundle["metrics"]
        st.caption(f"Held-out accuracy {m['accuracy']*100:.0f}% (trained on {m['train_rows']} records, "
                   f"tested on {m['test_rows']}). Feature importance: "
                   + ", ".join(f"{k} {v:.2f}" for k, v in bundle["importances"].items()))
    if user["role"] == "admin" and st.button("Retrain model from historical records"):
        try:
            st.success(f"Retrained. Accuracy on held-out data: {train_model()['accuracy']*100:.0f}%")
            st.rerun()
        except ValueError as e:
            st.error(str(e))
    df = predict_all(faculty_id=fid)
    if df.empty:
        st.info("No students to analyse.")
        return
    counts = df["prediction"].value_counts().reset_index()
    counts.columns = ["prediction", "count"]
    show_fig(px.pie(counts, names="prediction", values="count", hole=0.5, title="Predicted performance",
                    color="prediction", color_discrete_map={"Good": "#1f6feb", "Average": "#f0b429",
                                                            "At Risk": "#d1242f", "Insufficient data": "#8c959f"}))
    st.subheader("Students at academic risk")
    st.dataframe(df[df["prediction"] == "At Risk"], hide_index=True)
    st.subheader("All predictions")
    st.dataframe(df, hide_index=True)
    st.caption("Predictions are decision support only. Inputs missing from a student's record "
               "(e.g. assignments) are filled with the training median.")
