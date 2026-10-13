"""THE ONLY DOOR to the data for the web pages.

Every function here takes (cur, user, ...). Before touching the database it checks
what this user is allowed to see or change. The pages never call the repositories
directly, so hiding a button is never the only protection.

Rules
  admin    everything (users, students, attendance, marks, dashboard)
  teacher  only the classes + subjects assigned to them (looked up fresh in the database every time)
  student  only their OWN records; these functions take no student id at all, so
           changing an ID or a URL cannot show someone else's data
"""
from typing import Optional

from psycopg2.extras import Json

from app.config import get_settings
from app.repositories import analytics_repository as analytics_repo
from app.repositories import attendance_repository as att_repo
from app.repositories import marks_repository as marks_repo
from app.repositories import student_repository as stu_repo
from app.repositories.attendance_repository import DuplicateSessionError  # noqa: F401  (pages catch these)
from app.repositories.marks_repository import AssessmentNotFoundError, DuplicateAssessmentError  # noqa: F401
from app.repositories.student_repository import DuplicateStudentError, StudentNotFoundError  # noqa: F401
from app.security.models import AuthorizationError, CurrentUser
from app.services import analytics, reports
from app.services import attendance_import as attendance_import_module
from app.services import marks_import as marks_import_module
from app.services import student_import as student_import_module
from app.services.student_import import ImportResult, RowError  # noqa: F401
from app.validation import ValidationError


def _rows_as_dicts(cur) -> list:
    columns = [c[0] for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


# ---------------------------------------------------------------- permission helpers
def _require_admin(user: CurrentUser) -> None:
    if user is None or user.role != "admin":
        raise AuthorizationError("Only an administrator can do this.")


def _scope(cur, user: CurrentUser):
    """None = no limit (admin). Set of (class_id, subject_id) for a teacher. Students are refused."""
    if user is None:
        raise AuthorizationError("Please log in.")
    if user.role == "admin":
        return None
    if user.role == "teacher":
        if user.teacher_id is None:
            return set()
        cur.execute("SELECT class_id, subject_id FROM teacher_assignments WHERE teacher_id = %s",
                    (user.teacher_id,))
        return {(c, s) for c, s in cur.fetchall()}
    raise AuthorizationError("Your account type cannot use this function.")


def _classes_in(scope) -> set:
    return {c for c, _ in scope}


def _require_pair(cur, user: CurrentUser, class_id: int, subject_id: int) -> None:
    scope = _scope(cur, user)
    if scope is not None and (class_id, subject_id) not in scope:
        raise AuthorizationError("You are not assigned to this class and subject.")


def _restrict_import_to_scope(result: ImportResult, scope) -> ImportResult:
    """Rows for classes/subjects the teacher is not assigned to become errors."""
    if scope is None:
        return result
    kept = []
    for row in result.valid_rows:
        if (row["class_id"], row["subject_id"]) in scope:
            kept.append(row)
        else:
            result.errors.append(RowError(row["row_number"], row["student_code"],
                                          "You are not assigned to this class and subject."))
    result.valid_rows = kept
    result.errors.sort(key=lambda e: e.row_number)
    return result


def _audit_event(cur, user: CurrentUser, action: str, table_name: str, new_value=None, old_value=None,
                 record_id=None) -> None:
    """Appends one row to the audit log (who did what, with old and new values)."""
    cur.execute(
        "INSERT INTO audit_logs (user_id, action, table_name, record_id, old_value, new_value) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (user.user_id, action, table_name, record_id,
         Json(old_value) if old_value is not None else None,
         Json(new_value) if new_value is not None else None),
    )


# ---------------------------------------------------------------- classes, subjects, departments
def list_classes(cur, user: CurrentUser) -> list:
    scope = _scope(cur, user)
    classes = stu_repo.list_classes(cur)
    if scope is None:
        return classes
    allowed = _classes_in(scope)
    return [c for c in classes if c["id"] in allowed]


def list_subjects_for_class(cur, user: CurrentUser, class_id: int) -> list:
    scope = _scope(cur, user)
    subjects = att_repo.list_subjects_for_class(cur, class_id)
    if scope is None:
        return subjects
    return [s for s in subjects if (class_id, s["id"]) in scope]


def list_departments(cur, user: CurrentUser) -> list:
    scope = _scope(cur, user)
    if scope is None:
        return analytics_repo.list_departments(cur)
    cur.execute("SELECT DISTINCT d.id, d.name FROM departments d JOIN classes c ON c.department_id = d.id "
                "WHERE c.id = ANY(%s) ORDER BY d.name", (sorted(_classes_in(scope)),))
    return _rows_as_dicts(cur)


