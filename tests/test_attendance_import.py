import io
from datetime import date
from pathlib import Path

import pytest

from app.services.attendance_import import REQUIRED_COLUMNS, validate_attendance_df
from app.services.attendance_report import build_attendance_report, summarize_report
from app.services.csv_utils import read_csv_required
from app.validation import ValidationError
from scripts.generate_sample_data import CLASSES, generate

STUDENTS = {
    "S1": {"id": 1, "class_id": 10, "semester": 3, "department_id": 1, "status": "active"},
    "S2": {"id": 2, "class_id": 10, "semester": 3, "department_id": 1, "status": "inactive"},
}
SUBJECTS = {
    "CS301": {"id": 5, "semester": 3, "department_id": 1},
    "CS501": {"id": 6, "semester": 5, "department_id": 1},
}
HEADER = "student_code,subject_code,session_date,session_no,status\n"


def check(text, existing=None):
    df = read_csv_required(io.BytesIO(text.encode("utf-8")), REQUIRED_COLUMNS)
    return validate_attendance_df(df, STUDENTS, SUBJECTS, existing or set())


def problems(result):
    return [e.message for e in result.errors]


# ----- file level -----
def test_missing_column_rejected():
    with pytest.raises(ValidationError) as err:
        read_csv_required(io.BytesIO(b"student_code,status\nS1,present\n"), REQUIRED_COLUMNS)
    assert "session_date" in str(err.value)


def test_empty_and_header_only_rejected():
    for raw in (b"", HEADER.encode()):
        with pytest.raises(ValidationError):
            read_csv_required(io.BytesIO(raw), REQUIRED_COLUMNS)


# ----- row level -----
def test_valid_row_passes_and_status_is_lowercased():
    result = check(HEADER + "S1,CS301,2026-08-03,1,PRESENT\n")
    assert result.errors == []
    assert result.valid_rows[0]["status"] == "present"
    assert result.valid_rows[0]["session_date"] == date(2026, 8, 3)


def test_unknown_student_and_subject():
    result = check(HEADER + "NOPE,CS301,2026-08-03,1,present\nS1,CS999,2026-08-03,1,present\n")
    assert "does not exist" in problems(result)[0]
    assert "does not exist" in problems(result)[1]


def test_inactive_student_rejected():
    assert "inactive" in problems(check(HEADER + "S2,CS301,2026-08-03,1,present\n"))[0]


def test_subject_from_other_semester_rejected():
    assert "not taught" in problems(check(HEADER + "S1,CS501,2026-08-03,1,present\n"))[0]


def test_bad_date_session_no_and_status():
    text = (HEADER + "S1,CS301,03-08-2026,1,present\nS1,CS301,2026-08-03,0,present\n"
            "S1,CS301,2026-08-03,x,present\nS1,CS301,2026-08-03,1,late\n")
    msgs = problems(check(text))
    assert any("YYYY-MM-DD" in m for m in msgs)
    assert any("1 or more" in m for m in msgs)
    assert any("whole number" in m for m in msgs)
    assert any("present or absent" in m for m in msgs)


def test_future_date_rejected():
    assert "future" in problems(check(HEADER + "S1,CS301,2099-01-01,1,present\n"))[0]


def test_duplicate_inside_file_flags_both_rows():
    result = check(HEADER + "S1,CS301,2026-08-03,1,present\nS1,CS301,2026-08-03,1,absent\n")
    assert {e.row_number for e in result.errors} == {2, 3}


def test_same_day_second_lecture_is_not_a_duplicate():
    result = check(HEADER + "S1,CS301,2026-08-03,1,present\nS1,CS301,2026-08-03,2,absent\n")
    assert result.errors == [] and len(result.valid_rows) == 2


def test_already_in_database_flagged():
    existing = {(1, 5, date(2026, 8, 3), 1)}
    assert "already in the database" in problems(check(HEADER + "S1,CS301,2026-08-03,1,present\n", existing))[0]


def test_missing_fields_flagged():
    assert any("required" in m for m in problems(check(HEADER + ",CS301,2026-08-03,1,present\n")))


def test_invalid_sample_file_reports_every_bad_row():
    # Uses real student codes from the generated sample data
    path = Path(__file__).resolve().parents[1] / "data" / "sample" / "attendance_invalid.csv"
    students = {f"CSES3{n:03d}": {"id": n, "class_id": 1, "semester": 3, "department_id": 1, "status": "active"}
                for n in range(1, 15)}
    subjects = {"CS301": {"id": 1, "semester": 3, "department_id": 1},
                "CS501": {"id": 4, "semester": 5, "department_id": 1}}
    df = read_csv_required(path, REQUIRED_COLUMNS)
    result = validate_attendance_df(df, students, subjects, set())
    assert result.total_rows == 10
    assert {e.row_number for e in result.errors} == {3, 4, 5, 6, 7, 8, 9, 10, 11}
    assert [r["student_id"] for r in result.valid_rows] == [2]


def test_generated_sample_attendance_is_valid(tmp_path):
    generate(tmp_path)
    students_df = read_csv_required(tmp_path / "students.csv", ["student_code"])
    class_ids = {name: i for i, name in enumerate(CLASSES, start=1)}
    students = {r["student_code"]: {"id": n, "class_id": class_ids[r["class_name"]],
                                    "semester": int(r["semester"]), "department_id": 1, "status": r["status"]}
                for n, r in enumerate(students_df.to_dict("records"), start=1)}
    subjects = {}
    for info in CLASSES.values():
        for code, _ in info["subjects"]:
            subjects[code] = {"id": len(subjects) + 1, "semester": info["semester"], "department_id": 1}
    df = read_csv_required(tmp_path / "attendance.csv", REQUIRED_COLUMNS)
    result = validate_attendance_df(df, students, subjects, set())
    assert result.errors == []
    assert len(result.valid_rows) == 840


# ----- report -----
def test_report_percentages_flags_and_zero_sessions():
    rows = [
        {"student_code": "A", "attended": 9, "total_held": 10},
        {"student_code": "B", "attended": 7, "total_held": 10},
        {"student_code": "C", "attended": 0, "total_held": 0},
    ]
    report = build_attendance_report(rows, 75)
    assert [r["percentage"] for r in report] == [90.0, 70.0, None]
    assert [r["flag"] for r in report] == ["ok", "below_threshold", "no_data"]
    totals = summarize_report(report)
    assert totals["average_percentage"] == 80.0
    assert totals["below_threshold"] == 1
    assert totals["students_with_data"] == 2


def test_summary_of_empty_report():
    totals = summarize_report(build_attendance_report([], 75))
    assert totals["students"] == 0 and totals["average_percentage"] is None
