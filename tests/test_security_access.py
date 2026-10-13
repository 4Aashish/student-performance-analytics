import io
import uuid
from datetime import date

import pytest

from app.repositories import attendance_repository as att_repo
from app.repositories import marks_repository as marks_repo
from app.repositories import student_repository as stu
from app.security import access, passwords, users
from app.security.models import AuthorizationError, CurrentUser
from app.services.attendance_import import REQUIRED_COLUMNS as ATT_COLUMNS
from app.services.csv_utils import read_csv_required
from app.services.marks_import import REQUIRED_COLUMNS as MARKS_COLUMNS

HASH = passwords.hash_password("Sunshine42")
D1 = date(2026, 8, 3)


def add_user(cur, role, name):
    cur.execute("INSERT INTO users (username, password_hash, role) VALUES (%s,%s,%s) RETURNING id", (name, HASH, role))
    return cur.fetchone()[0]


@pytest.fixture
def w(db_cur):
    """Department with classes A and B (both semester 3) and subjects S1, S2.
    Teacher T is assigned to (A, S1) only. Students a1, a2 are in A, b1 is in B."""
    cur = db_cur
    tag = uuid.uuid4().hex[:8]
    cur.execute("INSERT INTO departments (name) VALUES (%s) RETURNING id", (f"D{tag}",))
    dept = cur.fetchone()[0]
    ids = {}
    for label in ("A", "B"):
        cur.execute("INSERT INTO classes (department_id, name, semester) VALUES (%s,%s,3) RETURNING id",
                    (dept, f"{label}{tag}"))
        ids[label] = cur.fetchone()[0]
    for label in ("S1", "S2"):
        cur.execute("INSERT INTO subjects (code, name, department_id, semester) VALUES (%s,%s,%s,3) RETURNING id",
                    (f"{label}{tag}", label, dept))
        ids[label] = cur.fetchone()[0]
    a1 = stu.create_student(cur, f"A{tag}1", "A One", ids["A"])
    a2 = stu.create_student(cur, f"A{tag}2", "A Two", ids["A"])
    b1 = stu.create_student(cur, f"B{tag}1", "B One", ids["B"])

    admin = CurrentUser(add_user(cur, "admin", f"adm{tag}"), f"adm{tag}", "admin")

    t_uid = add_user(cur, "teacher", f"tea{tag}")
    cur.execute("INSERT INTO teachers (user_id, name, department_id) VALUES (%s,'T',%s) RETURNING id", (t_uid, dept))
    t_id = cur.fetchone()[0]
    teacher = CurrentUser(t_uid, f"tea{tag}", "teacher", teacher_id=t_id)
    assignment = users.assign_teacher(cur, admin, t_id, ids["A"], ids["S1"])

    def student_user(student_id, label):
        uid = add_user(cur, "student", f"stu{label}{tag}")
        cur.execute("UPDATE students SET user_id = %s WHERE id = %s", (uid, student_id))
        return CurrentUser(uid, f"stu{label}{tag}", "student", student_id=student_id)

    student_a1, student_b1 = student_user(a1, "a1"), student_user(b1, "b1")

    # data: attendance in (A,S1), (A,S2), (B,S1); one assessment each with marks
    for cls, subj, sids in ((ids["A"], ids["S1"], [a1, a2]), (ids["A"], ids["S2"], [a1, a2]), (ids["B"], ids["S1"], [b1])):
        att_repo.save_attendance(cur, cls, subj, D1, 1, {s: "present" for s in sids})
    asm = {}
    for key, cls, subj, sids in (("A_S1", ids["A"], ids["S1"], [a1, a2]), ("A_S2", ids["A"], ids["S2"], [a1, a2]),
                                 ("B_S1", ids["B"], ids["S1"], [b1])):
        asm[key] = marks_repo.create_assessment(cur, cls, subj, "Quiz", 50)
        marks_repo.save_marks(cur, asm[key], {s: 40 for s in sids})
    return {"tag": tag, "dept": dept, **ids, "a1": a1, "a2": a2, "b1": b1, "admin": admin, "teacher": teacher,
            "student_a1": student_a1, "student_b1": student_b1, "asm": asm, "assignment": assignment, "t_id": t_id}


