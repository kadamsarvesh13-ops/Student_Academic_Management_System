"""Module 3 - Course and subject management (admin)."""

from __future__ import annotations

import sqlite3

import pandas as pd

from authentication.security import require_role
from database.db import df_query, execute, query, query_one, transaction
from utils.helpers import DEPT_RE

UPDATABLE = {"course_name", "department", "semester", "credits", "has_practical",
             "faculty_id", "is_active"}


def add_course(code: str, name: str, department: str, semester: int, credits: int,
               faculty_id: str | None = None, has_practical: bool = True) -> int:
    if not code.strip() or not name.strip():
        raise ValueError("Course code and name are required.")
    if not DEPT_RE.match(department or ""):
        raise ValueError("Department must be 2-10 letters/digits.")
    if not 1 <= int(semester) <= 8:
        raise ValueError("Semester must be between 1 and 8.")
    if not 1 <= int(credits) <= 10:
        raise ValueError("Credits must be between 1 and 10.")
    try:
        return execute(
            "INSERT INTO courses(course_code, course_name, department, semester, credits, "
            "has_practical, faculty_id) VALUES(?,?,?,?,?,?,?)",
            (code.strip().upper(), name.strip(), department.strip().upper(), int(semester),
             int(credits), int(has_practical), faculty_id or None))
    except sqlite3.IntegrityError as exc:
        if "UNIQUE" in str(exc).upper():
            raise ValueError("A course with this code already exists.") from exc
        raise ValueError("Unknown faculty ID.") from exc


def update_course(course_id: int, **fields) -> None:
    bad = set(fields) - UPDATABLE
    if bad:
        raise ValueError(f"Cannot update: {', '.join(sorted(bad))}")
    if not fields:
        return
    if not query_one("SELECT 1 AS x FROM courses WHERE course_id=?", (course_id,)):
        raise ValueError("Course not found.")
    sets = ", ".join(f"{k}=?" for k in fields)
    execute(f"UPDATE courses SET {sets} WHERE course_id=?", (*fields.values(), course_id))


def assign_faculty(course_id: int, faculty_id: str | None) -> None:
    if faculty_id and not query_one("SELECT 1 AS x FROM faculty WHERE faculty_id=?", (faculty_id,)):
        raise ValueError("Unknown faculty ID.")
    update_course(course_id, faculty_id=faculty_id)


def enroll_student(student_id: str, course_id: int) -> bool:
    """Enrol one student. Returns False if already enrolled."""
    if not query_one("SELECT 1 AS x FROM students WHERE student_id=?", (student_id,)):
        raise ValueError("Unknown student.")
    if not query_one("SELECT 1 AS x FROM courses WHERE course_id=?", (course_id,)):
        raise ValueError("Unknown course.")
    try:
        execute("INSERT INTO enrollments(student_id, course_id) VALUES(?,?)", (student_id, course_id))
        return True
    except sqlite3.IntegrityError:
        return False


def enroll_cohort(course_id: int) -> int:
    """Enrol every student of the course's department and semester. Returns new enrolments."""
    course = query_one("SELECT department, semester FROM courses WHERE course_id=?", (course_id,))
    if not course:
        raise ValueError("Unknown course.")
    with transaction() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO enrollments(student_id, course_id) "
            "SELECT student_id, ? FROM students WHERE department=? AND semester=?",
            (course_id, course["department"], course["semester"]))
        return cur.rowcount


def unenroll_student(student_id: str, course_id: int) -> None:
    execute("DELETE FROM enrollments WHERE student_id=? AND course_id=?", (student_id, course_id))


def list_courses(department: str | None = None, semester: int | None = None,
                 faculty_id: str | None = None, active_only: bool = False) -> pd.DataFrame:
    sql = ("SELECT c.course_id, c.course_code, c.course_name, c.department, c.semester, "
           "c.credits, c.has_practical, c.faculty_id, f.name AS faculty_name, c.is_active, "
           "(SELECT COUNT(*) FROM enrollments e WHERE e.course_id = c.course_id) AS enrolled "
           "FROM courses c LEFT JOIN faculty f ON f.faculty_id = c.faculty_id WHERE 1=1")
    params: list = []
    if department:
        sql += " AND c.department=?"
        params.append(department)
    if semester:
        sql += " AND c.semester=?"
        params.append(int(semester))
    if faculty_id:
        sql += " AND c.faculty_id=?"
        params.append(faculty_id)
    if active_only:
        sql += " AND c.is_active=1"
    return df_query(sql + " ORDER BY c.department, c.semester, c.course_code", tuple(params))


