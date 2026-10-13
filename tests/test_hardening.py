import io

import pytest

from app.security.passwords import COMMON_PASSWORDS, validate_password
from app.services.csv_utils import MAX_CSV_ROWS, read_csv_required
from app.services.student_import import read_students_csv
from app.validation import ValidationError


def csv_with_rows(count, header="student_code,name,class_name,department,semester\n"):
    body = "".join(f"S{i},N{i},C,D,3\n" for i in range(count))
    return io.BytesIO((header + body).encode("utf-8"))


def test_csv_with_exactly_the_maximum_rows_is_accepted():
    required = ["student_code", "name", "class_name", "department", "semester"]
    assert len(read_csv_required(csv_with_rows(MAX_CSV_ROWS), required)) == MAX_CSV_ROWS
    assert len(read_students_csv(csv_with_rows(MAX_CSV_ROWS))) == MAX_CSV_ROWS


def test_csv_with_too_many_rows_is_refused_by_both_readers():
    required = ["student_code", "name", "class_name", "department", "semester"]
    with pytest.raises(ValidationError) as err:
        read_csv_required(csv_with_rows(MAX_CSV_ROWS + 1), required)
    assert "split" in str(err.value)
    with pytest.raises(ValidationError):
        read_students_csv(csv_with_rows(MAX_CSV_ROWS + 1))


def test_common_passwords_are_refused_even_if_they_have_a_letter_and_a_digit():
    for common in ("Password1", "QWERTY123", "Admin123", "Welcome1"):
        with pytest.raises(ValidationError) as err:
            validate_password(common)
        assert "too common" in str(err.value)
    assert all(p == p.lower() for p in COMMON_PASSWORDS)


def test_normal_passwords_still_accepted():
    for good in ("Sunshine42", "Brand-new9", "Kapil&Aashish2026"):
        validate_password(good)


def test_user_message_hides_database_details_and_gives_a_reference(tmp_path, monkeypatch):
    pytest.importorskip("psycopg2")
    import psycopg2

    import app.errors as errors

    monkeypatch.setattr(errors, "LOG_DIR", tmp_path)
    monkeypatch.setattr(errors, "_logger", None)
    monkeypatch.setattr(errors.logging.getLogger("student_analytics"), "handlers", [])
    secret = 'connection to server at "10.20.30.40", port 5432 failed: password authentication failed for user "postgres"'
    message = errors.user_message(psycopg2.OperationalError(secret))
    assert "10.20.30.40" not in message and "postgres" not in message and "5432" not in message
    assert "reference" in message
    for handler in list(errors.logging.getLogger("student_analytics").handlers):
        handler.flush()
    log_text = (tmp_path / "app.log").read_text(encoding="utf-8")
    assert "10.20.30.40" in log_text and message.split("reference ")[1].rstrip(").") in log_text
    for handler in list(errors.logging.getLogger("student_analytics").handlers):
        handler.close()                      # lets Windows delete the temporary folder


def test_user_message_passes_our_own_messages_through():
    pytest.importorskip("psycopg2")
    from app.errors import user_message
    from app.security.models import AuthorizationError

    assert user_message(ValidationError("Marks cannot be negative.")) == "Marks cannot be negative."
    assert user_message(AuthorizationError("You are not assigned to this class.")) == "You are not assigned to this class."
