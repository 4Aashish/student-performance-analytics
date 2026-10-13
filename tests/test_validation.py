import pandas as pd
import pytest

from app.validation import (
    ValidationError,
    attendance_flag,
    attendance_percentage,
    find_duplicates,
    marks_percentage,
    missing_required_fields,
    validate_marks,
)


# ----- attendance -----
def test_attendance_percentage_basic():
    assert attendance_percentage(8, 10) == 80.0


def test_attendance_zero_sessions_returns_none_not_error():
    assert attendance_percentage(0, 0) is None


def test_attendance_all_and_none():
    assert attendance_percentage(10, 10) == 100.0
    assert attendance_percentage(0, 10) == 0.0


def test_attendance_more_than_held_rejected():
    with pytest.raises(ValidationError):
        attendance_percentage(11, 10)


def test_attendance_negative_rejected():
    with pytest.raises(ValidationError):
        attendance_percentage(-1, 10)
    with pytest.raises(ValidationError):
        attendance_percentage(1, -10)


def test_attendance_non_integer_rejected():
    for bad in (None, "8", 7.5, True):
        with pytest.raises(ValidationError):
            attendance_percentage(bad, 10)


def test_attendance_flag_boundaries():
    assert attendance_flag(74.9, 75) == "below_threshold"
    assert attendance_flag(75.0, 75) == "ok"
    assert attendance_flag(100.0, 75) == "ok"
    assert attendance_flag(None, 75) == "no_data"


# ----- marks -----
def test_marks_valid_boundaries():
    validate_marks(0, 30)
    validate_marks(30, 30)
    validate_marks(12.5, 30)


def test_marks_negative_rejected():
    with pytest.raises(ValidationError):
        validate_marks(-1, 30)


def test_marks_above_max_rejected():
    with pytest.raises(ValidationError):
        validate_marks(31, 30)


def test_marks_max_must_be_positive():
    for bad_max in (0, -5):
        with pytest.raises(ValidationError):
            validate_marks(0, bad_max)


def test_marks_missing_or_non_numeric_rejected():
    for bad in (None, "abc", float("nan"), float("inf"), True):
        with pytest.raises(ValidationError):
            validate_marks(bad, 30)
    with pytest.raises(ValidationError):
        validate_marks(10, None)


def test_marks_percentage():
    assert marks_percentage(15, 30) == 50.0
    assert marks_percentage(0, 50) == 0.0


# ----- required fields -----
def test_missing_required_fields():
    record = {"student_code": "S1", "name": "  ", "class_name": None, "status": float("nan")}
    missing = missing_required_fields(record, ["student_code", "name", "class_name", "status", "department"])
    assert missing == ["name", "class_name", "status", "department"]


def test_no_missing_fields():
    assert missing_required_fields({"a": "x", "b": 0}, ["a", "b"]) == []


# ----- duplicates -----
def test_find_duplicates_returns_all_copies():
    df = pd.DataFrame({"s": ["A", "A", "B"], "d": ["x", "x", "x"], "v": [1, 2, 3]})
    dups = find_duplicates(df, ["s", "d"])
    assert len(dups) == 2
    assert set(dups["s"]) == {"A"}


def test_find_duplicates_none_and_empty():
    df = pd.DataFrame({"s": ["A", "B"]})
    assert find_duplicates(df, ["s"]).empty
    assert find_duplicates(pd.DataFrame({"s": []}), ["s"]).empty


def test_find_duplicates_missing_column_rejected():
    with pytest.raises(ValidationError):
        find_duplicates(pd.DataFrame({"s": ["A"]}), ["nope"])
