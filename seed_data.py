"""Create a DEMO database: users, students, courses, attendance, marks, history.

    python seed_data.py            # create demo data (skips if data exists)
    python seed_data.py --reset    # delete the database and rebuild

*** Everything here is randomly generated sample data, not real students. ***
The 'historical_records' used to train the ML model are also synthetic.
Replace them with your institution's real past-cohort data for real use.
"""

from __future__ import annotations

import argparse
import random
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from authentication.register import create_faculty
from authentication.security import hash_password
from database.db import db_path, execute, init_database, query, query_one, transaction

DEMO_PASSWORDS = {"admin": "Admin@12345", "faculty": "Faculty@123", "student": "Student@123"}

FIRST = ["Rahul", "Priya", "Amit", "Sneha", "Rohan", "Ananya", "Vikram", "Neha", "Aditya", "Pooja",
         "Karan", "Isha", "Siddharth", "Meera", "Arjun", "Divya", "Nikhil", "Kavya", "Manish", "Riya",
         "Harsh", "Tanvi", "Yash", "Shruti", "Omkar", "Aarti", "Tejas", "Sakshi", "Varun", "Pallavi"]
LAST = ["Patil", "Sharma", "Deshmukh", "Joshi", "Kulkarni", "Mehta", "Iyer", "Singh", "Gupta", "Nair",
        "More", "Shah", "Jadhav", "Reddy", "Pawar"]

FACULTY = [("Dr. Sunita Rao", "AIML"), ("Prof. Mahesh Kale", "AIML"), ("Prof. Anita Verma", "AIML"),
           ("Dr. Rajesh Menon", "CSE"), ("Prof. Leena Thomas", "CSE")]

# code, name, dept, semester, credits, has_practical, faculty index
COURSES = [
    ("JP301", "Java Programming", "AIML", 3, 4, 1, 0),
    ("DB302", "Database Management Systems", "AIML", 3, 4, 1, 1),
    ("AI303", "Artificial Intelligence", "AIML", 3, 4, 1, 2),
    ("DO304", "DevOps", "AIML", 3, 3, 1, 1),
    ("MF305", "Management Fundamentals", "AIML", 3, 2, 0, 0),
    ("GR306", "German", "AIML", 3, 2, 0, 2),
    ("CS301", "Data Structures", "CSE", 3, 4, 1, 3),
    ("CS302", "Database Management Systems", "CSE", 3, 4, 1, 4),
    ("CS303", "Operating Systems", "CSE", 3, 4, 1, 3),
    ("CS304", "Java Programming", "CSE", 3, 3, 1, 4),
]

ARCHETYPES = {  # attendance prob, marks ratio mean, marks sd, assignment prob
    "good": (0.93, 0.85, 0.06, 0.95),
    "average": (0.80, 0.68, 0.09, 0.80),
    "poor": (0.55, 0.40, 0.11, 0.45),
}


def _set_password(username: str, password: str) -> None:
    execute("UPDATE users SET password_hash=?, must_reset=0 WHERE username=?",
            (hash_password(password), username))


def _weekdays_back(n: int) -> list[date]:
    out, d = [], date.today()
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out


def seed_historical(rng: np.random.Generator, n: int = 800) -> None:
    """Synthetic past-cohort records (features + outcome) for model training."""
    rows = []
    kinds = rng.choice(list(ARCHETYPES), size=n, p=[0.35, 0.40, 0.25])
    for k in kinds:
        att_m, mk_m, mk_sd, asg_m = ARCHETYPES[k]
        att = np.clip(rng.normal(att_m * 100, 7), 20, 100)
        internal = np.clip(rng.normal(mk_m * 100, mk_sd * 100 + 4), 5, 100)
        prev = np.clip(rng.normal(mk_m * 100 - 2, 10), 20, 98)
        assign = np.clip(rng.normal(asg_m * 100, 12), 0, 100)
        prac = np.clip(rng.normal(mk_m * 100 + 3, 9), 10, 100)
        score = (0.30 * att + 0.35 * internal + 0.15 * prev + 0.10 * assign + 0.10 * prac
                 + rng.normal(0, 3.5))
        outcome = "At Risk" if score < 58 else ("Good" if score >= 76 else "Average")
        rows.append((round(att, 1), round(internal, 1), round(prev, 1), round(assign, 1),
                     round(prac, 1), outcome))
    with transaction() as conn:
        conn.execute("DELETE FROM historical_records")
        conn.executemany("INSERT INTO historical_records(attendance_pct, internal_pct, previous_pct, "
                         "assignment_pct, practical_pct, outcome) VALUES(?,?,?,?,?,?)", rows)


