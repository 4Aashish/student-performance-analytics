"""Login, lockout and password change."""
from dataclasses import dataclass
from typing import Optional

from app.security import passwords
from app.security.models import CurrentUser
from app.validation import ValidationError

MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15
GENERIC_FAILURE = "Invalid username or password."

_dummy_hash: Optional[str] = None


@dataclass
class LoginResult:
    user: Optional[CurrentUser]
    message: str = ""


def _fake_check(password: str) -> None:
    """Costs the same time as a real check, so unknown usernames cannot be guessed by timing."""
    global _dummy_hash
    import bcrypt

    if _dummy_hash is None:
        _dummy_hash = bcrypt.hashpw(b"not-a-real-password-1", bcrypt.gensalt()).decode("ascii")
    passwords.verify_password(password, _dummy_hash)


def _audit(cur, user_id, action: str) -> None:
    cur.execute(
        "INSERT INTO audit_logs (user_id, action, table_name, record_id) VALUES (%s, %s, 'users', %s)",
        (user_id, action, user_id),
    )


def authenticate(cur, username: str, password: str) -> LoginResult:
    """Never raises for a wrong login. Wrong password, unknown user and disabled account
    all give the same message. After 5 wrong passwords the account is locked for 15 minutes."""
    username = (username or "").strip().lower()
    password = password or ""
    cur.execute(
        "SELECT u.id, u.username, u.password_hash, u.role, u.is_active, u.failed_attempts, "
        "(u.locked_until IS NOT NULL AND u.locked_until > now()) AS is_locked, "
        "COALESCE(CEIL(EXTRACT(EPOCH FROM (u.locked_until - now())) / 60), 0) AS minutes_left, "
        "t.id AS teacher_id, s.id AS student_id "
        "FROM users u LEFT JOIN teachers t ON t.user_id = u.id LEFT JOIN students s ON s.user_id = u.id "
        "WHERE u.username = %s",
        (username,),
    )
    row = cur.fetchone()
    if row is None:
        _fake_check(password)
        return LoginResult(None, GENERIC_FAILURE)

    user_id, uname, pw_hash, role, is_active, failed, is_locked, minutes_left, teacher_id, student_id = row
    if is_locked:
        return LoginResult(None, f"Too many failed attempts. Try again in {int(minutes_left)} minute(s).")

    correct = passwords.verify_password(password, pw_hash)
    if correct and is_active:
        cur.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = %s", (user_id,))
        _audit(cur, user_id, "login_success")
        return LoginResult(CurrentUser(user_id, uname, role, teacher_id, student_id))

    if not correct:
        failed += 1
        if failed >= MAX_FAILED_ATTEMPTS:
            cur.execute(
                "UPDATE users SET failed_attempts = 0, locked_until = now() + (%s * interval '1 minute') WHERE id = %s",
                (LOCK_MINUTES, user_id),
            )
            _audit(cur, user_id, "login_locked")
            return LoginResult(None, f"Too many failed attempts. The account is locked for {LOCK_MINUTES} minutes.")
        cur.execute("UPDATE users SET failed_attempts = %s WHERE id = %s", (failed, user_id))
        _audit(cur, user_id, "login_failed")
    return LoginResult(None, GENERIC_FAILURE)


def load_current_user(cur, user_id: int) -> Optional[CurrentUser]:
    """Fresh copy from the database. None if the account no longer exists or is disabled."""
    cur.execute(
        "SELECT u.id, u.username, u.role, t.id, s.id "
        "FROM users u LEFT JOIN teachers t ON t.user_id = u.id LEFT JOIN students s ON s.user_id = u.id "
        "WHERE u.id = %s AND u.is_active",
        (user_id,),
    )
    row = cur.fetchone()
    return None if row is None else CurrentUser(*row)


def change_password(cur, user: CurrentUser, old_password: str, new_password: str) -> None:
    cur.execute("SELECT password_hash FROM users WHERE id = %s", (user.user_id,))
    row = cur.fetchone()
    if row is None or not passwords.verify_password(old_password or "", row[0]):
        raise ValidationError("Current password is wrong.")
    if new_password == old_password:
        raise ValidationError("New password must be different from the current password.")
    new_hash = passwords.hash_password(new_password, user.username)
    cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (new_hash, user.user_id))
    _audit(cur, user.user_id, "password_change")
