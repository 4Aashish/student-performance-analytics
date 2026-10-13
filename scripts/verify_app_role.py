"""Checks that the limited database user (student_app) can do what the app needs and nothing more.
Run:  python -m scripts.verify_app_role

Every statement is rolled back, nothing is ever saved or changed."""
import getpass
import sys

from app.config import ConfigError, get_settings

ROLE = "student_app"

# (what we try, SQL, should it work for the app role?)
CHECKS = [
    ("read students", "SELECT COUNT(*) FROM students", True),
    ("add a row to the audit log", "INSERT INTO audit_logs (action, table_name) VALUES ('privilege_check', 'users')", True),
    ("update a student (no row matches)", "UPDATE students SET name = name WHERE id = -1", True),
    ("remove a teacher assignment (no row matches)", "DELETE FROM teacher_assignments WHERE id = -1", True),
    ("edit the audit log", "UPDATE audit_logs SET action = action WHERE id = -1", False),
    ("delete from the audit log", "DELETE FROM audit_logs WHERE id = -1", False),
    ("delete a student", "DELETE FROM students WHERE id = -1", False),
    ("delete marks", "DELETE FROM marks WHERE id = -1", False),
    ("drop a table", "DROP TABLE students", False),
    ("change a table", "ALTER TABLE users ADD COLUMN privilege_check_column INTEGER", False),
    ("create a table", "CREATE TABLE privilege_check_table (id INTEGER)", False),
    ("switch off the audit-log protection", "ALTER TABLE audit_logs DISABLE TRIGGER trg_audit_logs_append_only", False),
]


def main() -> int:
    import psycopg2

    try:
        settings = get_settings()
    except ConfigError as e:
        print(f"Configuration problem: {e}")
        return 1
    password = getpass.getpass(f"Password of the database user '{ROLE}' (hidden): ")
    try:
        conn = psycopg2.connect(host=settings.db_host, port=settings.db_port, dbname=settings.db_name,
                                user=ROLE, password=password, connect_timeout=5)
    except psycopg2.Error as e:
        print(f"Could not connect as {ROLE}: {str(e).strip()}")
        return 1

    problems = 0
    try:
        with conn.cursor() as cur:
            for description, statement, should_work in CHECKS:
                conn.rollback()
                try:
                    cur.execute(statement)
                    worked = True
                except psycopg2.Error:
                    worked = False
                finally:
                    conn.rollback()                      # never keep anything
                ok = worked == should_work
                problems += 0 if ok else 1
                print(f"{'OK     ' if ok else 'PROBLEM'}  {description}: "
                      f"{'allowed' if worked else 'refused'} (expected {'allowed' if should_work else 'refused'})")
    finally:
        conn.close()
    print()
    print("All checks passed." if problems == 0 else f"{problems} check(s) did not behave as expected.")
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
