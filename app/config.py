"""Application settings, loaded from environment variables (.env)."""
import os
from dataclasses import dataclass
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv()


class ConfigError(Exception):
    """Raised when a setting is missing or invalid."""


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got '{raw}'")


@dataclass(frozen=True)
class Settings:
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    attendance_threshold: float
    support_marks_threshold: float = 40.0

    def require_db_password(self) -> None:
        """Call this before connecting to the database (Milestone 3)."""
        if not self.db_password:
            raise ConfigError("DB_PASSWORD is empty. Set it in your .env file.")

    @property
    def database_url(self) -> str:
        self.require_db_password()
        pwd = quote_plus(self.db_password)
        return (
            f"postgresql://{self.db_user}:{pwd}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


def get_settings() -> Settings:
    threshold = _get_float("ATTENDANCE_THRESHOLD", 75.0)
    if not (0 < threshold <= 100):
        raise ConfigError("ATTENDANCE_THRESHOLD must be between 0 and 100.")

    support_threshold = _get_float("MARKS_SUPPORT_THRESHOLD", 40.0)
    if not (0 < support_threshold <= 100):
        raise ConfigError("MARKS_SUPPORT_THRESHOLD must be between 0 and 100.")

    port_raw = os.getenv("DB_PORT", "5432")
    try:
        port = int(port_raw)
    except ValueError:
        raise ConfigError(f"DB_PORT must be an integer, got '{port_raw}'")

    return Settings(
        db_host=os.getenv("DB_HOST", "localhost"),
        db_port=port,
        db_name=os.getenv("DB_NAME", "student_analytics"),
        db_user=os.getenv("DB_USER", "postgres"),
        db_password=os.getenv("DB_PASSWORD", ""),
        attendance_threshold=threshold,
        support_marks_threshold=support_threshold,
    )