# ---------------------------------------------------------------- teacher scope
def test_teacher_sees_only_assigned_classes_and_subjects(db_cur, w):
    assert [c["id"] for c in access.list_classes(db_cur, w["teacher"])] == [w["A"]]
    assert [s["id"] for s in access.list_subjects_for_class(db_cur, w["teacher"], w["A"])] == [w["S1"]]
    assert access.list_subjects_for_class(db_cur, w["teacher"], w["B"]) == []
    admin_classes = {c["id"] for c in access.list_classes(db_cur, w["admin"])}
    assert {w["A"], w["B"]} <= admin_classes
    assert {w["S1"], w["S2"]} <= {s["id"] for s in access.list_subjects_for_class(db_cur, w["admin"], w["A"])}


def test_teacher_student_search_is_limited_to_assigned_classes(db_cur, w):
    found = {s["id"] for s in access.search_students(db_cur, w["teacher"])}
    assert w["a1"] in found and w["a2"] in found and w["b1"] not in found
    assert {s["id"] for s in access.search_students(db_cur, w["teacher"], text=f"B{w['tag']}")} == set()
    with pytest.raises(AuthorizationError):
        access.search_students(db_cur, w["teacher"], class_id=w["B"])
    assert [s["id"] for s in access.search_students(db_cur, w["admin"], class_id=w["B"])] == [w["b1"]]


def test_teacher_cannot_read_unassigned_attendance(db_cur, w):
    assert len(access.attendance_summary(db_cur, w["teacher"], w["A"], w["S1"])) == 2
    for cls, subj in ((w["A"], w["S2"]), (w["B"], w["S1"])):
        with pytest.raises(AuthorizationError):
            access.attendance_summary(db_cur, w["teacher"], cls, subj)
        with pytest.raises(AuthorizationError):
            access.list_sessions(db_cur, w["teacher"], cls, subj)
        with pytest.raises(AuthorizationError):
            access.get_session_statuses(db_cur, w["teacher"], cls, subj, D1, 1)


def test_teacher_attendance_write_is_scoped_and_recorded(db_cur, w):
    day = date(2026, 8, 10)
    result = access.save_attendance(db_cur, w["teacher"], w["A"], w["S1"], day, 1, {w["a1"]: "present", w["a2"]: "absent"})
    db_cur.execute("SELECT created_by FROM attendance_sessions WHERE id = %s", (result["session_id"],))
    assert db_cur.fetchone()[0] == w["teacher"].user_id
    with pytest.raises(AuthorizationError):
        access.save_attendance(db_cur, w["teacher"], w["A"], w["S2"], day, 1, {w["a1"]: "present"})
    with pytest.raises(AuthorizationError):
        access.save_attendance(db_cur, w["teacher"], w["B"], w["S1"], day, 1, {w["b1"]: "present"})
    assert att_repo.get_session_statuses(db_cur, w["A"], w["S2"], day, 1) is None   # nothing was written


def test_teacher_marks_are_scoped(db_cur, w):
    ok = access.create_assessment(db_cur, w["teacher"], w["A"], w["S1"], "Quiz 2", 30)
    access.save_marks(db_cur, w["teacher"], ok, {w["a1"]: 25})
    db_cur.execute("SELECT user_id FROM audit_logs WHERE action = 'marks_create' ORDER BY id DESC LIMIT 1")
    assert db_cur.fetchone()[0] == w["teacher"].user_id                           # who changed the marks
    with pytest.raises(AuthorizationError):
        access.create_assessment(db_cur, w["teacher"], w["A"], w["S2"], "Sneaky", 30)
    for key in ("A_S2", "B_S1"):
        asm = w["asm"][key]
        for call in (lambda: access.marks_for_assessment(db_cur, w["teacher"], asm),
                     lambda: access.save_marks(db_cur, w["teacher"], asm, {w["a1"]: 1}),
                     lambda: access.get_marks_history(db_cur, w["teacher"], asm)):
            with pytest.raises(AuthorizationError):
                call()
    assert marks_repo.marks_for_assessment(db_cur, w["asm"]["A_S2"])[0]["obtained_marks"] == 40.0  # unchanged


