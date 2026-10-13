"""Creates all tables. Run:  python -m app.db.init_db"""
from pathlib import Path

from app.db.connection import transaction

SCHEMA_FILE = Path(__file__).with_name("schema.sql")


def init_db() -> list:
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )
            return [row[0] for row in cur.fetchall()]


if __name__ == "__main__":
    tables = init_db()
    print(f"Schema applied. {len(tables)} tables in database:")
    for t in tables:
        print(f"  - {t}")
