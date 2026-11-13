"""Module 2 - Student management (admin)."""

from __future__ import annotations

import sqlite3
from datetime import date

import pandas as pd

from authentication.register import create_user_in, generate_temp_password
from authentication.security import require_role
from database.db import df_query, query, query_one, transaction
from utils.helpers import DEPT_RE, is_valid_email, is_valid_mobile

FIELDS = ("name", "email", "mobile", "department", "semester", "division", "previous_percentage")


def generate_student_id(department: str, year: int | None = None) -> str:
    """e.g. AIML2026001 -- department + year + 3-digit running number."""
    prefix = f"{department.upper()}{year or date.today().year}"
    rows = query("SELECT student_id FROM students WHERE student_id LIKE ?", (prefix + "%",))
    nums = [int(r["student_id"][len(prefix):]) for r in rows
            if r["student_id"][len(prefix):].isdigit()]
    return f"{prefix}{(max(nums) if nums else 0) + 1:03d}"


def validate_student(data: dict) -> dict[str, str]:
    errors = {}
    if not str(data.get("name", "")).strip():
        errors["name"] = "Name is required."
    if not is_valid_email(str(data.get("email", ""))):
        errors["email"] = "Enter a valid email address."
    mobile = str(data.get("mobile") or "").strip()
    if mobile and not is_valid_mobile(mobile):
        errors["mobile"] = "Mobile must be a 10-digit number starting with 6-9."
    if not DEPT_RE.match(str(data.get("department", ""))):
        errors["department"] = "Department must be 2-10 letters/digits (e.g. AIML)."
    try:
        if not 1 <= int(data.get("semester", 0)) <= 8:
            raise ValueError
    except (TypeError, ValueError):
        errors["semester"] = "Semester must be between 1 and 8."
    division = str(data.get("division", "")).strip()
    if not division or len(division) > 2:
        errors["division"] = "Division is required (e.g. A)."
    prev = data.get("previous_percentage")
    if prev not in (None, ""):
        try:
            if not 0 <= float(prev) <= 100:
                raise ValueError
        except (TypeError, ValueError):
            errors["previous_percentage"] = "Must be between 0 and 100."
    return errors


def _clean(data: dict) -> dict:
    prev = data.get("previous_percentage")
    return {
        "name": data["name"].strip(),
        "email": data["email"].strip(),
        "mobile": (data.get("mobile") or "").strip() or None,
        "department": data["department"].strip().upper(),
        "semester": int(data["semester"]),
        "division": data["division"].strip().upper(),
        "previous_percentage": None if prev in (None, "") else float(prev),
    }


def add_student(data: dict, create_account: bool = True) -> dict:
    """Register a student (and a login). Raises ValueError on bad input/duplicates."""
    errors = validate_student(data)
    if errors:
        raise ValueError("; ".join(errors.values()))
    row = _clean(data)
    temp = generate_temp_password() if create_account else None
    for _ in range(3):  # retry if two admins grab the same ID at once
        sid = generate_student_id(row["department"])
        try:
            with transaction() as conn:
                conn.execute(
                    "INSERT INTO students(student_id, name, email, mobile, department, "
                    "semester, division, previous_percentage) VALUES(?,?,?,?,?,?,?,?)",
                    (sid, row["name"], row["email"], row["mobile"], row["department"],
                     row["semester"], row["division"], row["previous_percentage"]))
                if create_account:
                    create_user_in(conn, sid.lower(), temp, "student", row["name"], sid)
            return {"student_id": sid, "username": sid.lower() if create_account else None,
                    "temp_password": temp}
        except sqlite3.IntegrityError as exc:
            if "email" in str(exc).lower():
                raise ValueError("A student with this email already exists.") from exc
            if "students.student_id" in str(exc) or "users.username" in str(exc):
                continue
            raise
    raise ValueError("Could not generate a unique student ID. Please retry.")


def update_student(student_id: str, data: dict) -> None:
    errors = validate_student(data)
    if errors:
        raise ValueError("; ".join(errors.values()))
    if not get_student(student_id):
        raise ValueError("Student not found.")
    row = _clean(data)
    try:
        with transaction() as conn:
            conn.execute(
                "UPDATE students SET name=?, email=?, mobile=?, department=?, semester=?, "
                "division=?, previous_percentage=? WHERE student_id=?",
                (row["name"], row["email"], row["mobile"], row["department"], row["semester"],
                 row["division"], row["previous_percentage"], student_id))
            conn.execute("UPDATE users SET full_name=? WHERE role='student' AND ref_id=?",
                         (row["name"], student_id))
    except sqlite3.IntegrityError as exc:
        raise ValueError("A student with this email already exists.") from exc