def list_all_subjects(cur, user: CurrentUser) -> list:
    scope = _scope(cur, user)
    subjects = analytics_repo.list_all_subjects(cur)
    if scope is None:
        return subjects
    allowed = {s for _, s in scope}
    return [s for s in subjects if s["id"] in allowed]


# ---------------------------------------------------------------- students
def search_students(cur, user: CurrentUser, text: Optional[str] = None, class_id: Optional[int] = None,
                    semester: Optional[int] = None, status: Optional[str] = None, limit: int = 1000) -> list:
    scope = _scope(cur, user)
    class_ids = None
    if scope is not None:
        allowed = _classes_in(scope)
        if class_id is not None and class_id not in allowed:
            raise AuthorizationError("You are not assigned to this class.")
        class_ids = sorted(allowed)
    return stu_repo.search_students(cur, text=text, class_id=class_id, semester=semester,
                                    status=status, limit=limit, class_ids=class_ids)


def create_student(cur, user: CurrentUser, student_code: str, name: str, class_id: int,
                   status: str = "active") -> int:
    _require_admin(user)
    new_id = stu_repo.create_student(cur, student_code, name, class_id, status)
    _audit_event(cur, user, "student_create", "students",
                 {"student_code": student_code.strip(), "name": name.strip(), "class_id": class_id, "status": status},
                 record_id=new_id)
    return new_id


def update_student(cur, user: CurrentUser, student_id: int, name: Optional[str] = None,
                   class_id: Optional[int] = None, status: Optional[str] = None) -> None:
    _require_admin(user)
    old = stu_repo.get_student(cur, student_id)
    if old is None:
        raise StudentNotFoundError(f"No student with id {student_id}.")
    stu_repo.update_student(cur, student_id, name=name, class_id=class_id, status=status)
    new = stu_repo.get_student(cur, student_id)
    changed = [k for k in ("name", "class_id", "status") if old[k] != new[k]]
    if changed:
        _audit_event(cur, user, "student_update", "students", {k: new[k] for k in changed},
                     old_value={k: old[k] for k in changed}, record_id=student_id)


def validate_students_import(cur, user: CurrentUser, df) -> ImportResult:
    _require_admin(user)
    return student_import_module.validate_against_database(cur, df)


def import_students(cur, user: CurrentUser, df) -> ImportResult:
    _require_admin(user)
    result = student_import_module.import_students(cur, df)
    if result.inserted:
        _audit_event(cur, user, "student_import", "students", {"rows": result.inserted})
    return result


# ---------------------------------------------------------------- attendance
def get_session_statuses(cur, user: CurrentUser, class_id: int, subject_id: int, session_date, session_no: int):
    _require_pair(cur, user, class_id, subject_id)
    return att_repo.get_session_statuses(cur, class_id, subject_id, session_date, session_no)


def save_attendance(cur, user: CurrentUser, class_id: int, subject_id: int, session_date, session_no: int,
                    statuses: dict, overwrite: bool = False) -> dict:
    _require_pair(cur, user, class_id, subject_id)
    before = att_repo.get_session_statuses(cur, class_id, subject_id, session_date, session_no) if overwrite else None
    result = att_repo.save_attendance(cur, class_id, subject_id, session_date, session_no, statuses,
                                      overwrite=overwrite, created_by=user.user_id)
    if result["created"]:
        _audit_event(cur, user, "attendance_create", "attendance_sessions", {"records": result["records"]},
                     record_id=result["session_id"])
    elif before is not None:
        changes = [{"student_id": sid, "old": before.get(sid), "new": new}
                   for sid, new in statuses.items() if before.get(sid) != new]
        if changes:
            _audit_event(cur, user, "attendance_update", "attendance_sessions", {"changes": changes},
                         record_id=result["session_id"])
    return result


def attendance_summary(cur, user: CurrentUser, class_id: int, subject_id: int) -> list:
    _require_pair(cur, user, class_id, subject_id)
    return att_repo.attendance_summary(cur, class_id, subject_id)


def list_sessions(cur, user: CurrentUser, class_id: int, subject_id: int) -> list:
    _require_pair(cur, user, class_id, subject_id)
    return att_repo.list_sessions(cur, class_id, subject_id)


def validate_attendance_import(cur, user: CurrentUser, df) -> ImportResult:
    scope = _scope(cur, user)
    return _restrict_import_to_scope(attendance_import_module.validate_attendance_against_database(cur, df), scope)


def import_attendance(cur, user: CurrentUser, df) -> ImportResult:
    result = validate_attendance_import(cur, user, df)
    if result.errors:
        return result
    imported = attendance_import_module.import_attendance(cur, df, created_by=user.user_id)
    if imported.inserted:
        _audit_event(cur, user, "attendance_import", "attendance_records", {"rows": imported.inserted})
    return imported


