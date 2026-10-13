import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import psycopg2
import streamlit as st

from app.errors import user_message

from app.config import ConfigError
from app.db.helpers import db_call
from app.security import access
from app.security.models import AuthorizationError
from app.services.student_import import read_students_csv
from app.ui_auth import require_login
from app.validation import ValidationError

st.set_page_config(page_title="Students", layout="wide")
user = require_login("admin", "teacher")
is_admin = user.role == "admin"

st.title("Student Management")
st.caption("Administrators can add, edit and import students. Teachers can only view the students of their classes.")

try:
    classes = db_call(access.list_classes, user)
except (ConfigError, psycopg2.Error, AuthorizationError) as e:
    st.error(user_message(e))
    st.stop()

class_options = {f"{c['department']} / {c['class_name']} (Sem {c['semester']})": c["id"] for c in classes}
if not class_options:
    if is_admin:
        st.warning("No classes exist yet. For the sample data run:  python -m scripts.seed_reference_data")
    else:
        st.info("No classes are assigned to you yet. Please ask the administrator.")
        st.stop()


def render_search():
    c1, c2, c3, c4 = st.columns(4)
    text = c1.text_input("Search by student ID or name")
    class_pick = c2.selectbox("Class", ["All"] + list(class_options))
    semester_pick = c3.selectbox("Semester", ["All"] + list(range(1, 11)))
    status_pick = c4.selectbox("Status", ["All", "active", "inactive"])
    try:
        rows = db_call(
            access.search_students, user,
            text=text or None,
            class_id=None if class_pick == "All" else class_options[class_pick],
            semester=None if semester_pick == "All" else semester_pick,
            status=None if status_pick == "All" else status_pick,
        )
    except AuthorizationError as e:
        st.error(str(e))
        return
    if not rows:
        st.info("No students match these filters.")
    else:
        st.write(f"{len(rows)} student(s) found")
        st.dataframe(pd.DataFrame(rows).drop(columns=["id", "class_id"]))


def render_add_edit():
    if not class_options:
        st.info("Create classes first.")
        return
    st.subheader("Add a student")
    with st.form("add_student", clear_on_submit=True):
        code = st.text_input("Student ID")
        name = st.text_input("Name")
        class_new = st.selectbox("Class", list(class_options))
        status_new = st.selectbox("Status", ["active", "inactive"])
        add_clicked = st.form_submit_button("Add student")
    if add_clicked:
        try:
            db_call(access.create_student, user, code, name, class_options[class_new], status_new)
            st.success(f"Student '{code.strip()}' added.")
        except (ValidationError, access.DuplicateStudentError, AuthorizationError) as e:
            st.error(str(e))

    st.divider()
    st.subheader("Edit a student")
    everyone = db_call(access.search_students, user)
    if not everyone:
        st.info("No students to edit yet.")
        return
    by_label = {f"{s['student_code']} - {s['name']}": s for s in everyone}
    picked = by_label[st.selectbox("Select student", list(by_label))]
    labels = list(class_options)
    current = next((lab for lab, cid in class_options.items() if cid == picked["class_id"]), labels[0])
    statuses = ["active", "inactive"]
    with st.form(f"edit_student_{picked['id']}"):
        new_name = st.text_input("Name", value=picked["name"])
        new_class = st.selectbox("Class", labels, index=labels.index(current))
        new_status = st.selectbox("Status", statuses, index=statuses.index(picked["status"]))
        save_clicked = st.form_submit_button("Save changes")
    st.caption("Student ID cannot be changed.")
    if save_clicked:
        try:
            db_call(access.update_student, user, picked["id"], name=new_name,
                    class_id=class_options[new_class], status=new_status)
            st.success("Changes saved.")
        except (ValidationError, access.StudentNotFoundError, AuthorizationError) as e:
            st.error(str(e))


def render_import():
    st.write("Required columns: `student_code, name, class_name, department, semester`. "
             "Optional: `status` (default `active`).")
    st.write("The import is **all or nothing**: if any row has a problem, nothing is imported "
             "and every problem is listed below.")
    uploaded = st.file_uploader("Choose a CSV file", type=["csv"])
    if uploaded is None:
        return
    last = st.session_state.get("last_import")
    if last and last[:2] == (uploaded.name, uploaded.size):
        st.success(f"Imported {last[2]} students from this file. Upload another file to import more.")
        return
    try:
        df = read_students_csv(io.BytesIO(uploaded.getvalue()))
        result = db_call(access.validate_students_import, user, df)
    except (ValidationError, AuthorizationError) as e:
        st.error(str(e))
        return
    st.write(f"Rows read: **{result.total_rows}**  |  Ready to import: **{len(result.valid_rows)}**  |  "
             f"Rows with problems: **{result.rows_with_errors}**")
    if result.errors:
        st.error("Nothing has been imported. Fix the problems below in your CSV and upload it again.")
        st.dataframe(pd.DataFrame([{"Row": e.row_number, "Student ID": e.student_code, "Problem": e.message}
                                   for e in result.errors]))
        return
    st.success("All rows are valid.")
    st.dataframe(df.head(20))
    if st.button(f"Import {len(result.valid_rows)} students"):
        try:
            final = db_call(access.import_students, user, df)
        except psycopg2.Error as e:
            st.error("Nothing was imported. " + user_message(e))
            return
        if final.errors:
            st.error("The data changed while importing. Nothing was imported; upload again.")
        else:
            st.session_state["last_import"] = (uploaded.name, uploaded.size, final.inserted)
            st.rerun()


if is_admin:
    tab_search, tab_add, tab_import = st.tabs(["Search", "Add / Edit", "Import CSV"])
    with tab_search:
        render_search()
    with tab_add:
        render_add_edit()
    with tab_import:
        render_import()
else:
    render_search()
