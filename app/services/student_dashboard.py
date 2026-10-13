"""Calculations for the student's own dashboard (no database, no Streamlit)."""
from app.services.attendance_report import build_attendance_report
from app.validation import marks_percentage


def attendance_for_student(att_rows: list, threshold: float) -> list:
    """att_rows from access.my_attendance. Adds percentage and flag."""
    return build_attendance_report(att_rows, threshold)


def subjects_below_threshold(report: list) -> list:
    return [r for r in report if r["flag"] == "below_threshold"]


def marks_with_percentage(marks_rows: list) -> list:
    return [{**r, "percentage": marks_percentage(r["obtained_marks"], r["max_marks"])} for r in marks_rows]


def subject_marks_summary(marks_rows: list) -> list:
    """Per subject: number of assessments and the average percentage."""
    groups = {}
    for r in marks_with_percentage(marks_rows):
        g = groups.setdefault(r["subject_code"], {"subject_code": r["subject_code"],
                                                  "subject_name": r["subject_name"], "values": []})
        g["values"].append(r["percentage"])
    return [{"subject_code": g["subject_code"], "subject_name": g["subject_name"],
             "assessments": len(g["values"]), "average_percentage": sum(g["values"]) / len(g["values"])}
            for _, g in sorted(groups.items())]


def trend_points(marks_rows: list) -> list:
    """Percentages in the order the rows arrive (the database sorts by date, then creation order).
    'step' counts the assessments of each subject: 1, 2, 3 ..."""
    steps, points = {}, []
    for r in marks_with_percentage(marks_rows):
        steps[r["subject_code"]] = steps.get(r["subject_code"], 0) + 1
        points.append({"subject_code": r["subject_code"], "assessment_name": r["assessment_name"],
                       "step": steps[r["subject_code"]], "percentage": r["percentage"]})
    return points
