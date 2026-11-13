"""Login, logout, session handling and forced password change."""

from __future__ import annotations

from datetime import datetime, timedelta

from authentication.security import hash_password, validate_password, verify_password
from database.db import execute, query, query_one

MAX_ATTEMPTS = 5
LOCK_MINUTES = 10
_DUMMY_HASH = hash_password("dummy-password-for-timing")
GENERIC_ERROR = "Invalid username or password."


def _session_user(row: dict) -> dict:
    return {
        "user_id": row["user_id"], "username": row["username"], "role": row["role"],
        "full_name": row["full_name"], "ref_id": row["ref_id"],
        "must_reset": bool(row["must_reset"]),
    }


def authenticate(username: str, password: str) -> tuple[dict | None, str]:
    """Check credentials. Returns (user, message); user is None on failure."""
    username = (username or "").strip()
    if not username or not password:
        return None, "Enter both username and password."

    row = query_one("SELECT * FROM users WHERE username = ?", (username,))
    if row is None:
        verify_password(password, _DUMMY_HASH)  # keep timing similar
        return None, GENERIC_ERROR

    if row["locked_until"] and datetime.fromisoformat(row["locked_until"]) > datetime.now():
        return None, f"Account temporarily locked after too many failed attempts. Try again in {LOCK_MINUTES} minutes."

    if not verify_password(password, row["password_hash"]):
        attempts = row["failed_attempts"] + 1
        if attempts >= MAX_ATTEMPTS:
            until = (datetime.now() + timedelta(minutes=LOCK_MINUTES)).isoformat()
            execute("UPDATE users SET failed_attempts = 0, locked_until = ? WHERE user_id = ?",
                    (until, row["user_id"]))
        else:
            execute("UPDATE users SET failed_attempts = ? WHERE user_id = ?",
                    (attempts, row["user_id"]))
        return None, GENERIC_ERROR

    if not row["is_active"]:
        return None, "This account has been deactivated. Contact the administrator."

    execute("UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login = ? "
            "WHERE user_id = ?", (datetime.now().isoformat(timespec="seconds"), row["user_id"]))
    return _session_user(row), "OK"


def change_password(user_id: int, new_password: str) -> list[str]:
    """Set a new password. Returns policy errors (empty list on success)."""
    errors = validate_password(new_password)
    if errors:
        return errors
    execute("UPDATE users SET password_hash = ?, must_reset = 0 WHERE user_id = ?",
            (hash_password(new_password), user_id))
    return []


def get_user(user_id: int) -> dict | None:
    row = query_one("SELECT * FROM users WHERE user_id = ?", (user_id,))
    return _session_user(row) if row else None


# ----------------------------------------------------------- Streamlit UI
def current_user() -> dict | None:
    import streamlit as st

    user = st.session_state.get("user")
    if user:  # re-check the account is still active on every run
        row = query("SELECT is_active FROM users WHERE user_id = ?", (user["user_id"],))
        if not row or not row[0]["is_active"]:
            st.session_state.clear()
            return None
    return user


def logout() -> None:
    import streamlit as st

    st.session_state.clear()
    st.rerun()


def render_login() -> None:
    import streamlit as st

    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        st.markdown("<div class='login-card'><h1>SRAMS</h1>"
                    "<p>Student Record &amp; Academic Management System</p></div>",
                    unsafe_allow_html=True)
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in")
        if submitted:
            user, message = authenticate(username, password)
            if user:
                st.session_state["user"] = user
                st.rerun()
            else:
                st.error(message)
        st.caption("Forgot your password? Ask the administrator to reset it.")


def render_force_reset(user: dict) -> None:
    import streamlit as st

    st.subheader("Set a new password")
    st.info("For security you must choose a new password before continuing.")
    with st.form("reset_form"):
        pw1 = st.text_input("New password", type="password")
        pw2 = st.text_input("Confirm new password", type="password")
        go = st.form_submit_button("Update password")
    if go:
        if pw1 != pw2:
            st.error("Passwords do not match.")
            return
        errors = change_password(user["user_id"], pw1)
        if errors:
            for e in errors:
                st.error(e)
        else:
            st.session_state["user"]["must_reset"] = False
            st.success("Password updated.")
            st.rerun()
