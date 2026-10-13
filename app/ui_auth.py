"""Streamlit side of login: session handling used by every page."""
import time
from typing import Optional

import psycopg2
import streamlit as st

from app.errors import user_message

from app.config import ConfigError
from app.db.helpers import db_call
from app.security import auth
from app.security.models import CurrentUser
from app.security.session import IDLE_MINUTES, is_session_expired

USER_KEY = "current_user"
ACTIVITY_KEY = "last_activity"
NOTICE_KEY = "login_notice"


def start_session(user: CurrentUser) -> None:
    st.session_state[USER_KEY] = user
    st.session_state[ACTIVITY_KEY] = time.time()


def logout(notice: Optional[str] = None) -> None:
    st.session_state.pop(USER_KEY, None)
    st.session_state.pop(ACTIVITY_KEY, None)
    if notice:
        st.session_state[NOTICE_KEY] = notice


def has_session() -> bool:
    return st.session_state.get(USER_KEY) is not None


def require_login(*roles: str) -> CurrentUser:
    """Call at the top of EVERY page. Stops the page unless a valid user with an allowed role is logged in.
    The user is re-read from the database on every page load, so a disabled account or a changed
    role takes effect immediately."""
    user = st.session_state.get(USER_KEY)
    if user is None:
        st.warning("Please log in first. Open the Home page from the left menu.")
        st.stop()

    now = time.time()
    if is_session_expired(st.session_state.get(ACTIVITY_KEY), now, IDLE_MINUTES):
        logout(f"You were logged out after {IDLE_MINUTES} minutes without activity. Please log in again.")
        st.warning("Your session expired. Please log in again from the Home page.")
        st.stop()

    try:
        fresh = db_call(auth.load_current_user, user.user_id)
    except (ConfigError, psycopg2.Error) as e:
        st.error(user_message(e))
        st.stop()
    if fresh is None:
        logout("Your account is no longer active.")
        st.error("Your account is no longer active. Please contact the administrator.")
        st.stop()

    start_session(fresh)
    if roles and fresh.role not in roles:
        st.error("You do not have permission to open this page.")
        st.stop()

    st.sidebar.write(f"Logged in as **{fresh.username}** ({fresh.role})")
    if st.sidebar.button("Log out"):
        logout()
        st.rerun()
    return fresh
