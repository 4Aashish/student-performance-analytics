"""Builds CSV reports from rows (no database, no Streamlit).

CSV safety: a text cell that starts with = + - @ (or a tab / carriage return) could run as a formula when
the file is opened in Excel. Such cells get a leading apostrophe, so a name can never become a formula.
The file starts with a UTF-8 BOM so Excel shows Hindi and other non-English names correctly.
"""
import csv
import io
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from app.services.attendance_report import FLAG_LABELS, build_attendance_report
from app.validation import marks_percentage

FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")
FLAG_HEADER = "Flag (warning only, not an eligibility decision)"


@dataclass
class ReportResult:
    name: str
    filename: str
    row_count: int
    headers: list
    rows: list                       # list of dicts keyed by header (used for the on-screen preview)
    csv_bytes: Optional[bytes]       # None when there are no records
    filters: dict = field(default_factory=dict)


def safe_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return str(round(value, 2))
    if isinstance(value, date):
        return value.isoformat()
    text = str(value)
    return "'" + text if text.startswith(FORMULA_STARTS) else text


def to_csv_bytes(columns: list, rows: list) -> bytes:
    """columns = [(key, header), ...]; rows = list of dicts."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([header for _, header in columns])
    for row in rows:
        writer.writerow([safe_cell(row.get(key)) for key, _ in columns])
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def make_result(name: str, columns: list, rows: list, filters: Optional[dict] = None) -> ReportResult:
    headers = [header for _, header in columns]
    preview = [{header: row.get(key) for key, header in columns} for row in rows]
    return ReportResult(
        name=name,
        filename=f"{name}_{date.today().isoformat()}.csv",
        row_count=len(rows),
        headers=headers,
        rows=preview,
        csv_bytes=to_csv_bytes(columns, rows) if rows else None,
        filters=dict(filters or {}),
    )


# ---------------- Staff reports ----------------
def students_report(rows: list, filters: Optional[dict] = None) -> ReportResult:
    columns = [("student_code", "Student ID"), ("name", "Name"), ("department", "Department"),
               ("class_name", "Class"), ("semester", "Semester"), ("status", "Status")]
    return make_result("students_report", columns, rows, filters)


def attendance_report(rows: list, threshold: float, filters: Optional[dict] = None) -> ReportResult:
    """rows: one per student and subject with attended and total_held."""
    enriched = [{**r, "flag_label": FLAG_LABELS[r["flag"]]} for r in build_attendance_report(rows, threshold)]
    columns = [("student_code", "Student ID"), ("name", "Name"), ("department", "Department"),
               ("class_name", "Class"), ("semester", "Semester"), ("subject_code", "Subject code"),
               ("subject_name", "Subject"), ("attended", "Attended"), ("total_held", "Held"),
               ("percentage", "Attendance %"), ("flag_label", FLAG_HEADER)]
    return make_result("attendance_report", columns, enriched, filters)


def marks_report(rows: list, filters: Optional[dict] = None) -> ReportResult:
    enriched = [{**r, "percentage": marks_percentage(r["obtained_marks"], r["max_marks"])} for r in rows]
    columns = [("student_code", "Student ID"), ("name", "Name"), ("department", "Department"),
               ("class_name", "Class"), ("semester", "Semester"), ("subject_code", "Subject code"),
               ("subject_name", "Subject"), ("assessment_name", "Assessment"), ("obtained_marks", "Obtained"),
               ("max_marks", "Maximum"), ("percentage", "Percentage")]
    return make_result("marks_report", columns, enriched, filters)


def performance_report(student_att: list, student_marks_list: list, support: list,
                       filters: Optional[dict] = None) -> ReportResult:
    """One row per student that has attendance or marks data."""
    people = {}
    for s in student_att:
        entry = people.setdefault(s["student_id"], {"student_code": s["student_code"], "name": s["name"],
                                                    "class_name": s["class_name"], "semester": s["semester"]})
        entry["attendance_percentage"] = s["percentage"]
    for s in student_marks_list:
        entry = people.setdefault(s["student_id"], {"student_code": s["student_code"], "name": s["name"],
                                                    "class_name": s["class_name"], "semester": s["semester"]})
        entry["marks_percentage"] = s["average_percentage"]
    reasons = {p["student_id"]: p["reasons"] for p in support}
    rows = []
    for student_id, entry in people.items():
        entry["needs_support"] = student_id in reasons
        entry["reasons"] = reasons.get(student_id, "")
        rows.append(entry)
    rows.sort(key=lambda r: r["student_code"])
    columns = [("student_code", "Student ID"), ("name", "Name"), ("class_name", "Class"),
               ("semester", "Semester"), ("attendance_percentage", "Overall attendance %"),
               ("marks_percentage", "Average marks %"),
               ("needs_support", "May need support (indicator only)"), ("reasons", "Reason")]
    return make_result("performance_report", columns, rows, filters)


# ---------------- A student's own reports ----------------
def student_attendance_report(att_rows: list, threshold: float) -> ReportResult:
    enriched = [{**r, "flag_label": FLAG_LABELS[r["flag"]]} for r in build_attendance_report(att_rows, threshold)]
    columns = [("subject_code", "Subject code"), ("subject_name", "Subject"), ("attended", "Attended"),
               ("total_held", "Held"), ("percentage", "Attendance %"), ("flag_label", FLAG_HEADER)]
    return make_result("my_attendance_report", columns, enriched)


def student_marks_report(marks_rows: list) -> ReportResult:
    enriched = [{**r, "percentage": marks_percentage(r["obtained_marks"], r["max_marks"])} for r in marks_rows]
    columns = [("subject_code", "Subject code"), ("subject_name", "Subject"), ("assessment_name", "Assessment"),
               ("assessment_date", "Date"), ("obtained_marks", "Obtained"), ("max_marks", "Maximum"),
               ("percentage", "Percentage")]
    return make_result("my_marks_report", columns, enriched)


def student_summary_report(att_rows: list, marks_rows: list, threshold: float) -> ReportResult:
    """One row per subject: attendance and average marks together."""
    subjects = {}
    for r in build_attendance_report(att_rows, threshold):
        subjects.setdefault(r["subject_code"], {"subject_code": r["subject_code"], "subject_name": r["subject_name"]}).update(
            attended=r["attended"], total_held=r["total_held"], percentage=r["percentage"],
            flag_label=FLAG_LABELS[r["flag"]])
    per_subject = {}
    for r in marks_rows:
        per_subject.setdefault(r["subject_code"], {"name": r["subject_name"], "values": []})["values"].append(
            marks_percentage(r["obtained_marks"], r["max_marks"]))
    for code, info in per_subject.items():
        entry = subjects.setdefault(code, {"subject_code": code, "subject_name": info["name"]})
        entry["assessments"] = len(info["values"])
        entry["average_marks"] = sum(info["values"]) / len(info["values"])
    rows = [subjects[code] for code in sorted(subjects)]
    columns = [("subject_code", "Subject code"), ("subject_name", "Subject"), ("attended", "Attended"),
               ("total_held", "Held"), ("percentage", "Attendance %"), ("flag_label", FLAG_HEADER),
               ("assessments", "Assessments"), ("average_marks", "Average marks %")]
    return make_result("my_subject_summary", columns, rows)
