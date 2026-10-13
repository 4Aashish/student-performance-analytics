import psycopg2
import pytest

from app.config import ConfigError
from app.db.connection import get_connection
from app.db.init_db import SCHEMA_FILE


@pytest.fixture
def db_cur():
    """A cursor inside a transaction that is ALWAYS rolled back (real data untouched)."""
    try:
        conn = get_connection()
    except (ConfigError, psycopg2.OperationalError) as e:
        pytest.skip(f"Database not reachable: {e}")
    cursor = conn.cursor()
    cursor.execute(SCHEMA_FILE.read_text(encoding="utf-8"))
    yield cursor
    conn.rollback()
    conn.close()


# ---------------------------------------------------------------------------------------------
# A small school used by the audit-trail and page tests (everything is rolled back after the test)
# ---------------------------------------------------------------------------------------------
import functools
import uuid
from datetime import date

KNOWN_PASSWORD = "Sunshine42"


@functools.lru_cache(maxsize=1)
def _known_hash() -> str:
    from app.security.passwords import hash_password

    return hash_password(KNOWN_PASSWORD)


@pytest.fixture
def world(db_cur):
    """Classes A and B (semester 3), subjects S1 and S2.
    teacher is assigned to (A, S1) only. student is a1 (class A). Users all have KNOWN_PASSWORD."""
    from app.repositories import attendance_repository as att_repo
    from app.repositories import marks_repository as marks_repo
    from app.repositories import student_repository as stu
    from app.security import users
    from app.security.models import CurrentUser

    cur = db_cur
    tag = uuid.uuid4().hex[:8]

    def add_user(role, name):
        cur.execute("INSERT INTO users (username, password_hash, role) VALUES (%s,%s,%s) RETURNING id",
                    (name, _known_hash(), role))
        return cur.fetchone()[0]

    cur.execute("INSERT INTO departments (name) VALUES (%s) RETURNING id", (f"D{tag}",))
    dept = cur.fetchone()[0]
    w = {"tag": tag, "dept": dept}
    for label in ("A", "B"):
        cur.execute("INSERT INTO classes (department_id, name, semester) VALUES (%s,%s,3) RETURNING id", (dept, f"{label}{tag}"))
        w[label] = cur.fetchone()[0]
    for label in ("S1", "S2"):
        cur.execute("INSERT INTO subjects (code, name, department_id, semester) VALUES (%s,%s,%s,3) RETURNING id",
                    (f"{label}{tag}", label, dept))
        w[label] = cur.fetchone()[0]
    w["a1"] = stu.create_student(cur, f"A{tag}1", "A One", w["A"])
    w["a2"] = stu.create_student(cur, f"A{tag}2", "A Two", w["A"])
    w["b1"] = stu.create_student(cur, f"B{tag}1", "B One", w["B"])

    w["admin"] = CurrentUser(add_user("admin", f"adm{tag}"), f"adm{tag}", "admin")
    t_uid = add_user("teacher", f"tea{tag}")
    cur.execute("INSERT INTO teachers (user_id, name, department_id) VALUES (%s,'T',%s) RETURNING id", (t_uid, dept))
    t_id = cur.fetchone()[0]
    w["teacher"] = CurrentUser(t_uid, f"tea{tag}", "teacher", teacher_id=t_id)
    users.assign_teacher(cur, w["admin"], t_id, w["A"], w["S1"])
    s_uid = add_user("student", f"stu{tag}")
    cur.execute("UPDATE students SET user_id = %s WHERE id = %s", (s_uid, w["a1"]))
    w["student"] = CurrentUser(s_uid, f"stu{tag}", "student", student_id=w["a1"])

    for cls, subj, sids in ((w["A"], w["S1"], [w["a1"], w["a2"]]), (w["A"], w["S2"], [w["a1"], w["a2"]]),
                            (w["B"], w["S1"], [w["b1"]])):
        att_repo.save_attendance(cur, cls, subj, date(2026, 8, 3), 1, {s: "present" for s in sids})
        asm = marks_repo.create_assessment(cur, cls, subj, "Quiz", 50)
        marks_repo.save_marks(cur, asm, {s: 40 for s in sids})
    return w
