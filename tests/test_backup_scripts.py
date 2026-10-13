"""Backup, restore and limited-role scripts: the parts that need no running database."""
import os
import re
from datetime import datetime
from pathlib import Path

import pytest

from app.config import Settings
from scripts import backup_db, restore_db

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = Settings(db_host="db.example", db_port=5433, db_name="school", db_user="app_user",
                    db_password="s3cret-Pw!", attendance_threshold=75.0)


def test_backup_command_never_contains_the_password():
    command = backup_db.build_dump_command("pg_dump", SETTINGS, Path("backups/x.dump"))
    assert not any("s3cret" in part for part in command)
    assert command[:1] == ["pg_dump"]
    for expected in ("db.example", "5433", "app_user", "school", "-F", "c"):
        assert expected in command
    assert command[command.index("-f") + 1] == str(Path("backups/x.dump"))


def test_password_travels_only_in_the_environment_and_the_real_environment_is_untouched():
    base = {"PATH": "x"}
    env = backup_db.build_env(SETTINGS, base)
    assert env["PGPASSWORD"] == "s3cret-Pw!" and env["PATH"] == "x"
    assert "PGPASSWORD" not in base
    backup_db.build_env(SETTINGS)
    assert os.environ.get("PGPASSWORD") != "s3cret-Pw!"


def test_backup_file_name_has_database_name_and_timestamp():
    assert backup_db.backup_filename("school", datetime(2026, 10, 12, 21, 30, 5)) == "school_20261012_213005.dump"


def test_pg_bin_dir_is_used_to_find_the_tools(tmp_path, monkeypatch):
    exe = "pg_dump.exe" if os.name == "nt" else "pg_dump"
    (tmp_path / exe).write_text("fake")
    monkeypatch.setenv("PG_BIN_DIR", str(tmp_path))
    assert backup_db.find_pg_tool("pg_dump") == str(tmp_path / exe)


def test_restore_accepts_only_plain_database_names():
    for good in ("school_restored", "_x", "School2026", "a" * 63):
        assert restore_db.validate_database_name(good) == good
    for bad in ("", "1abc", "has space", "a;DROP DATABASE school", "x-y", "a" * 64, "naïve", None, 5, 'a"b'):
        with pytest.raises(ValueError):
            restore_db.validate_database_name(bad)


def test_restore_command_never_contains_the_password_and_targets_the_new_database():
    command = restore_db.build_restore_command("pg_restore", SETTINGS, "school_restored", Path("b.dump"))
    assert not any("s3cret" in part for part in command)
    assert command[command.index("-d") + 1] == "school_restored"
    assert command[-1] == "b.dump" and "--exit-on-error" in command


def test_the_privilege_check_never_commits_and_covers_the_dangerous_actions():
    source = (ROOT / "scripts" / "verify_app_role.py").read_text(encoding="utf-8")
    assert ".commit(" not in source and "autocommit" not in source
    from scripts import verify_app_role

    refused = " ".join(sql for _, sql, should_work in verify_app_role.CHECKS if not should_work)
    for dangerous in ("UPDATE audit_logs", "DELETE FROM audit_logs", "DROP TABLE", "ALTER TABLE", "CREATE TABLE", "DISABLE TRIGGER"):
        assert dangerous in refused
    assert any(should_work for _, _, should_work in verify_app_role.CHECKS)


def test_role_script_grants_least_privilege():
    sql = (ROOT / "scripts" / "create_app_role.sql").read_text(encoding="utf-8")
    assert "NOSUPERUSER" in sql and "CHANGE_ME_BEFORE_RUNNING" in sql
    assert re.search(r"REVOKE UPDATE ON audit_logs FROM student_app", sql)
    assert "GRANT DELETE ON teacher_assignments" in sql
    assert "GRANT DELETE ON ALL" not in sql and "GRANT ALL" not in sql


def test_backups_are_never_committed():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "backups/" in ignore and "*.dump" in ignore
