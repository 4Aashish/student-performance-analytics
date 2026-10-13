"""Database connection helpers."""
from contextlib import contextmanager

import psycopg2

from app.config import get_settings


def get_connection():
    """Open a new PostgreSQL connection using settings from .env."""
    s = get_settings()
    s.require_db_password()
    return psycopg2.connect(
        host=s.db_host,
        port=s.db_port,
        dbname=s.db_name,
        user=s.db_user,
        password=s.db_password,
        connect_timeout=5,                       # do not hang forever if the database is down
        options="-c statement_timeout=60000",    # stop any single query after 60 seconds
    )


@contextmanager
def transaction():
    """Run a block of SQL as ONE transaction.

    Everything is saved (commit) only if the block finishes without error.
    On any error everything is undone (rollback), so we never keep half-saved data.

        with transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(...)
    """
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
