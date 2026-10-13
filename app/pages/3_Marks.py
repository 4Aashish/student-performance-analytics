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
from app.services.csv_utils import read_csv_required
from app.services.marks_analysis import subject_summary, subject_wise_performance
from app.services.marks_import import REQUIRED_COLUMNS
from app.ui_auth import require_login
from app.validation import ValidationError

st.set_page_config(page_title="Marks", layout="wide")
user = require_login("admin", "teacher")
st.title("Marks")
st.caption("Teachers can only use the classes and subjects assigned to them. "
           "Every change to marks is saved in the history.")

try:
    classes = db_call(access.list_classes, user)
except (ConfigError, psycopg2.Error, AuthorizationError) as e:
    st.error(user_message(e))
    st.stop()

class_options = {f"{c['department']} / {c['class_name']} (Sem {c['semester']})": c["id"] for c in classes}
if not class_options:
    if user.role == "admin":
        st.warning("No classes exist yet. For the sample data run:  python -m scripts.seed_reference_data")
    else:
        st.info("No classes are assigned to you yet. Please ask the administrator.")
    st.stop()


def pick_class_and_subject(prefix: str, allow_all_subjects: bool = False):
    """Returns (class_id, subject_id, ok). subject_id is None for 'All subjects'."""
    class_id = class_options[st.selectbox("Class", list(class_options), key=f"{prefix}_class")]
    subjects = db_call(access.list_subjects_for_class, user, class_id)
    if not subjects:
        st.warning("You have no subjects in this class.")
        return class_id, None, False
    options = {f"{s['code']} - {s['name']}": s["id"] for s in subjects}
    labels = (["All subjects"] if allow_all_subjects else []) + list(options)
    choice = st.selectbox("Subject", labels, key=f"{prefix}_subject")
    return class_id, options.get(choice), True


tab_assess, tab_marks, tab_perf, tab_import = st.tabs(
    ["Assessments", "Enter / edit marks", "Performance", "Import CSV"])

with tab_assess:
    class_id, subject_id, ok = pick_class_and_subject("as")
    if ok:
        with st.form("new_assessment", clear_on_submit=True):
            st.subheader("New assessment")
            name = st.text_input("Name (for example Internal-1)")
            max_marks = st.number_input("Maximum marks", min_value=0.0, value=30.0, step=1.0)
            create_clicked = st.form_submit_button("Create assessment")
        if create_clicked:
            try:
                db_call(access.create_assessment, user, class_id, subject_id, name, max_marks)
                st.success(f"Assessment '{name.strip()}' created.")
            except (ValidationError, access.DuplicateAssessmentError, AuthorizationError) as e:
                st.error(str(e))
        existing = db_call(access.list_assessments, user, class_id, subject_id)
        if existing:
            st.dataframe(pd.DataFrame(existing).drop(columns=["id"]))
        else:
            st.info("No assessments yet for this class and subject.")

with tab_marks:
    class_id, subject_id, ok = pick_class_and_subject("mk")
    if ok:
        assessments = db_call(access.list_assessments, user, class_id, subject_id)
        if not assessments:
            st.info("Create an assessment first (Assessments tab).")
        else:
            labels = {f"{a['name']} (max {a['max_marks']:g})": a for a in assessments}
            assessment = labels[st.selectbox("Assessment", list(labels), key="mk_assessment")]
            students = db_call(access.marks_for_assessment, user, assessment["id"])
            if not students:
                st.info("This class has no active students.")
            else:
                table = pd.DataFrame({
                    "Student ID": [s["student_code"] for s in students],
                    "Name": [s["name"] for s in students],
                    "Marks": [s["obtained_marks"] for s in students],
                })
                edited = st.data_editor(
                    table, hide_index=True, disabled=["Student ID", "Name"],
                    column_config={"Marks": st.column_config.NumberColumn(
                        f"Marks (0 to {assessment['max_marks']:g})", min_value=0.0, max_value=assessment["max_marks"])},
                    key=f"marks_{assessment['id']}",
                )
                st.caption("Leave a cell empty if the marks are not entered yet. Marks cannot be deleted, only changed.")
                if st.button("Save marks"):
                    entered = {s["student_id"]: float(v)
                               for s, v in zip(students, edited["Marks"].tolist()) if pd.notna(v)}
                    try:
                        counts = db_call(access.save_marks, user, assessment["id"], entered)
                    except (ValidationError, access.AssessmentNotFoundError, AuthorizationError) as e:
                        st.error(f"Nothing was saved. {e}")
                    else:
                        st.success(f"Saved: {counts['created']} new, {counts['updated']} changed, "
                                   f"{counts['unchanged']} unchanged.")
                with st.expander("History of changes"):
                    history = db_call(access.get_marks_history, user, assessment["id"])
                    if history:
                        st.dataframe(pd.DataFrame(history).drop(columns=["id"]))
                    else:
                        st.write("No changes recorded yet.")

