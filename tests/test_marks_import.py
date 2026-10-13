import io
from pathlib import Path

import pytest

from app.services.csv_utils import read_csv_required
from app.services.marks_analysis import subject_summary, subject_wise_performance
from app.services.marks_import import REQUIRED_COLUMNS, validate_marks_df
from app.validation import ValidationError
from scripts.generate_sample_data import CLASSES, generate

STUDENTS = {
    "S1": {"id": 1, "class_id": 10, "semester": 3, "department_id": 1, "status": "active"},
    "S2": {"id": 2, "class_id": 10, "semester": 3, "department_id": 1, "status": "inactive"},
    "S3": {"id": 3, "class_id": 10, "semester": 3, "department_id": 1, "status": "active"},
}
SUBJECTS = {
    "CS301": {"id": 5, "semester": 3, "department_id": 1},
    "CS501": {"id": 6, "semester": 5, "department_id": 1},
}
HEADER = "student_code,subject_code,assessment_name,obtained_marks,max_marks\n"


def check(text, assessments=None, existing=None):
    df = read_csv_required(io.BytesIO(text.encode("utf-8")), REQUIRED_COLUMNS)
    return validate_marks_df(df, STUDENTS, SUBJECTS, assessments or {}, existing or set())


def problems(result):
    return [e.message for e in result.errors]


def test_missing_column_rejected():
    with pytest.raises(ValidationError) as err:
        read_csv_required(io.BytesIO(b"student_code,subject_code\nS1,CS301\n"), REQUIRED_COLUMNS)
    assert "max_marks" in str(err.value)


def test_valid_rows_pass_with_boundaries():
    result = check(HEADER + "S1,CS301,Quiz,0,30\nS3,CS301,Quiz,30,30\n")
    assert result.errors == []
    assert [r["obtained"] for r in result.valid_rows] == [0.0, 30.0]


def test_marks_above_max_and_negative_rejected():
    result = check(HEADER + "S1,CS301,Quiz,31,30\nS3,CS301,Quiz,-1,30\n")
    msgs = problems(result)
    assert "cannot be more than" in msgs[0]
    assert "cannot be negative" in msgs[1]


def test_non_numeric_and_zero_max_rejected():
    result = check(HEADER + "S1,CS301,A,abc,30\nS3,CS301,B,5,0\n")
    msgs = problems(result)
    assert any("must be a number" in m for m in msgs)
    assert any("greater than zero" in m for m in msgs)


def test_missing_obtained_or_name_flagged():
    result = check(HEADER + "S1,CS301,Quiz,,30\nS3,CS301,,10,30\n")
    assert sum("required" in m for m in problems(result)) == 2


def test_unknown_inactive_and_foreign_subject():
    result = check(HEADER + "NOPE,CS301,Quiz,5,30\nS2,CS301,Quiz,5,30\nS1,CS501,Quiz,5,30\nS3,CS999,Quiz,5,30\n")
    msgs = problems(result)
    assert "does not exist" in msgs[0]
    assert "inactive" in msgs[1]
    assert "not taught" in msgs[2]
    assert "does not exist" in msgs[3]


def test_inconsistent_max_inside_file_flags_both_rows():
    result = check(HEADER + "S1,CS301,Mid,20,50\nS3,CS301,Mid,20,40\n")
    assert {e.row_number for e in result.errors} == {2, 3}
    assert "different max_marks" in problems(result)[0]


def test_duplicate_entry_flags_both_rows():
    result = check(HEADER + "S1,CS301,Quiz,10,30\nS1,CS301,Quiz,12,30\n")
    assert {e.row_number for e in result.errors} == {2, 3}


def test_existing_marks_and_changed_max_flagged_against_database():
    existing_assessments = {(10, 5, "Quiz"): {"id": 77, "max_marks": 30.0}}
    result = check(HEADER + "S1,CS301,Quiz,10,30\nS3,CS301,Quiz,10,40\n",
                   assessments=existing_assessments, existing={(77, 1)})
    msgs = problems(result)
    assert any("already exist" in m for m in msgs)
    assert any("differs from the existing assessment" in m for m in msgs)


def test_invalid_sample_file_reports_every_bad_row():
    path = Path(__file__).resolve().parents[1] / "data" / "sample" / "marks_invalid.csv"
    students = {f"CSES3{n:03d}": {"id": n, "class_id": 1, "semester": 3, "department_id": 1, "status": "active"}
                for n in range(1, 15)}
    subjects = {"CS301": {"id": 1, "semester": 3, "department_id": 1},
                "CS501": {"id": 4, "semester": 5, "department_id": 1}}
    result = validate_marks_df(read_csv_required(path, REQUIRED_COLUMNS), students, subjects, {}, set())
    assert result.total_rows == 14
    assert {e.row_number for e in result.errors} == set(range(3, 16))
    assert [r["student_id"] for r in result.valid_rows] == [1]


def test_generated_sample_marks_are_valid(tmp_path):
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
    result = validate_marks_df(read_csv_required(tmp_path / "marks.csv", REQUIRED_COLUMNS),
                               students, subjects, {}, set())
    assert result.errors == []
    assert len(result.valid_rows) == 168


# ----- analysis -----
def _row(student_id, code, subject, obtained, maximum):
    return {"student_id": student_id, "student_code": code, "name": code, "subject_code": subject,
            "subject_name": subject, "obtained_marks": obtained, "max_marks": maximum}


def test_subject_wise_performance_normalizes_different_maximums():
    rows = [_row(1, "A", "S1", 15, 30), _row(1, "A", "S1", 40, 50),   # 50% and 80% -> 65%
            _row(2, "B", "S1", 30, 30), _row(2, "B", "S1", 50, 50),   # 100%
            _row(1, "A", "S2", 10, 20)]                               # 50%
    performance = subject_wise_performance(rows)
    by_key = {(p["student_code"], p["subject_code"]): p for p in performance}
    assert by_key[("A", "S1")]["average_percentage"] == pytest.approx(65.0)
    assert by_key[("A", "S1")]["assessments"] == 2
    assert by_key[("B", "S1")]["average_percentage"] == 100.0
    summary = {s["subject_code"]: s for s in subject_summary(performance)}
    assert summary["S1"]["average"] == pytest.approx(82.5)
    assert summary["S1"]["highest"] == 100.0 and summary["S1"]["lowest"] == pytest.approx(65.0)
    assert summary["S2"]["students"] == 1


def test_analysis_of_empty_input_is_empty():
    assert subject_wise_performance([]) == []
    assert subject_summary([]) == []


def test_analysis_rejects_invalid_stored_marks():
    with pytest.raises(ValidationError):
        subject_wise_performance([_row(1, "A", "S1", 31, 30)])
