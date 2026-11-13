"""Student academic assistant (rule-based, privacy-scoped).

Security rule: every answer is computed for the `student_id` passed in by the
app from the logged-in session. The question text is never used to choose
whose records are read; questions that name another student ID are refused.
"""

from __future__ import annotations

import re

from database.db import attendance_threshold, df_query, query_one
from modules.attendance import overall_attendance, student_attendance_summary
from modules.marks_management import course_results_df, semester_result
from modules.performance import recommendations

ID_RE = re.compile(r"\b[A-Za-z]{2,10}\d{7}\b")

HELP = ("I can answer questions about **your own** records, for example:\n"
        "- What is my attendance percentage?\n- Which subjects have low attendance?\n"
        "- What are my examination marks?\n- What is my semester result?\n"
        "- Which assignments are pending?\n- What should I focus on?")


def _has(text: str, *words: str) -> bool:
    return any(w in text for w in words)


def pending_assignments(student_id: str):
    return df_query(
        "SELECT c.course_code, a.title, a.due_date FROM enrollments e "
        "JOIN assignments a ON a.course_id=e.course_id "
        "JOIN courses c ON c.course_id=a.course_id "
        "LEFT JOIN submissions s ON s.assignment_id=a.assignment_id AND s.student_id=e.student_id "
        "WHERE e.student_id=? AND COALESCE(s.submitted,0)=0 ORDER BY a.due_date", (student_id,))


def answer(student_id: str, question: str) -> str:
    q = (question or "").lower().strip()
    if not q:
        return HELP
    other = {m.upper() for m in ID_RE.findall(question)} - {student_id.upper()}
    if other:
        return "I can only share your own academic records, not another student's."

    th = attendance_threshold()
    if _has(q, "low attendance", "short attendance", "below") or ("subject" in q and "attendance" in q):
        df = student_attendance_summary(student_id)
        low = df[df["status"] == "Low"]
        if low.empty:
            return f"None of your subjects is below {th:.0f}% attendance."
        lines = [f"- **{r.course_name}**: {r.percentage:.1f}% (attend {r.needed} more lecture(s) in a row to reach {th:.0f}%)"
                 if r.needed is not None else f"- **{r.course_name}**: {r.percentage:.1f}%"
                 for r in low.itertuples()]
        return f"Subjects below {th:.0f}%:\n" + "\n".join(lines)

    if "attendance" in q:
        overall = overall_attendance(student_id)
        if overall is None:
            return "No attendance has been recorded for you yet."
        df = student_attendance_summary(student_id)
        lines = [f"- {r.course_name}: {r.percentage:.1f}% ({r.present}/{r.total})"
                 for r in df.itertuples() if r.total > 0]
        return f"Your overall attendance is **{overall:.1f}%**.\n" + "\n".join(lines)

    if _has(q, "pending", "assignment", "homework"):
        df = pending_assignments(student_id)
        if df.empty:
            return "You have no pending assignments."
        return "Pending assignments:\n" + "\n".join(
            f"- {r.course_code}: {r.title} (due {r.due_date or 'n/a'})" for r in df.itertuples())

    if _has(q, "result", "sgpa", "grade", "pass", "fail"):
        me = query_one("SELECT semester FROM students WHERE student_id=?", (student_id,))
        res = semester_result(student_id, me["semester"])
        if res["status"] == "NO COURSES":
            return "You are not enrolled in any course this semester."
        head = f"Semester {res['semester']} result: **{res['status']}**"
        if res["sgpa"] is not None:
            head += f" - SGPA {res['sgpa']}, {res['percentage']:.1f}%"
        lines = [f"- {r.course_name}: {r.grade}" for r in res["rows"].itertuples()]
        return head + "\n" + "\n".join(lines)

    if _has(q, "mark", "score", "exam"):
        df = course_results_df(student_id)
        if df.empty:
            return "You are not enrolled in any course."
        lines = []
        for r in df.itertuples():
            parts = [f"{n} {v:g}" for n, v in (("Internal", r.internal), ("Practical", r.practical),
                                                ("External", r.external)) if v == v]
            lines.append(f"- {r.course_name}: " + (", ".join(parts) if parts else "no marks entered yet"))
        return "Your marks so far:\n" + "\n".join(lines)

    if _has(q, "focus", "improve", "study", "recommend", "advice", "priority", "plan"):
        rec = recommendations(student_id)
        if not rec["plan"]:
            return "You are on track in every subject. Keep it up!"
        return "Suggested priorities:\n" + "\n".join(rec["plan"])

    return "Sorry, I didn't understand that.\n\n" + HELP
