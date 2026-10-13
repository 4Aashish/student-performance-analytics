import pytest

from app.config import ConfigError, get_settings


def test_support_threshold_default(monkeypatch):
    monkeypatch.delenv("MARKS_SUPPORT_THRESHOLD", raising=False)
    assert get_settings().support_marks_threshold == 40.0


def test_support_threshold_custom(monkeypatch):
    monkeypatch.setenv("MARKS_SUPPORT_THRESHOLD", "50")
    assert get_settings().support_marks_threshold == 50.0


@pytest.mark.parametrize("bad", ["abc", "0", "-1", "101"])
def test_support_threshold_invalid(monkeypatch, bad):
    monkeypatch.setenv("MARKS_SUPPORT_THRESHOLD", bad)
    with pytest.raises(ConfigError):
        get_settings()
