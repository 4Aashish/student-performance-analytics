import pytest

pytest.importorskip("plotly")

from app.services import analytics
from app.services.charts import attendance_distribution_chart, semester_trend_chart, subject_marks_chart
from app.services.marks_analysis import subject_summary


def test_subject_marks_chart_uses_summary_values():
    summary = [{"subject_code": "S1", "subject_name": "One", "students": 2, "average": 82.54, "highest": 90.0, "lowest": 75.0},
               {"subject_code": "S2", "subject_name": "Two", "students": 1, "average": 50.0, "highest": 50.0, "lowest": 50.0}]
    fig = subject_marks_chart(summary)
    assert list(fig.data[0].x) == ["S1", "S2"]
    assert list(fig.data[0].y) == [82.5, 50.0]


def test_attendance_distribution_chart():
    dist = analytics.attendance_distribution([{"percentage": 95.0}, {"percentage": 40.0}])
    fig = attendance_distribution_chart(dist)
    assert sum(fig.data[0].y) == 2
    assert fig.data[0].x[0] == "0-50%"


def test_semester_trend_chart_handles_missing_values():
    fig = semester_trend_chart([{"semester": 3, "average_attendance": 80.0, "average_marks": None}])
    assert list(fig.data[0].x) == ["Sem 3"]
    assert fig.data[0].y[0] == 80.0
    assert fig.data[1].y[0] is None


def test_empty_summary_gives_empty_chart():
    assert len(subject_marks_chart(subject_summary([])).data[0].x) == 0
