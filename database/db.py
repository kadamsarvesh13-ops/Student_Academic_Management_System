"""SQLite access layer (plain sqlite3 -- no ORM needed at this scale)."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from database.schema import DEFAULT_SETTINGS, SCHEMA

BASE_DIR = Path(__file__).resolve().parent.parent


def db_path() -> str:
    """Resolved on every call so tests can point SRAMS_DB at a temp file."""
    return os.environ.get("SRAMS_DB", str(BASE_DIR / "database" / "academic.db"))


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction():
    """Commit on success, roll back on any error."""
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query(sql: str, params: tuple = ()) -> list[dict]:
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def query_one(sql: str, params: tuple = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple = ()) -> int:
    with transaction() as conn:
        return conn.execute(sql, params).lastrowid


def df_query(sql: str, params: tuple = ()) -> pd.DataFrame:
    conn = get_conn()
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


# ---------------------------------------------------------------- settings
def get_setting(key: str, default=None):
    row = query_one("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


def get_json_setting(key: str):
    return json.loads(get_setting(key, DEFAULT_SETTINGS[key]))


def set_setting(key: str, value) -> None:
    if not isinstance(value, str):
        value = json.dumps(value)
    execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def attendance_threshold() -> float:
    return float(get_setting("attendance_threshold", "75"))


# -------------------------------------------------------------------- init
def init_database() -> None:
    """Create tables, default settings and a first admin account if empty."""
    Path(db_path()).parent.mkdir(parents=True, exist_ok=True)
    with transaction() as conn:
        conn.executescript(SCHEMA)
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (key, value)
            )
    ensure_default_admin()


def ensure_default_admin() -> None:
    from authentication.security import hash_password

    if query_one("SELECT 1 AS x FROM users LIMIT 1"):
        return
    execute(
        "INSERT INTO users(username, password_hash, role, full_name, must_reset) "
        "VALUES(?, ?, 'admin', 'System Administrator', 1)",
        ("admin", hash_password("Admin@12345")),
    )
