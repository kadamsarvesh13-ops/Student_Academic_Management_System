"""Module 7b - Reports and exports (PDF / Excel / CSV)."""

from __future__ import annotations

import pandas as pd

from database.db import df_query, query, query_one
from modules.attendance import course_attendance_summary, student_attendance_summary
from modules.marks_management import course_results_df, semester_result
from modules.performance import student_overall


def profile_report(student_id: str) -> tuple[dict, pd.DataFrame]:
    prof = query_one("SELECT student_id, name, department, semester, division, email, mobile, "
                     "previous_percentage FROM students WHERE student_id=?", (student_id,)) or {}
    courses = df_query("SELECT c.course_code, c.course_name, c.semester, c.credits, "
                       "COALESCE(f.name,'-') AS faculty FROM enrollments e "
                       "JOIN courses c ON c.course_id=e.course_id "
                       "LEFT JOIN faculty f ON f.faculty_id=c.faculty_id WHERE e.student_id=? "
                       "ORDER BY c.course_code", (student_id,))
    return prof, courses


def attendance_report(student_id: str | None = None, course_id: int | None = None) -> pd.DataFrame:
    if student_id:
        return student_attendance_summary(student_id)[
            ["course_code", "course_name", "total", "present", "absent", "percentage", "status"]]
    return course_attendance_summary(course_id)[
        ["student_id", "name", "division", "total", "present", "absent", "percentage", "status"]]


def marks_report(student_id: str | None = None, course_id: int | None = None) -> pd.DataFrame:
    df = course_results_df(student_id=student_id, course_id=course_id)
    return df[["student_id", "name", "course_code", "course_name", "internal", "practical",
               "external", "total", "max_total", "percentage", "grade"]]


def course_report(course_id: int) -> pd.DataFrame:
    att = course_attendance_summary(course_id)[["student_id", "name", "percentage"]].rename(
        columns={"percentage": "attendance_pct"})
    res = course_results_df(course_id=course_id)[["student_id", "internal", "practical", "external",
                                                  "total", "percentage", "grade"]]
    return att.merge(res, on="student_id", how="left")


def department_report(department: str) -> pd.DataFrame:
    base = df_query("SELECT student_id, name, semester, division FROM students WHERE department=? "
                    "ORDER BY student_id", (department,))
    rows = []
    for s in base.itertuples():
        att = student_attendance_summary(s.student_id)
        tot, pres = att["total"].sum(), att["present"].sum()
        rows.append({"student_id": s.student_id, "name": s.name, "semester": s.semester,
                     "division": s.division,
                     "attendance_pct": round(pres / tot * 100, 1) if tot else None})
    out = pd.DataFrame(rows)
    perf = student_overall()[["student_id", "percentage", "sgpa"]]
    return out.merge(perf, on="student_id", how="left") if len(out) else out


# ----------------------------------------------------------- Streamlit UI
def render(user: dict) -> None:
    import streamlit as st

    from modules.course_management import courses_for_user
    from utils.excel_export import df_to_csv, dfs_to_excel
    from utils.helpers import page_header
    from utils.pdf_generator import result_sheet_pdf, table_pdf

    page_header("Reports", "Download academic reports as PDF, Excel or CSV.")
    role = user["role"]
    title, df, pdf_bytes = "", None, None

    if role == "student":
        sid = user["ref_id"]
        kind = st.selectbox("Report", ["Attendance report", "Marks report", "Semester result sheet", "Profile"])
        if kind == "Attendance report":
            title, df = "Attendance Report", attendance_report(student_id=sid)
        elif kind == "Marks report":
            title, df = "Marks Report", marks_report(student_id=sid).drop(columns=["student_id", "name"])
        elif kind == "Semester result sheet":
            res = semester_result(sid)
            title, df, pdf_bytes = "Semester Result", res["rows"][
                ["course_code", "course_name", "credits", "total", "max_total", "percentage", "grade"]], result_sheet_pdf(res)
        else:
            prof, df = profile_report(sid)
            title = "Student Profile"
            st.json(prof)
    else:
        kinds = ["Attendance report (course)", "Marks report (course)", "Course report",
                 "Student profile", "Semester result sheet"]
        if role == "admin":
            kinds.append("Department-wise report")
        kind = st.selectbox("Report", kinds)
        courses = courses_for_user(user)
        labels = {f"{r.course_code} - {r.course_name}": int(r.course_id) for r in courses.itertuples()}
        if kind in kinds[:3]:
            if not labels:
                st.info("No courses available.")
                return
            cid = labels[st.selectbox("Course", list(labels))]
            title = kind
            df = (attendance_report(course_id=cid) if kind.startswith("Attendance")
                  else marks_report(course_id=cid) if kind.startswith("Marks") else course_report(cid))
        elif kind == "Department-wise report":
            depts = [r["department"] for r in query("SELECT DISTINCT department FROM students ORDER BY 1")]
            if not depts:
                st.info("No students yet.")
                return
            dept = st.selectbox("Department", depts)
            title, df = f"Department report - {dept}", department_report(dept)
        else:
            if role == "faculty":
                ids = [int(c) for c in courses["course_id"]]
                marks = ",".join("?" * len(ids)) or "NULL"
                sids = [r["student_id"] for r in query(
                    f"SELECT DISTINCT student_id FROM enrollments WHERE course_id IN ({marks}) "
                    "ORDER BY 1", tuple(ids))]
            else:
                sids = [r["student_id"] for r in query("SELECT student_id FROM students ORDER BY 1")]
            if not sids:
                st.info("No students available.")
                return
            sid = st.selectbox("Student", sids)
            if kind == "Student profile":
                prof, df = profile_report(sid)
                title = f"Student Profile - {sid}"
                st.json(prof)
            else:
                res = semester_result(sid)
                title, df, pdf_bytes = f"Semester result - {sid}", res["rows"][
                    ["course_code", "course_name", "credits", "total", "max_total", "percentage", "grade"]], result_sheet_pdf(res)

    if df is None:
        return
    st.dataframe(df, hide_index=True)
    c1, c2, c3 = st.columns(3)
    c1.download_button("Download PDF", pdf_bytes or table_pdf(title, df), file_name=f"{title}.pdf".replace(" ", "_"),
                       mime="application/pdf")
    c2.download_button("Download Excel", dfs_to_excel({title[:31]: df}), file_name=f"{title}.xlsx".replace(" ", "_"))
    c3.download_button("Download CSV", df_to_csv(df), file_name=f"{title}.csv".replace(" ", "_"), mime="text/csv")
