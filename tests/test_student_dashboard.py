import pytest

from app.services import student_dashboard as sd

ATT = [{"subject_code": "CS1", "subject_name": "DS", "attended": 6, "total_held": 10},
       {"subject_code": "CS2", "subject_name": "DB", "attended": 8, "total_held": 10},
       {"subject_code": "CS3", "subject_name": "OS", "attended": 3, "total_held": 4}]    # exactly 75%
MARKS = [{"subject_code": "CS1", "subject_name": "DS", "assessment_name": "Q1", "obtained_marks": 15.0, "max_marks": 30.0},
         {"subject_code": "CS1", "subject_name": "DS", "assessment_name": "Mid", "obtained_marks": 40.0, "max_marks": 50.0},
         {"subject_code": "CS2", "subject_name": "DB", "assessment_name": "Q1", "obtained_marks": 9.0, "max_marks": 10.0}]


def test_attendance_flags_and_warning_list():
    report = sd.attendance_for_student(ATT, 75)
    assert [r["flag"] for r in report] == ["below_threshold", "ok", "ok"]      # 75% exactly is not a warning
    assert [r["subject_code"] for r in sd.subjects_below_threshold(report)] == ["CS1"]


def test_no_attendance_gives_empty_report():
    assert sd.attendance_for_student([], 75) == []
    assert sd.subjects_below_threshold([]) == []


def test_subject_summary_normalizes_marks():
    summary = {s["subject_code"]: s for s in sd.subject_marks_summary(MARKS)}
    assert summary["CS1"]["assessments"] == 2
    assert summary["CS1"]["average_percentage"] == pytest.approx(65.0)         # (50% + 80%) / 2
    assert summary["CS2"]["average_percentage"] == pytest.approx(90.0)


def test_trend_points_count_assessments_per_subject():
    points = sd.trend_points(MARKS)
    assert [(p["subject_code"], p["step"]) for p in points] == [("CS1", 1), ("CS1", 2), ("CS2", 1)]
    assert [round(p["percentage"], 1) for p in points] == [50.0, 80.0, 90.0]


def test_empty_marks():
    assert sd.subject_marks_summary([]) == [] and sd.trend_points([]) == [] and sd.marks_with_percentage([]) == []


def test_invalid_stored_marks_are_not_hidden():
    from app.validation import ValidationError

    with pytest.raises(ValidationError):
        sd.marks_with_percentage([{**MARKS[0], "obtained_marks": 99.0}])
