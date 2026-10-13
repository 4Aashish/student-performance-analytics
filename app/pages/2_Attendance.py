import io
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import psycopg2
import streamlit as st

from app.errors import user_message

from app.config import ConfigError, get_settings
from app.db.helpers import db_call
from app.security import access
from app.security.models import AuthorizationError
from app.services.attendance_import import REQUIRED_COLUMNS
from app.services.attendance_report import FLAG_LABELS, build_attendance_report, summarize_report
from app.services.csv_utils import read_csv_required
from app.ui_auth import require_login
from app.validation import ValidationError

st.set_page_config(page_title="Attendance", layout="wide")
user = require_login("admin", "teacher")
st.title("Attendance")
st.caption("Teachers can only use the classes and subjects assigned to them.")

try:
    settings = get_settings()
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


def pick_class_and_subject(prefix: str):
    class_id = class_options[st.selectbox("Class", list(class_options), key=f"{prefix}_class")]
    subjects = db_call(access.list_subjects_for_class, user, class_id)
    if not subjects:
        st.warning("You have no subjects in this class.")
        return class_id, None
    subject_options = {f"{s['code']} - {s['name']}": s["id"] for s in subjects}
    subject_id = subject_options[st.selectbox("Subject", list(subject_options), key=f"{prefix}_subject")]
    return class_id, subject_id


tab_take, tab_summary, tab_import = st.tabs(["Take attendance", "Summary", "Import CSV"])

with tab_take:
    class_id, subject_id = pick_class_and_subject("take")
    if subject_id is not None:
        c1, c2 = st.columns(2)
        session_date = c1.date_input("Date", value=date.today(), max_value=date.today(), key="take_date")
        session_no = int(c2.number_input("Lecture number of the day", min_value=1, value=1, step=1, key="take_no"))
        try:
            students = db_call(access.search_students, user, class_id=class_id, status="active")
            existing = db_call(access.get_session_statuses, user, class_id, subject_id, session_date, session_no)
        except AuthorizationError as e:
            st.error(str(e))
            st.stop()
        if not students:
            st.info("This class has no active students.")
        else:
            if existing is not None:
                st.info("Attendance for this lecture is already recorded. You are editing it.")
            table = pd.DataFrame({
                "Student ID": [s["student_code"] for s in students],
                "Name": [s["name"] for s in students],
                "Present": [True if existing is None else existing.get(s["id"], "present") == "present"
                            for s in students],
            })
            edited = st.data_editor(
                table, hide_index=True, disabled=["Student ID", "Name"],
                key=f"att_{class_id}_{subject_id}_{session_date}_{session_no}",
            )
            if st.button("Save attendance"):
                statuses = {s["id"]: ("present" if present else "absent")
                            for s, present in zip(students, edited["Present"].tolist())}
                try:
                    result = db_call(access.save_attendance, user, class_id, subject_id, session_date,
                                     session_no, statuses, overwrite=existing is not None)
                except (ValidationError, access.DuplicateSessionError, AuthorizationError) as e:
                    st.error(str(e))
                else:
                    word = "saved" if result["created"] else "updated"
                    st.success(f"Attendance {word} for {result['records']} students.")
        with st.expander("Lectures already recorded for this class and subject"):
            sessions = db_call(access.list_sessions, user, class_id, subject_id)
            if sessions:
                st.dataframe(pd.DataFrame(sessions))
            else:
                st.write("None yet.")

with tab_summary:
    class_id, subject_id = pick_class_and_subject("sum")
    if subject_id is not None:
        report = build_attendance_report(
            db_call(access.attendance_summary, user, class_id, subject_id), settings.attendance_threshold)
        if not report:
            st.info("This class has no active students.")
        elif all(r["total_held"] == 0 for r in report):
            st.info("No attendance has been recorded yet for this class and subject.")
        else:
            totals = summarize_report(report)
            m1, m2, m3 = st.columns(3)
            m1.metric("Students", totals["students"])
            m2.metric("Average attendance",
                      "-" if totals["average_percentage"] is None else f"{totals['average_percentage']:.1f}%")
            m3.metric(f"Below {settings.attendance_threshold:g}%", totals["below_threshold"])
            st.dataframe(pd.DataFrame([{
                "Student ID": r["student_code"], "Name": r["name"], "Attended": r["attended"],
                "Held": r["total_held"],
                "Attendance %": None if r["percentage"] is None else round(r["percentage"], 1),
                "Flag": FLAG_LABELS[r["flag"]],
            } for r in report]))
            st.caption("The flag is only a warning. It is NOT an official eligibility decision.")

with tab_import:
    st.write("Required columns: `student_code, subject_code, session_date, session_no, status`. "
             "Date format: `2026-08-03`. Status: `present` or `absent`. "
             "Teachers can only import rows for their own classes and subjects.")
    st.write("The import is **all or nothing**: if any row has a problem, nothing is imported "
             "and every problem is listed below.")
    uploaded = st.file_uploader("Choose a CSV file", type=["csv"], key="att_upload")
    if uploaded is not None:
        last = st.session_state.get("last_att_import")
        if last and last[:2] == (uploaded.name, uploaded.size):
            st.success(f"Imported {last[2]} attendance records from this file. Upload another file to import more.")
        else:
            try:
                df = read_csv_required(io.BytesIO(uploaded.getvalue()), REQUIRED_COLUMNS)
                result = db_call(access.validate_attendance_import, user, df)
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
                if st.button(f"Import {len(result.valid_rows)} attendance records"):
                    try:
                        final = db_call(access.import_attendance, user, df)
                    except psycopg2.Error as e:
                        st.error("Nothing was imported. " + user_message(e))
                    else:
                        if final.errors:
                            st.error("The data changed while importing. Nothing was imported; upload again.")
                        else:
                            st.session_state["last_att_import"] = (uploaded.name, uploaded.size, final.inserted)
                            st.rerun()
