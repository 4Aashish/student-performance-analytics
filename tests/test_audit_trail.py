"""Who did what: every important change leaves a row in the audit log, and the log cannot be edited."""
import io
import json
from datetime import date

import psycopg2
import pytest

from app.repositories import attendance_repository as att_repo
from app.security import access
from app.services.attendance_import import REQUIRED_COLUMNS as ATT_COLUMNS
from app.services.csv_utils import read_csv_required
from app.services.marks_import import REQUIRED_COLUMNS as MARKS_COLUMNS


def rows_of(cur, **where):
    clauses = " AND ".join(f"{k} = %s" for k in where)
    cur.execute(f"SELECT id, user_id, action, table_name, record_id, old_value, new_value FROM audit_logs "
                f"WHERE {clauses} ORDER BY id", list(where.values()))
    cols = ["id", "user_id", "action", "table_name", "record_id", "old_value", "new_value"]
    out = []
    for r in cur.fetchall():
        row = dict(zip(cols, r))
        for key in ("old_value", "new_value"):
            if isinstance(row[key], str):
                row[key] = json.loads(row[key])
        out.append(row)
    return out


def expect_error(cur, sql, params=()):
    cur.execute("SAVEPOINT before_error")
    with pytest.raises(psycopg2.Error):
        cur.execute(sql, params)
    cur.execute("ROLLBACK TO SAVEPOINT before_error")


# ---------------------------------------------------------------- the log is append-only
def test_audit_log_rows_cannot_be_edited_or_deleted(db_cur, world):
    access.create_student(db_cur, world["admin"], f"X{world['tag']}", "Someone", world["A"])
    row = rows_of(db_cur, user_id=world["admin"].user_id, action="student_create")[0]
    expect_error(db_cur, "UPDATE audit_logs SET action = 'nothing happened' WHERE id = %s", (row["id"],))
    expect_error(db_cur, "DELETE FROM audit_logs WHERE id = %s", (row["id"],))
    expect_error(db_cur, "UPDATE audit_logs SET user_id = NULL")
    assert rows_of(db_cur, id=row["id"])[0]["action"] == "student_create"


# ---------------------------------------------------------------- students
def test_student_create_and_update_are_audited_with_old_and_new_values(db_cur, world):
    admin = world["admin"]
    sid = access.create_student(db_cur, admin, f"N{world['tag']}", "  New Kid ", world["A"])
    created = rows_of(db_cur, user_id=admin.user_id, action="student_create", record_id=sid)
    assert created[0]["new_value"] == {"student_code": f"N{world['tag']}", "name": "New Kid",
                                       "class_id": world["A"], "status": "active"}
    access.update_student(db_cur, admin, sid, name="Renamed", class_id=world["B"], status="inactive")
    updated = rows_of(db_cur, user_id=admin.user_id, action="student_update", record_id=sid)
    assert updated[0]["old_value"] == {"name": "New Kid", "class_id": world["A"], "status": "active"}
    assert updated[0]["new_value"] == {"name": "Renamed", "class_id": world["B"], "status": "inactive"}


def test_update_that_changes_nothing_writes_no_audit_row(db_cur, world):
    admin = world["admin"]
    sid = access.create_student(db_cur, admin, f"Q{world['tag']}", "Same", world["A"])
    access.update_student(db_cur, admin, sid, name="Same", status="active")
    assert rows_of(db_cur, user_id=admin.user_id, action="student_update", record_id=sid) == []


def test_only_the_changed_fields_are_recorded(db_cur, world):
    admin = world["admin"]
    sid = access.create_student(db_cur, admin, f"R{world['tag']}", "Same", world["A"])
    access.update_student(db_cur, admin, sid, status="inactive")
    row = rows_of(db_cur, user_id=admin.user_id, action="student_update", record_id=sid)[0]
    assert row["old_value"] == {"status": "active"} and row["new_value"] == {"status": "inactive"}


