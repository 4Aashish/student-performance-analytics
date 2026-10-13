"""All SQL for assessments and marks, including the modification history (audit log).

NOTE (Milestone 7): only the teacher assigned to a class/subject will be allowed to
call the write functions here. Until then, any code can change marks.
"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from psycopg2 import errors
from psycopg2.extras import Json

from app.repositories.attendance_repository import _check_subject_in_class
from app.validation import ValidationError, validate_marks

MAX_ALLOWED_MARKS = 9999.99  # column is NUMERIC(6,2)
_TWO_PLACES = Decimal("0.01")


class DuplicateAssessmentError(Exception):
    """An assessment with this name already exists for this class and subject."""


class AssessmentNotFoundError(Exception):
    """No assessment with this id."""


def _rows_as_dicts(cur) -> list:
    columns = [c[0] for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def to_decimal(value) -> Decimal:
    """Exact 2-decimal number for the database (call only after validation)."""
    return Decimal(str(value)).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


# ---------- Assessments ----------
def create_assessment(cur, class_id: int, subject_id: int, name: str, max_marks,
                      assessment_date: Optional[date] = None) -> int:
    name = (name or "").strip()
    if not name:
        raise ValidationError("Assessment name cannot be empty.")
    if len(name) > 100:
        raise ValidationError("Assessment name is too long (maximum 100 characters).")
    validate_marks(0, max_marks)  # max_marks must be a real number greater than zero
    if float(max_marks) > MAX_ALLOWED_MARKS:
        raise ValidationError(f"Maximum marks cannot be more than {MAX_ALLOWED_MARKS:g}.")
    _check_subject_in_class(cur, class_id, subject_id)

    cur.execute("SAVEPOINT create_assessment")
    try:
        cur.execute(
            "INSERT INTO assessments (class_id, subject_id, name, max_marks, assessment_date) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (class_id, subject_id, name, to_decimal(max_marks), assessment_date),
        )
    except errors.UniqueViolation:
        cur.execute("ROLLBACK TO SAVEPOINT create_assessment")
        raise DuplicateAssessmentError(f"An assessment named '{name}' already exists for this class and subject.")
    new_id = cur.fetchone()[0]
    cur.execute("RELEASE SAVEPOINT create_assessment")
    return new_id


def get_assessment(cur, assessment_id: int) -> Optional[dict]:
    cur.execute("SELECT id, class_id, subject_id, name, max_marks FROM assessments WHERE id = %s", (assessment_id,))
    rows = _rows_as_dicts(cur)
    if not rows:
        return None
    rows[0]["max_marks"] = float(rows[0]["max_marks"])
    return rows[0]


def list_assessments(cur, class_id: int, subject_id: int) -> list:
    cur.execute(
        "SELECT a.id, a.name, a.max_marks, a.assessment_date, COUNT(m.id) AS marks_entered "
        "FROM assessments a LEFT JOIN marks m ON m.assessment_id = a.id "
        "WHERE a.class_id = %s AND a.subject_id = %s "
        "GROUP BY a.id ORDER BY a.assessment_date NULLS LAST, a.name",
        (class_id, subject_id),
    )
    rows = _rows_as_dicts(cur)
    for row in rows:
        row["max_marks"] = float(row["max_marks"])
    return rows


# ---------- Marks ----------
def _audit(cur, user_id, action: str, record_id: int, old: Optional[dict], new: Optional[dict]) -> None:
    cur.execute(
        "INSERT INTO audit_logs (user_id, action, table_name, record_id, old_value, new_value) "
        "VALUES (%s, %s, 'marks', %s, %s, %s)",
        (user_id, action, record_id,
         Json(old) if old is not None else None, Json(new) if new is not None else None),
    )


def save_marks(cur, assessment_id: int, marks: dict, updated_by: Optional[int] = None) -> dict:
    """Saves marks. marks = {student_id: obtained_marks}.

    Everything is checked FIRST; if any value is wrong nothing is saved.
    Every new or changed mark is written to the audit log (old value -> new value).
    """
    assessment = get_assessment(cur, assessment_id)
    if assessment is None:
        raise AssessmentNotFoundError(f"No assessment with id {assessment_id}.")
    if not marks:
        raise ValidationError("No marks to save.")

    cur.execute(
        "SELECT id, student_code, status FROM students WHERE class_id = %s AND id = ANY(%s)",
        (assessment["class_id"], list(marks)),
    )
    students = {sid: (code, status) for sid, code, status in cur.fetchall()}

    problems = []
    for sid, value in marks.items():
        if sid not in students:
            problems.append(f"Student id {sid} does not belong to this class.")
            continue
        code, status = students[sid]
        if status != "active":
            problems.append(f"Student {code} is inactive.")
            continue
        try:
            validate_marks(value, assessment["max_marks"])
        except ValidationError as e:
            problems.append(f"Student {code}: {e}")
    if problems:
        shown = "; ".join(problems[:10])
        more = f" (and {len(problems) - 10} more)" if len(problems) > 10 else ""
        raise ValidationError(shown + more)

    cur.execute(
        "SELECT student_id, id, obtained_marks FROM marks WHERE assessment_id = %s AND student_id = ANY(%s)",
        (assessment_id, list(marks)),
    )
    existing = {sid: (mid, obtained) for sid, mid, obtained in cur.fetchall()}

    counts = {"created": 0, "updated": 0, "unchanged": 0}
    for sid, value in marks.items():
        new_value = to_decimal(value)
        if sid not in existing:
            cur.execute(
                "INSERT INTO marks (assessment_id, student_id, obtained_marks, updated_by) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (assessment_id, sid, new_value, updated_by),
            )
            _audit(cur, updated_by, "marks_create", cur.fetchone()[0], None, {"obtained_marks": str(new_value)})
            counts["created"] += 1
        else:
            marks_id, old_value = existing[sid]
            if old_value == new_value:
                counts["unchanged"] += 1
                continue
            cur.execute("UPDATE marks SET obtained_marks = %s, updated_by = %s WHERE id = %s",
                        (new_value, updated_by, marks_id))
            _audit(cur, updated_by, "marks_update", marks_id,
                   {"obtained_marks": str(old_value)}, {"obtained_marks": str(new_value)})
            counts["updated"] += 1
    return counts


def marks_for_assessment(cur, assessment_id: int) -> list:
    """Active students of the assessment's class with their marks (None = not entered yet)."""
    cur.execute(
        "SELECT st.id AS student_id, st.student_code, st.name, m.obtained_marks "
        "FROM students st LEFT JOIN marks m ON m.student_id = st.id AND m.assessment_id = %s "
        "WHERE st.class_id = (SELECT class_id FROM assessments WHERE id = %s) AND st.status = 'active' "
        "ORDER BY st.student_code",
        (assessment_id, assessment_id),
    )
    rows = _rows_as_dicts(cur)
    for row in rows:
        row["obtained_marks"] = None if row["obtained_marks"] is None else float(row["obtained_marks"])
    return rows


