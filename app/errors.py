"""Safe error messages. Database errors can contain host names, table names and pieces of SQL,
so users only see a short message with a reference number. The full details go to logs/app.log."""
import logging
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
_logger = None


def get_logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger
    logger = logging.getLogger("student_analytics")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        try:
            LOG_DIR.mkdir(exist_ok=True)
            handler = RotatingFileHandler(LOG_DIR / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        except OSError:
            handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    _logger = logger
    return logger


def log_exception(exc: BaseException) -> str:
    """Writes the full error to the log file and returns a short reference for the user."""
    reference = uuid.uuid4().hex[:8]
    get_logger().error("ref=%s %s: %s", reference, type(exc).__name__, exc, exc_info=exc)
    return reference


def user_message(exc: BaseException) -> str:
    """Text that is safe to show in the browser."""
    from psycopg2 import Error as DatabaseError

    if isinstance(exc, DatabaseError):
        reference = log_exception(exc)
        return ("A database problem occurred. Please try again. "
                f"If it keeps happening, tell the administrator (reference {reference}).")
    return str(exc)
