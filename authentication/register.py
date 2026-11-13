"""Account creation and administration (admin-only; no public sign-up)."""

from __future__ import annotations

import secrets
import string
from datetime import date

import pandas as pd

from authentication.security import hash_password, require_role, validate_password
from database.db import df_query, execute, query, query_one, transaction
from utils.helpers import DEPT_RE, is_valid_email

ROLES = ("admin", "faculty", "student")


def generate_temp_password() -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(10))
        if not validate_password(pw):
            return pw


def create_user_in(conn, username: str, password: str, role: str, full_name: str,
                   ref_id: str | None = None, must_reset: bool = True) -> int:
    """Insert a user using an existing transaction connection."""
    if role not in ROLES:
        raise ValueError("Invalid role.")
    errors = validate_password(password)
    if errors:
        raise ValueError(" ".join(errors))
    if not username or not username.strip():
        raise ValueError("Username is required.")
    cur = conn.execute(
        "INSERT INTO users(username, password_hash, role, full_name, ref_id, must_reset) "
        "VALUES(?,?,?,?,?,?)",
        (username.strip(), hash_password(password), role, full_name.strip(), ref_id,
         int(must_reset)),
    )
    return cur.lastrowid


def create_user(username, password, role, full_name, ref_id=None, must_reset=True) -> int:
    with transaction() as conn:
        return create_user_in(conn, username, password, role, full_name, ref_id, must_reset)


def create_faculty(name: str, email: str, department: str) -> dict:
    """Create a faculty record plus a login. Returns the one-time temp password."""
    if not name.strip():
        raise ValueError("Name is required.")
    if not is_valid_email(email):
        raise ValueError("Enter a valid email address.")
    if not DEPT_RE.match(department or ""):
        raise ValueError("Department must be 2-10 letters/digits (e.g. AIML).")
    rows = query("SELECT faculty_id FROM faculty")
    nums = [int(r["faculty_id"][3:]) for r in rows if r["faculty_id"][3:].isdigit()]
    faculty_id = f"FAC{(max(nums) if nums else 0) + 1:03d}"
    temp = generate_temp_password()
    with transaction() as conn:
        conn.execute("INSERT INTO faculty(faculty_id, name, email, department) VALUES(?,?,?,?)",
                     (faculty_id, name.strip(), email.strip(), department.upper()))
        create_user_in(conn, faculty_id.lower(), temp, "faculty", name, faculty_id)
    return {"faculty_id": faculty_id, "username": faculty_id.lower(), "temp_password": temp}


def set_active(user_id: int, active: bool, actor_id: int | None = None) -> None:
    if actor_id is not None and user_id == actor_id and not active:
        raise ValueError("You cannot deactivate your own account.")
    execute("UPDATE users SET is_active = ? WHERE user_id = ?", (int(active), user_id))


def admin_reset_password(user_id: int) -> str:
    """Issue a temporary password; the user must change it at next login."""
    if not query_one("SELECT 1 AS x FROM users WHERE user_id = ?", (user_id,)):
        raise ValueError("User not found.")
    temp = generate_temp_password()
    execute("UPDATE users SET password_hash = ?, must_reset = 1, failed_attempts = 0, "
            "locked_until = NULL WHERE user_id = ?", (hash_password(temp), user_id))
    return temp


def list_users() -> pd.DataFrame:
    return df_query("SELECT user_id, username, full_name, role, ref_id, is_active, "
                    "last_login FROM users ORDER BY role, username")


def list_faculty() -> list[dict]:
    return query("SELECT * FROM faculty ORDER BY faculty_id")


# ----------------------------------------------------------- Streamlit UI
def render_user_management(user: dict) -> None:
    import streamlit as st
    from utils.helpers import page_header

    require_role(user, "admin")
    page_header("User Management", "Create faculty accounts, reset passwords, activate or deactivate users.")
    tab_users, tab_fac = st.tabs(["All users", "Add faculty"])

    with tab_users:
        df = list_users()
        st.dataframe(df, hide_index=True)
        options = {f"{r.username} ({r.role})": int(r.user_id) for r in df.itertuples()}
        choice = st.selectbox("Select user", list(options))
        uid = options[choice]
        c1, c2, c3 = st.columns(3)
        if c1.button("Reset password"):
            st.success(f"Temporary password (shown once): {admin_reset_password(uid)}")
        if c2.button("Activate"):
            set_active(uid, True)
            st.rerun()
        if c3.button("Deactivate"):
            try:
                set_active(uid, False, actor_id=user["user_id"])
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    with tab_fac:
        with st.form("add_faculty"):
            name = st.text_input("Full name")
            email = st.text_input("Email")
            dept = st.text_input("Department", value="AIML")
            go = st.form_submit_button("Create faculty")
        if go:
            try:
                res = create_faculty(name, email, dept)
                st.success(f"Created {res['faculty_id']}. Username: {res['username']} | "
                           f"Temporary password (shown once): {res['temp_password']}")
            except Exception as e:  # noqa: BLE001 - shown to the admin
                st.error(f"Could not create faculty: {e}")
