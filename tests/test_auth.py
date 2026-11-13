import pytest

from authentication.login import MAX_ATTEMPTS, authenticate, change_password
from authentication.register import (admin_reset_password, create_user, generate_temp_password,
                                     set_active)
from authentication.security import (ROLE_PAGES, can_access, hash_password, require_role,
                                     validate_password, verify_password)
from database.db import query_one


def test_hash_is_not_plaintext_and_verifies():
    h = hash_password("Secret@123")
    assert "Secret@123" not in h
    assert verify_password("Secret@123", h)
    assert not verify_password("secret@123", h)
    assert not verify_password("anything", "garbage-hash")


def test_same_password_gets_different_salts():
    assert hash_password("Secret@123") != hash_password("Secret@123")


@pytest.mark.parametrize("pw,ok", [("Abcdef12", True), ("short1A", False), ("alllowercase1", False),
                                   ("ALLUPPER123", False), ("NoDigitsHere", False), ("A1" + "a" * 70, False)])
def test_password_policy(pw, ok):
    assert (validate_password(pw) == []) is ok


def test_generated_temp_password_meets_policy():
    for _ in range(20):
        assert validate_password(generate_temp_password()) == []


def test_default_admin_must_reset_password(db):
    user, msg = authenticate("admin", "Admin@12345")
    assert user and user["role"] == "admin" and user["must_reset"] is True
    assert change_password(user["user_id"], "weak") != []
    assert change_password(user["user_id"], "NewStrong1") == []
    user, _ = authenticate("admin", "NewStrong1")
    assert user and user["must_reset"] is False
    assert authenticate("admin", "Admin@12345")[0] is None


def test_wrong_password_and_unknown_user_give_same_message(db):
    _, m1 = authenticate("admin", "wrong")
    _, m2 = authenticate("nobody", "wrong")
    assert m1 == m2


def test_lockout_after_repeated_failures(db):
    for _ in range(MAX_ATTEMPTS):
        assert authenticate("admin", "bad")[0] is None
    user, msg = authenticate("admin", "Admin@12345")  # correct, but locked
    assert user is None and "locked" in msg.lower()


def test_deactivated_account_cannot_log_in(db):
    uid = create_user("tester", "Tester@123", "faculty", "T", None, must_reset=False)
    assert authenticate("tester", "Tester@123")[0]
    set_active(uid, False)
    user, msg = authenticate("tester", "Tester@123")
    assert user is None and "deactivated" in msg.lower()
    set_active(uid, True)
    assert authenticate("tester", "Tester@123")[0]


def test_admin_cannot_deactivate_self(db):
    admin = query_one("SELECT user_id FROM users WHERE username='admin'")
    with pytest.raises(ValueError):
        set_active(admin["user_id"], False, actor_id=admin["user_id"])


def test_admin_reset_forces_change_and_clears_lock(db):
    uid = query_one("SELECT user_id FROM users WHERE username='admin'")["user_id"]
    temp = admin_reset_password(uid)
    user, _ = authenticate("admin", temp)
    assert user and user["must_reset"] is True


def test_usernames_are_unique_case_insensitive(db):
    create_user("dup", "Dupuser@123", "student", "A")
    with pytest.raises(Exception):
        create_user("DUP", "Dupuser@123", "student", "B")


def test_weak_password_rejected_on_create(db):
    with pytest.raises(ValueError):
        create_user("weak", "123", "student", "W")


def test_role_based_page_access():
    assert can_access("admin", "User Management")
    assert not can_access("faculty", "User Management")
    assert not can_access("faculty", "Students")
    assert not can_access("student", "Students")
    assert not can_access("student", "Attendance")  # marking is faculty/admin only
    assert can_access("student", "My Attendance")
    assert not can_access("unknown", "Dashboard")
    assert all("Dashboard" in pages for pages in ROLE_PAGES.values())


def test_require_role():
    require_role({"role": "admin"}, "admin")
    with pytest.raises(PermissionError):
        require_role({"role": "student"}, "admin", "faculty")
    with pytest.raises(PermissionError):
        require_role(None, "admin")
