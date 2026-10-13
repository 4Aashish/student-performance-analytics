"""Drives the admin and student pages like a person would: filling forms and pressing buttons.
The database calls run inside the test transaction, so nothing is saved."""
import time
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from app.security import users

ROOT = Path(__file__).resolve().parents[1]
PAGES = {"students": "app/pages/1_Students.py", "users": "app/pages/5_Users.py",
         "my_dashboard": "app/pages/6_My_Dashboard.py", "reports": "app/pages/7_Reports.py"}


def texts(elements):
    return [str(e.value) for e in elements]


def logged_in(at):
    try:
        return at.session_state["current_user"] is not None
    except KeyError:
        return False


@pytest.fixture
def ui(db_cur, monkeypatch):
    import app.db.helpers as helpers
    import app.ui_auth as ui_auth

    def fake_db_call(func, *args, **kwargs):
        return func(db_cur, *args, **kwargs)

    monkeypatch.setattr(helpers, "db_call", fake_db_call)
    monkeypatch.setattr(ui_auth, "db_call", fake_db_call)

    def run(page, user):
        at = AppTest.from_file(str(ROOT / PAGES[page]), default_timeout=60)
        at.session_state["current_user"] = user
        at.run()
        return at

    return run


# ---------------------------------------------------------------- logout
def test_logout_button_ends_the_session(ui, world):
    at = ui("students", world["admin"])
    assert logged_in(at)
    at.sidebar.button[0].click().run()
    assert not logged_in(at)


# ---------------------------------------------------------------- Users page
def test_admin_creates_a_teacher_account(ui, world, db_cur):
    at = ui("users", world["admin"])
    name = f"newt{world['tag']}"
    at.text_input(key="new_username").set_value(name)
    at.text_input(key="new_password").set_value("Sunshine42x")
    at.text_input(key="new_teacher_name").set_value("New Teacher")
    at.button(key="create_account_button").click().run()
    assert not at.exception
    assert any("created" in m for m in texts(at.success)), texts(at.error)
    db_cur.execute("SELECT role FROM users WHERE username = %s", (name,))
    assert db_cur.fetchone()[0] == "teacher"


def test_weak_password_is_rejected_on_the_users_page(ui, world, db_cur):
    at = ui("users", world["admin"])
    at.text_input(key="new_username").set_value(f"weak{world['tag']}")
    at.text_input(key="new_password").set_value("short1")
    at.text_input(key="new_teacher_name").set_value("Weak")
    at.button(key="create_account_button").click().run()
    assert any("at least 8" in m for m in texts(at.error))
    db_cur.execute("SELECT COUNT(*) FROM users WHERE username = %s", (f"weak{world['tag']}",))
    assert db_cur.fetchone()[0] == 0


def test_admin_creates_a_student_account(ui, world, db_cur):
    at = ui("users", world["admin"])
    at.selectbox(key="new_role").select("student").run()
    name = f"newst{world['tag']}"
    at.selectbox(key="new_student").select(f"A{world['tag']}2 - A Two")
    at.text_input(key="new_username").set_value(name)
    at.text_input(key="new_password").set_value("Sunshine42x")
    at.button(key="create_account_button").click().run()
    assert not at.exception, [e.value for e in at.exception]
    db_cur.execute("SELECT s.id FROM students s JOIN users u ON u.id = s.user_id WHERE u.username = %s", (name,))
    assert db_cur.fetchone()[0] == world["a2"]


def test_admin_disables_an_account(ui, world, db_cur):
    at = ui("users", world["admin"])
    at.selectbox(key="selected_account").select(f"{world['teacher'].username} (teacher)")
    at.button(key="disable_account").click().run()
    assert not at.exception
    db_cur.execute("SELECT is_active FROM users WHERE id = %s", (world["teacher"].user_id,))
    assert db_cur.fetchone()[0] is False


def test_admin_assigns_and_removes_a_teacher_subject(ui, world, db_cur):
    at = ui("users", world["admin"])
    at.selectbox(key="assign_teacher").select(f"T ({world['teacher'].username})")
    at.selectbox(key="assign_class").select(f"D{world['tag']} / A{world['tag']} (Sem 3)").run()
    # the subject list depends on the class, so it is only available after the page re-ran
    at.selectbox(key="assign_subject").select(f"S2{world['tag']} - S2")
    at.button(key="assign_button").click().run()
    assert not at.exception
    db_cur.execute("SELECT COUNT(*) FROM teacher_assignments WHERE teacher_id = %s AND class_id = %s AND subject_id = %s",
                   (world["teacher"].teacher_id, world["A"], world["S2"]))
    assert db_cur.fetchone()[0] == 1

    at = ui("users", world["admin"])
    at.selectbox(key="remove_assignment_select").select(f"T / A{world['tag']} / S2{world['tag']}")
    at.button(key="remove_assignment_button").click().run()
    assert not at.exception
    db_cur.execute("SELECT COUNT(*) FROM teacher_assignments WHERE teacher_id = %s AND subject_id = %s",
                   (world["teacher"].teacher_id, world["S2"]))
    assert db_cur.fetchone()[0] == 0


# ---------------------------------------------------------------- Reports page
def generate(at, report_index, department_name, semester=None):
    at.selectbox(key="report_type").select_index(report_index)
    at.selectbox(key="rep_department").select(department_name)
    if semester is not None:
        at.selectbox(key="rep_semester").select(semester)
    at.button(key="generate_report").click().run()
    assert not at.exception, [e.value for e in at.exception]
    return at.session_state["report"]


def test_admin_generates_an_attendance_report(ui, world):
    report = generate(ui("reports", world["admin"]), 1, f"D{world['tag']}")
    assert report.name == "attendance_report" and report.row_count == 5 and report.csv_bytes


def test_teacher_report_contains_only_the_teachers_rows(ui, world):
    report = generate(ui("reports", world["teacher"]), 1, f"D{world['tag']}")
    assert report.row_count == 2                                  # class A, subject S1, two students


def test_report_without_records_says_there_is_nothing_to_download(ui, world):
    at = ui("reports", world["admin"])
    report = generate(at, 2, f"D{world['tag']}", semester=7)
    assert report.row_count == 0 and report.csv_bytes is None
    assert any("nothing to download" in m for m in texts(at.info))


# ---------------------------------------------------------------- student with no data
def test_student_without_records_sees_friendly_messages(ui, world, db_cur):
    from app.repositories import student_repository as stu
    from app.security.models import CurrentUser
    from tests.conftest import _known_hash

    sid = stu.create_student(db_cur, f"E{world['tag']}1", "Empty Student", world["A"])
    db_cur.execute("INSERT INTO users (username, password_hash, role) VALUES (%s,%s,'student') RETURNING id",
                   (f"empty{world['tag']}", _known_hash()))
    uid = db_cur.fetchone()[0]
    db_cur.execute("UPDATE students SET user_id = %s WHERE id = %s", (uid, sid))
    at = ui("my_dashboard", CurrentUser(uid, f"empty{world['tag']}", "student", student_id=sid))
    assert not at.exception
    shown = texts(at.info)
    assert any("No attendance has been recorded" in m for m in shown)
    assert any("No marks have been entered" in m for m in shown)
    assert any("nothing to download" in m for m in shown)
