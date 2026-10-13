import sys
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
from app.services import reports, student_dashboard
from app.services.attendance_report import FLAG_LABELS
from app.services.charts import marks_trend_chart, student_attendance_chart
from app.ui_auth import require_login

st.set_page_config(page_title="My Dashboard", layout="wide")
user = require_login("student")

try:
    settings = get_settings()
    profile = db_call(access.my_profile, user)
    att_rows = db_call(access.my_attendance, user)
    marks_rows = db_call(access.my_marks, user)
except (ConfigError, psycopg2.Error, AuthorizationError) as e:
    st.error(user_message(e))
    st.stop()

threshold = settings.attendance_threshold
st.title("My Dashboard")
st.write(f"**{profile['name']}** ({profile['student_code']}) - {profile['department']} / "
         f"{profile['class_name']}, semester {profile['semester']}")
st.caption("You can only see your own records.")

# ---------------- Attendance ----------------
st.header("Attendance")
attendance = student_dashboard.attendance_for_student(att_rows, threshold)
if not attendance:
    st.info("No attendance has been recorded for you yet.")
else:
    low = student_dashboard.subjects_below_threshold(attendance)
    if low:
        names = ", ".join(f"{r['subject_code']} ({r['percentage']:.1f}%)" for r in low)
        st.warning(f"Your attendance is below {threshold:g}% in: {names}. "
                   "This is a warning only, not an official eligibility decision. "
                   "Please talk to your teacher.")
    else:
        st.success(f"Your attendance is at or above {threshold:g}% in every subject.")
    left, right = st.columns(2)
    with left:
        st.dataframe(pd.DataFrame([{
            "Subject": f"{r['subject_code']} - {r['subject_name']}",
            "Attended": r["attended"], "Held": r["total_held"],
            "Attendance %": None if r["percentage"] is None else round(r["percentage"], 1),
            "Flag": FLAG_LABELS[r["flag"]],
        } for r in attendance]))
    with right:
        st.plotly_chart(student_attendance_chart(attendance, threshold))

# ---------------- Marks ----------------
st.header("Marks")
if not marks_rows:
    st.info("No marks have been entered for you yet.")
else:
    left, right = st.columns(2)
    with left:
        st.subheader("Subject averages")
        st.dataframe(pd.DataFrame([{
            "Subject": f"{s['subject_code']} - {s['subject_name']}",
            "Assessments": s["assessments"],
            "Average %": round(s["average_percentage"], 1),
        } for s in student_dashboard.subject_marks_summary(marks_rows)]))
    with right:
        st.plotly_chart(marks_trend_chart(student_dashboard.trend_points(marks_rows)))
        st.caption("Assessments are shown in order of their date (or the order they were created).")
    st.subheader("All assessments")
    st.dataframe(pd.DataFrame([{
        "Subject": r["subject_code"], "Assessment": r["assessment_name"], "Date": r["assessment_date"],
        "Obtained": r["obtained_marks"], "Maximum": r["max_marks"], "Percentage": round(r["percentage"], 1),
    } for r in student_dashboard.marks_with_percentage(marks_rows)]))

# ---------------- Downloads ----------------
st.header("Download my reports")
downloads = [
    ("Subject summary (attendance + marks)", reports.student_summary_report(att_rows, marks_rows, threshold)),
    ("Attendance report", reports.student_attendance_report(att_rows, threshold)),
    ("Marks report", reports.student_marks_report(marks_rows)),
]
if not att_rows and not marks_rows:
    st.info("There is nothing to download yet because no attendance or marks are recorded for you.")
else:
    for label, report in downloads:
        if report.csv_bytes is None:
            st.write(f"{label}: no records yet.")
        else:
            st.download_button(f"Download: {label} (CSV)", data=report.csv_bytes,
                               file_name=report.filename, mime="text/csv", key=f"dl_{report.name}")
