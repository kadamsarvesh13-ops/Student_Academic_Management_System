"""Pure calculation helpers plus small Streamlit UI helpers."""

from __future__ import annotations

import math
import re
import smtplib
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_GRADE_SCALE = [[90, "O", 10], [80, "A+", 9], [70, "A", 8], [60, "B+", 7],
                       [50, "B", 6], [40, "C", 5], [0, "F", 0]]
EXAM_TYPES = ["Internal", "Practical", "External"]


# ------------------------------------------------------------ calculations
def attendance_percentage(present: int, total: int) -> float:
    """Attendance % = present / total * 100 (0 when no lectures yet)."""
    if total <= 0:
        return 0.0
    return round(present / total * 100, 2)


def lectures_needed(present: int, total: int, threshold: float = 75.0) -> int | None:
    """Consecutive lectures that must all be attended to reach `threshold` %.

    Returns 0 if already at/above the threshold, or None when it is
    mathematically impossible (threshold >= 100 and a lecture was missed).
    """
    if total <= 0 or present * 100 >= threshold * total:
        return 0
    if threshold >= 100:
        return None
    return max(math.ceil((threshold * total - 100 * present) / (100 - threshold)), 0)


def grade_for(percentage: float, scale=None) -> tuple[str, int]:
    """Map a percentage to (grade, grade points) using a configurable scale."""
    scale = sorted(scale or DEFAULT_GRADE_SCALE, key=lambda r: r[0], reverse=True)
    for minimum, grade, points in scale:
        if percentage >= minimum:
            return grade, points
    return scale[-1][1], scale[-1][2]


# -------------------------------------------------------------- validation
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MOBILE_RE = re.compile(r"^[6-9]\d{9}$")
DEPT_RE = re.compile(r"^[A-Za-z0-9&-]{2,10}$")


def is_valid_email(value: str) -> bool:
    return bool(value and EMAIL_RE.match(value.strip()))


def is_valid_mobile(value: str) -> bool:
    return bool(value and MOBILE_RE.match(value.strip()))


def to_iso_date(value) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return datetime.strptime(str(value), "%Y-%m-%d").date().isoformat()


# ------------------------------------------------------------------- email
def send_email(to_address: str, subject: str, body: str) -> bool:
    """Send an email via SMTP if SRAMS_SMTP_* env vars are set.

    Returns False (and does nothing) when SMTP is not configured, so the
    rest of the app works without any mail server.
    """
    host = os.environ.get("SRAMS_SMTP_HOST")
    if not host or not to_address:
        return False
    msg = EmailMessage()
    msg["From"] = os.environ.get("SRAMS_SMTP_FROM", os.environ.get("SRAMS_SMTP_USER", ""))
    msg["To"] = to_address
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, int(os.environ.get("SRAMS_SMTP_PORT", "587")), timeout=15) as s:
            s.starttls()
            if os.environ.get("SRAMS_SMTP_USER"):
                s.login(os.environ["SRAMS_SMTP_USER"], os.environ.get("SRAMS_SMTP_PASSWORD", ""))
            s.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError):
        return False


# ------------------------------------------------------------ Streamlit UI
def load_css() -> None:
    import streamlit as st

    css = (BASE_DIR / "assets" / "style.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def show_fig(fig) -> None:
    """Render a Plotly figure across Streamlit versions."""
    import inspect

    import streamlit as st

    fig.update_layout(margin=dict(l=10, r=10, t=40, b=10), template="plotly_white")
    # Newer Streamlit uses width="stretch"; older versions use use_container_width.
    if "width" in inspect.signature(st.plotly_chart).parameters:
        st.plotly_chart(fig, width="stretch")
    else:
        st.plotly_chart(fig, use_container_width=True)


def page_header(title: str, subtitle: str = "") -> None:
    import streamlit as st

    st.markdown(f"<div class='page-title'>{title}</div>", unsafe_allow_html=True)
    if subtitle:
        st.caption(subtitle)
