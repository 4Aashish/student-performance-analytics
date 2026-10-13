"""Edge cases found by the coverage report: error branches that no test had run before."""
import io
from datetime import date

import pytest

from app.security.passwords import validate_password
from app.services.csv_utils import read_csv_required
from app.services.marks_import import REQUIRED_COLUMNS as MARKS_COLUMNS
from app.services.marks_import import validate_marks_df
from app.services.student_import import read_students_csv
from app.validation import ValidationError


# ---------------------------------------------------------------- passwords
def test_password_equal_to_username_is_refused_even_if_it_is_not_a_common_password():
    with pytest.raises(ValidationError) as err:
        validate_password("Kapil2026x", username="kapil2026x")
    assert "same as the username" in str(err.value)
    validate_password("Kapil2026x", username="someone-else")


# ---------------------------------------------------------------- unreadable CSV files
def test_non_utf8_file_is_refused_with_a_helpful_message():
    raw = b"a,b\n1,\xff\xfe\n"
    with pytest.raises(ValidationError) as err:
        read_csv_required(io.BytesIO(raw), ["a", "b"])
    assert "UTF-8" in str(err.value)


def test_broken_csv_structure_is_refused_by_both_readers():
    broken = b"a,b\n1,2\n3,4,5,6\n"                       # line 3 has more fields than the header
    with pytest.raises(ValidationError) as err:
        read_csv_required(io.BytesIO(broken), ["a", "b"])
    assert "could not be read" in str(err.value)
    header = b"student_code,name,class_name,department,semester\n"
    with pytest.raises(ValidationError) as err:
        read_students_csv(io.BytesIO(header + b"S1,A,C,D,3\nS2,B,C,D,3,extra,more\n"))
    assert "could not be read" in str(err.value)


# ---------------------------------------------------------------- marks CSV: unusual max_marks / names
STUDENTS = {"S1": {"id": 1, "class_id": 10, "semester": 3, "department_id": 1, "status": "active"}}
SUBJECTS = {"CS301": {"id": 5, "semester": 3, "department_id": 1}}
HEADER = "student_code,subject_code,assessment_name,obtained_marks,max_marks\n"


def check(text):
    df = read_csv_required(io.BytesIO(text.encode()), MARKS_COLUMNS)
    return [e.message for e in validate_marks_df(df, STUDENTS, SUBJECTS, {}, set()).errors]


def test_max_marks_that_is_not_a_number():
    assert any("must be a number" in m for m in check(HEADER + "S1,CS301,Quiz,5,abc\n"))


def test_max_marks_over_the_database_limit():
    assert any("cannot be more than" in m for m in check(HEADER + "S1,CS301,Quiz,5,10000\n"))
    assert check(HEADER + "S1,CS301,Quiz,5,9999.99\n") == []


def test_assessment_name_too_long():
    assert any("too long" in m for m in check(HEADER + f"S1,CS301,{'N' * 101},5,30\n"))


def test_invalid_max_marks_is_reported_even_when_obtained_marks_are_missing():
    messages = check(HEADER + "S1,CS301,Quiz,,abc\n")
    assert any("'obtained_marks' is required" in m for m in messages)
    assert any("must be a number" in m for m in messages)


# ---------------------------------------------------------------- database-backed edge cases
def test_student_field_length_limits(db_cur, world):
    from app.repositories import student_repository as stu

    with pytest.raises(ValidationError):
        stu.create_student(db_cur, "C" * 31, "Name", world["A"])
    with pytest.raises(ValidationError):
        stu.create_student(db_cur, f"L{world['tag']}", "N" * 101, world["A"])
    with pytest.raises(ValidationError):
        stu.update_student(db_cur, world["a1"], name="N" * 101)
    stu.update_student(db_cur, world["a1"])                     # nothing to change: quietly does nothing


def test_assessment_name_length_limit(db_cur, world):
    from app.repositories import marks_repository as marks_repo

    with pytest.raises(ValidationError):
        marks_repo.create_assessment(db_cur, world["A"], world["S1"], "N" * 101, 30)


def test_attendance_date_must_be_a_real_date(db_cur, world):
    from app.repositories import attendance_repository as att_repo

    for bad in ("2026-08-03", None, 20260803):
        with pytest.raises(ValidationError):
            att_repo.save_attendance(db_cur, world["A"], world["S1"], bad, 1, {world["a1"]: "present"})


def test_updating_a_missing_student_is_reported(db_cur, world):
    from app.security import access

    with pytest.raises(access.StudentNotFoundError):
        access.update_student(db_cur, world["admin"], 999999999, name="Nobody")


def test_admin_can_validate_a_student_import(db_cur, world):
    from app.security import access

    head = "student_code,name,class_name,department,semester\n"
    row = f"V{world['tag']}1,New,A{world['tag']},D{world['tag']},3\n"
    result = access.validate_students_import(db_cur, world["admin"], read_students_csv(io.BytesIO((head + row).encode())))
    assert result.errors == [] and len(result.valid_rows) == 1


def test_teacher_marks_overview_with_an_assigned_subject(db_cur, world):
    from app.security import access

    rows = access.fetch_marks_rows(db_cur, world["teacher"], world["A"], world["S1"])
    assert {r["subject_code"] for r in rows} == {f"S1{world['tag']}"}


def test_report_filters_with_empty_values_are_ignored(db_cur, world):
    from app.security import access

    result = access.build_report(db_cur, world["admin"], "students",
                                 {"department_id": world["dept"], "class_id": None, "semester": None, "status": None})
    assert result.row_count == 3 and result.filters == {"department_id": world["dept"]}


# ---------------------------------------------------------------- account management edge cases
def test_first_admin_can_be_created_when_no_admin_exists(db_cur, world):
    from app.security import auth, users

    db_cur.execute("UPDATE users SET role = 'student' WHERE role = 'admin'")   # undone by the test rollback
    uid = users.create_first_admin(db_cur, f"first{world['tag']}", "Sunshine42x")
    assert auth.authenticate(db_cur, f"first{world['tag']}", "Sunshine42x").user.role == "admin"
    db_cur.execute("SELECT COUNT(*) FROM audit_logs WHERE action = 'create_first_admin' AND user_id = %s", (uid,))
    assert db_cur.fetchone()[0] == 1
    with pytest.raises(ValidationError):                                      # and only once
        users.create_first_admin(db_cur, f"second{world['tag']}", "Sunshine42x")


def test_account_actions_on_missing_things_are_reported(db_cur, world):
    from app.security import users

    admin = world["admin"]
    with pytest.raises(ValidationError):
        users.set_user_active(db_cur, admin, 999999999, True)
    with pytest.raises(ValidationError):
        users.reset_password(db_cur, admin, 999999999, "Sunshine42x")
    with pytest.raises(ValidationError):
        users.assign_teacher(db_cur, admin, 999999999, world["A"], world["S1"])
    with pytest.raises(ValidationError):
        users.remove_assignment(db_cur, admin, 999999999)


def test_the_same_assignment_cannot_be_added_twice(db_cur, world):
    from app.security import users

    with pytest.raises(ValidationError) as err:                               # the world already has (A, S1)
        users.assign_teacher(db_cur, world["admin"], world["teacher"].teacher_id, world["A"], world["S1"])
    assert "already assigned" in str(err.value)
    users.assign_teacher(db_cur, world["admin"], world["teacher"].teacher_id, world["A"], world["S2"])   # still usable
