"""All SQL for attendance sessions and records.

NOTE (Milestone 7): teacher/student authorization checks will be added here.
"""
from datetime import date
from typing import Optional

from app.validation import ValidationError

ATTENDANCE_STATUSES = ("present", "absent")


class DuplicateSessionError(Exception):
    """Attendance for this class, subject, date and lecture number already exists."""


def _rows_as_dicts(cur) -> list:
    columns = [c[0] for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def list_subjects_for_class(cur, class_id: int) -> list:
    """Subjects of the same department and semester as the class."""
    cur.execute(
        "SELECT sub.id, sub.code, sub.name FROM subjects sub "
        "JOIN classes c ON c.department_id = sub.department_id AND c.semester = sub.semester "
        "WHERE c.id = %s ORDER BY sub.code",
        (class_id,),
    )
    return _rows_as_dicts(cur)


def _check_subject_in_class(cur, class_id: int, subject_id: int) -> None:
    cur.execute(
        "SELECT 1 FROM subjects sub JOIN classes c "
        "ON c.department_id = sub.department_id AND c.semester = sub.semester "
        "WHERE c.id = %s AND sub.id = %s",
        (class_id, subject_id),
    )
    if cur.fetchone() is None:
        raise ValidationError("This subject is not taught in this class (department or semester does not match).")


def get_session_statuses(cur, class_id: int, subject_id: int, session_date: date, session_no: int) -> Optional[dict]:
    """{student_id: status} of an existing session, or None if no such session exists."""
    cur.execute(
        "SELECT id FROM attendance_sessions "
        "WHERE class_id = %s AND subject_id = %s AND session_date = %s AND session_no = %s",
        (class_id, subject_id, session_date, session_no),
    )
    row = cur.fetchone()
    if row is None:
        return None
    cur.execute("SELECT student_id, status FROM attendance_records WHERE session_id = %s", (row[0],))
    return {student_id: status for student_id, status in cur.fetchall()}


def get_or_create_session(cur, class_id: int, subject_id: int, session_date: date,
                          session_no: int, created_by: Optional[int] = None) -> int:
    cur.execute(
        "INSERT INTO attendance_sessions (class_id, subject_id, session_date, session_no, created_by) "
        "VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (class_id, subject_id, session_date, session_no) DO NOTHING RETURNING id",
        (class_id, subject_id, session_date, session_no, created_by),
    )
    row = cur.fetchone()
    if row is not None:
        return row[0]
    cur.execute(
        "SELECT id FROM attendance_sessions "
        "WHERE class_id = %s AND subject_id = %s AND session_date = %s AND session_no = %s",
        (class_id, subject_id, session_date, session_no),
    )
    return cur.fetchone()[0]


def save_attendance(cur, class_id: int, subject_id: int, session_date: date, session_no: int,
                    statuses: dict, overwrite: bool = False, created_by: Optional[int] = None) -> dict:
    """Saves one class session. statuses = {student_id: 'present' | 'absent'}.

    If the session already exists and overwrite is False -> DuplicateSessionError.
    """
    from psycopg2.extras import execute_values

    if not isinstance(session_date, date):
        raise ValidationError("Date is invalid.")
    if session_date > date.today():
        raise ValidationError("Attendance cannot be recorded for a future date.")
    if isinstance(session_no, bool) or not isinstance(session_no, int) or session_no < 1:
        raise ValidationError("Lecture number must be 1 or more.")
    if not statuses:
        raise ValidationError("No students to save attendance for.")
    bad = sorted({s for s in statuses.values() if s not in ATTENDANCE_STATUSES})
    if bad:
        raise ValidationError(f"Attendance status must be present or absent, got: {', '.join(map(str, bad))}.")

    _check_subject_in_class(cur, class_id, subject_id)

    cur.execute(
        "SELECT id, status FROM students WHERE class_id = %s AND id = ANY(%s)",
        (class_id, list(statuses)),
    )
    found = dict(cur.fetchall())
    not_in_class = [sid for sid in statuses if sid not in found]
    if not_in_class:
        raise ValidationError(f"{len(not_in_class)} student(s) do not belong to this class.")
    inactive = [sid for sid in statuses if found[sid] != "active"]
    if inactive:
        raise ValidationError(f"{len(inactive)} student(s) are inactive and cannot get new attendance.")

    already = get_session_statuses(cur, class_id, subject_id, session_date, session_no) is not None
    if already and not overwrite:
        raise DuplicateSessionError(
            f"Attendance for {session_date.isoformat()} lecture {session_no} is already recorded."
        )

    session_id = get_or_create_session(cur, class_id, subject_id, session_date, session_no, created_by)
    execute_values(
        cur,
        "INSERT INTO attendance_records (session_id, student_id, status) VALUES %s "
        "ON CONFLICT (session_id, student_id) DO UPDATE SET status = EXCLUDED.status",
        [(session_id, sid, status) for sid, status in statuses.items()],
    )
    return {"session_id": session_id, "created": not already, "records": len(statuses)}


def attendance_summary(cur, class_id: int, subject_id: int) -> list:
    """Per active student: attended and total held sessions (0 when nothing recorded yet)."""
    cur.execute(
        "SELECT st.id AS student_id, st.student_code, st.name, "
        "COUNT(ar.id) FILTER (WHERE ar.status = 'present') AS attended, "
        "COUNT(ar.id) AS total_held "
        "FROM students st "
        "LEFT JOIN attendance_records ar ON ar.student_id = st.id "
        "  AND ar.session_id IN (SELECT id FROM attendance_sessions WHERE class_id = %s AND subject_id = %s) "
        "WHERE st.class_id = %s AND st.status = 'active' "
        "GROUP BY st.id, st.student_code, st.name ORDER BY st.student_code",
        (class_id, subject_id, class_id),
    )
    return _rows_as_dicts(cur)


def list_sessions(cur, class_id: int, subject_id: int) -> list:
    cur.execute(
        "SELECT s.session_date, s.session_no, "
        "COUNT(ar.id) FILTER (WHERE ar.status = 'present') AS present, "
        "COUNT(ar.id) FILTER (WHERE ar.status = 'absent') AS absent "
        "FROM attendance_sessions s LEFT JOIN attendance_records ar ON ar.session_id = s.id "
        "WHERE s.class_id = %s AND s.subject_id = %s "
        "GROUP BY s.id ORDER BY s.session_date, s.session_no",
        (class_id, subject_id),
    )
    return _rows_as_dicts(cur)
