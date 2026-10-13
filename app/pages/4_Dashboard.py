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
from app.services import analytics
from app.services.charts import attendance_distribution_chart, semester_trend_chart, subject_marks_chart
from app.services.marks_analysis import subject_summary, subject_wise_performance
from app.ui_auth import require_login

st.set_page_config(page_title="Analytics Dashboard", layout="wide")
user = require_login("admin", "teacher")
st.title("Analytics Dashboard")
st.caption("Every number below is calculated from the database. "
           + ("You see the whole institution." if user.role == "admin"
              else "You see only the classes and subjects assigned to you."))

try:
    settings = get_settings()
    departments = db_call(access.list_departments, user)
    classes = db_call(access.list_classes, user)
    subjects = db_call(access.list_all_subjects, user)
except (ConfigError, psycopg2.Error, AuthorizationError) as e:
    st.error(user_message(e))
    st.stop()

if user.role == "teacher" and not classes:
    st.info("No classes are assigned to you yet. Please ask the administrator.")
    st.stop()

# ---------------- Filters ----------------
f1, f2, f3, f4 = st.columns(4)
dept_options = {"All": None, **{d["name"]: d["id"] for d in departments}}
class_options = {"All": None, **{f"{c['department']} / {c['class_name']}": c["id"] for c in classes}}
subject_options = {"All": None, **{f"{s['code']} - {s['name']}": s["id"] for s in subjects}}
semester_pick = f3.selectbox("Semester", ["All"] + list(range(1, 11)))
filters = {
    "department_id": dept_options[f1.selectbox("Department", list(dept_options))],
    "class_id": class_options[f2.selectbox("Class", list(class_options))],
    "semester": None if semester_pick == "All" else semester_pick,
    "subject_id": subject_options[f4.selectbox("Subject", list(subject_options))],
}
filters = {k: v for k, v in filters.items() if v is not None}

# ---------------- Data from the database (through the security layer) ----------------
try:
    active_students = db_call(access.dashboard_student_count, user, filters)
    att_rows = db_call(access.dashboard_attendance_rows, user, filters)
    marks_rows = db_call(access.dashboard_marks_rows, user, filters)
except AuthorizationError as e:
    st.error(str(e))
    st.stop()

student_att = analytics.student_attendance(att_rows)
student_marks = analytics.student_marks(marks_rows)
att_totals = analytics.attendance_summary(student_att, settings.attendance_threshold)
overall_marks = [s["average_percentage"] for s in student_marks]
support = analytics.students_needing_support(
    student_att, student_marks, settings.attendance_threshold, settings.support_marks_threshold)

k1, k2, k3, k4 = st.columns(4)
k1.metric("Total active students", active_students)
k2.metric("Average attendance", "-" if att_totals["average"] is None else f"{att_totals['average']:.1f}%")
k3.metric("Average marks", "-" if not overall_marks else f"{sum(overall_marks) / len(overall_marks):.1f}%")
k4.metric("Students needing support", len(support))

if not att_rows and not marks_rows:
    st.info("No attendance or marks match these filters yet.")
    st.stop()

st.divider()
left, right = st.columns(2)
with left:
    if marks_rows:
        st.plotly_chart(subject_marks_chart(subject_summary(subject_wise_performance(marks_rows))))
        st.caption("Subject average = average of each student's average (percent of maximum marks).")
    else:
        st.info("No marks for these filters.")
with right:
    extremes = analytics.marks_extremes(marks_rows)
    if extremes is None:
        st.info("No marks for these filters.")
    else:
        st.subheader("Highest and lowest scores")
        for label, key in (("Highest", "highest"), ("Lowest", "lowest")):
            item = extremes[key]
            st.metric(f"{label}: {item['student_code']} ({item['subject_code']}, {item['assessment_name']})",
                      f"{item['percentage']:.1f}%")
            st.caption(f"{item['obtained']:g} out of {item['max_marks']:g}")

st.divider()
left, right = st.columns(2)
with left:
    if student_att:
        st.plotly_chart(attendance_distribution_chart(analytics.attendance_distribution(student_att)))
        st.caption("Each student's attendance = all attended sessions / all held sessions, over all subjects. "
                   f"Students below {settings.attendance_threshold:g}%: {att_totals['below_threshold']} "
                   "(a warning only, not an official eligibility decision).")
    else:
        st.info("No attendance for these filters.")
with right:
    trends = analytics.semester_trends(student_att, student_marks)
    if trends:
        st.plotly_chart(semester_trend_chart(trends))
        st.caption("Compares the semesters that exist in the database. With one academic year of data this shows "
                   "differences between classes, not the progress of the same students over time.")
    else:
        st.info("No data for a semester comparison.")

st.divider()
st.subheader("Students who may need academic support")
if not support:
    st.success("No student is below the attendance or marks thresholds for these filters.")
else:
    st.dataframe(pd.DataFrame([{
        "Student ID": p["student_code"], "Name": p["name"], "Class": p["class_name"],
        "Attendance %": None if p["attendance_percentage"] is None else round(p["attendance_percentage"], 1),
        "Average marks %": None if p["marks_percentage"] is None else round(p["marks_percentage"], 1),
        "Reason": p["reasons"],
    } for p in support]))
st.caption(f"Thresholds: attendance below {settings.attendance_threshold:g}% or average marks below "
           f"{settings.support_marks_threshold:g}%. This list is a decision-support indicator to start a "
           "conversation, not a judgement about a student.")
