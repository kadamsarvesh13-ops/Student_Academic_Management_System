"""Student-only pages: profile and academic assistant chatbot."""

from __future__ import annotations

from authentication.security import require_role
from database.db import query_one


def render_profile(user: dict) -> None:
    import streamlit as st

    from utils.helpers import page_header

    require_role(user, "student")
    page_header("My Profile")
    prof = query_one("SELECT student_id, name, department, semester, division, email, mobile "
                     "FROM students WHERE student_id=?", (user["ref_id"],))
    import pandas as pd

    st.dataframe(pd.DataFrame(list(prof.items()), columns=["Field", "Value"]), hide_index=True)
    st.subheader("Change password")
    from authentication.login import change_password

    with st.form("pw_change"):
        p1 = st.text_input("New password", type="password")
        p2 = st.text_input("Confirm", type="password")
        go = st.form_submit_button("Update password")
    if go:
        if p1 != p2:
            st.error("Passwords do not match.")
        else:
            errs = change_password(user["user_id"], p1)
            for e in errs:
                st.error(e)
            if not errs:
                st.success("Password updated.")


def render_assistant(user: dict) -> None:
    import streamlit as st

    from ai.chatbot import HELP, answer
    from utils.helpers import page_header

    require_role(user, "student")
    page_header("Academic Assistant", "Ask about your own attendance, marks, results and assignments.")
    hist = st.session_state.setdefault("chat", [{"role": "assistant", "content": HELP}])
    for m in hist:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
    q = st.chat_input("Ask a question...")
    if q:
        hist.append({"role": "user", "content": q})
        hist.append({"role": "assistant", "content": answer(user["ref_id"], q)})
        st.rerun()
