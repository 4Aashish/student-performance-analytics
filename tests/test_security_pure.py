import pytest

from app.security.passwords import hash_password, validate_password, verify_password
from app.security.session import is_session_expired
from app.validation import ValidationError


def test_good_password_accepted():
    validate_password("Sunshine42")


def test_short_password_rejected():
    with pytest.raises(ValidationError):
        validate_password("abc12")


def test_password_needs_letter_and_digit():
    for bad in ("12345678", "abcdefgh", "!!!!!!!!"):
        with pytest.raises(ValidationError):
            validate_password(bad)


def test_password_not_same_as_username():
    with pytest.raises(ValidationError):
        validate_password("Teacher123", username="teacher123")


def test_password_too_long_for_bcrypt_rejected():
    with pytest.raises(ValidationError):
        validate_password("a1" * 37)          # 74 bytes
    validate_password("a1" * 36)              # 72 bytes is fine


def test_multibyte_password_counts_bytes_not_characters():
    with pytest.raises(ValidationError):
        validate_password("é1" * 30)          # 60 characters but 90 bytes


def test_non_text_password_rejected():
    for bad in (None, 12345678, b"password1"):
        with pytest.raises(ValidationError):
            validate_password(bad)


def test_session_expiry_rules():
    assert is_session_expired(None, 1000.0) is False           # nothing recorded yet
    assert is_session_expired(1000.0, 1000.0 + 29 * 60) is False
    assert is_session_expired(1000.0, 1000.0 + 31 * 60) is True
    assert is_session_expired(1000.0, 1000.0 + 5 * 60, idle_minutes=1) is True


def test_username_rules():
    pytest.importorskip("psycopg2")
    from app.security.users import normalize_username

    assert normalize_username("  Teacher.One-1  ") == "teacher.one-1"
    for bad in ("ab", "has space", "semi;colon", "x" * 51, "", None, "naïve"):
        with pytest.raises(ValidationError):
            normalize_username(bad)


def test_password_is_hashed_not_stored_and_verifies():
    pytest.importorskip("bcrypt")
    hashed = hash_password("Sunshine42")
    assert hashed != "Sunshine42" and "Sunshine42" not in hashed
    assert hashed.startswith("$2")
    assert verify_password("Sunshine42", hashed) is True
    assert verify_password("sunshine42", hashed) is False
    assert hash_password("Sunshine42") != hashed          # random salt: same password, different hash


def test_verify_never_crashes_on_bad_input():
    pytest.importorskip("bcrypt")
    assert verify_password("x" * 100, "not-a-hash") is False
    assert verify_password("Sunshine42", "not-a-hash") is False
    assert verify_password("Sunshine42", None) is False
