"""Module 5 - Marks, grades and result sheets."""

from __future__ import annotations

import pandas as pd

from authentication.security import require_role
from database.db import df_query, get_json_setting, query, query_one, transaction
from utils.helpers import EXAM_TYPES, grade_for


def max_marks() -> dict:
    return get_json_setting("max_marks")


def grade_scale() -> list:
    return get_json_setting("grade_scale")


def save_marks(student_id: str, course_id: int, exam_type: str, marks: float,
               entered_by: str | None = None) -> None:
    """Insert or update one mark, enforcing the configured examination limits."""
    if exam_type not in EXAM_TYPES:
        raise ValueError("Exam type must be Internal, Practical or External.")
    limit = max_marks()[exam_type]
    try:
        marks = float(marks)
    except (TypeError, ValueError) as exc:
        raise ValueError("Marks must be a number.") from exc
    if not 0 <= marks <= limit:
        raise ValueError(f"{exam_type} marks must be between 0 and {limit}.")
    course = query_one("SELECT has_practical FROM courses WHERE course_id=?", (course_id,))
    if not course:
        raise ValueError("Unknown course.")
    if exam_type == "Practical" and not course["has_practical"]:
        raise ValueError("This course has no practical component.")
    if not query_one("SELECT 1 AS x FROM enrollments WHERE student_id=? AND course_id=?",
                     (student_id, course_id)):
        raise ValueError(f"{student_id} is not enrolled in this course.")
    with transaction() as conn:
        conn.execute(
            "INSERT INTO marks(student_id, course_id, exam_type, marks, entered_by) "
            "VALUES(?,?,?,?,?) ON CONFLICT(student_id, course_id, exam_type) "
            "DO UPDATE SET marks=excluded.marks, entered_by=excluded.entered_by, "
            "updated_at=datetime('now')", (student_id, course_id, exam_type, marks, entered_by))


def course_marks_grid(course_id: int, exam_type: str) -> pd.DataFrame:
    return df_query(
        "SELECT s.student_id, s.name, m.marks FROM enrollments e "
        "JOIN students s ON s.student_id=e.student_id "
        "LEFT JOIN marks m ON m.student_id=e.student_id AND m.course_id=e.course_id "
        "AND m.exam_type=? WHERE e.course_id=? ORDER BY s.student_id", (exam_type, course_id))


