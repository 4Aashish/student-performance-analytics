"""Account management. Every function except create_first_admin needs an ADMIN as actor."""
import re
from typing import Optional

from psycopg2 import errors

from app.repositories.attendance_repository import _check_subject_in_class
from app.security import passwords
from app.security.models import ROLES, AuthorizationError, CurrentUser
from app.validation import ValidationError

USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,50}$")


def _rows_as_dicts(cur) -> list:
    columns = [c[0] for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _require_admin(actor: CurrentUser) -> None:
    if actor is None or actor.role != "admin":
        raise AuthorizationError("Only an administrator can do this.")


def _audit(cur, actor_id, action: str, table: str, record_id) -> None:
    cur.execute(
        "INSERT INTO audit_logs (user_id, action, table_name, record_id) VALUES (%s, %s, %s, %s)",
        (actor_id, action, table, record_id),
    )


def normalize_username(username: str) -> str:
    username = (username or "").strip().lower()
    if not USERNAME_RE.match(username):
        raise ValidationError("Username must be 3 to 50 characters: letters, digits, dot, dash or underscore.")
    return username


def _insert_user(cur, username: str, password: str, role: str) -> int:
    username = normalize_username(username)
    if role not in ROLES:
        raise ValidationError(f"Role must be one of: {', '.join(ROLES)}.")
    password_hash = passwords.hash_password(password, username)
    cur.execute("SAVEPOINT insert_user")
    try:
        cur.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s) RETURNING id",
            (username, password_hash, role),
        )
    except errors.UniqueViolation:
        cur.execute("ROLLBACK TO SAVEPOINT insert_user")
        raise ValidationError(f"Username '{username}' is already taken.")
    user_id = cur.fetchone()[0]
    cur.execute("RELEASE SAVEPOINT insert_user")
    return user_id


def create_first_admin(cur, username: str, password: str) -> int:
    """Only works while NO admin exists (used by scripts/create_admin.py)."""
    cur.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
    if cur.fetchone()[0] > 0:
        raise ValidationError("An admin already exists. Log in and use the Users page instead.")
    user_id = _insert_user(cur, username, password, "admin")
    _audit(cur, user_id, "create_first_admin", "users", user_id)
    return user_id


def create_account(cur, actor: CurrentUser, username: str, password: str, role: str,
                   name: Optional[str] = None, department_id: Optional[int] = None,
                   student_id: Optional[int] = None) -> int:
    _require_admin(actor)
    if role == "teacher":
        if not (name or "").strip():
            raise ValidationError("Teacher name is required.")
        cur.execute("SELECT 1 FROM departments WHERE id = %s", (department_id,))
        if cur.fetchone() is None:
            raise ValidationError("Choose a valid department for the teacher.")
    if role == "student":
        cur.execute("SELECT user_id FROM students WHERE id = %s", (student_id,))
        row = cur.fetchone()
        if row is None:
            raise ValidationError("Choose a valid student.")
        if row[0] is not None:
            raise ValidationError("This student already has an account.")

    user_id = _insert_user(cur, username, password, role)
    if role == "teacher":
        cur.execute("INSERT INTO teachers (user_id, name, department_id) VALUES (%s, %s, %s)",
                    (user_id, name.strip(), department_id))
    elif role == "student":
        cur.execute("UPDATE students SET user_id = %s WHERE id = %s", (user_id, student_id))
    _audit(cur, actor.user_id, f"create_{role}_account", "users", user_id)
    return user_id


def list_users(cur, actor: CurrentUser) -> list:
    _require_admin(actor)
    cur.execute(
        "SELECT u.id, u.username, u.role, u.is_active, "
        "(u.locked_until IS NOT NULL AND u.locked_until > now()) AS locked, "
        "COALESCE(t.name, s.name) AS profile_name, s.student_code "
        "FROM users u LEFT JOIN teachers t ON t.user_id = u.id LEFT JOIN students s ON s.user_id = u.id "
        "ORDER BY u.role, u.username"
    )
    return _rows_as_dicts(cur)


