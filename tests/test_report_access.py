import csv
import io
import json
import uuid
from datetime import date

import pytest

from app.repositories import attendance_repository as att_repo
from app.repositories import marks_repository as marks_repo
from app.repositories import student_repository as stu
from app.security import access, passwords, users
from app.security.models import AuthorizationError, CurrentUser
from app.services import reports
from app.validation import ValidationError

HASH = passwords.hash_password("Sunshine42")
D1 = date(2026, 8, 3)


def add_user(cur, role, name):
    cur.execute("INSERT INTO users (username, password_hash, role) VALUES (%s,%s,%s) RETURNING id", (name, HASH, role))
    return cur.fetchone()[0]


def parse(result):
    return list(csv.reader(io.StringIO(result.csv_bytes.decode("utf-8-sig"))))


@pytest.fixture
def w(db_cur):
    """Classes A and B (semester 3), subjects S1 and S2. Teacher is assigned to (A, S1) only.
    Student a1 has a formula-like name on purpose."""
    cur = db_cur
    tag = uuid.uuid4().hex[:8]
    cur.execute("INSERT INTO departments (name) VALUES (%s) RETURNING id", (f"D{tag}",))
    dept = cur.fetchone()[0]
    ids = {"dept": dept, "tag": tag}
    for label in ("A", "B"):
        cur.execute("INSERT INTO classes (department_id, name, semester) VALUES (%s,%s,3) RETURNING id", (dept, f"{label}{tag}"))
        ids[label] = cur.fetchone()[0]
    for label in ("S1", "S2"):
        cur.execute("INSERT INTO subjects (code, name, department_id, semester) VALUES (%s,%s,%s,3) RETURNING id",
                    (f"{label}{tag}", label, dept))
        ids[label] = cur.fetchone()[0]
    a1 = stu.create_student(cur, f"A{tag}1", "=HYPERLINK(evil)", ids["A"])
    a2 = stu.create_student(cur, f"A{tag}2", "A Two", ids["A"], status="inactive")
    a3 = stu.create_student(cur, f"A{tag}3", "A Three", ids["A"])
    b1 = stu.create_student(cur, f"B{tag}1", "B One", ids["B"])

    admin = CurrentUser(add_user(cur, "admin", f"adm{tag}"), f"adm{tag}", "admin")
    t_uid = add_user(cur, "teacher", f"tea{tag}")
    cur.execute("INSERT INTO teachers (user_id, name, department_id) VALUES (%s,'T',%s) RETURNING id", (t_uid, dept))
    t_id = cur.fetchone()[0]
    teacher = CurrentUser(t_uid, f"tea{tag}", "teacher", teacher_id=t_id)
    users.assign_teacher(cur, admin, t_id, ids["A"], ids["S1"])
    s_uid = add_user(cur, "student", f"stu{tag}")
    cur.execute("UPDATE students SET user_id = %s WHERE id = %s", (s_uid, a1))
    student = CurrentUser(s_uid, f"stu{tag}", "student", student_id=a1)

    # attendance: a1 and a3 present on day 1, a1 absent on day 2 (in A/S1); same for A/S2 and B/S1
    for cls, subj, sids in ((ids["A"], ids["S1"], [a1, a3]), (ids["A"], ids["S2"], [a1, a3]), (ids["B"], ids["S1"], [b1])):
        att_repo.save_attendance(cur, cls, subj, D1, 1, {s: "present" for s in sids})
        att_repo.save_attendance(cur, cls, subj, date(2026, 8, 4), 1, {sids[0]: "absent", **{s: "present" for s in sids[1:]}})
    for key, cls, subj, sids in (("A_S1", ids["A"], ids["S1"], [a1, a3]), ("A_S2", ids["A"], ids["S2"], [a1, a3]),
                                 ("B_S1", ids["B"], ids["S1"], [b1])):
        asm = marks_repo.create_assessment(cur, cls, subj, "Quiz", 50)
        marks_repo.save_marks(cur, asm, {s: 40 for s in sids})
    return {**ids, "a1": a1, "a3": a3, "b1": b1, "admin": admin, "teacher": teacher, "student": student}


# ---------------------------------------------------------------- who may export
def test_students_cannot_export_and_nobody_anonymous(db_cur, w):
    for report_type in access.REPORT_TYPES:
        with pytest.raises(AuthorizationError):
            access.build_report(db_cur, w["student"], report_type)
        with pytest.raises(AuthorizationError):
            access.build_report(db_cur, None, report_type)


def test_teacher_report_contains_only_assigned_rows(db_cur, w):
    result = access.build_report(db_cur, w["teacher"], "attendance", {"department_id": w["dept"]})
    parsed = parse(result)
    codes = {row[0] for row in parsed[1:]}
    assert codes == {f"A{w['tag']}1", f"A{w['tag']}3"}                      # class A only, active only
    assert {row[5] for row in parsed[1:]} == {f"S1{w['tag']}"}              # subject S1 only
    admin_result = access.build_report(db_cur, w["admin"], "attendance", {"department_id": w["dept"]})
    assert admin_result.row_count == 5                                      # A/S1 x2, A/S2 x2, B/S1 x1


def test_teacher_cannot_ask_for_an_unassigned_class(db_cur, w):
    for report_type in ("students", "attendance", "marks", "performance"):
        with pytest.raises(AuthorizationError):
            access.build_report(db_cur, w["teacher"], report_type, {"class_id": w["B"]})


