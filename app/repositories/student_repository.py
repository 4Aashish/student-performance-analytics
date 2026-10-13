"""All SQL for students lives here.

NOTE (Milestone 7): role-based authorization checks will be added to these
functions. Until then, any code that calls them can read and change students.
"""
from typing import Optional

from psycopg2 import errors

from app.validation import (
    MAX_STUDENT_CODE_LEN,
    MAX_STUDENT_NAME_LEN,
    VALID_STATUS,
    ValidationError,
    missing_required_fields,
)


class DuplicateStudentError(Exception):
    """A student with this student_code already exists."""


class StudentNotFoundError(Exception):
    """No student with this id."""


def _rows_as_dicts(cur) -> list:
    columns = [c[0] for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _check_name_and_status(name, status) -> None:
    if name is not None:
        if not str(name).strip():
            raise ValidationError("Name cannot be empty.")
        if len(str(name).strip()) > MAX_STUDENT_NAME_LEN:
            raise ValidationError(f"Name is too long (maximum {MAX_STUDENT_NAME_LEN} characters).")
    if status is not None and status not in VALID_STATUS:
        raise ValidationError(f"Status must be one of: {', '.join(VALID_STATUS)}.")


# ---------- Reference data ----------
def get_class_lookup(cur) -> dict:
    """{(department_name_lower, class_name_lower): {'id': .., 'semester': ..}}"""
    cur.execute(
        "SELECT d.name, c.name, c.id, c.semester "
        "FROM classes c JOIN departments d ON d.id = c.department_id"
    )
    return {
        (dept.lower(), cls.lower()): {"id": cid, "semester": sem}
        for dept, cls, cid, sem in cur.fetchall()
    }


def list_classes(cur) -> list:
    cur.execute(
        "SELECT c.id, d.name AS department, c.name AS class_name, c.semester "
        "FROM classes c JOIN departments d ON d.id = c.department_id "
        "ORDER BY d.name, c.semester, c.name"
    )
    return _rows_as_dicts(cur)


def existing_codes(cur, codes: list) -> set:
    cur.execute("SELECT student_code FROM students WHERE student_code = ANY(%s)", (list(codes),))
    return {row[0] for row in cur.fetchall()}


# ---------- Create / update ----------
def create_student(cur, student_code: str, name: str, class_id: int, status: str = "active") -> int:
    student_code = (student_code or "").strip()
    name = (name or "").strip()
    missing = missing_required_fields({"student_code": student_code, "name": name}, ["student_code", "name"])
    if missing:
        raise ValidationError(f"Required field(s) empty: {', '.join(missing)}.")
    if len(student_code) > MAX_STUDENT_CODE_LEN:
        raise ValidationError(f"Student ID is too long (maximum {MAX_STUDENT_CODE_LEN} characters).")
    _check_name_and_status(name, status)

    cur.execute("SAVEPOINT create_student")  # so a failure does not break the caller's transaction
    try:
        cur.execute(
            "INSERT INTO students (student_code, name, class_id, status) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (student_code, name, class_id, status),
        )
    except errors.UniqueViolation:
        cur.execute("ROLLBACK TO SAVEPOINT create_student")
        raise DuplicateStudentError(f"Student ID '{student_code}' already exists.")
    new_id = cur.fetchone()[0]
    cur.execute("RELEASE SAVEPOINT create_student")
    return new_id


def update_student(cur, student_id: int, name: Optional[str] = None,
                   class_id: Optional[int] = None, status: Optional[str] = None) -> None:
    """Changes only the fields you pass. student_code can never be changed."""
    _check_name_and_status(name, status)
    sets, params = [], []
    if name is not None:
        sets.append("name = %s")
        params.append(name.strip())
    if class_id is not None:
        sets.append("class_id = %s")
        params.append(class_id)
    if status is not None:
        sets.append("status = %s")
        params.append(status)
    if not sets:
        return
    params.append(student_id)
    cur.execute(f"UPDATE students SET {', '.join(sets)} WHERE id = %s", params)
    if cur.rowcount == 0:
        raise StudentNotFoundError(f"No student with id {student_id}.")


# ---------- Read ----------
def get_student(cur, student_id: int) -> Optional[dict]:
    cur.execute("SELECT id, student_code, name, class_id, status FROM students WHERE id = %s", (student_id,))
    rows = _rows_as_dicts(cur)
    return rows[0] if rows else None



def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_students(cur, text: Optional[str] = None, class_id: Optional[int] = None,
                    semester: Optional[int] = None, status: Optional[str] = None,
                    limit: int = 1000, class_ids: Optional[list] = None) -> list:
    if class_ids is not None and len(class_ids) == 0:
        return []
    where, params = [], []
    if class_ids is not None:
        where.append("s.class_id = ANY(%s)")
        params.append(list(class_ids))
    if text and text.strip():
        pattern = f"%{_escape_like(text.strip())}%"
        where.append("(s.student_code ILIKE %s OR s.name ILIKE %s)")
        params += [pattern, pattern]
    if class_id is not None:
        where.append("s.class_id = %s")
        params.append(class_id)
    if semester is not None:
        where.append("c.semester = %s")
        params.append(semester)
    if status is not None:
        where.append("s.status = %s")
        params.append(status)
    sql = (
        "SELECT s.id, s.student_code, s.name, d.name AS department, "
        "c.id AS class_id, c.name AS class_name, c.semester, s.status "
        "FROM students s "
        "JOIN classes c ON c.id = s.class_id "
        "JOIN departments d ON d.id = c.department_id "
    )
    if where:
        sql += "WHERE " + " AND ".join(where) + " "
    sql += "ORDER BY s.student_code LIMIT %s"
    params.append(limit)
    cur.execute(sql, params)
    return _rows_as_dicts(cur)


def count_students(cur, status: Optional[str] = None) -> int:
    if status is None:
        cur.execute("SELECT count(*) FROM students")
    else:
        cur.execute("SELECT count(*) FROM students WHERE status = %s", (status,))
    return cur.fetchone()[0]