# ---------------------------------------------------------------- marks
def _assessment_checked(cur, user: CurrentUser, assessment_id: int) -> dict:
    assessment = marks_repo.get_assessment(cur, assessment_id)
    if assessment is None:
        raise AssessmentNotFoundError(f"No assessment with id {assessment_id}.")
    _require_pair(cur, user, assessment["class_id"], assessment["subject_id"])
    return assessment


def create_assessment(cur, user: CurrentUser, class_id: int, subject_id: int, name: str, max_marks,
                      assessment_date=None) -> int:
    _require_pair(cur, user, class_id, subject_id)
    return marks_repo.create_assessment(cur, class_id, subject_id, name, max_marks, assessment_date)


def list_assessments(cur, user: CurrentUser, class_id: int, subject_id: int) -> list:
    _require_pair(cur, user, class_id, subject_id)
    return marks_repo.list_assessments(cur, class_id, subject_id)


def marks_for_assessment(cur, user: CurrentUser, assessment_id: int) -> list:
    _assessment_checked(cur, user, assessment_id)
    return marks_repo.marks_for_assessment(cur, assessment_id)


def save_marks(cur, user: CurrentUser, assessment_id: int, marks: dict) -> dict:
    _assessment_checked(cur, user, assessment_id)
    return marks_repo.save_marks(cur, assessment_id, marks, updated_by=user.user_id)


def get_marks_history(cur, user: CurrentUser, assessment_id: int, limit: int = 100) -> list:
    _assessment_checked(cur, user, assessment_id)
    return marks_repo.get_marks_history(cur, assessment_id, limit)


def fetch_marks_rows(cur, user: CurrentUser, class_id: int, subject_id: Optional[int] = None) -> list:
    scope = _scope(cur, user)
    if scope is None:
        return marks_repo.fetch_marks_rows(cur, class_id, subject_id)
    if subject_id is not None:
        _require_pair(cur, user, class_id, subject_id)
        return marks_repo.fetch_marks_rows(cur, class_id, subject_id)
    subject_ids = sorted(s for c, s in scope if c == class_id)
    if not subject_ids:
        raise AuthorizationError("You are not assigned to this class.")
    rows = []
    for sid in subject_ids:
        rows.extend(marks_repo.fetch_marks_rows(cur, class_id, sid))
    return rows


def validate_marks_import(cur, user: CurrentUser, df) -> ImportResult:
    scope = _scope(cur, user)
    return _restrict_import_to_scope(marks_import_module.validate_marks_against_database(cur, df), scope)


def import_marks(cur, user: CurrentUser, df) -> ImportResult:
    result = validate_marks_import(cur, user, df)
    if result.errors:
        return result
    imported = marks_import_module.import_marks(cur, df, user_id=user.user_id)
    if imported.inserted:
        _audit_event(cur, user, "marks_import_summary", "marks", {"rows": imported.inserted})
    return imported


# ---------------------------------------------------------------- dashboard (admin = all, teacher = assigned)
def _dashboard_filters(cur, user: CurrentUser, filters: Optional[dict]):
    scope = _scope(cur, user)
    filters = dict(filters or {})
    filters.pop("allowed_class_ids", None)  # callers can never set this themselves
    if scope is not None:
        allowed = _classes_in(scope)
        if filters.get("class_id") is not None and filters["class_id"] not in allowed:
            raise AuthorizationError("You are not assigned to this class.")
        filters["allowed_class_ids"] = sorted(allowed)
    return filters, scope


def dashboard_student_count(cur, user: CurrentUser, filters: Optional[dict] = None) -> int:
    filters, _ = _dashboard_filters(cur, user, filters)
    return analytics_repo.count_active_students(cur, filters)


def dashboard_attendance_rows(cur, user: CurrentUser, filters: Optional[dict] = None) -> list:
    filters, scope = _dashboard_filters(cur, user, filters)
    rows = analytics_repo.fetch_attendance_rows(cur, filters)
    if scope is None:
        return rows
    return [r for r in rows if (r["class_id"], r["subject_id"]) in scope]


def dashboard_marks_rows(cur, user: CurrentUser, filters: Optional[dict] = None) -> list:
    filters, scope = _dashboard_filters(cur, user, filters)
    rows = analytics_repo.fetch_marks_rows(cur, filters)
    if scope is None:
        return rows
    return [r for r in rows if (r["class_id"], r["subject_id"]) in scope]


# ---------------------------------------------------------------- a student's own records
def _own_student_id(user: CurrentUser) -> int:
    if user is None or user.role != "student" or user.student_id is None:
        raise AuthorizationError("This is only available to students with a linked student record.")
    return user.student_id


