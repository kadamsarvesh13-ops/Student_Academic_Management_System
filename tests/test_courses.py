import pytest

from authentication.register import create_faculty
from modules.course_management import (add_course, assign_faculty, courses_for_user, enroll_cohort,
                                       enroll_student, list_courses, unenroll_student, update_course,
                                       user_can_use_course)
from database.db import query


def test_add_course_validation_and_duplicates(db):
    add_course("ai301", "AI", "AIML", 3, 4)
    assert list_courses().iloc[0]["course_code"] == "AI301"  # normalised
    with pytest.raises(ValueError, match="already exists"):
        add_course("AI301", "Other", "AIML", 3, 4)
    for bad in [dict(code="", name="x", department="AIML", semester=3, credits=3),
                dict(code="X1", name="x", department="AIML", semester=9, credits=3),
                dict(code="X2", name="x", department="AIML", semester=3, credits=0),
                dict(code="X3", name="x", department="A", semester=3, credits=3)]:
        with pytest.raises(ValueError):
            add_course(bad["code"], bad["name"], bad["department"], bad["semester"], bad["credits"])
    with pytest.raises(ValueError, match="faculty"):
        add_course("X4", "x", "AIML", 3, 3, faculty_id="FAC999")


def test_update_and_assign_faculty(world):
    cid = world["course"]
    update_course(cid, course_name="AI (revised)", credits=3)
    row = list_courses().set_index("course_id").loc[cid]
    assert row.course_name == "AI (revised)" and row.credits == 3
    with pytest.raises(ValueError):
        update_course(cid, course_code="HACK")  # not an updatable field
    with pytest.raises(ValueError):
        assign_faculty(cid, "FAC999")
    other = create_faculty("Prof. Two", "two@example.com", "AIML")
    assign_faculty(cid, other["faculty_id"])
    assert list_courses().set_index("course_id").loc[cid, "faculty_id"] == other["faculty_id"]


def test_enrolment_is_unique_and_cohort_enrolment_counts(world):
    cid, sid = world["course"], world["students"][0]
    assert enroll_student(sid, cid) is False  # already enrolled by the fixture
    unenroll_student(sid, cid)
    assert enroll_student(sid, cid) is True
    assert enroll_cohort(cid) == 0  # everyone already in
    with pytest.raises(ValueError):
        enroll_student("NOPE2026001", cid)


def test_faculty_only_sees_and_uses_own_courses(world):
    other = create_faculty("Prof. Two", "two@example.com", "AIML")
    other_course = add_course("ML302", "ML", "AIML", 3, 3, other["faculty_id"])
    mine = {"role": "faculty", "ref_id": world["faculty"]["faculty_id"]}
    theirs = {"role": "faculty", "ref_id": other["faculty_id"]}
    admin = {"role": "admin", "ref_id": None}
    assert set(courses_for_user(mine)["course_id"]) == {world["course"], world["theory_course"]}
    assert list(courses_for_user(theirs)["course_id"]) == [other_course]
    assert user_can_use_course(mine, world["course"])
    assert not user_can_use_course(mine, other_course)
    assert user_can_use_course(admin, other_course)
    assert not user_can_use_course({"role": "student", "ref_id": world["students"][0]}, world["course"])


def test_student_sees_only_enrolled_courses(world):
    sid = world["students"][0]
    unenroll_student(sid, world["theory_course"])
    df = courses_for_user({"role": "student", "ref_id": sid})
    assert list(df["course_id"]) == [world["course"]]
    assert query("SELECT COUNT(*) AS n FROM enrollments")[0]["n"] == 5
