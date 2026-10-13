"""Database tests.

They run inside ONE transaction that is rolled back at the end, so your real
data is never changed. If the database is not reachable, they are skipped.
"""
import uuid

import psycopg2
import pytest
from psycopg2 import errors

from app.config import ConfigError
from app.db.connection import get_connection
from app.db.init_db import SCHEMA_FILE


@pytest.fixture
def cur():
    try:
        conn = get_connection()
    except (ConfigError, psycopg2.OperationalError) as e:
        pytest.skip(f"Database not reachable: {e}")
    cursor = conn.cursor()
    cursor.execute(SCHEMA_FILE.read_text(encoding="utf-8"))
    yield cursor
    conn.rollback()  # undo everything, including test tables/rows
    conn.close()


def expect_error(cursor, error_class, sql, params=()):
    """Run SQL that must fail, then recover so the test can continue."""
    cursor.execute("SAVEPOINT before_error")
    with pytest.raises(error_class):
        cursor.execute(sql, params)
    cursor.execute("ROLLBACK TO SAVEPOINT before_error")


def make_base(cursor):
    """Creates department, class, subject, 1 student, 1 assessment. Returns ids."""
    tag = uuid.uuid4().hex[:8]
    cursor.execute("INSERT INTO departments (name) VALUES (%s) RETURNING id", (f"Dept-{tag}",))
    dept = cursor.fetchone()[0]
    cursor.execute("INSERT INTO classes (department_id, name, semester) VALUES (%s,%s,3) RETURNING id", (dept, f"C-{tag}"))
    cls = cursor.fetchone()[0]
    cursor.execute("INSERT INTO subjects (code, name, department_id, semester) VALUES (%s,'Sub',%s,3) RETURNING id", (f"SUB-{tag}", dept))
    subj = cursor.fetchone()[0]
    cursor.execute("INSERT INTO students (student_code, name, class_id) VALUES (%s,'Test Student',%s) RETURNING id", (f"TEST-{tag}", cls))
    stu = cursor.fetchone()[0]
    cursor.execute("INSERT INTO assessments (class_id, subject_id, name, max_marks) VALUES (%s,%s,'Quiz',30) RETURNING id", (cls, subj))
    asm = cursor.fetchone()[0]
    return {"dept": dept, "cls": cls, "subj": subj, "stu": stu, "asm": asm, "tag": tag}


def test_all_expected_tables_exist(cur):
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
    existing = {r[0] for r in cur.fetchall()}
    expected = {"users", "departments", "classes", "subjects", "students", "teachers",
                "teacher_assignments", "attendance_sessions", "attendance_records",
                "assessments", "marks", "audit_logs"}
    assert expected <= existing


def test_duplicate_student_code_rejected(cur):
    b = make_base(cur)
    expect_error(cur, errors.UniqueViolation,
                 "INSERT INTO students (student_code, name, class_id) VALUES (%s,'Other',%s)",
                 (f"TEST-{b['tag']}", b["cls"]))


def test_blank_student_name_rejected(cur):
    b = make_base(cur)
    expect_error(cur, errors.CheckViolation,
                 "INSERT INTO students (student_code, name, class_id) VALUES (%s,'   ',%s)",
                 (f"X-{b['tag']}", b["cls"]))


def test_invalid_student_status_rejected(cur):
    b = make_base(cur)
    expect_error(cur, errors.CheckViolation,
                 "INSERT INTO students (student_code, name, class_id, status) VALUES (%s,'N',%s,'banned')",
                 (f"Y-{b['tag']}", b["cls"]))


def test_invalid_user_role_rejected(cur):
    expect_error(cur, errors.CheckViolation,
                 "INSERT INTO users (username, password_hash, role) VALUES ('u_test','hash','superuser')")


def test_marks_above_max_rejected_on_insert(cur):
    b = make_base(cur)
    expect_error(cur, errors.CheckViolation,
                 "INSERT INTO marks (assessment_id, student_id, obtained_marks) VALUES (%s,%s,31)",
                 (b["asm"], b["stu"]))


