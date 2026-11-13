"""Module 7a - Notifications and announcements."""

from __future__ import annotations

import pandas as pd

from authentication.security import require_role
from database.db import attendance_threshold, df_query, execute, query, query_one, transaction
from utils.helpers import send_email


def create_notification(user_id: int, message: str) -> int:
    return execute("INSERT INTO notifications(user_id, message) VALUES(?,?)", (user_id, message))


def _recently_sent(user_id: int, prefix: str, days: int = 7) -> bool:
    return query_one(
        "SELECT 1 AS x FROM notifications WHERE user_id=? AND message LIKE ? "
        "AND created_at >= datetime('now', ?)", (user_id, prefix + "%", f"-{days} days")
    ) is not None


def list_notifications(user_id: int, unread_only: bool = False) -> pd.DataFrame:
    sql = "SELECT notification_id, message, created_at, is_read FROM notifications WHERE user_id=?"
    if unread_only:
        sql += " AND is_read=0"
    return df_query(sql + " ORDER BY created_at DESC, notification_id DESC", (user_id,))


def unread_count(user_id: int) -> int:
    return query_one("SELECT COUNT(*) AS n FROM notifications WHERE user_id=? AND is_read=0",
                     (user_id,))["n"]


def mark_all_read(user_id: int) -> None:
    execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (user_id,))


def add_announcement(title: str, description: str, created_by: str,
                     audience: str = "all") -> int:
    """Post a notice and notify users. audience: all | students | faculty."""
    if not title.strip() or not description.strip():
        raise ValueError("Title and description are required.")
    if audience not in ("all", "students", "faculty"):
        raise ValueError("Invalid audience.")
    roles = {"all": ("student", "faculty"), "students": ("student",), "faculty": ("faculty",)}[audience]
    with transaction() as conn:
        aid = conn.execute("INSERT INTO announcements(title, description, created_by) "
                           "VALUES(?,?,?)", (title.strip(), description.strip(), created_by)).lastrowid
        marks = ",".join("?" * len(roles))
        conn.execute(
            f"INSERT INTO notifications(user_id, message) SELECT user_id, ? FROM users "
            f"WHERE is_active=1 AND role IN ({marks})",
            (f"Notice: {title.strip()}", *roles))
    return aid


def list_announcements(limit: int = 20) -> pd.DataFrame:
    return df_query("SELECT announcement_id, title, description, created_at, created_by "
                    "FROM announcements ORDER BY created_at DESC, announcement_id DESC LIMIT ?",
                    (limit,))


def publish_results(semester: int, department: str | None, published_by: str) -> int:
    """Announce result publication and notify the affected students."""
    sql = "SELECT s.student_id, u.user_id, s.email FROM students s JOIN users u ON u.ref_id=s.student_id AND u.role='student' WHERE s.semester=?"
    params: list = [int(semester)]
    if department:
        sql += " AND s.department=?"
        params.append(department)
    targets = query(sql, tuple(params))
    scope = f"Semester {semester}" + (f" ({department})" if department else "")
    msg = f"Results for {scope} have been published. Check My Results."
    with transaction() as conn:
        conn.execute("INSERT INTO announcements(title, description, created_by) VALUES(?,?,?)",
                     (f"Results published: {scope}", msg, published_by))
        conn.executemany("INSERT INTO notifications(user_id, message) VALUES(?,?)",
                         [(t["user_id"], msg) for t in targets])
    for t in targets:
        send_email(t["email"], "Results published", msg)
    return len(targets)


def send_low_attendance_alerts(faculty_id: str | None = None) -> int:
    """Notify students below the threshold (and the faculty who teach them).

    A student gets at most one alert per course per week. Returns alerts created.
    Emails are also sent when SMTP is configured (see README).
    """
    from modules.attendance import low_attendance_report

    th = attendance_threshold()
    low = low_attendance_report(th, faculty_id)
    if low.empty:
        return 0
    user_ids = {r["ref_id"]: r["user_id"] for r in query(
        "SELECT user_id, ref_id FROM users WHERE role IN ('student','faculty') AND ref_id IS NOT NULL")}
    emails = {r["student_id"]: r["email"] for r in query("SELECT student_id, email FROM students")}
    created = 0
    for r in low.itertuples():
        uid = user_ids.get(r.student_id)
        if uid is None:
            continue
        prefix = f"Low attendance in {r.course_code}"
        if _recently_sent(uid, prefix):
            continue
        need = (f"attend the next {r.needed} lecture(s) to reach {th:.0f}%"
                if r.needed is not None else "the threshold can no longer be reached")
        msg = f"{prefix}: {r.percentage:.1f}% (required {th:.0f}%). You need to {need}."
        create_notification(uid, msg)
        send_email(emails.get(r.student_id, ""), "Low attendance alert", msg)
        created += 1
    # one summary per faculty member
    for fid, grp in low.groupby("faculty_id", dropna=True):
        uid = user_ids.get(fid)
        if uid is None or _recently_sent(uid, "Attendance alert summary"):
            continue
        create_notification(uid, f"Attendance alert summary: {grp['student_id'].nunique()} "
                                 f"student(s) below {th:.0f}% in your courses.")
        created += 1
    return created


# ----------------------------------------------------------- Streamlit UI
def render(user: dict) -> None:
    import streamlit as st
    from utils.helpers import page_header

    page_header("Notifications", "Alerts, announcements and academic notices.")
    notes = list_notifications(user["user_id"])
    tab_inbox, tab_notice = st.tabs(["My notifications", "Announcements"])
    with tab_inbox:
        if notes.empty:
            st.info("You have no notifications.")
        else:
            if st.button("Mark all as read"):
                mark_all_read(user["user_id"])
                st.rerun()
            for r in notes.head(50).itertuples():
                st.markdown(f"{'**' if not r.is_read else ''}{r.message}{'**' if not r.is_read else ''}"
                            f"  \n<small>{r.created_at}</small>", unsafe_allow_html=True)
                st.divider()
    with tab_notice:
        for r in list_announcements().itertuples():
            with st.expander(f"{r.title} - {r.created_at[:10]}"):
                st.write(r.description)
        if user["role"] in ("admin", "faculty"):
            st.subheader("Post an announcement")
            with st.form("announce"):
                title = st.text_input("Title")
                desc = st.text_area("Description")
                aud = st.selectbox("Audience", ["all", "students", "faculty"])
                go = st.form_submit_button("Publish")
            if go:
                try:
                    add_announcement(title, desc, user["username"], aud)
                    st.success("Announcement published.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
        if user["role"] == "admin":
            st.subheader("Publish results")
            c1, c2 = st.columns(2)
            sem = c1.number_input("Semester", 1, 8, 3, key="pub_sem")
            dept = c2.text_input("Department (blank = all)", key="pub_dept").strip().upper() or None
            if st.button("Publish & notify students"):
                st.success(f"Notified {publish_results(int(sem), dept, user['username'])} student(s).")
