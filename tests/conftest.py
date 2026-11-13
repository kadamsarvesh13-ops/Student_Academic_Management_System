"""Shared fixtures: every test gets its own empty SQLite database."""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("SRAMS_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("SRAMS_MODEL", str(tmp_path / "model.joblib"))
    from database.db import init_database

    init_database()
    return tmp_path


@pytest.fixture
def world(db):
    """1 faculty, 1 course (with practical), 1 theory-only course, 3 enrolled students."""
    from authentication.register import create_faculty
    from modules.course_management import add_course, enroll_cohort
    from modules.student_management import add_student

    fac = create_faculty("Dr. Test", "dr.test@example.com", "AIML")
    c1 = add_course("AI301", "Artificial Intelligence", "AIML", 3, 4, fac["faculty_id"], True)
    c2 = add_course("MF305", "Management", "AIML", 3, 2, fac["faculty_id"], False)
    students = []
    for i, name in enumerate(["Rahul Patil", "Priya Sharma", "Amit Singh"]):
        students.append(add_student({
            "name": name, "email": f"s{i}@example.com", "mobile": "9876543210",
            "department": "AIML", "semester": 3, "division": "A",
            "previous_percentage": 70})["student_id"])
    enroll_cohort(c1)
    enroll_cohort(c2)
    return {"faculty": fac, "course": c1, "theory_course": c2, "students": students}
