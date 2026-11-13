"""Password hashing, password policy and role/page permissions."""

from __future__ import annotations

import hashlib
import hmac
import os
import re

try:  # bcrypt is the preferred hasher (listed in requirements.txt)
    import bcrypt
except ImportError:  # pragma: no cover - fallback so the app still runs
    bcrypt = None

PBKDF2_ROUNDS = 260_000
MIN_LEN, MAX_LEN = 8, 64


def _pw_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:72]  # bcrypt only reads 72 bytes


def hash_password(password: str) -> str:
    """Return a salted hash. Passwords are never stored in plain text."""
    if bcrypt is not None:
        return bcrypt.hashpw(_pw_bytes(password), bcrypt.gensalt()).decode()
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        if stored.startswith("pbkdf2$"):
            _, rounds, salt_hex, digest_hex = stored.split("$")
            digest = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)
            )
            return hmac.compare_digest(digest.hex(), digest_hex)
        if bcrypt is not None and stored.startswith("$2"):
            return bcrypt.checkpw(_pw_bytes(password), stored.encode())
    except (ValueError, TypeError):
        return False
    return False


def validate_password(password: str) -> list[str]:
    """Return a list of policy violations (empty list = acceptable)."""
    errors = []
    if len(password) < MIN_LEN:
        errors.append(f"Password must be at least {MIN_LEN} characters.")
    if len(password) > MAX_LEN:
        errors.append(f"Password must be at most {MAX_LEN} characters.")
    if not re.search(r"[a-z]", password):
        errors.append("Include a lowercase letter.")
    if not re.search(r"[A-Z]", password):
        errors.append("Include an uppercase letter.")
    if not re.search(r"\d", password):
        errors.append("Include a digit.")
    return errors


# ------------------------------------------------------- role-based access
ROLE_PAGES = {
    "admin": [
        "Dashboard", "Students", "Courses", "Attendance", "Marks & Results",
        "Analytics", "AI Analytics", "Notifications", "Reports", "User Management",
    ],
    "faculty": [
        "Dashboard", "Attendance", "Marks & Results", "Analytics",
        "AI Analytics", "Notifications", "Reports",
    ],
    "student": [
        "Dashboard", "My Profile", "My Attendance", "My Results",
        "Academic Assistant", "Notifications", "Reports",
    ],
}


def allowed_pages(role: str) -> list[str]:
    return list(ROLE_PAGES.get(role, []))


def can_access(role: str, page: str) -> bool:
    return page in ROLE_PAGES.get(role, [])


def require_role(user: dict | None, *roles: str) -> None:
    """Raise PermissionError unless the user has one of the given roles."""
    if not user or user.get("role") not in roles:
        raise PermissionError("You are not authorised to perform this action.")
