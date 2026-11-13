"""Module 4 - Attendance management."""

from __future__ import annotations

from datetime import date

import pandas as pd

from authentication.security import require_role
from database.db import attendance_threshold, df_query, query, transaction
from utils.helpers import attendance_percentage, lectures_needed, to_iso_date

STATUSES = ("Present", "Absent")


def mark_attendance(course_id: int, lecture_date, statuses: dict[str, str],
                    marked_by: str | None = None) -> int:
    """Save (or correct) attendance for one lecture.

    `statuses` maps student_id -> 'Present'/'Absent'. A student can only have
    one record per course and date: saving again updates it, never duplicates.
    """
    iso = to_iso_date(lecture_date)
    if iso > date.today().isoformat():
        raise ValueError("Cannot mark attendance for a future date.")
    if not statuses:
        raise ValueError("No students to save.")
    if any(s not in STATUSES for s in statuses.values()):
        raise ValueError("Status must be 'Present' or 'Absent'.")
    enrolled = {r["student_id"] for r in query(
        "SELECT student_id FROM enrollments WHERE course_id=?", (course_id,))}
    unknown = set(statuses) - enrolled
    if unknown:
        raise ValueError(f"Not enrolled in this course: {', '.join(sorted(unknown))}")
    with transaction() as conn:
        conn.executemany(
            "INSERT INTO attendance(student_id, course_id, lecture_date, status, marked_by) "
            "VALUES(?,?,?,?,?) ON CONFLICT(student_id, course_id, lecture_date) "
            "DO UPDATE SET status=excluded.status, marked_by=excluded.marked_by",
            [(sid, course_id, iso, st, marked_by) for sid, st in statuses.items()])
    return len(statuses)


def existing_statuses(course_id: int, lecture_date) -> dict[str, str]:
    rows = query("SELECT student_id, status FROM attendance WHERE course_id=? AND lecture_date=?",
                 (course_id, to_iso_date(lecture_date)))
    return {r["student_id"]: r["status"] for r in rows}


def lecture_dates(course_id: int) -> list[str]:
    return [r["lecture_date"] for r in query(
        "SELECT DISTINCT lecture_date FROM attendance WHERE course_id=? "
        "ORDER BY lecture_date DESC", (course_id,))]