def seed(reset: bool = False) -> dict:
    from modules.attendance import mark_attendance
    from modules.course_management import add_course, enroll_cohort
    from modules.marks_management import max_marks, save_marks
    from modules.notifications import add_announcement, send_low_attendance_alerts
    from modules.student_management import add_student

    path = Path(db_path())
    if reset and path.exists():
        path.unlink()
    init_database()
    if query_one("SELECT 1 AS x FROM students LIMIT 1"):
        return {"skipped": True}

    rng, pyrng = np.random.default_rng(42), random.Random(42)
    _set_password("admin", DEMO_PASSWORDS["admin"])

    fac_ids = []
    for name, dept in FACULTY:
        res = create_faculty(name, f"{name.split()[-1].lower()}{len(fac_ids)}@college.example", dept)
        _set_password(res["username"], DEMO_PASSWORDS["faculty"])
        fac_ids.append(res["faculty_id"])

    cids = {}
    for code, name, dept, sem, cr, prac, fi in COURSES:
        cids[code] = add_course(code, name, dept, sem, cr, fac_ids[fi], bool(prac))

    # students: 18 AIML (div A/B) + 12 CSE (div A/B)
    students = []  # (student_id, archetype)
    names = [f"{f} {l}" for f in FIRST for l in LAST]
    pyrng.shuffle(names)
    plan = [("AIML", 18), ("CSE", 12)]
    k = 0
    for dept, count in plan:
        for i in range(count):
            arche = pyrng.choices(list(ARCHETYPES), weights=[35, 40, 25])[0]
            prev = round(float(np.clip(rng.normal(ARCHETYPES[arche][1] * 100, 8), 30, 97)), 1)
            nm = names[k]
            res = add_student({"name": nm, "email": f"{nm.lower().replace(' ', '.')}{k}@student.example",
                               "mobile": f"9{pyrng.randint(100000000, 999999999)}", "department": dept,
                               "semester": 3, "division": "A" if i % 2 == 0 else "B",
                               "previous_percentage": prev})
            _set_password(res["username"], DEMO_PASSWORDS["student"])
            students.append((res["student_id"], arche))
            k += 1
    arche_of = dict(students)

    for code in cids:
        enroll_cohort(cids[code])

    # attendance: 24 lectures per course on alternating weekdays
    days = _weekdays_back(60)
    for ci, (code, *_rest) in enumerate(COURSES):
        lecture_days = days[(ci % 2)::2][:24]
        enrolled = [r["student_id"] for r in query(
            "SELECT student_id FROM enrollments WHERE course_id=?", (cids[code],))]
        for d in lecture_days:
            statuses = {sid: "Present" if pyrng.random() < ARCHETYPES[arche_of[sid]][0] else "Absent"
                        for sid in enrolled}
            mark_attendance(cids[code], d, statuses, marked_by="seed")

    # marks (leave DevOps external empty for 4 students so 'Pending' is visible)
    limits = max_marks()
    skip = {sid for sid, _ in students[:4]}
    for code, *_rest in COURSES:
        has_prac = [c for c in COURSES if c[0] == code][0][5]
        enrolled = [r["student_id"] for r in query(
            "SELECT student_id FROM enrollments WHERE course_id=?", (cids[code],))]
        for sid in enrolled:
            _, mean, sd, _ = ARCHETYPES[arche_of[sid]]
            for exam in ("Internal", "Practical", "External"):
                if exam == "Practical" and not has_prac:
                    continue
                if code == "DO304" and exam == "External" and sid in skip:
                    continue
                ratio = float(np.clip(rng.normal(mean, sd), 0.12, 1.0))
                save_marks(sid, cids[code], exam, round(limits[exam] * ratio), "seed")

    # assignments and submissions
    with transaction() as conn:
        for code in cids:
            for n, offset in enumerate((-30, -12, 10), 1):
                conn.execute("INSERT INTO assignments(course_id, title, due_date) VALUES(?,?,?)",
                             (cids[code], f"{code} Assignment {n}", (date.today() + timedelta(days=offset)).isoformat()))
        for a in conn.execute("SELECT assignment_id, course_id, due_date FROM assignments").fetchall():
            future = a["due_date"] > date.today().isoformat()
            for e in conn.execute("SELECT student_id FROM enrollments WHERE course_id=?",
                                  (a["course_id"],)).fetchall():
                p = ARCHETYPES[arche_of[e["student_id"]]][3] * (0.15 if future else 1)
                conn.execute("INSERT INTO submissions(assignment_id, student_id, submitted) VALUES(?,?,?)",
                             (a["assignment_id"], e["student_id"], int(pyrng.random() < p)))

    add_announcement("Mid-semester examination schedule", "Internal examinations begin next month. "
                     "Check the notice board for the timetable.", "admin", "all")
    add_announcement("Minimum attendance policy", "Students must maintain at least 75% attendance in every subject.",
                     "admin", "students")
    send_low_attendance_alerts()

    seed_historical(rng)
    from ai.train_model import train_model
    metrics = train_model()
    return {"skipped": False, "students": len(students), "model_accuracy": metrics["accuracy"]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="delete and rebuild the database")
    out = seed(ap.parse_args().reset)
    if out["skipped"]:
        print("Database already has data. Use --reset to rebuild.")
    else:
        print(f"Demo data created: {out['students']} students. Model accuracy on held-out "
              f"synthetic history: {out['model_accuracy']:.0%}")
        print("\nDemo logins (sample data only):")
        print("  admin     /  Admin@12345")
        print("  faculty   /  fac001 ... fac005   (password Faculty@123)")
        first = query_one("SELECT username FROM users WHERE role='student' ORDER BY user_id LIMIT 1")
        print(f"  student   /  {first['username']}   (password Student@123)")
