"""SQLite schema and default configuration for SRAMS."""

import json

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('admin','faculty','student')),
    full_name       TEXT NOT NULL,
    ref_id          TEXT,                       -- student_id or faculty_id
    is_active       INTEGER NOT NULL DEFAULT 1,
    must_reset      INTEGER NOT NULL DEFAULT 0,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until    TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_login      TEXT
);

CREATE TABLE IF NOT EXISTS students (
    student_id          TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    email               TEXT NOT NULL UNIQUE COLLATE NOCASE,
    mobile              TEXT,
    department          TEXT NOT NULL,
    semester            INTEGER NOT NULL CHECK (semester BETWEEN 1 AND 8),
    division            TEXT NOT NULL DEFAULT 'A',
    previous_percentage REAL CHECK (previous_percentage IS NULL
                                    OR previous_percentage BETWEEN 0 AND 100),
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS faculty (
    faculty_id  TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    department  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS courses (
    course_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    course_code   TEXT NOT NULL UNIQUE COLLATE NOCASE,
    course_name   TEXT NOT NULL,
    department    TEXT NOT NULL,
    semester      INTEGER NOT NULL CHECK (semester BETWEEN 1 AND 8),
    credits       INTEGER NOT NULL CHECK (credits BETWEEN 1 AND 10),
    has_practical INTEGER NOT NULL DEFAULT 1,
    faculty_id    TEXT REFERENCES faculty(faculty_id) ON DELETE SET NULL,
    is_active     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS enrollments (
    enrollment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id    TEXT NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    course_id     INTEGER NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    UNIQUE (student_id, course_id)
);

CREATE TABLE IF NOT EXISTS attendance (
    attendance_id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id    TEXT NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    course_id     INTEGER NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    lecture_date  TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('Present','Absent')),
    marked_by     TEXT,
    UNIQUE (student_id, course_id, lecture_date)
);

CREATE TABLE IF NOT EXISTS marks (
    marks_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  TEXT NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    course_id   INTEGER NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    exam_type   TEXT NOT NULL CHECK (exam_type IN ('Internal','Practical','External')),
    marks       REAL NOT NULL CHECK (marks >= 0),
    entered_by  TEXT,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (student_id, course_id, exam_type)
);

CREATE TABLE IF NOT EXISTS assignments (
    assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id     INTEGER NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    title         TEXT NOT NULL,
    due_date      TEXT
);

CREATE TABLE IF NOT EXISTS submissions (
    submission_id INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id INTEGER NOT NULL REFERENCES assignments(assignment_id) ON DELETE CASCADE,
    student_id    TEXT NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    submitted     INTEGER NOT NULL DEFAULT 0,
    UNIQUE (assignment_id, student_id)
);

CREATE TABLE IF NOT EXISTS notifications (
    notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    message         TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    is_read         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS announcements (
    announcement_id INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    description     TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    created_by      TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Past cohorts' outcomes, used to train the performance-prediction model.
CREATE TABLE IF NOT EXISTS historical_records (
    record_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    attendance_pct REAL NOT NULL,
    internal_pct   REAL NOT NULL,
    previous_pct   REAL NOT NULL,
    assignment_pct REAL NOT NULL,
    practical_pct  REAL NOT NULL,
    outcome        TEXT NOT NULL CHECK (outcome IN ('Good','Average','At Risk'))
);

CREATE INDEX IF NOT EXISTS idx_att_course   ON attendance(course_id, lecture_date);
CREATE INDEX IF NOT EXISTS idx_att_student  ON attendance(student_id);
CREATE INDEX IF NOT EXISTS idx_marks_sc     ON marks(student_id, course_id);
CREATE INDEX IF NOT EXISTS idx_enroll_course ON enrollments(course_id);
CREATE INDEX IF NOT EXISTS idx_notif_user   ON notifications(user_id, is_read);
"""

# Configurable according to the university's examination scheme.
# grade_scale rows: [minimum percentage, grade, grade points]
DEFAULT_SETTINGS = {
    "grade_scale": json.dumps(
        [[90, "O", 10], [80, "A+", 9], [70, "A", 8], [60, "B+", 7],
         [50, "B", 6], [40, "C", 5], [0, "F", 0]]
    ),
    "max_marks": json.dumps({"Internal": 30, "Practical": 20, "External": 50}),
    "attendance_threshold": "75",
    "institution_name": "Demo College of Engineering",
}