def _with_percentages(df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    df = df.copy()
    df["absent"] = df["total"] - df["present"]
    df["percentage"] = [attendance_percentage(p, t) for p, t in zip(df["present"], df["total"])]
    df["needed"] = [lectures_needed(int(p), int(t), threshold)
                    for p, t in zip(df["present"], df["total"])]
    df["status"] = ["No lectures" if t == 0 else ("Low" if pct < threshold else "OK")
                    for pct, t in zip(df["percentage"], df["total"])]
    return df


def student_attendance_summary(student_id: str, threshold: float | None = None) -> pd.DataFrame:
    """Subject-wise attendance for one student."""
    th = threshold if threshold is not None else attendance_threshold()
    df = df_query(
        "SELECT c.course_id, c.course_code, c.course_name, COUNT(a.attendance_id) AS total, "
        "COALESCE(SUM(a.status='Present'), 0) AS present FROM enrollments e "
        "JOIN courses c ON c.course_id = e.course_id "
        "LEFT JOIN attendance a ON a.course_id = c.course_id AND a.student_id = e.student_id "
        "WHERE e.student_id=? GROUP BY c.course_id ORDER BY c.course_code", (student_id,))
    return _with_percentages(df, th)


def course_attendance_summary(course_id: int, threshold: float | None = None) -> pd.DataFrame:
    th = threshold if threshold is not None else attendance_threshold()
    df = df_query(
        "SELECT s.student_id, s.name, s.division, COUNT(a.attendance_id) AS total, "
        "COALESCE(SUM(a.status='Present'), 0) AS present FROM enrollments e "
        "JOIN students s ON s.student_id = e.student_id "
        "LEFT JOIN attendance a ON a.course_id = e.course_id AND a.student_id = e.student_id "
        "WHERE e.course_id=? GROUP BY s.student_id ORDER BY s.student_id", (course_id,))
    return _with_percentages(df, th)


def overall_attendance(student_id: str) -> float | None:
    """Overall % across all subjects, or None if no lectures recorded yet."""
    df = student_attendance_summary(student_id)
    total = int(df["total"].sum()) if len(df) else 0
    return attendance_percentage(int(df["present"].sum()), total) if total else None


def low_attendance_report(threshold: float | None = None,
                          faculty_id: str | None = None) -> pd.DataFrame:
    """Every student/course pair currently below the threshold."""
    th = threshold if threshold is not None else attendance_threshold()
    sql = ("SELECT s.student_id, s.name, s.department, s.semester, s.division, "
           "c.course_id, c.course_code, c.course_name, c.faculty_id, "
           "COUNT(a.attendance_id) AS total, COALESCE(SUM(a.status='Present'),0) AS present "
           "FROM enrollments e JOIN students s ON s.student_id=e.student_id "
           "JOIN courses c ON c.course_id=e.course_id "
           "JOIN attendance a ON a.course_id=e.course_id AND a.student_id=e.student_id ")
    params: tuple = ()
    if faculty_id:
        sql += "WHERE c.faculty_id=? "
        params = (faculty_id,)
    df = df_query(sql + "GROUP BY e.student_id, e.course_id", params)
    df = _with_percentages(df, th)
    return df[df["status"] == "Low"].sort_values("percentage").reset_index(drop=True)


def monthly_report(student_id: str | None = None, course_id: int | None = None) -> pd.DataFrame:
    sql = ("SELECT strftime('%Y-%m', lecture_date) AS month, COUNT(*) AS total, "
           "SUM(status='Present') AS present FROM attendance WHERE 1=1")
    params: list = []
    if student_id:
        sql += " AND student_id=?"
        params.append(student_id)
    if course_id:
        sql += " AND course_id=?"
        params.append(course_id)
    df = df_query(sql + " GROUP BY month ORDER BY month", tuple(params))
    df["percentage"] = [attendance_percentage(int(p), int(t))
                        for p, t in zip(df["present"], df["total"])]
    return df


def attendance_history(student_id: str, course_id: int | None = None) -> pd.DataFrame:
    sql = ("SELECT a.lecture_date, c.course_code, c.course_name, a.status FROM attendance a "
           "JOIN courses c ON c.course_id=a.course_id WHERE a.student_id=?")
    params: list = [student_id]
    if course_id:
        sql += " AND a.course_id=?"
        params.append(course_id)
    return df_query(sql + " ORDER BY a.lecture_date DESC, c.course_code", tuple(params))


# ----------------------------------------------------------- Streamlit UI
def render(user: dict) -> None:
    """Faculty / admin attendance workspace."""
    import plotly.express as px
    import streamlit as st

    from modules.course_management import course_students, courses_for_user, user_can_use_course
    from modules.notifications import send_low_attendance_alerts
    from utils.excel_export import dfs_to_excel
    from utils.helpers import page_header, show_fig

    require_role(user, "admin", "faculty")
    page_header("Attendance", "Mark lectures, review percentages and spot low attendance.")
    courses = courses_for_user(user)
    if courses.empty:
        st.info("No courses assigned to you yet.")
        return
    labels = {f"{r.course_code} - {r.course_name} (Sem {r.semester})": int(r.course_id)
              for r in courses.itertuples()}
    th = attendance_threshold()
    tab_mark, tab_course, tab_low, tab_month = st.tabs(
        ["Mark attendance", "Course summary", "Low-attendance alerts", "Monthly report"])

    with tab_mark:
        cid = labels[st.selectbox("Course", list(labels), key="att_course")]
        if not user_can_use_course(user, cid):
            st.error("You are not assigned to this course.")
            return
        c1, c2 = st.columns(2)
        division = c1.selectbox("Division", ["All", "A", "B", "C", "D"])
        lec_date = c2.date_input("Lecture date", value=date.today(), max_value=date.today())
        students = course_students(cid, None if division == "All" else division)
        if students.empty:
            st.info("No students enrolled for this selection.")
        else:
            prev = existing_statuses(cid, lec_date)
            if prev:
                st.info("Attendance already saved for this date - saving again will update it.")
            grid = students[["student_id", "name", "division"]].copy()
            grid["Present"] = [prev.get(s, "Present") == "Present" for s in grid["student_id"]]
            edited = st.data_editor(
                grid, hide_index=True, disabled=["student_id", "name", "division"],
                key=f"grid_{cid}_{lec_date}_{division}")
            c1, c2 = st.columns(2)
            c1.metric("Present", int(edited["Present"].sum()))
            c2.metric("Absent", int((~edited["Present"]).sum()))
            if st.button("Save attendance"):
                try:
                    n = mark_attendance(
                        cid, lec_date,
                        {r.student_id: "Present" if r.Present else "Absent"
                         for r in edited.itertuples()}, marked_by=user["username"])
                    st.success(f"Saved attendance for {n} student(s).")
                except ValueError as e:
                    st.error(str(e))

    with tab_course:
        cid = labels[st.selectbox("Course", list(labels), key="sum_course")]
        df = course_attendance_summary(cid)
        st.dataframe(df, hide_index=True)
        if len(df):
            fig = px.bar(df, x="name", y="percentage", color="status",
                         color_discrete_map={"OK": "#1f6feb", "Low": "#d1242f", "No lectures": "#8c959f"},
                         title="Attendance % by student")
            fig.add_hline(y=th, line_dash="dash", annotation_text=f"{th:.0f}% threshold")
            show_fig(fig)
            st.download_button("Download Excel", dfs_to_excel({"Attendance": df}),
                               file_name="attendance_report.xlsx")

    with tab_low:
        fid = user["ref_id"] if user["role"] == "faculty" else None
        low = low_attendance_report(faculty_id=fid)
        st.caption(f"Students below {th:.0f}% in at least one course: {low['student_id'].nunique()}")
        st.dataframe(low[["student_id", "name", "course_code", "total", "present",
                          "percentage", "needed"]] if len(low) else low, hide_index=True)
        if st.button("Send alerts to students and faculty"):
            st.success(f"{send_low_attendance_alerts(faculty_id=fid)} new alert(s) sent.")

    with tab_month:
        cid = labels[st.selectbox("Course", list(labels), key="month_course")]
        m = monthly_report(course_id=cid)
        st.dataframe(m, hide_index=True)
        if len(m):
            show_fig(px.line(m, x="month", y="percentage", markers=True,
                             title="Monthly attendance %"))


def render_student(user: dict) -> None:
    import plotly.express as px
    import streamlit as st

    from utils.excel_export import dfs_to_excel
    from utils.helpers import page_header, show_fig

    require_role(user, "student")
    sid = user["ref_id"]  # always the logged-in student's own ID
    page_header("My Attendance", "Subject-wise attendance and what you need to reach the threshold.")
    th = attendance_threshold()
    df = student_attendance_summary(sid)
    overall = overall_attendance(sid)
    st.metric("Overall attendance", f"{overall:.1f}%" if overall is not None else "No data yet")
    if df.empty:
        st.info("You are not enrolled in any course yet.")
        return
    low = df[df["status"] == "Low"]
    for r in low.itertuples():
        need = f"attend the next {r.needed} lecture(s)" if r.needed is not None else "this is no longer reachable"
        st.warning(f"{r.course_name}: {r.percentage:.1f}% - {need} to reach {th:.0f}%.")
    st.dataframe(df[["course_code", "course_name", "total", "present", "absent",
                     "percentage", "status", "needed"]], hide_index=True)
    fig = px.bar(df, x="course_code", y="percentage", color="status",
                 color_discrete_map={"OK": "#1f6feb", "Low": "#d1242f", "No lectures": "#8c959f"},
                 title="Subject-wise attendance %")
    fig.add_hline(y=th, line_dash="dash", annotation_text=f"{th:.0f}% threshold")
    show_fig(fig)
    with st.expander("Attendance history"):
        st.dataframe(attendance_history(sid), hide_index=True)
    st.download_button("Download my attendance (Excel)", dfs_to_excel({"Attendance": df}),
                       file_name=f"{sid}_attendance.xlsx")
