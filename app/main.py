import sys
from pathlib import Path

# Project root ko path mein add kar rahe hain, taaki "from app.config" chale.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg2
import streamlit as st

from app.errors import user_message

from app import ui_auth
from app.config import ConfigError, get_settings
from app.db.helpers import db_call
from app.security import access, auth
from app.security.models import AuthorizationError
from app.validation import ValidationError

st.set_page_config(page_title="Student Performance Analytics", layout="wide")
st.title("Student Performance Analytics System")

try:
    settings = get_settings()
except ConfigError as e:
    st.error(f"Configuration error: {e}")
    st.stop()

# ---------------- Not logged in: show the login form ----------------
if not ui_auth.has_session():
    notice = st.session_state.pop(ui_auth.NOTICE_KEY, None)
    if notice:
        st.info(notice)
    st.subheader("Log in")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")
    if submitted:
        try:
            result = db_call(auth.authenticate, username, password)
        except (ConfigError, psycopg2.Error) as e:
            st.error(user_message(e))
            st.stop()
        if result.user is None:
            st.error(result.message)
        else:
            ui_auth.start_session(result.user)
            st.rerun()
    st.caption("No account yet? The administrator creates accounts. "
               "The very first administrator is created with:  python -m scripts.create_admin")
    st.stop()

# ---------------- Logged in ----------------
user = ui_auth.require_login()
st.write(f"Welcome, **{user.username}** ({user.role}).")

try:
    if user.role in ("admin", "teacher"):
        count = db_call(access.dashboard_student_count, user, {})
        label = "Active students" if user.role == "admin" else "Active students in your classes"
        st.metric(label, count)
        st.caption(f"Attendance warning threshold: {settings.attendance_threshold:g}% "
                   "(a warning only, not an official eligibility decision). "
                   "Use the left menu to open the other pages.")
    else:
        profile = db_call(access.my_profile, user)
        st.write(f"**{profile['name']}** ({profile['student_code']}) - {profile['department']} / "
                 f"{profile['class_name']}, semester {profile['semester']}")
        st.info("Open **My Dashboard** in the left menu to see your attendance, marks and reports.")
except AuthorizationError as e:
    st.warning(str(e))
except (ConfigError, psycopg2.Error) as e:
    st.error(user_message(e))

with st.expander("Change my password"):
    with st.form("change_password_form", clear_on_submit=True):
        old = st.text_input("Current password", type="password")
        new = st.text_input("New password (at least 8 characters, a letter and a digit)", type="password")
        again = st.text_input("New password again", type="password")
        change_clicked = st.form_submit_button("Change password")
    if change_clicked:
        if new != again:
            st.error("The two new passwords are different.")
        else:
            try:
                db_call(auth.change_password, user, old, new)
                st.success("Password changed.")
            except ValidationError as e:
                st.error(str(e))
