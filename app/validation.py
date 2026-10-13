"""Pure validation and calculation rules (no database needed)."""
import math
import numbers
from typing import Optional

import pandas as pd


class ValidationError(ValueError):
    """Raised when data breaks a validation rule. The message is user-friendly."""


# ---------- Attendance ----------
def _check_count(value, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, numbers.Integral):
        raise ValidationError(f"{name} must be a whole number, got {value!r}.")
    if value < 0:
        raise ValidationError(f"{name} cannot be negative, got {value}.")


def attendance_percentage(attended: int, total_held: int) -> Optional[float]:
    """attended / total_held * 100. Returns None when no sessions were held yet."""
    _check_count(attended, "Attended sessions")
    _check_count(total_held, "Total held sessions")
    if attended > total_held:
        raise ValidationError(
            f"Attended sessions ({attended}) cannot be more than total held sessions ({total_held})."
        )
    if total_held == 0:
        return None
    return attended / total_held * 100


def attendance_flag(percentage: Optional[float], threshold: float) -> str:
    """Returns 'no_data', 'below_threshold' or 'ok'.

    This is only a WARNING indicator. It is NOT an official eligibility decision.
    """
    if percentage is None:
        return "no_data"
    return "below_threshold" if percentage < threshold else "ok"


# ---------- Marks ----------
def _to_number(value, name: str) -> float:
    if isinstance(value, bool) or value is None:
        raise ValidationError(f"{name} must be a number, got {value!r}.")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{name} must be a number, got {value!r}.")
    if not math.isfinite(number):
        raise ValidationError(f"{name} must be a real number, got {value!r}.")
    return number


def validate_marks(obtained, max_marks) -> None:
    """Raises ValidationError unless 0 <= obtained <= max_marks and max_marks > 0."""
    max_value = _to_number(max_marks, "Maximum marks")
    got = _to_number(obtained, "Obtained marks")
    if max_value <= 0:
        raise ValidationError(f"Maximum marks must be greater than zero, got {max_value:g}.")
    if got < 0:
        raise ValidationError(f"Obtained marks cannot be negative, got {got:g}.")
    if got > max_value:
        raise ValidationError(
            f"Obtained marks ({got:g}) cannot be more than maximum marks ({max_value:g})."
        )


def marks_percentage(obtained, max_marks) -> float:
    """Normalized percentage = obtained / max * 100 (after validating)."""
    validate_marks(obtained, max_marks)
    return float(obtained) / float(max_marks) * 100


# ---------- Required fields and duplicates ----------
def missing_required_fields(record: dict, required: list) -> list:
    """Returns the names of required fields that are missing, empty or blank."""
    missing = []
    for field in required:
        value = record.get(field)
        is_nan = isinstance(value, float) and value != value
        if value is None or is_nan or (isinstance(value, str) and value.strip() == ""):
            missing.append(field)
    return missing


def find_duplicates(df: pd.DataFrame, key_columns: list) -> pd.DataFrame:
    """Returns every row that shares its key with another row (empty if none)."""
    absent = [c for c in key_columns if c not in df.columns]
    if absent:
        raise ValidationError(f"Missing column(s) for duplicate check: {', '.join(absent)}")
    return df[df.duplicated(subset=key_columns, keep=False)]


# ---------- Student rules (shared by the repository and the CSV importer) ----------
VALID_STATUS = ("active", "inactive")
MAX_STUDENT_CODE_LEN = 30
MAX_STUDENT_NAME_LEN = 100
MIN_SEMESTER, MAX_SEMESTER = 1, 10
