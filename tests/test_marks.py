import json

import pytest

from database.db import query, set_setting
from modules.marks_management import course_results_df, save_marks, semester_result
from utils.helpers import grade_for


@pytest.mark.parametrize("pct,grade,points", [
    (100, "O", 10), (90, "O", 10), (89.99, "A+", 9), (80, "A+", 9), (79.5, "A", 8),
    (70, "A", 8), (60, "B+", 7), (50, "B", 6), (49.99, "C", 5), (40, "C", 5),
    (39.99, "F", 0), (0, "F", 0)])
def test_default_grade_boundaries(pct, grade, points):
    assert grade_for(pct) == (grade, points)


def test_grade_scale_is_configurable():
    scale = [[85, "Distinction", 10], [50, "Pass", 5], [0, "Fail", 0]]
    assert grade_for(90, scale)[0] == "Distinction"
    assert grade_for(60, scale)[0] == "Pass"
    assert grade_for(49, scale)[0] == "Fail"


@pytest.mark.parametrize("exam,bad", [("Internal", 31), ("Internal", -1), ("Practical", 21),
                                      ("External", 51), ("External", "abc")])
def test_marks_outside_limits_rejected(world, exam, bad):
    with pytest.raises(ValueError):
        save_marks(world["students"][0], world["course"], exam, bad)
    assert query("SELECT 1 FROM marks") == []


def test_marks_at_limits_accepted_and_updatable(world):
    sid, cid = world["students"][0], world["course"]
    save_marks(sid, cid, "Internal", 30)
    save_marks(sid, cid, "Internal", 25)  # update, not duplicate
    rows = query("SELECT marks FROM marks WHERE student_id=? AND course_id=?", (sid, cid))
    assert [r["marks"] for r in rows] == [25.0]


def test_unknown_exam_type_unenrolled_and_no_practical_rejected(world):
    sid = world["students"][0]
    with pytest.raises(ValueError):
        save_marks(sid, world["course"], "Viva", 5)
    with pytest.raises(ValueError, match="no practical"):
        save_marks(sid, world["theory_course"], "Practical", 5)
    with pytest.raises(ValueError, match="enrolled"):
        save_marks("CSE2026999", world["course"], "Internal", 5)


def test_limits_follow_settings(world):
    set_setting("max_marks", {"Internal": 40, "Practical": 10, "External": 50})
    save_marks(world["students"][0], world["course"], "Internal", 38)
    with pytest.raises(ValueError):
        save_marks(world["students"][0], world["course"], "Practical", 11)


def _fill(sid, cid, i, p, e):
    save_marks(sid, cid, "Internal", i)
    save_marks(sid, cid, "Practical", p)
    save_marks(sid, cid, "External", e)


def test_total_percentage_and_grade(world):
    sid, cid = world["students"][0], world["course"]
    _fill(sid, cid, 27, 18, 45)  # 90/100
    r = course_results_df(sid, cid).iloc[0]
    assert (r.total, r.max_total, r.percentage, r.grade, r.grade_points) == (90, 100, 90.0, "O", 10)


def test_incomplete_marks_are_pending_not_graded(world):
    sid, cid = world["students"][0], world["course"]
    save_marks(sid, cid, "Internal", 20)
    r = course_results_df(sid, cid).iloc[0]
    assert r.grade == "Pending" and not r.complete and r.total != r.total  # NaN


def test_theory_only_course_scales_to_its_own_max(world):
    sid, cid = world["students"][0], world["theory_course"]
    save_marks(sid, cid, "Internal", 24)
    save_marks(sid, cid, "External", 40)  # 64 / 80
    r = course_results_df(sid, cid).iloc[0]
    assert r.max_total == 80 and r.percentage == 80.0 and r.grade == "A+"


def test_semester_result_sgpa_and_pass(world):
    sid = world["students"][0]
    _fill(sid, world["course"], 27, 18, 45)       # O  (10) x 4 credits
    save_marks(sid, world["theory_course"], "Internal", 18)
    save_marks(sid, world["theory_course"], "External", 30)  # 48/80 = 60% -> B+ (7) x 2 credits
    res = semester_result(sid, 3)
    assert res["status"] == "PASS"
    assert res["sgpa"] == round((10 * 4 + 7 * 2) / 6, 2)
    assert res["percentage"] == round((90 + 48) / (100 + 80) * 100, 2)


def test_semester_result_fail_and_pending(world):
    sid = world["students"][1]
    assert semester_result(sid)["status"] == "PENDING"
    _fill(sid, world["course"], 5, 3, 10)  # 18% -> F
    save_marks(sid, world["theory_course"], "Internal", 20)
    save_marks(sid, world["theory_course"], "External", 40)
    assert semester_result(sid)["status"] == "FAIL"


def test_unknown_student_raises(world):
    with pytest.raises(ValueError):
        semester_result("NOPE2026001")