with tab_perf:
    class_id, subject_id, ok = pick_class_and_subject("pf", allow_all_subjects=True)
    if ok:
        rows = db_call(access.fetch_marks_rows, user, class_id, subject_id)
        if not rows:
            st.info("No marks have been entered yet for this selection.")
        else:
            performance = subject_wise_performance(rows)
            st.subheader("Subject summary")
            st.dataframe(pd.DataFrame([{
                "Subject": f"{s['subject_code']} - {s['subject_name']}",
                "Students": s["students"],
                "Average %": round(s["average"], 1),
                "Highest %": round(s["highest"], 1),
                "Lowest %": round(s["lowest"], 1),
            } for s in subject_summary(performance)]))
            st.subheader("Student-wise")
            st.dataframe(pd.DataFrame([{
                "Student ID": p["student_code"], "Name": p["name"], "Subject": p["subject_code"],
                "Assessments": p["assessments"], "Average %": round(p["average_percentage"], 1),
            } for p in performance]))
            st.caption("Percentage = obtained marks / maximum marks x 100, averaged over the assessments.")

with tab_import:
    st.write("Required columns: `student_code, subject_code, assessment_name, obtained_marks, max_marks`. "
             "Assessments that do not exist yet are created from the file. "
             "Teachers can only import rows for their own classes and subjects.")
    st.write("The import is **all or nothing**: if any row has a problem, nothing is imported "
             "and every problem is listed below.")
    uploaded = st.file_uploader("Choose a CSV file", type=["csv"], key="marks_upload")
    if uploaded is not None:
        last = st.session_state.get("last_marks_import")
        if last and last[:2] == (uploaded.name, uploaded.size):
            st.success(f"Imported {last[2]} marks from this file. Upload another file to import more.")
        else:
            try:
                df = read_csv_required(io.BytesIO(uploaded.getvalue()), REQUIRED_COLUMNS)
                result = db_call(access.validate_marks_import, user, df)
            except (ValidationError, AuthorizationError) as e:
                st.error(str(e))
                st.stop()
            st.write(f"Rows read: **{result.total_rows}**  |  Ready to import: **{len(result.valid_rows)}**  |  "
                     f"Rows with problems: **{result.rows_with_errors}**")
            if result.errors:
                st.error("Nothing has been imported. Fix the problems below in your CSV and upload it again.")
                st.dataframe(pd.DataFrame([{"Row": e.row_number, "Student ID": e.student_code, "Problem": e.message}
                                           for e in result.errors]))
            else:
                st.success("All rows are valid.")
                st.dataframe(df.head(20))
                if st.button(f"Import {len(result.valid_rows)} marks"):
                    try:
                        final = db_call(access.import_marks, user, df)
                    except psycopg2.Error as e:
                        st.error("Nothing was imported. " + user_message(e))
                    else:
                        if final.errors:
                            st.error("The data changed while importing. Nothing was imported; upload again.")
                        else:
                            st.session_state["last_marks_import"] = (uploaded.name, uploaded.size, final.inserted)
                            st.rerun()
