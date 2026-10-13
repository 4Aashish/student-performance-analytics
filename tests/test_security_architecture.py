"""Rules that keep the security design from being broken by accident later."""
import inspect
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGES = sorted((ROOT / "app" / "pages").glob("*.py"))

# A page must never reach the database or the importers except through app.security.
BANNED_IN_PAGES = [
    r"app\.repositories", r"app\.db\.connection", r"\btransaction\(",
    r"\bimport_students\b(?!_)", r"\bimport_attendance\b", r"\bimport_marks\b",
    r"validate_against_database", r"validate_attendance_against_database", r"validate_marks_against_database",
]


def test_there_are_pages_to_check():
    assert len(PAGES) >= 5


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_every_page_requires_login(page):
    assert "require_login(" in page.read_text(encoding="utf-8")


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_pages_do_not_bypass_the_security_layer(page):
    source = page.read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.strip().startswith("#"))
    # access.import_students(...) is allowed: it IS the security layer
    code = code.replace("access.import_students", "ACCESS_CALL").replace("access.import_attendance", "ACCESS_CALL") \
               .replace("access.import_marks", "ACCESS_CALL")
    for pattern in BANNED_IN_PAGES:
        assert not re.search(pattern, code), f"{page.name} uses '{pattern}' directly"


def test_main_page_checks_login():
    assert "require_login(" in (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def test_admin_page_is_admin_only():
    source = (ROOT / "app" / "pages" / "5_Users.py").read_text(encoding="utf-8")
    assert 'require_login("admin")' in source


def test_every_access_function_takes_the_logged_in_user():
    pytest.importorskip("psycopg2")
    from app.security import access

    checked = 0
    for name, func in inspect.getmembers(access, inspect.isfunction):
        if name.startswith("_") or func.__module__ != access.__name__:
            continue
        params = list(inspect.signature(func).parameters)
        assert params[:2] == ["cur", "user"], f"access.{name} must start with (cur, user)"
        checked += 1
    assert checked >= 25


def test_student_functions_have_no_student_id_parameter():
    """A student cannot ask for someone else's data if the function has nowhere to put an ID."""
    pytest.importorskip("psycopg2")
    from app.security import access

    for name in ("my_profile", "my_attendance", "my_marks"):
        assert list(inspect.signature(getattr(access, name)).parameters) == ["cur", "user"]


def test_every_user_management_function_takes_an_actor():
    pytest.importorskip("psycopg2")
    from app.security import users

    exempt = {"create_first_admin", "normalize_username"}
    checked = 0
    for name, func in inspect.getmembers(users, inspect.isfunction):
        if name.startswith("_") or func.__module__ != users.__name__ or name in exempt:
            continue
        assert list(inspect.signature(func).parameters)[:2] == ["cur", "actor"], name
        checked += 1
    assert checked >= 8
