"""Opens every page in a headless Streamlit (streamlit.testing AppTest) as each role.
The database calls run inside the test transaction, so nothing is saved.

What this proves: no page crashes, every page refuses the wrong role and a missing login,
expired / disabled / demoted sessions are handled, and raw database errors never reach the browser."""
import time
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from app.security import auth
from app.security.models import CurrentUser

ROOT = Path(__file__).resolve().parents[1]
PAGES = {
    "main": "app/main.py",
    "students": "app/pages/1_Students.py",
    "attendance": "app/pages/2_Attendance.py",
    "marks": "app/pages/3_Marks.py",
    "dashboard": "app/pages/4_Dashboard.py",
    "users": "app/pages/5_Users.py",
    "my_dashboard": "app/pages/6_My_Dashboard.py",
    "reports": "app/pages/7_Reports.py",
}
ALLOWED = {
    "admin": {"main", "students", "attendance", "marks", "dashboard", "users", "reports"},
    "teacher": {"main", "students", "attendance", "marks", "dashboard", "reports"},
    "student": {"main", "my_dashboard"},
}


def messages(elements):
    return [str(e.value) for e in elements]


def logged_in(at):
    try:
        return at.session_state["current_user"] is not None
    except KeyError:
        return False


@pytest.fixture
def ui(db_cur, monkeypatch):
    """run(page, user=None, **session_values) -> AppTest after one run."""
    import app.db.helpers as helpers
    import app.ui_auth as ui_auth

    def fake_db_call(func, *args, **kwargs):
        return func(db_cur, *args, **kwargs)

    monkeypatch.setattr(helpers, "db_call", fake_db_call)
    monkeypatch.setattr(ui_auth, "db_call", fake_db_call)

    def run(page, user=None, **session_values):
        at = AppTest.from_file(str(ROOT / PAGES[page]), default_timeout=60)
        if user is not None:
            at.session_state["current_user"] = user
        for key, value in session_values.items():
            at.session_state[key] = value
        at.run()
        return at

    return run


# ---------------------------------------------------------------- role matrix
@pytest.mark.parametrize("page", list(PAGES))
@pytest.mark.parametrize("role", ["admin", "teacher", "student"])
def test_each_page_works_for_allowed_roles_and_refuses_the_others(ui, world, role, page):
    at = ui(page, world[role])
    assert not at.exception, f"{page} crashed for {role}: {[e.value for e in at.exception]}"
    refused = any("permission" in m for m in messages(at.error))
    assert refused == (page not in ALLOWED[role]), f"{page} as {role}: errors={messages(at.error)}"


@pytest.mark.parametrize("page", [p for p in PAGES if p != "main"])
def test_pages_ask_for_a_login_when_nobody_is_logged_in(ui, world, page):
    at = ui(page)
    assert not at.exception
    assert any("log in" in m.lower() for m in messages(at.warning))
    assert not logged_in(at)


def test_home_page_shows_the_login_form(ui, world):
    at = ui("main")
    assert not at.exception
    assert len(at.text_input) == 2


# ---------------------------------------------------------------- login through the form
def test_wrong_password_gives_the_generic_message_and_no_session(ui, world):
    at = ui("main")
    at.text_input[0].set_value(world["admin"].username)
    at.text_input[1].set_value("Wrong-pass1")
    at.button[0].click().run()
    assert messages(at.error) == [auth.GENERIC_FAILURE]
    assert not logged_in(at)


def test_correct_login_starts_a_session(ui, world):
    from tests.conftest import KNOWN_PASSWORD

    at = ui("main")
    at.text_input[0].set_value(world["teacher"].username)
    at.text_input[1].set_value(KNOWN_PASSWORD)
    at.button[0].click().run()
    assert not at.exception
    assert logged_in(at)
    assert at.session_state["current_user"].role == "teacher"


# ---------------------------------------------------------------- sessions
def test_idle_session_expires(ui, world):
    at = ui("students", world["admin"], last_activity=time.time() - 31 * 60)
    assert any("expired" in m.lower() for m in messages(at.warning))
    assert not logged_in(at)


def test_disabled_account_is_logged_out_on_the_next_page_load(ui, world, db_cur):
    from app.security import users

    users.set_user_active(db_cur, world["admin"], world["teacher"].user_id, False)
    at = ui("students", world["teacher"])
    assert any("no longer active" in m for m in messages(at.error))
    assert not logged_in(at)


def test_a_stale_admin_session_cannot_keep_admin_rights_after_demotion(ui, world):
    forged = CurrentUser(world["teacher"].user_id, world["teacher"].username, "admin",
                         teacher_id=world["teacher"].teacher_id)         # the database says: teacher
    at = ui("users", forged)
    assert any("permission" in m for m in messages(at.error))
    assert at.session_state["current_user"].role == "teacher"


# ---------------------------------------------------------------- error hygiene
def test_database_errors_never_reach_the_browser(monkeypatch):
    import psycopg2

    import app.db.helpers as helpers
    import app.ui_auth as ui_auth

    secret = 'connection to server at "10.20.30.40", port 5432 failed'

    def broken_db_call(func, *args, **kwargs):
        raise psycopg2.OperationalError(secret)

    monkeypatch.setattr(helpers, "db_call", broken_db_call)
    monkeypatch.setattr(ui_auth, "db_call", broken_db_call)
    at = AppTest.from_file(str(ROOT / PAGES["students"]), default_timeout=60)
    at.session_state["current_user"] = CurrentUser(1, "someone", "admin")
    at.run()
    shown = " ".join(messages(at.error))
    assert "10.20.30.40" not in shown and "5432" not in shown
    assert "reference" in shown
