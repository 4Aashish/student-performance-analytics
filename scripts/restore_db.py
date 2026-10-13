"""Restores a backup into a NEW database (it never overwrites an existing one).

Run:  python -m scripts.restore_db backups\\student_analytics_20261012_213005.dump student_analytics_restored

Afterwards check the data (for example set DB_NAME in a copy of .env to the new database and start the app).
To go back to normal, point DB_NAME at your real database again."""
import re
import subprocess
import sys
from pathlib import Path

from app.config import ConfigError, Settings, get_settings
from scripts.backup_db import build_env, find_pg_tool

DB_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def validate_database_name(name) -> str:
    """Only plain names are accepted, because the name is used in a CREATE DATABASE statement."""
    if not isinstance(name, str) or not DB_NAME_RE.match(name):
        raise ValueError("Database name must start with a letter or underscore and contain only letters, "
                         "digits and underscores (maximum 63 characters).")
    return name


def build_restore_command(pg_restore: str, settings: Settings, target_db: str, dump_file: Path) -> list:
    """No password in here on purpose."""
    return [pg_restore, "-h", settings.db_host, "-p", str(settings.db_port), "-U", settings.db_user,
            "-d", target_db, "--no-owner", "--exit-on-error", str(dump_file)]


def create_empty_database(settings: Settings, target_db: str) -> None:
    import psycopg2
    from psycopg2 import sql

    conn = psycopg2.connect(host=settings.db_host, port=settings.db_port, dbname="postgres",
                            user=settings.db_user, password=settings.db_password, connect_timeout=5)
    try:
        conn.autocommit = True                                  # CREATE DATABASE cannot run inside a transaction
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
            if cur.fetchone() is not None:
                raise ValueError(f"A database named '{target_db}' already exists. Choose a new name; "
                                 "this script never overwrites a database.")
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_db)))
    finally:
        conn.close()


def main(argv: list) -> int:
    if len(argv) != 3:
        print(r"Usage: python -m scripts.restore_db <backup file> <NEW database name>")
        return 1
    dump_file, target_db = Path(argv[1]), argv[2]
    try:
        validate_database_name(target_db)
        if not dump_file.is_file():
            raise ValueError(f"Backup file not found: {dump_file}")
        settings = get_settings()
        settings.require_db_password()
    except (ValueError, ConfigError) as e:
        print(f"Problem: {e}")
        return 1
    pg_restore = find_pg_tool("pg_restore")
    if pg_restore is None:
        print("pg_restore was not found. Set PG_BIN_DIR to the PostgreSQL 'bin' folder.")
        return 1

    try:
        create_empty_database(settings, target_db)
    except ValueError as e:
        print(f"Problem: {e}")
        return 1
    result = subprocess.run(build_restore_command(pg_restore, settings, target_db, dump_file),
                            env=build_env(settings), capture_output=True, text=True)
    if result.returncode != 0:
        print("Restore FAILED:")
        print(result.stderr.strip() or "(no message from pg_restore)")
        print(f"The empty database '{target_db}' was created. Delete it in pgAdmin if you do not need it.")
        return 1
    print(f"Restored into the new database '{target_db}'.")
    print(f"Check it: set DB_NAME={target_db} in a copy of your .env, start the app and look at the data.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
