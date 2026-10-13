import pytest

pytest.importorskip("plotly")

from app.services import student_dashboard as sd
from app.services.charts import marks_trend_chart, student_attendance_chart


def test_student_attendance_chart_values_and_threshold_line():
    report = sd.attendance_for_student(
        [{"subject_code": "CS1", "subject_name": "DS", "attended": 6, "total_held": 10},
         {"subject_code": "CS2", "subject_name": "DB", "attended": 9, "total_held": 10}], 75)
    fig = student_attendance_chart(report, 75)
    assert list(fig.data[0].x) == ["CS1", "CS2"]
    assert list(fig.data[0].y) == [60.0, 90.0]
    assert any(shape.y0 == 75 for shape in fig.layout.shapes)


def test_marks_trend_chart_one_line_per_subject():
    points = sd.trend_points([
        {"subject_code": "CS1", "subject_name": "DS", "assessment_name": "Q1", "obtained_marks": 15.0, "max_marks": 30.0},
        {"subject_code": "CS1", "subject_name": "DS", "assessment_name": "Mid", "obtained_marks": 40.0, "max_marks": 50.0},
        {"subject_code": "CS2", "subject_name": "DB", "assessment_name": "Q1", "obtained_marks": 9.0, "max_marks": 10.0}])
    fig = marks_trend_chart(points)
    assert [t.name for t in fig.data] == ["CS1", "CS2"]
    assert list(fig.data[0].y) == [50.0, 80.0] and list(fig.data[0].x) == [1, 2]


def test_empty_charts_do_not_crash():
    assert len(student_attendance_chart([], 75).data[0].x) == 0
    assert len(marks_trend_chart([]).data) == 0
