import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import psycopg2
import streamlit as st

from app.config import ConfigError
from app.db.helpers import db_call
from app.security import access
from app.security.models import AuthorizationError
from app.ui_auth import require_login
from app.validation import ValidationError

st.set_page_config(page_title="Reports", layout="wide")
user = require_login("admin", "teacher")
st.title("Reports (CSV download)")
st.caption("Choose a report and filters, then press Generate. The filters are applied before the file is made. "
           + ("You can export data of the whole institution." if user.role == "admin"
              else "You can only export data of your own classes and subjects.")
           + " Every export is recorded in the audit log.")

REPORT_LABELS = {
    "students": "Student list",
    "attendance": "Attendance (per student and subject)",
    "marks": "Marks (every assessment)",
    "performance": "Performance summary (per student)",
}

try:
    departments = db_call(access.list_departments, user)
    classes = db_call(access.list_classes, user)
    subjects = db_call(access.list_all_subjects, user)
except (ConfigError, psycopg2.Error, AuthorizationError) as e:
    st.error(f"Problem: {e}")
    st.stop()

if user.role == "teacher" and not classes:
    st.info("No classes are assigned to you yet. Please ask the administrator.")
    st.stop()

report_type = st.selectbox("Report", list(REPORT_LABELS), format_func=lambda key: REPORT_LABELS[key])
f1, f2, f3, f4, f5 = st.columns(5)
dept_options = {"All": None, **{d["name"]: d["id"] for d in departments}}
class_options = {"All": None, **{f"{c['department']} / {c['class_name']}": c["id"] for c in classes}}
subject_options = {"All": None, **{f"{s['code']} - {s['name']}": s["id"] for s in subjects}}
department_id = dept_options[f1.selectbox("Department", list(dept_options))]
class_id = class_options[f2.selectbox("Class", list(class_options))]
semester_pick = f3.selectbox("Semester", ["All"] + list(range(1, 11)))
if report_type == "students":
    subject_id = None
    f4.write("Subject filter does not apply to the student list.")
    status_pick = f5.selectbox("Status", ["All", "active", "inactive"])
else:
    subject_id = subject_options[f4.selectbox("Subject", list(subject_options))]
    status_pick = "All"

filters = {
    "department_id": department_id,
    "class_id": class_id,
    "semester": None if semester_pick == "All" else semester_pick,
    "subject_id": subject_id,
    "status": None if status_pick == "All" else status_pick,
}

if st.button("Generate report"):
    try:
        st.session_state["report"] = db_call(access.build_report, user, report_type, filters)
    except (ValidationError, AuthorizationError) as e:
        st.session_state.pop("report", None)
        st.error(str(e))
    except psycopg2.Error as e:
        st.session_state.pop("report", None)
        st.error(f"Database problem: {e}")

report = st.session_state.get("report")
if report is not None:
    st.divider()
    used = ", ".join(f"{k}={v}" for k, v in report.filters.items()) or "no filters"
    if report.row_count == 0:
        st.info(f"No records match these filters ({used}), so there is nothing to download.")
    else:
        st.success(f"{REPORT_LABELS.get(report.name.replace('_report', ''), report.name)}: "
                   f"{report.row_count} row(s). Filters: {used}.")
        st.dataframe(pd.DataFrame(report.rows).head(50))
        if report.row_count > 50:
            st.caption(f"Preview shows the first 50 rows. The CSV file contains all {report.row_count}.")
        st.download_button("Download CSV", data=report.csv_bytes, file_name=report.filename, mime="text/csv")
