"""Session rules that do not need Streamlit (so they can be tested)."""
from typing import Optional

IDLE_MINUTES = 30


def is_session_expired(last_activity: Optional[float], now: float, idle_minutes: float = IDLE_MINUTES) -> bool:
    """True when the user did nothing for longer than idle_minutes. No activity recorded = not expired."""
    if last_activity is None:
        return False
    return (now - last_activity) > idle_minutes * 60