def test_negative_marks_rejected(cur):
    b = make_base(cur)
    expect_error(cur, errors.CheckViolation,
                 "INSERT INTO marks (assessment_id, student_id, obtained_marks) VALUES (%s,%s,-1)",
                 (b["asm"], b["stu"]))


def test_marks_at_max_accepted_and_update_above_max_rejected(cur):
    b = make_base(cur)
    cur.execute("INSERT INTO marks (assessment_id, student_id, obtained_marks) VALUES (%s,%s,30)",
                (b["asm"], b["stu"]))
    expect_error(cur, errors.CheckViolation,
                 "UPDATE marks SET obtained_marks = 35 WHERE assessment_id=%s AND student_id=%s",
                 (b["asm"], b["stu"]))


def test_duplicate_marks_rejected(cur):
    b = make_base(cur)
    cur.execute("INSERT INTO marks (assessment_id, student_id, obtained_marks) VALUES (%s,%s,10)",
                (b["asm"], b["stu"]))
    expect_error(cur, errors.UniqueViolation,
                 "INSERT INTO marks (assessment_id, student_id, obtained_marks) VALUES (%s,%s,12)",
                 (b["asm"], b["stu"]))


def test_cannot_lower_max_below_existing_marks(cur):
    b = make_base(cur)
    cur.execute("INSERT INTO marks (assessment_id, student_id, obtained_marks) VALUES (%s,%s,25)",
                (b["asm"], b["stu"]))
    expect_error(cur, errors.CheckViolation,
                 "UPDATE assessments SET max_marks = 20 WHERE id = %s", (b["asm"],))


def test_assessment_needs_positive_max(cur):
    b = make_base(cur)
    expect_error(cur, errors.CheckViolation,
                 "INSERT INTO assessments (class_id, subject_id, name, max_marks) VALUES (%s,%s,'Bad',0)",
                 (b["cls"], b["subj"]))


def test_duplicate_assessment_rejected(cur):
    b = make_base(cur)
    expect_error(cur, errors.UniqueViolation,
                 "INSERT INTO assessments (class_id, subject_id, name, max_marks) VALUES (%s,%s,'Quiz',50)",
                 (b["cls"], b["subj"]))


def test_duplicate_attendance_session_and_record_rejected(cur):
    b = make_base(cur)
    cur.execute("INSERT INTO attendance_sessions (class_id, subject_id, session_date) VALUES (%s,%s,'2026-08-03') RETURNING id",
                (b["cls"], b["subj"]))
    sess = cur.fetchone()[0]
    expect_error(cur, errors.UniqueViolation,
                 "INSERT INTO attendance_sessions (class_id, subject_id, session_date) VALUES (%s,%s,'2026-08-03')",
                 (b["cls"], b["subj"]))
    # a second lecture on the same day (session_no = 2) is allowed
    cur.execute("INSERT INTO attendance_sessions (class_id, subject_id, session_date, session_no) VALUES (%s,%s,'2026-08-03',2)",
                (b["cls"], b["subj"]))
    cur.execute("INSERT INTO attendance_records (session_id, student_id, status) VALUES (%s,%s,'present')",
                (sess, b["stu"]))
    expect_error(cur, errors.UniqueViolation,
                 "INSERT INTO attendance_records (session_id, student_id, status) VALUES (%s,%s,'absent')",
                 (sess, b["stu"]))


def test_invalid_attendance_status_rejected(cur):
    b = make_base(cur)
    cur.execute("INSERT INTO attendance_sessions (class_id, subject_id, session_date) VALUES (%s,%s,'2026-08-04') RETURNING id",
                (b["cls"], b["subj"]))
    sess = cur.fetchone()[0]
    expect_error(cur, errors.CheckViolation,
                 "INSERT INTO attendance_records (session_id, student_id, status) VALUES (%s,%s,'late')",
                 (sess, b["stu"]))


def test_foreign_key_enforced(cur):
    expect_error(cur, errors.ForeignKeyViolation,
                 "INSERT INTO students (student_code, name, class_id) VALUES ('FK-TEST','N',999999999)")