def test_unknown_assessment_is_reported_as_not_found(db_cur, w):
    with pytest.raises(access.AssessmentNotFoundError):
        access.marks_for_assessment(db_cur, w["teacher"], 999999999)


def test_teacher_marks_overview_only_shows_assigned_subjects(db_cur, w):
    rows = access.fetch_marks_rows(db_cur, w["teacher"], w["A"])
    assert {r["subject_code"] for r in rows} == {f"S1{w['tag']}"}
    with pytest.raises(AuthorizationError):
        access.fetch_marks_rows(db_cur, w["teacher"], w["B"])
    with pytest.raises(AuthorizationError):
        access.fetch_marks_rows(db_cur, w["teacher"], w["A"], w["S2"])
    assert {r["subject_code"] for r in access.fetch_marks_rows(db_cur, w["admin"], w["A"])} == \
        {f"S1{w['tag']}", f"S2{w['tag']}"}


def test_removing_an_assignment_takes_effect_immediately(db_cur, w):
    access.attendance_summary(db_cur, w["teacher"], w["A"], w["S1"])                # allowed
    users.remove_assignment(db_cur, w["admin"], w["assignment"])
    with pytest.raises(AuthorizationError):
        access.attendance_summary(db_cur, w["teacher"], w["A"], w["S1"])
    assert access.list_classes(db_cur, w["teacher"]) == []


def test_teacher_without_assignments_sees_nothing(db_cur, w):
    nobody = CurrentUser(w["teacher"].user_id, "x", "teacher", teacher_id=None)
    assert access.list_classes(db_cur, nobody) == []
    assert access.search_students(db_cur, nobody) == []
    assert access.dashboard_student_count(db_cur, nobody) == 0


# ---------------------------------------------------------------- imports
def _att_csv(w, rows):
    head = "student_code,subject_code,session_date,session_no,status\n"
    return read_csv_required(io.BytesIO((head + "".join(rows)).encode()), ATT_COLUMNS)


def test_teacher_attendance_import_is_limited_to_own_assignments(db_cur, w):
    t = w["tag"]
    df = _att_csv(w, [f"A{t}1,S1{t},2026-08-10,1,present\n", f"B{t}1,S1{t},2026-08-10,1,present\n"])
    result = access.import_attendance(db_cur, w["teacher"], df)
    assert result.inserted == 0 and len(result.errors) == 1
    assert result.errors[0].row_number == 3 and "not assigned" in result.errors[0].message
    assert att_repo.get_session_statuses(db_cur, w["A"], w["S1"], date(2026, 8, 10), 1) is None   # all or nothing
    assert access.import_attendance(db_cur, w["admin"], df).inserted == 2


def test_teacher_marks_import_is_limited_to_own_assignments(db_cur, w):
    t = w["tag"]
    head = "student_code,subject_code,assessment_name,obtained_marks,max_marks\n"
    df = read_csv_required(io.BytesIO((head + f"A{t}1,S1{t},Mid,20,50\nA{t}1,S2{t},Mid,20,50\n").encode()), MARKS_COLUMNS)
    result = access.import_marks(db_cur, w["teacher"], df)
    assert result.inserted == 0 and "not assigned" in result.errors[0].message
    assert access.import_marks(db_cur, w["admin"], df).inserted == 2


# ---------------------------------------------------------------- dashboard
def test_dashboard_is_scoped_for_teachers(db_cur, w):
    assert access.dashboard_student_count(db_cur, w["teacher"], {}) == 2
    assert access.dashboard_student_count(db_cur, w["admin"], {"department_id": w["dept"]}) == 3
    rows = access.dashboard_attendance_rows(db_cur, w["teacher"], {"department_id": w["dept"]})
    assert {(r["class_id"], r["subject_id"]) for r in rows} == {(w["A"], w["S1"])}
    marks = access.dashboard_marks_rows(db_cur, w["teacher"], {})
    assert {(r["class_id"], r["subject_id"]) for r in marks} == {(w["A"], w["S1"])}
    with pytest.raises(AuthorizationError):
        access.dashboard_student_count(db_cur, w["teacher"], {"class_id": w["B"]})


def test_teacher_cannot_widen_the_dashboard_by_passing_allowed_class_ids(db_cur, w):
    rows = access.dashboard_attendance_rows(db_cur, w["teacher"], {"allowed_class_ids": [w["A"], w["B"]]})
    assert {r["class_id"] for r in rows} == {w["A"]}


