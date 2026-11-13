"""SRAMS - Student Record and Academic Management System (Streamlit entry point).

Run with:  streamlit run app.py
"""

import os

import streamlit as st

from authentication.login import current_user, logout, render_force_reset, render_login
from authentication.register import render_user_management
from authentication.security import allowed_pages, can_access
from database.db import get_setting, init_database
from modules import (attendance, course_management, dashboard, marks_management,
                     notifications, performance, reports, student_management, student_portal)
from utils.helpers import load_css

st.set_page_config(page_title="SRAMS", page_icon="🎓", layout="wide")


@st.cache_resource
def _bootstrap() -> bool:
    init_database()
    if os.environ.get("SRAMS_AUTO_SEED") == "1":  # optional: demo data on first run
        from seed_data import seed
        seed()
    return True


_bootstrap()
load_css()

user = current_user()
if not user:
    render_login()
    st.stop()
if user.get("must_reset"):
    render_force_reset(user)
    st.stop()

# page name -> function; role access is enforced both here and inside each module
PAGES = {
    "admin": {
        "Dashboard": dashboard.render, "Students": student_management.render,
        "Courses": course_management.render, "Attendance": attendance.render,
        "Marks & Results": marks_management.render, "Analytics": performance.render,
        "AI Analytics": performance.render_ai, "Notifications": notifications.render,
        "Reports": reports.render, "User Management": render_user_management,
    },
    "faculty": {
        "Dashboard": dashboard.render, "Attendance": attendance.render,
        "Marks & Results": marks_management.render, "Analytics": performance.render,
        "AI Analytics": performance.render_ai, "Notifications": notifications.render,
        "Reports": reports.render,
    },
    "student": {
        "Dashboard": dashboard.render, "My Profile": student_portal.render_profile,
        "My Attendance": attendance.render_student, "My Results": marks_management.render_student,
        "Academic Assistant": student_portal.render_assistant,
        "Notifications": notifications.render, "Reports": reports.render,
    },
}

with st.sidebar:
    st.markdown(f"<div class='side-brand'>🎓 SRAMS<br><small>{get_setting('institution_name', '')}</small></div>",
                unsafe_allow_html=True)
    unread = notifications.unread_count(user["user_id"])
    st.markdown(f"**{user['full_name']}**  \n<small>{user['role'].title()}"
                f"{f' - {unread} unread' if unread else ''}</small>", unsafe_allow_html=True)
    page = st.radio("Navigate", allowed_pages(user["role"]), label_visibility="collapsed")
    st.divider()
    if st.button("Log out"):
        logout()

if not can_access(user["role"], page):  # defence in depth
    st.error("You are not authorised to view this page.")
    st.stop()

try:
    PAGES[user["role"]][page](user)
except PermissionError as exc:
    st.error(str(exc))
