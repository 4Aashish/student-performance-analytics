import pytest
from app.config import ConfigError, get_settings


def test_defaults(monkeypatch):
    monkeypatch.delenv("ATTENDANCE_THRESHOLD", raising=False)
    monkeypatch.delenv("DB_PORT", raising=False)
    s = get_settings()
    assert s.attendance_threshold == 75.0
    assert s.db_port == 5432


def test_custom_threshold(monkeypatch):
    monkeypatch.setenv("ATTENDANCE_THRESHOLD", "80")
    assert get_settings().attendance_threshold == 80.0


@pytest.mark.parametrize("bad", ["abc", "0", "-5", "101"])
def test_invalid_threshold_rejected(monkeypatch, bad):
    monkeypatch.setenv("ATTENDANCE_THRESHOLD", bad)
    with pytest.raises(ConfigError):
        get_settings()


def test_invalid_port_rejected(monkeypatch):
    monkeypatch.setenv("DB_PORT", "not-a-number")
    with pytest.raises(ConfigError):
        get_settings()


def test_missing_password_blocks_database_url(monkeypatch):
    monkeypatch.setenv("DB_PASSWORD", "")
    with pytest.raises(ConfigError):
        _ = get_settings().database_url


def test_database_url_escapes_special_characters(monkeypatch):
    monkeypatch.setenv("DB_PASSWORD", "p@ss/word")
    assert "p%40ss%2Fword" in get_settings().database_url
