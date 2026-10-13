"""Password hashing (bcrypt) and password rules. Plain passwords are never stored."""
from typing import Optional

from app.validation import ValidationError

MIN_LENGTH = 8
MAX_BYTES = 72
COMMON_PASSWORDS = {
    "password1", "password12", "password123", "password1234", "qwerty123", "qwerty1234", "abc12345",
    "abcd1234", "admin123", "admin1234", "welcome1", "welcome123", "iloveyou1", "letmein123", "changeme1",
    "passw0rd", "p@ssw0rd", "test1234", "student123", "teacher123", "1q2w3e4r", "11111111a", "a1234567",
}  # bcrypt only uses the first 72 bytes, so longer passwords are refused


def validate_password(password, username: Optional[str] = None) -> None:
    if not isinstance(password, str):
        raise ValidationError("Password must be text.")
    if len(password) < MIN_LENGTH:
        raise ValidationError(f"Password must be at least {MIN_LENGTH} characters long.")
    if len(password.encode("utf-8")) > MAX_BYTES:
        raise ValidationError(f"Password is too long (maximum {MAX_BYTES} bytes).")
    if not any(ch.isalpha() for ch in password) or not any(ch.isdigit() for ch in password):
        raise ValidationError("Password must contain at least one letter and one digit.")
    if password.lower() in COMMON_PASSWORDS:
        raise ValidationError("This password is too common. Choose a less predictable one.")
    if username and password.lower() == username.strip().lower():
        raise ValidationError("Password cannot be the same as the username.")


def hash_password(password: str, username: Optional[str] = None) -> str:
    import bcrypt

    validate_password(password, username)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    import bcrypt

    try:
        raw = password.encode("utf-8")
        if len(raw) > MAX_BYTES:
            return False
        return bcrypt.checkpw(raw, password_hash.encode("ascii"))
    except (ValueError, AttributeError, TypeError):
        return False
