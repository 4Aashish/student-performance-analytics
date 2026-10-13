"""Fills in the forms of the Students, Attendance, Marks and Home pages and presses their buttons.
(File uploads cannot be simulated by the test tool: the CSV import tabs are covered by TEST_CHECKLIST.md.)
Database calls run inside the test transaction, so nothing is saved."""
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from app.security import auth

ROOT = Path(__file__).resolve().parents[1]
PAGES = {"main": "app/main.py", "students": "app/pages/1_Students.py",
         "attendance": "app/pages/2_Attendance.py", "marks": "app/pages/3_Marks.py"}


def texts(elements):
    return [str(e.value) for e in elements]


def by_label(elements, label, index=0):
    matches = [e for e in elements if e.label == label]
    assert matches, f"no widget labelled {label!r}; found {[e.label for e in elements]}"
    return matches[index]


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


# ---------------------------------------------------------------- Students page (admin)
def add_student(at, code, name):
    by_label(at.text_input, "Student ID").set_value(code)
    by_label(at.text_input, "Name", 0).set_value(name)
    by_label(at.button, "Add student").click().run()


def test_admin_adds_a_student_and_a_duplicate_id_is_refused(ui, world, db_cur):
    at = ui("students", world["admin"])
    code = f"F{world['tag']}1"
    add_student(at, code, "Form Student")
    assert not at.exception, [e.value for e in at.exception]
    assert any("added" in m for m in texts(at.success)), texts(at.error)
    db_cur.execute("SELECT name, status FROM students WHERE student_code = %s", (code,))
    assert db_cur.fetchone() == ("Form Student", "active")

    add_student(at, code, "Same Id Again")
    assert any("already exists" in m for m in texts(at.error))
    db_cur.execute("SELECT COUNT(*) FROM students WHERE student_code = %s", (code,))
    assert db_cur.fetchone()[0] == 1


def test_admin_edits_a_student(ui, world, db_cur):
    at = ui("students", world["admin"])
    by_label(at.selectbox, "Select student").select(f"A{world['tag']}2 - A Two").run()
    by_label(at.text_input, "Name", 1).set_value("Renamed Two")           # the second 'Name' is the edit form
    by_label(at.button, "Save changes").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Changes saved" in m for m in texts(at.success)), texts(at.error)
    db_cur.execute("SELECT name FROM students WHERE id = %s", (world["a2"],))
    assert db_cur.fetchone()[0] == "Renamed Two"


# ---------------------------------------------------------------- Attendance page (teacher)
def test_teacher_saves_attendance_and_then_edits_it(ui, world, db_cur):
    at = ui("attendance", world["teacher"])
    by_label(at.button, "Save attendance").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("saved for 2 students" in m for m in texts(at.success)), texts(at.error)
    db_cur.execute("SELECT COUNT(*) FROM attendance_sessions WHERE class_id = %s AND subject_id = %s AND session_date = %s",
                   (world["A"], world["S1"], date.today()))
    assert db_cur.fetchone()[0] == 1

    by_label(at.button, "Save attendance").click().run()                   # same lecture again = editing it
    assert any("already recorded" in m for m in texts(at.info))
    assert any("updated for 2 students" in m for m in texts(at.success)), texts(at.error)


# ---------------------------------------------------------------- Marks page (teacher)
def test_teacher_creates_an_assessment_and_a_duplicate_is_refused(ui, world, db_cur):
    at = ui("marks", world["teacher"])
    by_label(at.text_input, "Name (for example Internal-1)").set_value("Viva")
    by_label(at.number_input, "Maximum marks").set_value(20)
    by_label(at.button, "Create assessment").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("created" in m for m in texts(at.success)), texts(at.error)
    db_cur.execute("SELECT max_marks FROM assessments WHERE name = 'Viva' AND class_id = %s AND subject_id = %s",
                   (world["A"], world["S1"]))
    assert float(db_cur.fetchone()[0]) == 20.0

    by_label(at.text_input, "Name (for example Internal-1)").set_value("Viva")
    by_label(at.button, "Create assessment").click().run()
    assert any("already exists" in m for m in texts(at.error))


def test_teacher_saves_marks_without_changing_them(ui, world, db_cur):
    at = ui("marks", world["teacher"])
    by_label(at.button, "Save marks").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("2 unchanged" in m for m in texts(at.success)), texts(at.error)
    db_cur.execute("SELECT COUNT(*) FROM audit_logs WHERE action = 'marks_update' AND user_id = %s",
                   (world["teacher"].user_id,))
    assert db_cur.fetchone()[0] == 0                                        # nothing changed, nothing logged


# ---------------------------------------------------------------- Home page: change password
NEW_PASSWORD_LABEL = "New password (at least 8 characters, a letter and a digit)"


def test_user_changes_their_own_password(ui, world, db_cur):
    from tests.conftest import KNOWN_PASSWORD

    at = ui("main", world["teacher"])
    by_label(at.text_input, "Current password").set_value(KNOWN_PASSWORD)
    by_label(at.text_input, NEW_PASSWORD_LABEL).set_value("Brand-new9x")
    by_label(at.text_input, "New password again").set_value("Brand-new9x")
    by_label(at.button, "Change password").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Password changed" in m for m in texts(at.success)), texts(at.error)
    assert auth.authenticate(db_cur, world["teacher"].username, "Brand-new9x").user is not None
    assert auth.authenticate(db_cur, world["teacher"].username, KNOWN_PASSWORD).user is None


def test_password_change_with_two_different_new_passwords_is_refused(ui, world, db_cur):
    from tests.conftest import KNOWN_PASSWORD

    at = ui("main", world["teacher"])
    by_label(at.text_input, "Current password").set_value(KNOWN_PASSWORD)
    by_label(at.text_input, NEW_PASSWORD_LABEL).set_value("Brand-new9x")
    by_label(at.text_input, "New password again").set_value("Different-9y")
    by_label(at.button, "Change password").click().run()
    assert any("different" in m for m in texts(at.error))
    assert auth.authenticate(db_cur, world["teacher"].username, KNOWN_PASSWORD).user is not None
