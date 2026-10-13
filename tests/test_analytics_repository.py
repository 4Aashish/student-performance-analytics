import uuid
from datetime import date

import pytest

from app.repositories import analytics_repository as repo
from app.repositories import attendance_repository as att_repo
from app.repositories import marks_repository as marks_repo
from app.repositories import student_repository as stu
from app.services import analytics

D1, D2 = date(2026, 8, 3), date(2026, 8, 4)


def make_class(cur, dept, semester, tag, label):
    cur.execute("INSERT INTO classes (department_id, name, semester) VALUES (%s,%s,%s) RETURNING id",
                (dept, f"{label}{tag}", semester))
    return cur.fetchone()[0]


def make_subject(cur, dept, semester, code):
    cur.execute("INSERT INTO subjects (code, name, department_id, semester) VALUES (%s,'Subj',%s,%s) RETURNING id",
                (code, dept, semester))
    return cur.fetchone()[0]


@pytest.fixture
def world(db_cur):
    """Two classes (semester 3 and 5) in one new department, each with 2 active students and subject."""
    tag = uuid.uuid4().hex[:8]
    db_cur.execute("INSERT INTO departments (name) VALUES (%s) RETURNING id", (f"D{tag}",))
    dept = db_cur.fetchone()[0]
    w = {"dept": dept, "tag": tag}
    for sem, label in ((3, "X"), (5, "Y")):
        cls = make_class(db_cur, dept, sem, tag, label)
        subj = make_subject(db_cur, dept, sem, f"{label}{tag}")
        s1 = stu.create_student(db_cur, f"{label}{tag}1", "One", cls)
        s2 = stu.create_student(db_cur, f"{label}{tag}2", "Two", cls)
        w[label] = {"cls": cls, "subj": subj, "s1": s1, "s2": s2}
        # attendance: s1 present both days, s2 present once of two
        att_repo.save_attendance(db_cur, cls, subj, D1, 1, {s1: "present", s2: "present"})
        att_repo.save_attendance(db_cur, cls, subj, D2, 1, {s1: "present", s2: "absent"})
        # marks: max 50, s1 45, s2 10
        asm = marks_repo.create_assessment(db_cur, cls, subj, "Mid", 50)
        marks_repo.save_marks(db_cur, asm, {s1: 45, s2: 10})
    # an inactive student with data must never be counted
    inactive = stu.create_student(db_cur, f"Z{tag}9", "Gone", w["X"]["cls"])
    att_repo.save_attendance(db_cur, w["X"]["cls"], w["X"]["subj"], date(2026, 8, 5), 1,
                             {w["X"]["s1"]: "present", w["X"]["s2"]: "present", inactive: "present"})
    stu.update_student(db_cur, inactive, status="inactive")
    return w


def test_count_active_students_with_filters(db_cur, world):
    base = {"department_id": world["dept"]}
    assert repo.count_active_students(db_cur, base) == 4
    assert repo.count_active_students(db_cur, {**base, "semester": 3}) == 2
    assert repo.count_active_students(db_cur, {**base, "class_id": world["Y"]["cls"]}) == 2
    assert repo.count_active_students(db_cur, {**base, "subject_id": world["X"]["subj"]}) == 2
    assert repo.count_active_students(db_cur, {"department_id": 999999999}) == 0


def test_attendance_rows_filters_and_values(db_cur, world):
    rows = repo.fetch_attendance_rows(db_cur, {"department_id": world["dept"]})
    assert len(rows) == 4                                  # 4 active students x 1 subject each
    only_x = repo.fetch_attendance_rows(db_cur, {"class_id": world["X"]["cls"]})
    by_id = {r["student_id"]: r for r in only_x}
    assert (by_id[world["X"]["s1"]]["attended"], by_id[world["X"]["s1"]]["total_held"]) == (3, 3)
    assert (by_id[world["X"]["s2"]]["attended"], by_id[world["X"]["s2"]]["total_held"]) == (2, 3)
    assert len(repo.fetch_attendance_rows(db_cur, {"department_id": world["dept"], "semester": 5})) == 2
    assert len(repo.fetch_attendance_rows(db_cur, {"subject_id": world["Y"]["subj"]})) == 2


def test_inactive_students_are_excluded(db_cur, world):
    rows = repo.fetch_attendance_rows(db_cur, {"department_id": world["dept"]})
    assert all(not r["student_code"].startswith("Z") for r in rows)


def test_marks_rows_filters_and_numbers(db_cur, world):
    rows = repo.fetch_marks_rows(db_cur, {"department_id": world["dept"]})
    assert len(rows) == 4
    assert all(isinstance(r["obtained_marks"], float) and r["max_marks"] == 50.0 for r in rows)
    sem3 = repo.fetch_marks_rows(db_cur, {"department_id": world["dept"], "semester": 3})
    assert sorted(r["obtained_marks"] for r in sem3) == [10.0, 45.0]
    assert repo.fetch_marks_rows(db_cur, {"department_id": 999999999}) == []


def test_end_to_end_dashboard_numbers_come_from_the_database(db_cur, world):
    filters = {"department_id": world["dept"]}
    student_att = analytics.student_attendance(repo.fetch_attendance_rows(db_cur, filters))
    student_marks = analytics.student_marks(repo.fetch_marks_rows(db_cur, filters))
    pct = {s["student_code"]: s["percentage"] for s in student_att}
    assert pct[f"X{world['tag']}1"] == 100.0
    assert pct[f"X{world['tag']}2"] == pytest.approx(2 / 3 * 100)
    trends = analytics.semester_trends(student_att, student_marks)
    assert [t["semester"] for t in trends] == [3, 5]
    assert trends[0]["average_marks"] == pytest.approx((90.0 + 20.0) / 2)
    flagged = analytics.students_needing_support(student_att, student_marks, 75, 40)
    assert {p["student_code"] for p in flagged} == {f"X{world['tag']}2", f"Y{world['tag']}2"}


def test_filter_option_lists(db_cur, world):
    assert any(d["id"] == world["dept"] for d in repo.list_departments(db_cur))
    assert any(s["id"] == world["X"]["subj"] for s in repo.list_all_subjects(db_cur))