def my_profile(cur, user: CurrentUser) -> dict:
    student_id = _own_student_id(user)
    cur.execute(
        "SELECT s.student_code, s.name, d.name AS department, c.name AS class_name, c.semester, s.status "
        "FROM students s JOIN classes c ON c.id = s.class_id JOIN departments d ON d.id = c.department_id "
        "WHERE s.id = %s", (student_id,))
    return _rows_as_dicts(cur)[0]


def my_attendance(cur, user: CurrentUser) -> list:
    """Own attendance per subject (attended and total held sessions)."""
    student_id = _own_student_id(user)
    cur.execute(
        "SELECT sub.code AS subject_code, sub.name AS subject_name, "
        "COUNT(ar.id) FILTER (WHERE ar.status = 'present') AS attended, COUNT(ar.id) AS total_held "
        "FROM attendance_records ar JOIN attendance_sessions s ON s.id = ar.session_id "
        "JOIN subjects sub ON sub.id = s.subject_id WHERE ar.student_id = %s "
        "GROUP BY sub.id, sub.code, sub.name ORDER BY sub.code", (student_id,))
    return _rows_as_dicts(cur)


def my_marks(cur, user: CurrentUser) -> list:
    """Own marks, one row per assessment."""
    student_id = _own_student_id(user)
    cur.execute(
        "SELECT sub.code AS subject_code, sub.name AS subject_name, a.name AS assessment_name, "
        "a.assessment_date, m.obtained_marks, a.max_marks "
        "FROM marks m JOIN assessments a ON a.id = m.assessment_id JOIN subjects sub ON sub.id = a.subject_id "
        "WHERE m.student_id = %s ORDER BY sub.code, a.assessment_date NULLS LAST, a.id", (student_id,))
    rows = _rows_as_dicts(cur)
    for row in rows:
        row["obtained_marks"] = float(row["obtained_marks"])
        row["max_marks"] = float(row["max_marks"])
    return rows


# ---------------------------------------------------------------- CSV reports for staff
REPORT_TYPES = ("students", "attendance", "marks", "performance")
_ALLOWED_REPORT_FILTERS = {"department_id", "class_id", "semester", "subject_id", "status"}


def _clean_report_filters(filters: Optional[dict]) -> dict:
    cleaned = {}
    for key, value in (filters or {}).items():
        if key not in _ALLOWED_REPORT_FILTERS:
            raise ValidationError(f"Unknown filter: {key}")
        if value is None:
            continue
        if key == "status":
            if value not in ("active", "inactive"):
                raise ValidationError("Status must be active or inactive.")
        else:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValidationError(f"Filter {key} must be a whole number.")
            if key == "semester" and not 1 <= value <= 10:
                raise ValidationError("Semester must be between 1 and 10.")
        cleaned[key] = value
    return cleaned


def build_report(cur, user: CurrentUser, report_type: str, filters: Optional[dict] = None) -> "reports.ReportResult":
    """Builds a CSV report for admins and teachers. The filters are applied BEFORE the file is built.
    A teacher only ever gets rows from their own classes and subjects, a student gets AuthorizationError.
    Every export that contains data is written to the audit log."""
    if report_type not in REPORT_TYPES:
        raise ValidationError(f"Unknown report. Choose one of: {', '.join(REPORT_TYPES)}.")
    _scope(cur, user)  # refuses students and anonymous callers before anything else happens
    clean = _clean_report_filters(filters)
    status = clean.pop("status", None)
    if status is not None and report_type != "students":
        raise ValidationError("The status filter only applies to the students list.")
    settings = get_settings()

    if report_type == "students":
        rows = search_students(cur, user, class_id=clean.get("class_id"), semester=clean.get("semester"),
                               status=status)
        if clean.get("department_id") is not None:
            names = {d["id"]: d["name"] for d in list_departments(cur, user)}
            wanted = names.get(clean["department_id"])
            rows = [r for r in rows if r["department"] == wanted]
        result = reports.students_report(rows, {**clean, **({"status": status} if status else {})})
    elif report_type == "attendance":
        rows = dashboard_attendance_rows(cur, user, clean)
        result = reports.attendance_report(rows, settings.attendance_threshold, clean)
    elif report_type == "marks":
        result = reports.marks_report(dashboard_marks_rows(cur, user, clean), clean)
    else:
        student_att = analytics.student_attendance(dashboard_attendance_rows(cur, user, clean))
        student_marks = analytics.student_marks(dashboard_marks_rows(cur, user, clean))
        support = analytics.students_needing_support(
            student_att, student_marks, settings.attendance_threshold, settings.support_marks_threshold)
        result = reports.performance_report(student_att, student_marks, support, clean)

    if result.row_count > 0:
        cur.execute(
            "INSERT INTO audit_logs (user_id, action, table_name, new_value) VALUES (%s, 'export_report', 'reports', %s)",
            (user.user_id, Json({"report": report_type, "rows": result.row_count, "filters": result.filters})),
        )
    return result
