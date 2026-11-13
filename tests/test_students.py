import pytest

from authentication.login import authenticate
from database.db import query, query_one
from modules.attendance import mark_attendance
from modules.marks_management import save_marks
from modules.student_management import (add_student, delete_student, generate_student_id,
                                        search_students, update_student, validate_student)

BASE = {"name": "Rahul Patil", "email": "rahul@example.com", "mobile": "9876543210",
        "department": "AIML", "semester": 3, "division": "A"}


def test_student_id_format_and_sequence(db):
    assert generate_student_id("aiml", 2026) == "AIML2026001"
    a = add_student({**BASE})
    b = add_student({**BASE, "email": "b@example.com"})
    assert a["student_id"].startswith("AIML") and a["student_id"].endswith("001")
    assert b["student_id"].endswith("002")
    assert a["student_id"] != b["student_id"]


def test_ids_are_per_department(db):
    a = add_student({**BASE})
    b = add_student({**BASE, "email": "c@example.com", "department": "CSE"})
    assert b["student_id"].startswith("CSE") and b["student_id"].endswith("001")
    assert a["student_id"] != b["student_id"]


@pytest.mark.parametrize("field,value", [("name", " "), ("email", "not-an-email"), ("mobile", "12345"),
                                         ("department", "A"), ("semester", 9), ("semester", "x"),
                                         ("division", ""), ("previous_percentage", 120)])
def test_validation_rejects_bad_input(field, value):
    assert field in validate_student({**BASE, field: value})


def test_valid_input_has_no_errors():
    assert validate_student(BASE) == {}


def test_add_student_creates_hashed_login_that_must_reset(db):
    res = add_student({**BASE})
    row = query_one("SELECT * FROM users WHERE ref_id=?", (res["student_id"],))
    assert row["role"] == "student" and row["must_reset"] == 1
    assert res["temp_password"] not in row["password_hash"]
    user, _ = authenticate(res["username"], res["temp_password"])
    assert user and user["ref_id"] == res["student_id"]


def test_duplicate_email_rejected_and_nothing_half_created(db):
    add_student({**BASE})
    with pytest.raises(ValueError, match="email"):
        add_student({**BASE, "name": "Someone Else", "email": "RAHUL@example.com"})
    assert query_one("SELECT COUNT(*) AS n FROM students")["n"] == 1
    assert query_one("SELECT COUNT(*) AS n FROM users WHERE role='student'")["n"] == 1


def test_update_student(db):
    sid = add_student({**BASE})["student_id"]
    update_student(sid, {**BASE, "name": "Rahul P. Patil", "semester": 4})
    row = query_one("SELECT * FROM students WHERE student_id=?", (sid,))
    assert row["name"] == "Rahul P. Patil" and row["semester"] == 4
    assert query_one("SELECT full_name FROM users WHERE ref_id=?", (sid,))["full_name"] == "Rahul P. Patil"
    with pytest.raises(ValueError):
        update_student("NOPE2026999", BASE)


def test_search_by_name_id_and_filters(db):
    add_student({**BASE})
    add_student({**BASE, "name": "Priya Sharma", "email": "p@example.com", "semester": 4, "division": "B"})
    assert len(search_students("priya")) == 1
    sid = search_students("Rahul")["student_id"].iloc[0]
    assert len(search_students(sid)) == 1
    assert len(search_students(semester=4)) == 1
    assert len(search_students(division="A")) == 1
    assert len(search_students(department="AIML")) == 2
    assert search_students("zzz").empty


def test_delete_removes_login_and_all_records(world):
    sid = world["students"][0]
    mark_attendance(world["course"], "2026-01-05", {sid: "Present"})
    save_marks(sid, world["course"], "Internal", 20)
    delete_student(sid)
    assert query("SELECT 1 FROM students WHERE student_id=?", (sid,)) == []
    assert query("SELECT 1 FROM users WHERE ref_id=?", (sid,)) == []
    assert query("SELECT 1 FROM attendance WHERE student_id=?", (sid,)) == []
    assert query("SELECT 1 FROM marks WHERE student_id=?", (sid,)) == []
    assert query("SELECT 1 FROM enrollments WHERE student_id=?", (sid,)) == []
    assert len(query("SELECT 1 FROM students")) == 2  # others untouched