def delete_student(student_id: str) -> None:
    """Remove the student, their login and (via CASCADE) all academic records."""
    with transaction() as conn:
        conn.execute("DELETE FROM users WHERE role='student' AND ref_id=?", (student_id,))
        conn.execute("DELETE FROM students WHERE student_id=?", (student_id,))


def get_student(student_id: str) -> dict | None:
    return query_one("SELECT * FROM students WHERE student_id = ?", (student_id,))


def search_students(text: str = "", department: str | None = None,
                    semester: int | None = None, division: str | None = None) -> pd.DataFrame:
    sql = ("SELECT student_id, name, department, semester, division, email, mobile, "
           "previous_percentage FROM students WHERE 1=1")
    params: list = []
    if text.strip():
        sql += " AND (name LIKE ? OR student_id LIKE ?)"
        params += [f"%{text.strip()}%"] * 2
    if department:
        sql += " AND department = ?"
        params.append(department)
    if semester:
        sql += " AND semester = ?"
        params.append(int(semester))
    if division:
        sql += " AND division = ?"
        params.append(division)
    return df_query(sql + " ORDER BY student_id", tuple(params))


def departments() -> list[str]:
    return [r["department"] for r in query("SELECT DISTINCT department FROM students ORDER BY 1")]


# ----------------------------------------------------------- Streamlit UI
def render(user: dict) -> None:
    import streamlit as st
    from utils.helpers import page_header

    require_role(user, "admin")
    page_header("Student Management", "Register, search, update and remove student records.")
    tab_list, tab_add, tab_edit = st.tabs(["Search & profiles", "Register student", "Update / delete"])

    with tab_list:
        c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
        text = c1.text_input("Search by name or ID")
        dept = c2.selectbox("Department", ["All"] + departments())
        sem = c3.selectbox("Semester", ["All"] + list(range(1, 9)))
        div = c4.selectbox("Division", ["All", "A", "B", "C", "D"])
        df = search_students(text, None if dept == "All" else dept,
                             None if sem == "All" else sem, None if div == "All" else div)
        st.caption(f"{len(df)} student(s)")
        st.dataframe(df, hide_index=True)
        if len(df):
            sid = st.selectbox("View full profile", df["student_id"])
            from modules.reports import profile_report
            prof, courses = profile_report(sid)
            st.json(prof)
            st.dataframe(courses, hide_index=True)

    with tab_add:
        with st.form("add_student", clear_on_submit=False):
            c1, c2 = st.columns(2)
            name = c1.text_input("Full name")
            email = c2.text_input("Email")
            mobile = c1.text_input("Mobile (10 digits)")
            dept = c2.text_input("Department", value="AIML")
            semester = c1.number_input("Semester", 1, 8, 3)
            division = c2.text_input("Division", value="A")
            prev = c1.number_input("Previous semester % (optional, 0 = none)", 0.0, 100.0, 0.0)
            go = st.form_submit_button("Register student")
        if go:
            try:
                res = add_student({"name": name, "email": email, "mobile": mobile,
                                   "department": dept, "semester": semester,
                                   "division": division,
                                   "previous_percentage": prev if prev > 0 else None})
                st.success(f"Registered {res['student_id']}. Login: {res['username']} | "
                           f"Temporary password (shown once): {res['temp_password']}")
            except ValueError as e:
                st.error(str(e))

    with tab_edit:
        df = search_students()
        if df.empty:
            st.info("No students yet.")
            return
        sid = st.selectbox("Student", df["student_id"], key="edit_sid")
        cur = get_student(sid)
        with st.form("edit_student"):
            c1, c2 = st.columns(2)
            name = c1.text_input("Full name", cur["name"])
            email = c2.text_input("Email", cur["email"])
            mobile = c1.text_input("Mobile", cur["mobile"] or "")
            dept = c2.text_input("Department", cur["department"])
            semester = c1.number_input("Semester", 1, 8, int(cur["semester"]))
            division = c2.text_input("Division", cur["division"])
            prev = c1.number_input("Previous semester %", 0.0, 100.0,
                                   float(cur["previous_percentage"] or 0.0))
            save = st.form_submit_button("Save changes")
        if save:
            try:
                update_student(sid, {"name": name, "email": email, "mobile": mobile,
                                     "department": dept, "semester": semester,
                                     "division": division,
                                     "previous_percentage": prev if prev > 0 else None})
                st.success("Student updated.")
            except ValueError as e:
                st.error(str(e))
        st.divider()
        confirm = st.checkbox(f"I understand deleting {sid} permanently removes all their records")
        if st.button("Delete student", disabled=not confirm):
            delete_student(sid)
            st.success(f"{sid} deleted.")
            st.rerun()
