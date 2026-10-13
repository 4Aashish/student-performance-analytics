import csv
import io

import pytest

from app.services import reports
from app.services.reports import safe_cell, to_csv_bytes
from app.validation import ValidationError


def parse(csv_bytes):
    assert csv_bytes.startswith("\ufeff".encode("utf-8"))              # Excel-friendly BOM
    return list(csv.reader(io.StringIO(csv_bytes.decode("utf-8-sig"))))


# ----- CSV safety and format -----
def test_formula_like_text_is_neutralised():
    for dangerous in ("=1+1", "+cmd", "-2+3", "@SUM(A1)", "\tTAB", "\rCR"):
        assert safe_cell(dangerous) == "'" + dangerous
    assert safe_cell("Normal Name") == "Normal Name"
    assert safe_cell("a=b") == "a=b"


def test_numbers_none_bool_and_dates():
    from datetime import date

    assert safe_cell(None) == ""
    assert safe_cell(66.66666) == "66.67"
    assert safe_cell(80.0) == "80.0"
    assert safe_cell(7) == "7"
    assert safe_cell(True) == "Yes"
    assert safe_cell(date(2026, 8, 3)) == "2026-08-03"


def test_csv_escapes_commas_quotes_and_newlines_and_keeps_unicode():
    columns = [("name", "Name"), ("note", "Note")]
    rows = [{"name": 'Sharma, "Aashish"', "note": "line1\nline2"}, {"name": "आशीष", "note": "=EVIL()"}]
    parsed = parse(to_csv_bytes(columns, rows))
    assert parsed[0] == ["Name", "Note"]
    assert parsed[1] == ['Sharma, "Aashish"', "line1\nline2"]
    assert parsed[2] == ["आशीष", "'=EVIL()"]


def test_missing_keys_become_empty_cells():
    parsed = parse(to_csv_bytes([("a", "A"), ("b", "B")], [{"a": 1}]))
    assert parsed[1] == ["1", ""]


# ----- staff reports -----
ATT_ROW = {"student_id": 1, "student_code": "S1", "name": "=Bad Name", "department": "CSE", "class_name": "C3",
           "semester": 3, "subject_code": "CS1", "subject_name": "DS", "attended": 6, "total_held": 10}


def test_attendance_report_values_flags_and_injection():
    result = reports.attendance_report([ATT_ROW, {**ATT_ROW, "subject_code": "CS2", "attended": 9}], 75, {"class_id": 5})
    assert result.row_count == 2 and result.filters == {"class_id": 5}
    parsed = parse(result.csv_bytes)
    assert parsed[0][-1] == reports.FLAG_HEADER
    assert parsed[1][1] == "'=Bad Name"
    assert (parsed[1][9], parsed[1][10]) == ("60.0", "Below threshold (warning)")
    assert (parsed[2][9], parsed[2][10]) == ("90.0", "OK")
    assert result.filename.startswith("attendance_report_") and result.filename.endswith(".csv")


def test_empty_report_has_no_file():
    for result in (reports.students_report([]), reports.attendance_report([], 75), reports.marks_report([]),
                   reports.performance_report([], [], [])):
        assert result.row_count == 0 and result.csv_bytes is None and result.rows == []


def test_marks_report_percentage():
    row = {"student_code": "S1", "name": "A", "department": "CSE", "class_name": "C3", "semester": 3,
           "subject_code": "CS1", "subject_name": "DS", "assessment_name": "Q1", "obtained_marks": 15.0, "max_marks": 30.0}
    parsed = parse(reports.marks_report([row]).csv_bytes)
    assert parsed[1][-3:] == ["15.0", "30.0", "50.0"]


def test_invalid_stored_marks_are_not_exported_silently():
    row = {"student_code": "S1", "name": "A", "department": "CSE", "class_name": "C3", "semester": 3,
           "subject_code": "CS1", "subject_name": "DS", "assessment_name": "Q1", "obtained_marks": 31.0, "max_marks": 30.0}
    with pytest.raises(ValidationError):
        reports.marks_report([row])


def test_performance_report_merges_attendance_marks_and_support():
    student_att = [{"student_id": 1, "student_code": "A", "name": "A", "class_name": "C", "semester": 3, "percentage": 50.0},
                   {"student_id": 2, "student_code": "B", "name": "B", "class_name": "C", "semester": 3, "percentage": 90.0}]
    student_marks = [{"student_id": 1, "student_code": "A", "name": "A", "class_name": "C", "semester": 3, "average_percentage": 70.0},
                     {"student_id": 3, "student_code": "C", "name": "C", "class_name": "C", "semester": 3, "average_percentage": 20.0}]
    support = [{"student_id": 1, "reasons": "Attendance 50.0% (below 75%)"}, {"student_id": 3, "reasons": "Average marks 20.0% (below 40%)"}]
    parsed = parse(reports.performance_report(student_att, student_marks, support).csv_bytes)
    by_code = {row[0]: row for row in parsed[1:]}
    assert set(by_code) == {"A", "B", "C"}
    assert by_code["A"][4:7] == ["50.0", "70.0", "Yes"]
    assert by_code["B"][4:7] == ["90.0", "", "No"]            # no marks yet -> empty, not 0
    assert by_code["C"][4:7] == ["", "20.0", "Yes"]


# ----- a student's own reports -----
MY_ATT = [{"subject_code": "CS1", "subject_name": "DS", "attended": 6, "total_held": 10},
          {"subject_code": "CS2", "subject_name": "DB", "attended": 10, "total_held": 10}]
MY_MARKS = [{"subject_code": "CS1", "subject_name": "DS", "assessment_name": "Q1", "assessment_date": None,
             "obtained_marks": 15.0, "max_marks": 30.0},
            {"subject_code": "CS1", "subject_name": "DS", "assessment_name": "Mid", "assessment_date": None,
             "obtained_marks": 40.0, "max_marks": 50.0}]


def test_student_reports():
    att = parse(reports.student_attendance_report(MY_ATT, 75).csv_bytes)
    assert att[1][:5] == ["CS1", "DS", "6", "10", "60.0"] and att[1][5] == "Below threshold (warning)"
    marks = parse(reports.student_marks_report(MY_MARKS).csv_bytes)
    assert [row[-1] for row in marks[1:]] == ["50.0", "80.0"]
    summary = parse(reports.student_summary_report(MY_ATT, MY_MARKS, 75).csv_bytes)
    by_subject = {row[0]: row for row in summary[1:]}
    assert by_subject["CS1"][6:8] == ["2", "65.0"]            # two assessments, average of 50% and 80%
    assert by_subject["CS2"][6:8] == ["", ""]                 # attendance only, no marks yet


def test_student_reports_with_no_data():
    assert reports.student_attendance_report([], 75).csv_bytes is None
    assert reports.student_marks_report([]).csv_bytes is None
    assert reports.student_summary_report([], [], 75).csv_bytes is None


def test_summary_includes_subjects_that_only_have_marks():
    summary = parse(reports.student_summary_report([], MY_MARKS, 75).csv_bytes)
    assert summary[1][0] == "CS1" and summary[1][2:5] == ["", "", ""]
