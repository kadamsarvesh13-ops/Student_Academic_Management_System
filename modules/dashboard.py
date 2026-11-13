"""Module 6 - Role-based dashboards (admin, faculty, student)."""

from __future__ import annotations

from database.db import attendance_threshold, query, query_one


def _stat(label: str, value) -> str:
    return (f"<div class='stat-card'><div class='stat-value'>{value}</div>"
            f"<div class='stat-label'>{label}</div></div>")


def render(user: dict) -> None:
    {"admin": render_admin, "faculty": render_faculty, "student": render_student}[user["role"]](user)


def render_admin(user: dict) -> None:
    import plotly.express as px
    import streamlit as st

    from modules.notifications import list_announcements
    from modules.performance import (attendance_by_course, course_performance,
                                     overview_stats, pass_fail)
    from utils.helpers import page_header, show_fig

    page_header("Admin Dashboard", "Institution-wide overview (live data).")
    s = overview_stats()
    try:
        from ai.predict_performance import predict_all
        at_risk = int((predict_all()["prediction"] == "At Risk").sum())
    except Exception:  # noqa: BLE001 - dashboard must still load without the model
        at_risk = "n/a"
    fmt = lambda v: "-" if v is None else f"{v}%"  # noqa: E731
    cols = st.columns(5)
    for col, (label, val) in zip(cols, [
            ("Total students", s["students"]), ("Active courses", s["active_courses"]),
            ("Average attendance", fmt(s["avg_attendance"])),
            ("Average performance", fmt(s["avg_performance"])), ("Students at risk", at_risk)]):
        col.markdown(_stat(label, val), unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    att = attendance_by_course()
    with c1:
        if att["total"].sum():
            show_fig(px.bar(att, x="course_code", y="percentage", title="Attendance by subject"))
    perf = course_performance()
    with c2:
        if len(perf):
            show_fig(px.bar(perf, x="course_code", y="avg_percentage", title="Average marks % by subject"))
    pf = pass_fail()
    if pf["count"].sum():
        show_fig(px.pie(pf, names="result", values="count", hole=0.55, title="Pass / fail (all subjects)",
                        color="result", color_discrete_map={"Pass": "#1f6feb", "Fail": "#d1242f"}))
    st.subheader("Recent announcements")
    ann = list_announcements(5)
    if ann.empty:
        st.caption("No announcements yet.")
    for r in ann.itertuples():
        st.markdown(f"**{r.title}** - {r.description}  \n<small>{r.created_at}</small>", unsafe_allow_html=True)


def render_faculty(user: dict) -> None:
    import streamlit as st

    from modules.attendance import low_attendance_report
    from modules.course_management import courses_for_user
    from modules.marks_management import students_with_pending_marks
    from utils.helpers import page_header

    page_header(f"Welcome, {user['full_name']}", "Your courses at a glance.")
    courses = courses_for_user(user)
    low = low_attendance_report(faculty_id=user["ref_id"])
    c = st.columns(3)
    c[0].markdown(_stat("My courses", len(courses)), unsafe_allow_html=True)
    c[1].markdown(_stat("Students below attendance threshold", low["student_id"].nunique()), unsafe_allow_html=True)
    pending = sum(students_with_pending_marks(int(cid)) for cid in courses["course_id"]) if len(courses) else 0
    c[2].markdown(_stat("Incomplete mark entries", pending), unsafe_allow_html=True)
    st.subheader("My courses")
    st.dataframe(courses[["course_code", "course_name", "department", "semester", "credits", "enrolled"]]
                 if len(courses) else courses, hide_index=True)


def render_student(user: dict) -> None:
    import plotly.express as px
    import streamlit as st

    from modules.attendance import overall_attendance, student_attendance_summary
    from modules.marks_management import semester_result
    from modules.notifications import list_notifications
    from modules.performance import recommendations
    from utils.helpers import page_header, show_fig

    sid = user["ref_id"]
    me = query_one("SELECT * FROM students WHERE student_id=?", (sid,))
    page_header(f"Welcome, {user['full_name']}", f"{me['department']} - Semester {me['semester']} - Division {me['division']}")
    att = overall_attendance(sid)
    res = semester_result(sid, me["semester"])
    c = st.columns(4)
    c[0].markdown(_stat("Overall attendance", "-" if att is None else f"{att:.1f}%"), unsafe_allow_html=True)
    c[1].markdown(_stat("SGPA", "-" if res["sgpa"] is None else res["sgpa"]), unsafe_allow_html=True)
    c[2].markdown(_stat("Result", res["status"]), unsafe_allow_html=True)
    unread = int((list_notifications(user["user_id"])["is_read"] == 0).sum())
    c[3].markdown(_stat("Unread notifications", unread), unsafe_allow_html=True)
    df = student_attendance_summary(sid)
    if len(df):
        th = attendance_threshold()
        fig = px.bar(df, x="course_code", y="percentage", color="status", title="Attendance by subject",
                     color_discrete_map={"OK": "#1f6feb", "Low": "#d1242f", "No lectures": "#8c959f"})
        fig.add_hline(y=th, line_dash="dash")
        show_fig(fig)
    rec = recommendations(sid)
    st.subheader("Where to focus")
    if rec["plan"]:
        for line in rec["plan"]:
            st.write(line)
    else:
        st.success("You are on track in every subject.")