def fetch_marks_rows(cur, class_id: int, subject_id: Optional[int] = None) -> list:
    """Raw marks of active students, ready for marks_analysis."""
    sql = (
        "SELECT st.id AS student_id, st.student_code, st.name, sub.code AS subject_code, "
        "sub.name AS subject_name, a.name AS assessment_name, m.obtained_marks, a.max_marks "
        "FROM marks m JOIN assessments a ON a.id = m.assessment_id "
        "JOIN students st ON st.id = m.student_id JOIN subjects sub ON sub.id = a.subject_id "
        "WHERE a.class_id = %s AND st.status = 'active'"
    )
    params = [class_id]
    if subject_id is not None:
        sql += " AND a.subject_id = %s"
        params.append(subject_id)
    sql += " ORDER BY sub.code, st.student_code, a.name"
    cur.execute(sql, params)
    rows = _rows_as_dicts(cur)
    for row in rows:
        row["obtained_marks"] = float(row["obtained_marks"])
        row["max_marks"] = float(row["max_marks"])
    return rows


def get_marks_history(cur, assessment_id: int, limit: int = 100) -> list:
    """Newest first: who/what changed, old marks and new marks."""
    cur.execute(
        "SELECT al.id, al.created_at, al.action, st.student_code, "
        "al.old_value->>'obtained_marks' AS old_marks, al.new_value->>'obtained_marks' AS new_marks "
        "FROM audit_logs al JOIN marks m ON m.id = al.record_id "
        "JOIN students st ON st.id = m.student_id "
        "WHERE al.table_name = 'marks' AND m.assessment_id = %s "
        "ORDER BY al.id DESC LIMIT %s",
        (assessment_id, limit),
    )
    return _rows_as_dicts(cur)