def test_filters_are_validated(db_cur, w):
    admin = w["admin"]
    for bad in ({"allowed_class_ids": [1]}, {"semester": 99}, {"class_id": "1"}, {"class_id": True},
                {"status": "banned"}, {"nonsense": 1}):
        with pytest.raises(ValidationError):
            access.build_report(db_cur, admin, "students", bad)
    with pytest.raises(ValidationError):
        access.build_report(db_cur, admin, "unknown_report")
    with pytest.raises(ValidationError):
        access.build_report(db_cur, admin, "marks", {"status": "active"})     # status only for the student list


# ---------------------------------------------------------------- the filters really filter
def test_student_list_report_filters(db_cur, w):
    admin = w["admin"]
    all_students = access.build_report(db_cur, admin, "students", {"department_id": w["dept"]})
    assert all_students.row_count == 4
    only_b = access.build_report(db_cur, admin, "students", {"class_id": w["B"]})
    assert [row[0] for row in parse(only_b)[1:]] == [f"B{w['tag']}1"]
    inactive = access.build_report(db_cur, admin, "students", {"department_id": w["dept"], "status": "inactive"})
    assert [row[0] for row in parse(inactive)[1:]] == [f"A{w['tag']}2"]
    teacher_list = access.build_report(db_cur, w["teacher"], "students", {"department_id": w["dept"]})
    assert {row[0] for row in parse(teacher_list)[1:]} == {f"A{w['tag']}1", f"A{w['tag']}2", f"A{w['tag']}3"}


def test_attendance_and_marks_reports_values(db_cur, w):
    att = access.build_report(db_cur, w["admin"], "attendance", {"class_id": w["A"], "subject_id": w["S1"]})
    rows = {row[0]: row for row in parse(att)[1:]}
    assert rows[f"A{w['tag']}1"][7:10] == ["1", "2", "50.0"]                # present once of two days
    assert rows[f"A{w['tag']}1"][10] == "Below threshold (warning)"
    assert rows[f"A{w['tag']}3"][7:10] == ["2", "2", "100.0"]
    marks = access.build_report(db_cur, w["admin"], "marks", {"class_id": w["A"], "subject_id": w["S2"]})
    assert [row[-3:] for row in parse(marks)[1:]] == [["40.0", "50.0", "80.0"]] * 2


def test_performance_report(db_cur, w):
    result = access.build_report(db_cur, w["admin"], "performance", {"department_id": w["dept"]})
    by_code = {row[0]: row for row in parse(result)[1:]}
    assert set(by_code) == {f"A{w['tag']}1", f"A{w['tag']}3", f"B{w['tag']}1"}
    a1 = by_code[f"A{w['tag']}1"]
    assert a1[4] == "50.0" and a1[5] == "80.0" and a1[6] == "Yes"           # attendance 2 of 4 sessions
    assert by_code[f"A{w['tag']}3"][6] == "No"


# ---------------------------------------------------------------- empty results and safety
def test_report_with_no_records_has_no_file_and_no_audit_entry(db_cur, w):
    db_cur.execute("SELECT COUNT(*) FROM audit_logs WHERE action = 'export_report'")
    before = db_cur.fetchone()[0]
    result = access.build_report(db_cur, w["admin"], "marks", {"department_id": w["dept"], "semester": 7})
    assert result.row_count == 0 and result.csv_bytes is None
    db_cur.execute("SELECT COUNT(*) FROM audit_logs WHERE action = 'export_report'")
    assert db_cur.fetchone()[0] == before


def test_formula_like_name_is_neutralised_in_the_file(db_cur, w):
    result = access.build_report(db_cur, w["admin"], "students", {"class_id": w["A"], "status": "active"})
    assert "'=HYPERLINK(evil)" in {row[1] for row in parse(result)[1:]}


def test_exports_are_written_to_the_audit_log(db_cur, w):
    access.build_report(db_cur, w["teacher"], "attendance", {"department_id": w["dept"]})
    db_cur.execute("SELECT user_id, new_value FROM audit_logs WHERE action = 'export_report' ORDER BY id DESC LIMIT 1")
    user_id, details = db_cur.fetchone()
    details = details if isinstance(details, dict) else json.loads(details)
    assert user_id == w["teacher"].user_id
    assert details["report"] == "attendance" and details["rows"] == 2
    assert details["filters"] == {"department_id": w["dept"]}


def test_denied_attempts_are_not_logged_as_exports(db_cur, w):
    db_cur.execute("SELECT COUNT(*) FROM audit_logs WHERE action = 'export_report'")
    before = db_cur.fetchone()[0]
    with pytest.raises(AuthorizationError):
        access.build_report(db_cur, w["teacher"], "attendance", {"class_id": w["B"]})
    db_cur.execute("SELECT COUNT(*) FROM audit_logs WHERE action = 'export_report'")
    assert db_cur.fetchone()[0] == before


# ---------------------------------------------------------------- a student's own downloads
def test_student_downloads_contain_only_own_data(db_cur, w):
    student = w["student"]
    att_rows = access.my_attendance(db_cur, student)
    marks_rows = access.my_marks(db_cur, student)
    summary = reports.student_summary_report(att_rows, marks_rows, 75)
    parsed = parse(summary)
    assert {row[0] for row in parsed[1:]} == {f"S1{w['tag']}", f"S2{w['tag']}"}   # A's subjects, not B's rows
    for row in parsed[1:]:
        assert row[2:5] == ["1", "2", "50.0"]                                    # a1: present 1 of 2 in each subject
        assert row[6:8] == ["1", "80.0"]
    other = CurrentUser(student.user_id, student.username, "student", student_id=w["b1"])
    other_att = access.my_attendance(db_cur, other)
    assert [r["subject_code"] for r in other_att] == [f"S1{w['tag']}"]
