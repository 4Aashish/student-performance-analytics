import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import psycopg2
import streamlit as st

from app.errors import user_message

from app.config import ConfigError
from app.db.helpers import db_call
from app.security import access, users
from app.security.models import AuthorizationError
from app.ui_auth import require_login
from app.validation import ValidationError

st.set_page_config(page_title="Users", layout="wide")
user = require_login("admin")
st.title("Users and teacher assignments")
st.caption("Only administrators can open this page.")

tab_accounts, tab_create, tab_assign = st.tabs(["Accounts", "Create account", "Teacher assignments"])

# ---------------- Accounts ----------------
with tab_accounts:
    try:
        accounts = db_call(users.list_users, user)
    except (ConfigError, psycopg2.Error, AuthorizationError) as e:
        st.error(user_message(e))
        st.stop()
    st.dataframe(pd.DataFrame([{
        "Username": a["username"], "Role": a["role"], "Name": a["profile_name"],
        "Student ID": a["student_code"], "Active": a["is_active"], "Locked": a["locked"],
    } for a in accounts]))

    by_label = {f"{a['username']} ({a['role']})": a for a in accounts}
    picked = by_label[st.selectbox("Select an account", list(by_label), key="selected_account")]
    c1, c2 = st.columns(2)
    with c1:
        if picked["is_active"]:
            if st.button("Disable this account", key="disable_account"):
                try:
                    db_call(users.set_user_active, user, picked["id"], False)
                    st.success("Account disabled.")
                    st.rerun()
                except (ValidationError, AuthorizationError) as e:
                    st.error(str(e))
        else:
            if st.button("Enable this account", key="enable_account"):
                db_call(users.set_user_active, user, picked["id"], True)
                st.success("Account enabled.")
                st.rerun()
    with c2:
        with st.form(f"reset_{picked['id']}", clear_on_submit=True):
            new_password = st.text_input("New password for this account", type="password", key="reset_password_value")
            reset_clicked = st.form_submit_button("Reset password", key="reset_password_button")
        if reset_clicked:
            try:
                db_call(users.reset_password, user, picked["id"], new_password)
                st.success("Password reset. Tell the user their new password privately.")
            except (ValidationError, AuthorizationError) as e:
                st.error(str(e))

# ---------------- Create account ----------------
with tab_create:
    role = st.selectbox("Role of the new account", ["teacher", "student", "admin"], key="new_role")
    departments = db_call(access.list_departments, user)
    unlinked = db_call(users.list_unlinked_students, user)
    with st.form(f"create_{role}", clear_on_submit=True):
        new_username = st.text_input("Username (letters, digits, dot, dash, underscore)", key="new_username")
        new_password = st.text_input("Password (at least 8 characters, a letter and a digit)", type="password", key="new_password")
        teacher_name, department_id, student_id = None, None, None
        if role == "teacher":
            teacher_name = st.text_input("Teacher name", key="new_teacher_name")
            dept_options = {d["name"]: d["id"] for d in departments}
            dept_label = st.selectbox("Department", list(dept_options)) if dept_options else None
            department_id = dept_options.get(dept_label)
        elif role == "student":
            student_options = {f"{s['student_code']} - {s['name']}": s["id"] for s in unlinked}
            student_label = st.selectbox("Student (without an account)", list(student_options), key="new_student") \
                if student_options else None
            student_id = student_options.get(student_label)
        create_clicked = st.form_submit_button("Create account", key="create_account_button")
    if create_clicked:
        try:
            db_call(users.create_account, user, new_username, new_password, role,
                    name=teacher_name, department_id=department_id, student_id=student_id)
            st.success(f"Account '{new_username.strip().lower()}' created.")
        except (ValidationError, AuthorizationError) as e:
            st.error(str(e))

# ---------------- Teacher assignments ----------------
with tab_assign:
    teachers = db_call(users.list_teachers, user)
    if not teachers:
        st.info("Create a teacher account first.")
    else:
        classes = db_call(access.list_classes, user)
        class_options = {f"{c['department']} / {c['class_name']} (Sem {c['semester']})": c["id"] for c in classes}
        teacher_options = {f"{t['name']} ({t['username']})": t["id"] for t in teachers}
        a1, a2, a3 = st.columns(3)
        teacher_id = teacher_options[a1.selectbox("Teacher", list(teacher_options), key="assign_teacher")]
        class_id = class_options[a2.selectbox("Class", list(class_options), key="assign_class")] if class_options else None
        subject_options = {}
        if class_id is not None:
            subject_options = {f"{s['code']} - {s['name']}": s["id"]
                               for s in db_call(access.list_subjects_for_class, user, class_id)}
        subject_label = a3.selectbox("Subject", list(subject_options), key="assign_subject") if subject_options else None
        if st.button("Assign teacher", key="assign_button") and subject_label:
            try:
                db_call(users.assign_teacher, user, teacher_id, class_id, subject_options[subject_label])
                st.success("Teacher assigned.")
                st.rerun()
            except (ValidationError, AuthorizationError) as e:
                st.error(str(e))

    assignments = db_call(users.list_assignments, user)
    st.subheader("Current assignments")
    if not assignments:
        st.info("No assignments yet. A teacher cannot see any class until one is assigned.")
    else:
        st.dataframe(pd.DataFrame([{"Teacher": a["teacher"], "Class": a["class_name"],
                                    "Subject": f"{a['subject_code']} - {a['subject_name']}"} for a in assignments]))
        remove_options = {f"{a['teacher']} / {a['class_name']} / {a['subject_code']}": a["id"] for a in assignments}
        remove_label = st.selectbox("Remove an assignment", list(remove_options), key="remove_assignment_select")
        if st.button("Remove assignment", key="remove_assignment_button"):
            try:
                db_call(users.remove_assignment, user, remove_options[remove_label])
                st.success("Assignment removed. The teacher loses access immediately.")
                st.rerun()
            except (ValidationError, AuthorizationError) as e:
                st.error(str(e))
