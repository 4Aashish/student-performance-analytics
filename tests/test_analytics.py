import pytest

from app.services import analytics

A, B, C = 1, 2, 3


def att(student_id, code, subject, attended, held, semester=3, cls="C3"):
    return {"student_id": student_id, "student_code": code, "name": code, "class_name": cls,
            "semester": semester, "subject_code": subject, "attended": attended, "total_held": held}


def mk(student_id, code, subject, assessment, obtained, maximum, semester=3, cls="C3"):
    return {"student_id": student_id, "student_code": code, "name": code, "class_name": cls,
            "semester": semester, "subject_code": subject, "assessment_name": assessment,
            "obtained_marks": obtained, "max_marks": maximum}


ATT_ROWS = [
    att(A, "A", "S1", 9, 10), att(A, "A", "S2", 8, 10),     # 17/20 = 85%
    att(B, "B", "S1", 5, 10), att(B, "B", "S2", 5, 10),     # 50%
    att(C, "C", "S1", 0, 0),                                 # no sessions
]


def test_student_attendance_pools_all_subjects():
    result = {s["student_code"]: s for s in analytics.student_attendance(ATT_ROWS)}
    assert result["A"]["percentage"] == pytest.approx(85.0)
    assert result["B"]["percentage"] == 50.0
    assert result["C"]["percentage"] is None


def test_attendance_summary():
    totals = analytics.attendance_summary(analytics.student_attendance(ATT_ROWS), 75)
    assert totals["average"] == pytest.approx(67.5)
    assert totals["students_with_data"] == 2
    assert totals["below_threshold"] == 1


def test_attendance_summary_with_no_data():
    totals = analytics.attendance_summary(analytics.student_attendance([]), 75)
    assert totals == {"average": None, "students_with_data": 0, "below_threshold": 0}


def test_distribution_boundaries_and_totals():
    students = [{"percentage": p} for p in (0.0, 49.9, 50.0, 59.99, 60.0, 89.9, 90.0, 100.0, None)]
    dist = {d["range"]: d["students"] for d in analytics.attendance_distribution(students)}
    assert dist == {"0-50%": 2, "50-60%": 2, "60-70%": 1, "70-80%": 0, "80-90%": 1, "90-100%": 2}
    assert sum(dist.values()) == 8  # the student without data is not counted


MARK_ROWS = [
    mk(A, "A", "S1", "Q1", 15, 30), mk(A, "A", "S1", "Mid", 40, 50),   # S1: 50% and 80% -> 65%
    mk(A, "A", "S2", "Q1", 18, 20),                                     # S2: 90%  -> student avg 77.5
    mk(B, "B", "S1", "Q1", 6, 30),                                      # 20%
    mk(C, "C", "S1", "Q1", 30, 30, semester=5, cls="C5"),               # 100%
]


def test_student_marks_average_of_subject_averages():
    result = {s["student_code"]: s["average_percentage"] for s in analytics.student_marks(MARK_ROWS)}
    assert result["A"] == pytest.approx(77.5)
    assert result["B"] == pytest.approx(20.0)
    assert result["C"] == 100.0


def test_marks_extremes():
    extremes = analytics.marks_extremes(MARK_ROWS)
    assert (extremes["highest"]["student_code"], extremes["highest"]["percentage"]) == ("C", 100.0)
    assert (extremes["lowest"]["student_code"], extremes["lowest"]["percentage"]) == ("B", pytest.approx(20.0))
    assert extremes["lowest"]["obtained"] == 6


def test_marks_extremes_and_students_with_no_marks():
    assert analytics.marks_extremes([]) is None
    assert analytics.student_marks([]) == []


def test_semester_trends():
    student_att = analytics.student_attendance(ATT_ROWS)
    trends = analytics.semester_trends(student_att, analytics.student_marks(MARK_ROWS))
    assert [t["semester"] for t in trends] == [3, 5]
    assert trends[0]["average_attendance"] == pytest.approx(67.5)
    assert trends[0]["average_marks"] == pytest.approx((77.5 + 20.0) / 2)
    assert trends[1]["average_attendance"] is None
    assert trends[1]["average_marks"] == 100.0


def test_students_needing_support_reasons_and_boundaries():
    student_att = analytics.student_attendance(ATT_ROWS)
    student_marks = analytics.student_marks(MARK_ROWS)
    flagged = {p["student_code"]: p for p in analytics.students_needing_support(student_att, student_marks, 75, 40)}
    assert set(flagged) == {"B"}                       # A is fine, C has no attendance and 100% marks
    assert "Attendance 50.0%" in flagged["B"]["reasons"]
    assert "Average marks 20.0%" in flagged["B"]["reasons"]


def test_exactly_at_threshold_is_not_flagged():
    rows = [att(A, "A", "S1", 3, 4)]                         # exactly 75%
    marks = [mk(A, "A", "S1", "Q", 12, 30)]                  # exactly 40%
    assert analytics.students_needing_support(
        analytics.student_attendance(rows), analytics.student_marks(marks), 75, 40) == []


def test_student_without_any_data_is_not_flagged():
    assert analytics.students_needing_support([], [], 75, 40) == []
