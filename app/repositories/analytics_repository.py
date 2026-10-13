"""Read-only SQL for the dashboard. Every number on the dashboard comes from these queries.

filters is a dict that may contain: department_id, class_id, semester, subject_id,
and allowed_class_ids (set by the security layer to limit a teacher to assigned classes).

NOTE (Milestone 7): teachers will only see their own classes, students only themselves.
"""
from typing import Optional


def _rows_as_dicts(cur) -> list:
    columns = [c[0] for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _where(filters: dict, with_subject_column: bool = True):
    """Builds extra WHERE conditions. Tables must use the aliases c (classes) and sub (subjects)."""
    clauses, params = [], []
    if filters.get("department_id") is not None:
        clauses.append("c.department_id = %s")
        params.append(filters["department_id"])
    if filters.get("class_id") is not None:
        clauses.append("c.id = %s")
        params.append(filters["class_id"])
    if filters.get("semester") is not None:
        clauses.append("c.semester = %s")
        params.append(filters["semester"])
    if filters.get("allowed_class_ids") is not None:
        clauses.append("c.id = ANY(%s)")
        params.append(list(filters["allowed_class_ids"]))
    if filters.get("subject_id") is not None:
        if with_subject_column:
            clauses.append("sub.id = %s")
        else:  # no subject column available: keep classes that study this subject
            clauses.append("EXISTS (SELECT 1 FROM subjects sb WHERE sb.id = %s "
                           "AND sb.department_id = c.department_id AND sb.semester = c.semester)")
        params.append(filters["subject_id"])
    sql = "".join(f" AND {c}" for c in clauses)
    return sql, params


# ---------- Filter dropdown options ----------
def list_departments(cur) -> list:
    cur.execute("SELECT id, name FROM departments ORDER BY name")
    return _rows_as_dicts(cur)


def list_all_subjects(cur) -> list:
    cur.execute("SELECT id, code, name, semester FROM subjects ORDER BY code")
    return _rows_as_dicts(cur)


# ---------- Metrics ----------
def count_active_students(cur, filters: Optional[dict] = None) -> int:
    extra, params = _where(filters or {}, with_subject_column=False)
    cur.execute(
        "SELECT COUNT(*) FROM students st JOIN classes c ON c.id = st.class_id "
        "WHERE st.status = 'active'" + extra,
        params,
    )
    return cur.fetchone()[0]


_GROUP_COLUMNS = (
    "st.id AS student_id, st.student_code, st.name, d.name AS department, "
    "c.id AS class_id, c.name AS class_name, c.semester, "
    "sub.id AS subject_id, sub.code AS subject_code, sub.name AS subject_name"
)


def fetch_attendance_rows(cur, filters: Optional[dict] = None) -> list:
    """One row per active student and subject: attended and total held sessions."""
    extra, params = _where(filters or {})
    cur.execute(
        f"SELECT {_GROUP_COLUMNS}, "
        "COUNT(ar.id) FILTER (WHERE ar.status = 'present') AS attended, "
        "COUNT(ar.id) AS total_held "
        "FROM attendance_records ar "
        "JOIN attendance_sessions s ON s.id = ar.session_id "
        "JOIN students st ON st.id = ar.student_id "
        "JOIN classes c ON c.id = st.class_id AND c.id = s.class_id "
        "JOIN departments d ON d.id = c.department_id "
        "JOIN subjects sub ON sub.id = s.subject_id "
        "WHERE st.status = 'active'" + extra + " "
        "GROUP BY st.id, st.student_code, st.name, d.name, c.id, c.name, c.semester, "
        "sub.id, sub.code, sub.name ORDER BY st.student_code, sub.code",
        params,
    )
    return _rows_as_dicts(cur)


def fetch_marks_rows(cur, filters: Optional[dict] = None) -> list:
    """One row per active student's mark, with its maximum."""
    extra, params = _where(filters or {})
    cur.execute(
        f"SELECT {_GROUP_COLUMNS}, a.name AS assessment_name, m.obtained_marks, a.max_marks "
        "FROM marks m "
        "JOIN assessments a ON a.id = m.assessment_id "
        "JOIN students st ON st.id = m.student_id "
        "JOIN classes c ON c.id = st.class_id AND c.id = a.class_id "
        "JOIN departments d ON d.id = c.department_id "
        "JOIN subjects sub ON sub.id = a.subject_id "
        "WHERE st.status = 'active'" + extra + " "
        "ORDER BY st.student_code, sub.code, a.name",
        params,
    )
    rows = _rows_as_dicts(cur)
    for row in rows:
        row["obtained_marks"] = float(row["obtained_marks"])
        row["max_marks"] = float(row["max_marks"])
    return rows