def course_results_df(student_id: str | None = None, course_id: int | None = None) -> pd.DataFrame:
    """One row per enrolled student/course with components, total, %, grade.

    Totals/grades are only computed once every component the course requires
    (Internal + External, plus Practical if the course has one) has been entered.
    """
    sql = ("SELECT s.student_id, s.name, s.department, s.semester AS student_semester, "
           "c.course_id, c.course_code, c.course_name, c.semester AS course_semester, "
           "c.credits, c.has_practical, "
           "MAX(CASE WHEN m.exam_type='Internal'  THEN m.marks END) AS internal, "
           "MAX(CASE WHEN m.exam_type='Practical' THEN m.marks END) AS practical, "
           "MAX(CASE WHEN m.exam_type='External'  THEN m.marks END) AS external "
           "FROM enrollments e JOIN students s ON s.student_id=e.student_id "
           "JOIN courses c ON c.course_id=e.course_id "
           "LEFT JOIN marks m ON m.student_id=e.student_id AND m.course_id=e.course_id "
           "WHERE 1=1")
    params: list = []
    if student_id:
        sql += " AND e.student_id=?"
        params.append(student_id)
    if course_id:
        sql += " AND e.course_id=?"
        params.append(course_id)
    df = df_query(sql + " GROUP BY e.student_id, e.course_id "
                  "ORDER BY s.student_id, c.course_code", tuple(params))
    for col in ("internal", "practical", "external"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    limits, scale = max_marks(), grade_scale()
    totals, maxes, pcts, grades, points, complete = [], [], [], [], [], []
    for r in df.itertuples():
        needs_prac = bool(r.has_practical)
        done = pd.notna(r.internal) and pd.notna(r.external) and (pd.notna(r.practical) or not needs_prac)
        mx = limits["Internal"] + limits["External"] + (limits["Practical"] if needs_prac else 0)
        complete.append(bool(done))
        maxes.append(mx)
        if done:
            tot = r.internal + r.external + (r.practical if needs_prac else 0)
            pct = round(tot / mx * 100, 2)
            g, p = grade_for(pct, scale)
            totals.append(tot); pcts.append(pct); grades.append(g); points.append(p)
        else:
            totals.append(None); pcts.append(None); grades.append("Pending"); points.append(None)
    df["complete"], df["max_total"] = complete, maxes
    df["total"] = pd.to_numeric(pd.Series(totals, index=df.index), errors="coerce")
    df["percentage"] = pd.to_numeric(pd.Series(pcts, index=df.index), errors="coerce")
    df["grade"] = grades
    df["grade_points"] = pd.to_numeric(pd.Series(points, index=df.index), errors="coerce")
    return df


def semester_result(student_id: str, semester: int | None = None) -> dict:
    """Result sheet for one semester: subject rows, SGPA, overall %, PASS/FAIL/PENDING."""
    student = query_one("SELECT * FROM students WHERE student_id=?", (student_id,))
    if not student:
        raise ValueError("Unknown student.")
    sem = int(semester or student["semester"])
    df = course_results_df(student_id)
    df = df[df["course_semester"] == sem].reset_index(drop=True)
    done = df[df["complete"]]
    if df.empty:
        status = "NO COURSES"
    elif len(done) < len(df):
        status = "PENDING"
    else:
        status = "FAIL" if (done["grade"] == "F").any() else "PASS"
    credits = done["credits"].sum()
    sgpa = round(float((done["grade_points"] * done["credits"]).sum() / credits), 2) if credits else None
    overall = round(float(done["total"].sum() / done["max_total"].sum() * 100), 2) if len(done) else None
    return {"student": student, "semester": sem, "rows": df, "sgpa": sgpa,
            "percentage": overall, "status": status}


def students_with_pending_marks(course_id: int) -> int:
    df = course_results_df(course_id=course_id)
    return int((~df["complete"]).sum()) if len(df) else 0


# ----------------------------------------------------------- Streamlit UI
def render(user: dict) -> None:
    import streamlit as st

    from modules.course_management import courses_for_user, user_can_use_course
    from utils.helpers import page_header

    require_role(user, "admin", "faculty")
    page_header("Marks & Results", "Enter internal, practical and external marks; grades are automatic.")
    courses = courses_for_user(user)
    if courses.empty:
        st.info("No courses assigned to you yet.")
        return
    labels = {f"{r.course_code} - {r.course_name} (Sem {r.semester})": int(r.course_id)
              for r in courses.itertuples()}
    limits = max_marks()
    tab_enter, tab_results, tab_cfg = st.tabs(["Enter / update marks", "Course results", "Grading rules"])

    with tab_enter:
        cid = labels[st.selectbox("Course", list(labels), key="marks_course")]
        if not user_can_use_course(user, cid):
            st.error("You are not assigned to this course.")
            return
        has_prac = bool(query_one("SELECT has_practical FROM courses WHERE course_id=?", (cid,))["has_practical"])
        types = [t for t in EXAM_TYPES if t != "Practical" or has_prac]
        exam = st.selectbox("Exam type", types)
        grid = course_marks_grid(cid, exam)
        st.caption(f"Maximum marks for {exam}: {limits[exam]}")
        edited = st.data_editor(
            grid, hide_index=True, disabled=["student_id", "name"], key=f"mk_{cid}_{exam}",
            column_config={"marks": st.column_config.NumberColumn(
                f"Marks (0-{limits[exam]})", min_value=0.0, max_value=float(limits[exam]))})
        if st.button("Save marks"):
            saved, errors = 0, []
            for old, new in zip(grid.itertuples(), edited.itertuples()):
                if pd.isna(new.marks) or (not pd.isna(old.marks) and old.marks == new.marks):
                    continue
                try:
                    save_marks(new.student_id, cid, exam, new.marks, user["username"])
                    saved += 1
                except ValueError as e:
                    errors.append(f"{new.student_id}: {e}")
            if saved:
                st.success(f"Saved {saved} mark(s).")
            for e in errors:
                st.error(e)

    with tab_results:
        cid = labels[st.selectbox("Course", list(labels), key="res_course")]
        df = course_results_df(course_id=cid)
        st.dataframe(df[["student_id", "name", "internal", "practical", "external", "total",
                         "max_total", "percentage", "grade"]], hide_index=True)

    with tab_cfg:
        st.write("Grade scale (min % -> grade -> points)")
        st.dataframe(pd.DataFrame(grade_scale(), columns=["Min %", "Grade", "Points"]), hide_index=True)
        st.write("Maximum marks", limits)
        if user["role"] == "admin":
            from database.db import set_setting
            with st.form("cfg"):
                ints = {t: st.number_input(f"Max {t} marks", 1, 200, int(limits[t])) for t in EXAM_TYPES}
                go = st.form_submit_button("Save maximum marks")
            if go:
                set_setting("max_marks", {t: int(v) for t, v in ints.items()})
                st.success("Saved. Existing marks above a new limit are not changed automatically.")


def render_student(user: dict) -> None:
    import plotly.express as px
    import streamlit as st

    from utils.excel_export import dfs_to_excel
    from utils.helpers import page_header, show_fig
    from utils.pdf_generator import result_sheet_pdf

    require_role(user, "student")
    sid = user["ref_id"]
    page_header("My Results", "Marks, grades and semester result.")
    me = query_one("SELECT semester FROM students WHERE student_id=?", (sid,))
    sems = sorted({int(r["semester"]) for r in query(
        "SELECT DISTINCT c.semester FROM enrollments e JOIN courses c ON c.course_id=e.course_id "
        "WHERE e.student_id=?", (sid,))} | {int(me["semester"])})
    sem = st.selectbox("Semester", sems, index=sems.index(int(me["semester"])))
    res = semester_result(sid, sem)
    c1, c2, c3 = st.columns(3)
    c1.metric("Result", res["status"])
    c2.metric("SGPA", res["sgpa"] if res["sgpa"] is not None else "-")
    c3.metric("Percentage", f"{res['percentage']:.1f}%" if res["percentage"] is not None else "-")
    rows = res["rows"]
    if rows.empty:
        st.info("No courses for this semester.")
        return
    st.dataframe(rows[["course_code", "course_name", "credits", "internal", "practical",
                       "external", "total", "max_total", "percentage", "grade"]], hide_index=True)
    done = rows[rows["complete"]]
    if len(done):
        show_fig(px.bar(done, x="course_code", y="percentage", color="grade",
                        title="Percentage by subject"))
    st.download_button("Download result sheet (PDF)", result_sheet_pdf(res),
                       file_name=f"{sid}_sem{sem}_result.pdf", mime="application/pdf")
    st.download_button("Download marks (Excel)", dfs_to_excel({"Marks": rows}),
                       file_name=f"{sid}_sem{sem}_marks.xlsx")