def courses_for_user(user: dict) -> pd.DataFrame:
    """Courses a user may work with: admin = all, faculty = assigned only."""
    if user["role"] == "admin":
        return list_courses(active_only=True)
    if user["role"] == "faculty":
        return list_courses(faculty_id=user["ref_id"], active_only=True)
    return df_query(
        "SELECT c.course_id, c.course_code, c.course_name, c.semester, c.credits "
        "FROM enrollments e JOIN courses c ON c.course_id=e.course_id WHERE e.student_id=?",
        (user["ref_id"],))


def course_students(course_id: int, division: str | None = None) -> pd.DataFrame:
    sql = ("SELECT s.student_id, s.name, s.division, s.semester FROM enrollments e "
           "JOIN students s ON s.student_id = e.student_id WHERE e.course_id=?")
    params: list = [course_id]
    if division:
        sql += " AND s.division=?"
        params.append(division)
    return df_query(sql + " ORDER BY s.student_id", tuple(params))


def user_can_use_course(user: dict, course_id: int) -> bool:
    if user["role"] == "admin":
        return True
    if user["role"] == "faculty":
        return query_one("SELECT 1 AS x FROM courses WHERE course_id=? AND faculty_id=?",
                         (course_id, user["ref_id"])) is not None
    return False


# ----------------------------------------------------------- Streamlit UI
def render(user: dict) -> None:
    import streamlit as st
    from utils.helpers import page_header

    require_role(user, "admin")
    page_header("Course Management", "Subjects, credits, faculty allocation and enrolment.")
    tab_list, tab_add, tab_edit, tab_enrol = st.tabs(
        ["Semester-wise subjects", "Add course", "Update / assign faculty", "Enrolment"])
    faculty = query("SELECT faculty_id, name FROM faculty ORDER BY faculty_id")
    fac_opts = {"(unassigned)": None, **{f"{f['faculty_id']} - {f['name']}": f["faculty_id"] for f in faculty}}

    with tab_list:
        sem = st.selectbox("Semester", ["All"] + list(range(1, 9)))
        st.dataframe(list_courses(semester=None if sem == "All" else sem), hide_index=True)

    with tab_add:
        with st.form("add_course"):
            c1, c2 = st.columns(2)
            code = c1.text_input("Course code (e.g. AI301)")
            name = c2.text_input("Course name")
            dept = c1.text_input("Department", value="AIML")
            sem = c2.number_input("Semester", 1, 8, 3)
            credits = c1.number_input("Credits", 1, 10, 3)
            fac = c2.selectbox("Faculty", list(fac_opts))
            prac = st.checkbox("Has practical component", value=True)
            go = st.form_submit_button("Add course")
        if go:
            try:
                add_course(code, name, dept, sem, credits, fac_opts[fac], prac)
                st.success("Course added.")
            except ValueError as e:
                st.error(str(e))

    courses = list_courses()
    labels = {f"{r.course_code} - {r.course_name} (Sem {r.semester})": int(r.course_id)
              for r in courses.itertuples()}
    with tab_edit:
        if not labels:
            st.info("No courses yet.")
        else:
            cid = labels[st.selectbox("Course", list(labels), key="edit_course")]
            cur = courses[courses.course_id == cid].iloc[0]
            with st.form("edit_course"):
                name = st.text_input("Course name", cur.course_name)
                credits = st.number_input("Credits", 1, 10, int(cur.credits))
                prac = st.checkbox("Has practical component", bool(cur.has_practical))
                active = st.checkbox("Active", bool(cur.is_active))
                fac = st.selectbox("Faculty", list(fac_opts),
                                   index=next((i for i, v in enumerate(fac_opts.values())
                                               if v == cur.faculty_id), 0))
                save = st.form_submit_button("Save")
            if save:
                try:
                    update_course(cid, course_name=name, credits=int(credits),
                                  has_practical=int(prac), is_active=int(active),
                                  faculty_id=fac_opts[fac])
                    st.success("Course updated.")
                except ValueError as e:
                    st.error(str(e))

    with tab_enrol:
        if labels:
            cid = labels[st.selectbox("Course", list(labels), key="enrol_course")]
            if st.button("Enrol all students of this course's department & semester"):
                st.success(f"{enroll_cohort(cid)} new enrolment(s).")
            st.dataframe(course_students(cid), hide_index=True)
            sids = [r["student_id"] for r in query("SELECT student_id FROM students ORDER BY 1")]
            if sids:
                c1, c2 = st.columns(2)
                one = c1.selectbox("Enrol / remove a single student", sids)
                if c2.button("Enrol"):
                    st.info("Enrolled." if enroll_student(one, cid) else "Already enrolled.")
                if c2.button("Remove from course"):
                    unenroll_student(one, cid)
                    st.info("Removed.")
