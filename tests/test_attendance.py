import sqlite3
from datetime import date, timedelta

import pytest

from database.db import execute, query
from modules.attendance import (course_attendance_summary, low_attendance_report, mark_attendance,
                                monthly_report, overall_attendance, student_attendance_summary)
from modules.notifications import send_low_attendance_alerts
from utils.helpers import attendance_percentage, lectures_needed


def test_percentage_formula_from_spec():
    assert attendance_percentage(34, 40) == 85.0
    assert attendance_percentage(0, 0) == 0.0
    assert attendance_percentage(1, 3) == 33.33


@pytest.mark.parametrize("present,total,th,expected", [
    (28, 40, 75, 8),     # 36/48 = 75%
    (30, 40, 75, 0),     # exactly at threshold
    (34, 40, 75, 0),
    (0, 4, 75, 12),      # 12/16
    (39, 40, 100, None),  # 100% impossible after a miss
    (40, 40, 100, 0),
    (0, 0, 75, 0),
])
def test_lectures_needed(present, total, th, expected):
    assert lectures_needed(present, total, th) == expected


def test_lectures_needed_is_minimal_and_sufficient():
    for total in range(1, 30):
        for present in range(total + 1):
            n = lectures_needed(present, total, 75)
            assert (present + n) / (total + n) >= 0.75 - 1e-9
            if n > 0:
                assert (present + n - 1) / (total + n - 1) < 0.75


def test_saving_twice_never_duplicates(world):
    cid, sid = world["course"], world["students"][0]
    mark_attendance(cid, "2026-01-05", {sid: "Present"})
    mark_attendance(cid, "2026-01-05", {sid: "Absent"})  # correction
    rows = query("SELECT * FROM attendance WHERE student_id=? AND course_id=?", (sid, cid))
    assert len(rows) == 1 and rows[0]["status"] == "Absent"


def test_database_itself_blocks_duplicates(world):
    cid, sid = world["course"], world["students"][0]
    mark_attendance(cid, "2026-01-05", {sid: "Present"})
    with pytest.raises(sqlite3.IntegrityError):
        execute("INSERT INTO attendance(student_id, course_id, lecture_date, status) "
                "VALUES(?,?,?,?)", (sid, cid, "2026-01-05", "Present"))


def test_rejects_future_date_bad_status_and_unenrolled(world):
    cid, sid = world["course"], world["students"][0]
    with pytest.raises(ValueError, match="future"):
        mark_attendance(cid, date.today() + timedelta(days=1), {sid: "Present"})
    with pytest.raises(ValueError, match="Present"):
        mark_attendance(cid, "2026-01-05", {sid: "Late"})
    with pytest.raises(ValueError, match="enrolled"):
        mark_attendance(cid, "2026-01-05", {"CSE2026999": "Present"})
    with pytest.raises(ValueError):
        mark_attendance(cid, "2026-01-05", {})
    assert query("SELECT 1 FROM attendance") == []  # nothing partially saved


def _record(world, sid, present, absent, start="2026-02-02"):
    d = date.fromisoformat(start)
    for i in range(present + absent):
        mark_attendance(world["course"], d + timedelta(days=i), {sid: "Present" if i < present else "Absent"})


def test_student_summary_matches_hand_calculation(world):
    sid = world["students"][0]
    _record(world, sid, 34, 6)
    row = student_attendance_summary(sid).set_index("course_code").loc["AI301"]
    assert (row.total, row.present, row.absent, row.percentage) == (40, 34, 6, 85.0)
    assert row.status == "OK" and row.needed == 0
    assert overall_attendance(sid) == 85.0


def test_no_lectures_is_not_flagged_low(world):
    df = student_attendance_summary(world["students"][0])
    assert set(df["status"]) == {"No lectures"}
    assert overall_attendance(world["students"][0]) is None


def test_low_attendance_report_and_needed_lectures(world):
    a, b = world["students"][:2]
    _record(world, a, 28, 12)   # 70%
    _record(world, b, 36, 4)    # 90%
    low = low_attendance_report(75)
    assert list(low["student_id"]) == [a]
    assert low.iloc[0]["needed"] == 8
    assert len(low_attendance_report(95)) == 2


def test_course_summary_covers_all_enrolled(world):
    assert len(course_attendance_summary(world["course"])) == 3


def test_monthly_report(world):
    sid = world["students"][0]
    mark_attendance(world["course"], "2026-01-05", {sid: "Present"})
    mark_attendance(world["course"], "2026-01-06", {sid: "Absent"})
    mark_attendance(world["course"], "2026-02-02", {sid: "Present"})
    m = monthly_report(student_id=sid).set_index("month")
    assert m.loc["2026-01", "percentage"] == 50.0 and m.loc["2026-02", "percentage"] == 100.0


def test_alerts_created_once_per_week_and_only_for_low(world):
    a, b = world["students"][:2]
    _record(world, a, 20, 20)
    _record(world, b, 38, 2)
    first = send_low_attendance_alerts()
    assert first == 2  # one student alert + one faculty summary
    msgs = [r["message"] for r in query("SELECT message FROM notifications")]
    assert any("Low attendance in AI301" in m and "50.0%" in m for m in msgs)
    assert send_low_attendance_alerts() == 0  # de-duplicated
    student_users = {r["ref_id"] for r in query(
        "SELECT u.ref_id FROM notifications n JOIN users u ON u.user_id=n.user_id")}
    assert b not in student_users
