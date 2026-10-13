"""CSV import for students: read -> validate everything -> insert all or nothing."""
from dataclasses import dataclass, field

import pandas as pd

from app.services.csv_utils import MAX_CSV_ROWS
from app.validation import (
    MAX_SEMESTER,
    MAX_STUDENT_CODE_LEN,
    MAX_STUDENT_NAME_LEN,
    MIN_SEMESTER,
    VALID_STATUS,
    ValidationError,
    missing_required_fields,
)

REQUIRED_COLUMNS = ["student_code", "name", "class_name", "department", "semester"]


@dataclass
class RowError:
    row_number: int      # row as Excel shows it (header is row 1, first student is row 2)
    student_code: str
    message: str


@dataclass
class ImportResult:
    total_rows: int
    valid_rows: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    inserted: int = 0

    @property
    def rows_with_errors(self) -> int:
        return len({e.row_number for e in self.errors})


def read_students_csv(source) -> pd.DataFrame:
    """Reads a CSV (path or file-like object). Raises ValidationError with a clear message."""
    try:
        df = pd.read_csv(source, dtype=str, keep_default_na=False, encoding="utf-8-sig", nrows=MAX_CSV_ROWS + 1)
    except pd.errors.EmptyDataError:
        raise ValidationError("The CSV file is empty.")
    except UnicodeDecodeError:
        raise ValidationError("The file is not UTF-8 text. In Excel use 'Save As' -> 'CSV UTF-8'.")
    except pd.errors.ParserError as e:
        raise ValidationError(f"The CSV could not be read: {e}")

    if len(df) > MAX_CSV_ROWS:
        raise ValidationError(f"The CSV has more than {MAX_CSV_ROWS:,} rows. Please split it into smaller files.")
    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValidationError(
            f"Missing required column(s): {', '.join(missing)}. "
            f"Columns found: {', '.join(df.columns)}."
        )
    if df.empty:
        raise ValidationError("The CSV has a header row but no student rows.")
    df = df.fillna("")
    for column in df.columns:
        df[column] = df[column].astype(str).str.strip()
    return df


def validate_students_df(df: pd.DataFrame, class_lookup: dict, existing_codes: set) -> ImportResult:
    """Checks every row. Never drops a bad row silently: each problem becomes a RowError."""
    records = df.to_dict("records")
    result = ImportResult(total_rows=len(records))

    rows_by_code = {}
    for i, rec in enumerate(records):
        code = rec.get("student_code", "")
        if code:
            rows_by_code.setdefault(code, []).append(i + 2)

    for i, rec in enumerate(records):
        row_no = i + 2
        code = rec.get("student_code", "")
        name = rec.get("name", "")
        problems = []

        for missing in missing_required_fields(rec, REQUIRED_COLUMNS):
            problems.append(f"'{missing}' is required but empty.")

        if code:
            if len(code) > MAX_STUDENT_CODE_LEN:
                problems.append(f"student_code is too long (maximum {MAX_STUDENT_CODE_LEN} characters).")
            if len(rows_by_code[code]) > 1:
                rows = ", ".join(str(r) for r in rows_by_code[code])
                problems.append(f"Duplicate student_code '{code}' inside this file (rows {rows}).")
            if code in existing_codes:
                problems.append(f"student_code '{code}' already exists in the database.")

        if name and len(name) > MAX_STUDENT_NAME_LEN:
            problems.append(f"name is too long (maximum {MAX_STUDENT_NAME_LEN} characters).")

        department, class_name = rec.get("department", ""), rec.get("class_name", "")
        class_info = None
        if department and class_name:
            class_info = class_lookup.get((department.lower(), class_name.lower()))
            if class_info is None:
                problems.append(
                    f"Class '{class_name}' in department '{department}' does not exist. "
                    "Ask the admin to create it first."
                )

        semester = None
        semester_raw = rec.get("semester", "")
        if semester_raw:
            try:
                semester = int(semester_raw)
            except ValueError:
                problems.append(f"semester must be a whole number, got '{semester_raw}'.")
            else:
                if not (MIN_SEMESTER <= semester <= MAX_SEMESTER):
                    problems.append(f"semester must be between {MIN_SEMESTER} and {MAX_SEMESTER}, got {semester}.")
                    semester = None
        if class_info is not None and semester is not None and semester != class_info["semester"]:
            problems.append(
                f"semester {semester} does not match class '{class_name}' (which is semester {class_info['semester']})."
            )

        status = rec.get("status", "").lower() or "active"
        if status not in VALID_STATUS:
            problems.append(f"status must be one of {', '.join(VALID_STATUS)}, got '{rec.get('status', '')}'.")

        if problems:
            result.errors.extend(RowError(row_no, code, p) for p in problems)
        else:
            result.valid_rows.append(
                {"student_code": code, "name": name, "class_id": class_info["id"], "status": status}
            )
    return result


def validate_against_database(cur, df: pd.DataFrame) -> ImportResult:
    """Validates the file against the real database. Writes NOTHING."""
    from app.repositories import student_repository as repo

    class_lookup = repo.get_class_lookup(cur)
    codes = [c for c in df["student_code"] if c]
    return validate_students_df(df, class_lookup, repo.existing_codes(cur, codes))


def import_students(cur, df: pd.DataFrame) -> ImportResult:
    """All or nothing: if even one row has a problem, NO student is inserted."""
    from psycopg2.extras import execute_values

    result = validate_against_database(cur, df)
    if result.errors:
        return result
    execute_values(
        cur,
        "INSERT INTO students (student_code, name, class_id, status) VALUES %s",
        [(r["student_code"], r["name"], r["class_id"], r["status"]) for r in result.valid_rows],
    )
    result.inserted = len(result.valid_rows)
    return result
