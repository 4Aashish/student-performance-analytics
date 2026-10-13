from app.db.connection import transaction


def db_call(func, *args, **kwargs):
    """Runs func(cursor, ...) inside ONE transaction (saved only if there is no error)."""
    with transaction() as conn:
        with conn.cursor() as cur:
            return func(cur, *args, **kwargs)
