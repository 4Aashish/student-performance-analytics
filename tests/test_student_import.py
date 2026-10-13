import io
from pathlib import Path

import pytest

from app.services.student_import import read_students_csv, validate_students_df
from app.validation import ValidationError
from scripts.generate_sample_data import CLASSES, generate

LOOKUP = {("cse", "cse-s3"): {"id": 1, "semester": 3}, ("cse", "cse-s5"): {"id": 2, "semester": 5}}
HEADER = "student_code,name,class_name,department,semester,status\n"


def df_from(text: str):
    return read_students_csv(io.BytesIO(text.encode("utf-8")))


def messages(result):
    return [e.message for e in result.errors]


# ----- reading the file -----
def test_empty_file_rejected():
    with pytest.raises(ValidationError):
        df_from("")


def test_header_only_rejected():
    with pytest.raises(ValidationError):
        df_from(HEADER)


def test_missing_column_named_in_message():
    with pytest.raises(ValidationError) as err:
        df_from("student_code,name\nS1,A\n")
    assert "class_name" in str(err.value)


def test_bom_and_whitespace_handled():
    raw = ("\ufeff" + HEADER + "  S1 , Asha ,CSE-S3, CSE ,3,Active\n").encode("utf-8")
    df = read_students_csv(io.BytesIO(raw))
    result = validate_students_df(df, LOOKUP, set())
    assert result.errors == []
    assert result.valid_rows == [{"student_code": "S1", "name": "Asha", "class_id": 1, "status": "active"}]


def test_non_utf8_file_gives_clear_error():
    with pytest.raises(ValidationError):
        read_students_csv(io.BytesIO(b"student_code,name,class_name,department,semester\nS1,\xff\xfe,CSE-S3,CSE,3\n"))


# ----- validating rows -----
def test_valid_rows_pass_and_status_defaults_to_active():
    result = validate_students_df(df_from(HEADER + "S1,A,CSE-S3,CSE,3,\nS2,B,CSE-S5,CSE,5,inactive\n"), LOOKUP, set())
    assert result.errors == []
    assert [r["status"] for r in result.valid_rows] == ["active", "inactive"]


def test_duplicate_inside_file_flags_both_rows():
    result = validate_students_df(df_from(HEADER + "S1,A,CSE-S3,CSE,3,active\nS1,B,CSE-S3,CSE,3,active\n"), LOOKUP, set())
    assert sorted({e.row_number for e in result.errors}) == [2, 3]
    assert result.valid_rows == []


def test_existing_in_database_flagged():
    result = validate_students_df(df_from(HEADER + "S1,A,CSE-S3,CSE,3,active\n"), LOOKUP, {"S1"})
    assert "already exists" in messages(result)[0]


def test_unknown_class_flagged():
    result = validate_students_df(df_from(HEADER + "S1,A,CSE-S9,CSE,3,active\n"), LOOKUP, set())
    assert "does not exist" in messages(result)[0]


def test_semester_problems_flagged():
    text = HEADER + "S1,A,CSE-S3,CSE,abc,active\nS2,B,CSE-S3,CSE,5,active\nS3,C,CSE-S3,CSE,99,active\n"
    result = validate_students_df(df_from(text), LOOKUP, set())
    by_row = {e.row_number: e.message for e in result.errors}
    assert "whole number" in by_row[2]
    assert "does not match" in by_row[3]
    assert "between 1 and 10" in by_row[4]


def test_bad_status_and_missing_name_flagged():
    result = validate_students_df(df_from(HEADER + "S1,,CSE-S3,CSE,3,active\nS2,B,CSE-S3,CSE,3,graduated\n"), LOOKUP, set())
    by_row = {e.row_number: e.message for e in result.errors}
    assert "'name' is required" in by_row[2]
    assert "status must be" in by_row[3]


def test_too_long_values_flagged():
    long_code = "S" * 31
    long_name = "N" * 101
    result = validate_students_df(df_from(HEADER + f"{long_code},A,CSE-S3,CSE,3,active\nS2,{long_name},CSE-S3,CSE,3,active\n"), LOOKUP, set())
    assert len(result.errors) == 2


def test_one_row_can_report_several_problems():
    result = validate_students_df(df_from(HEADER + ",,CSE-S9,CSE,abc,graduated\n"), LOOKUP, set())
    assert len(result.errors) >= 4
    assert result.rows_with_errors == 1


def test_invalid_sample_file_every_bad_row_reported_and_good_rows_kept():
    path = Path(__file__).resolve().parents[1] / "data" / "sample" / "students_invalid.csv"
    result = validate_students_df(read_students_csv(path), LOOKUP, set())
    assert result.total_rows == 8
    assert {e.row_number for e in result.errors} == {2, 3, 4, 5, 6, 7, 8}
    assert [r["student_code"] for r in result.valid_rows] == ["CSE3107"]


def test_generated_sample_students_file_is_valid(tmp_path):
    generate(tmp_path)
    lookup = {("cse", name.lower()): {"id": i, "semester": info["semester"]}
              for i, (name, info) in enumerate(CLASSES.items(), start=1)}
    result = validate_students_df(read_students_csv(tmp_path / "students.csv"), lookup, set())
    assert result.errors == []
    assert len(result.valid_rows) == 30