def test_student_import_is_summarised_in_the_audit_log(db_cur, world):
    from app.services.student_import import read_students_csv

    head = "student_code,name,class_name,department,semester\n"
    dept_name = f"D{world['tag']}"
    body = "".join(f"I{world['tag']}{n},Kid {n},A{world['tag']},{dept_name},3\n" for n in range(3))
    result = access.import_students(db_cur, world["admin"], read_students_csv(io.BytesIO((head + body).encode())))
    assert result.inserted == 3
    assert rows_of(db_cur, user_id=world["admin"].user_id, action="student_import")[0]["new_value"] == {"rows": 3}


# ---------------------------------------------------------------- attendance
def test_attendance_create_and_correction_are_audited(db_cur, world):
    teacher, day = world["teacher"], date(2026, 8, 10)
    first = access.save_attendance(db_cur, teacher, world["A"], world["S1"], day, 1,
                                   {world["a1"]: "present", world["a2"]: "present"})
    created = rows_of(db_cur, user_id=teacher.user_id, action="attendance_create", record_id=first["session_id"])
    assert created[0]["new_value"] == {"records": 2}

    access.save_attendance(db_cur, teacher, world["A"], world["S1"], day, 1,
                           {world["a1"]: "present", world["a2"]: "absent"}, overwrite=True)
    change = rows_of(db_cur, user_id=teacher.user_id, action="attendance_update", record_id=first["session_id"])
    assert change[0]["new_value"] == {"changes": [{"student_id": world["a2"], "old": "present", "new": "absent"}]}

    access.save_attendance(db_cur, teacher, world["A"], world["S1"], day, 1,
                           {world["a1"]: "present", world["a2"]: "absent"}, overwrite=True)   # identical
    assert len(rows_of(db_cur, user_id=teacher.user_id, action="attendance_update")) == 1


def test_attendance_import_records_the_importing_teacher(db_cur, world):
    teacher, t = world["teacher"], world["tag"]
    head = "student_code,subject_code,session_date,session_no,status\n"
    df = read_csv_required(io.BytesIO((head + f"A{t}1,S1{t},2026-08-12,1,present\nA{t}2,S1{t},2026-08-12,1,absent\n").encode()), ATT_COLUMNS)
    assert access.import_attendance(db_cur, teacher, df).inserted == 2
    db_cur.execute("SELECT created_by FROM attendance_sessions WHERE class_id = %s AND subject_id = %s AND session_date = %s",
                   (world["A"], world["S1"], date(2026, 8, 12)))
    assert db_cur.fetchone()[0] == teacher.user_id
    assert rows_of(db_cur, user_id=teacher.user_id, action="attendance_import")[0]["new_value"] == {"rows": 2}


# ---------------------------------------------------------------- marks
def test_marks_import_records_the_importing_teacher(db_cur, world):
    teacher, t = world["teacher"], world["tag"]
    head = "student_code,subject_code,assessment_name,obtained_marks,max_marks\n"
    df = read_csv_required(io.BytesIO((head + f"A{t}1,S1{t},Mid,20,50\nA{t}2,S1{t},Mid,30,50\n").encode()), MARKS_COLUMNS)
    assert access.import_marks(db_cur, teacher, df).inserted == 2
    db_cur.execute("SELECT updated_by FROM marks m JOIN assessments a ON a.id = m.assessment_id "
                   "WHERE a.name = 'Mid' AND a.class_id = %s", (world["A"],))
    assert {r[0] for r in db_cur.fetchall()} == {teacher.user_id}
    per_mark = rows_of(db_cur, user_id=teacher.user_id, action="marks_import")
    assert len(per_mark) == 2 and all(r["user_id"] == teacher.user_id for r in per_mark)
    assert rows_of(db_cur, user_id=teacher.user_id, action="marks_import_summary")[0]["new_value"] == {"rows": 2}


def test_failed_imports_leave_no_audit_rows(db_cur, world):
    teacher, t = world["teacher"], world["tag"]
    head = "student_code,subject_code,assessment_name,obtained_marks,max_marks\n"
    df = read_csv_required(io.BytesIO((head + f"B{t}1,S1{t},Mid,20,50\n").encode()), MARKS_COLUMNS)   # class B: not assigned
    assert access.import_marks(db_cur, teacher, df).errors
    assert rows_of(db_cur, user_id=teacher.user_id, action="marks_import_summary") == []
    assert rows_of(db_cur, user_id=teacher.user_id, action="marks_import") == []