# ---------------------------------------------------------------- students
def test_student_cannot_use_staff_functions(db_cur, w):
    s = w["student_a1"]
    calls = [lambda: access.list_classes(db_cur, s),
             lambda: access.search_students(db_cur, s),
             lambda: access.attendance_summary(db_cur, s, w["A"], w["S1"]),
             lambda: access.save_attendance(db_cur, s, w["A"], w["S1"], D1, 2, {w["a1"]: "present"}),
             lambda: access.save_marks(db_cur, s, w["asm"]["A_S1"], {w["a1"]: 50}),
             lambda: access.dashboard_student_count(db_cur, s, {}),
             lambda: access.fetch_marks_rows(db_cur, s, w["A"]),
             lambda: access.create_student(db_cur, s, "X1", "X", w["A"]),
             lambda: access.import_students(db_cur, s, None)]
    for call in calls:
        with pytest.raises(AuthorizationError):
            call()


def test_student_sees_only_own_records(db_cur, w):
    mine = access.my_profile(db_cur, w["student_a1"])
    assert mine["student_code"] == f"A{w['tag']}1"
    assert access.my_profile(db_cur, w["student_b1"])["student_code"] == f"B{w['tag']}1"
    attendance = access.my_attendance(db_cur, w["student_a1"])
    assert {a["subject_code"] for a in attendance} == {f"S1{w['tag']}", f"S2{w['tag']}"}
    assert all(a["total_held"] == 1 and a["attended"] == 1 for a in attendance)
    marks = access.my_marks(db_cur, w["student_a1"])
    assert len(marks) == 2 and all(m["obtained_marks"] == 40.0 and m["max_marks"] == 50.0 for m in marks)
    # student B only has class B / subject S1 data
    assert [a["subject_code"] for a in access.my_attendance(db_cur, w["student_b1"])] == [f"S1{w['tag']}"]
    # a mark changed for a1 must not appear for b1
    marks_repo.save_marks(db_cur, w["asm"]["A_S1"], {w["a1"]: 11})
    assert [m["obtained_marks"] for m in access.my_marks(db_cur, w["student_b1"])] == [40.0]


def test_my_records_need_a_linked_student(db_cur, w):
    unlinked = CurrentUser(1, "x", "student", student_id=None)
    for func in (access.my_profile, access.my_attendance, access.my_marks):
        with pytest.raises(AuthorizationError):
            func(db_cur, unlinked)
        with pytest.raises(AuthorizationError):
            func(db_cur, w["teacher"])
        with pytest.raises(AuthorizationError):
            func(db_cur, w["admin"])


# ---------------------------------------------------------------- admin-only actions
def test_teacher_cannot_manage_students(db_cur, w):
    t = w["teacher"]
    with pytest.raises(AuthorizationError):
        access.create_student(db_cur, t, "HACK1", "Hacker", w["A"])
    with pytest.raises(AuthorizationError):
        access.update_student(db_cur, t, w["a1"], name="Renamed")
    with pytest.raises(AuthorizationError):
        access.validate_students_import(db_cur, t, None)
    with pytest.raises(AuthorizationError):
        access.import_students(db_cur, t, None)


def test_admin_can_do_everything(db_cur, w):
    admin = w["admin"]
    sid = access.create_student(db_cur, admin, f"N{w['tag']}", "New Kid", w["A"])
    access.update_student(db_cur, admin, sid, name="Renamed")
    assert access.search_students(db_cur, admin, text="Renamed")[0]["id"] == sid
    access.save_attendance(db_cur, admin, w["A"], w["S2"], date(2026, 8, 11), 1, {w["a1"]: "present"})
    access.save_marks(db_cur, admin, w["asm"]["A_S2"], {w["a1"]: 45})
    assert access.dashboard_student_count(db_cur, admin, {"department_id": w["dept"]}) == 4


def test_nobody_can_call_the_layer_without_a_user(db_cur, w):
    with pytest.raises(AuthorizationError):
        access.list_classes(db_cur, None)
    with pytest.raises(AuthorizationError):
        access.my_profile(db_cur, None)