def set_user_active(cur, actor: CurrentUser, user_id: int, active: bool) -> None:
    _require_admin(actor)
    if user_id == actor.user_id and not active:
        raise ValidationError("You cannot disable your own account.")
    cur.execute("UPDATE users SET is_active = %s, failed_attempts = 0, locked_until = NULL WHERE id = %s",
                (active, user_id))
    if cur.rowcount == 0:
        raise ValidationError("No such user.")
    _audit(cur, actor.user_id, "enable_user" if active else "disable_user", "users", user_id)


def reset_password(cur, actor: CurrentUser, user_id: int, new_password: str) -> None:
    _require_admin(actor)
    cur.execute("SELECT username FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    if row is None:
        raise ValidationError("No such user.")
    password_hash = passwords.hash_password(new_password, row[0])
    cur.execute("UPDATE users SET password_hash = %s, failed_attempts = 0, locked_until = NULL WHERE id = %s",
                (password_hash, user_id))
    _audit(cur, actor.user_id, "reset_password", "users", user_id)


def list_teachers(cur, actor: CurrentUser) -> list:
    _require_admin(actor)
    cur.execute(
        "SELECT t.id, t.name, u.username, d.name AS department FROM teachers t "
        "JOIN users u ON u.id = t.user_id JOIN departments d ON d.id = t.department_id ORDER BY t.name"
    )
    return _rows_as_dicts(cur)


def list_unlinked_students(cur, actor: CurrentUser) -> list:
    """Active students who do not have a login yet."""
    _require_admin(actor)
    cur.execute("SELECT id, student_code, name FROM students WHERE user_id IS NULL AND status = 'active' "
                "ORDER BY student_code")
    return _rows_as_dicts(cur)


def assign_teacher(cur, actor: CurrentUser, teacher_id: int, class_id: int, subject_id: int) -> int:
    _require_admin(actor)
    cur.execute("SELECT 1 FROM teachers WHERE id = %s", (teacher_id,))
    if cur.fetchone() is None:
        raise ValidationError("Choose a valid teacher.")
    _check_subject_in_class(cur, class_id, subject_id)
    cur.execute("SAVEPOINT assign_teacher")
    try:
        cur.execute(
            "INSERT INTO teacher_assignments (teacher_id, subject_id, class_id) VALUES (%s, %s, %s) RETURNING id",
            (teacher_id, subject_id, class_id),
        )
    except errors.UniqueViolation:
        cur.execute("ROLLBACK TO SAVEPOINT assign_teacher")
        raise ValidationError("This teacher is already assigned to this class and subject.")
    assignment_id = cur.fetchone()[0]
    cur.execute("RELEASE SAVEPOINT assign_teacher")
    _audit(cur, actor.user_id, "assign_teacher", "teacher_assignments", assignment_id)
    return assignment_id


def list_assignments(cur, actor: CurrentUser) -> list:
    _require_admin(actor)
    cur.execute(
        "SELECT ta.id, t.name AS teacher, c.name AS class_name, sub.code AS subject_code, sub.name AS subject_name "
        "FROM teacher_assignments ta JOIN teachers t ON t.id = ta.teacher_id "
        "JOIN classes c ON c.id = ta.class_id JOIN subjects sub ON sub.id = ta.subject_id "
        "ORDER BY t.name, c.name, sub.code"
    )
    return _rows_as_dicts(cur)


def remove_assignment(cur, actor: CurrentUser, assignment_id: int) -> None:
    _require_admin(actor)
    cur.execute("DELETE FROM teacher_assignments WHERE id = %s", (assignment_id,))
    if cur.rowcount == 0:
        raise ValidationError("No such assignment.")
    _audit(cur, actor.user_id, "remove_assignment", "teacher_assignments", assignment_id)
