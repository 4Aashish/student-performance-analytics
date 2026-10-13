"""Normalized percentages and subject-wise performance (no database needed)."""
from app.validation import marks_percentage


def subject_wise_performance(rows: list) -> list:
    """rows: dicts with student_id, student_code, name, subject_code, subject_name,
    obtained_marks, max_marks. Returns one dict per student and subject:
    average of the normalized percentages (obtained / max * 100) of that student's assessments."""
    groups = {}
    for row in rows:
        pct = marks_percentage(row["obtained_marks"], row["max_marks"])
        key = (row["student_id"], row["subject_code"])
        group = groups.setdefault(key, {
            "student_id": row["student_id"], "student_code": row["student_code"], "name": row["name"],
            "subject_code": row["subject_code"], "subject_name": row["subject_name"], "percentages": [],
        })
        group["percentages"].append(pct)

    result = []
    for group in groups.values():
        percentages = group.pop("percentages")
        group["assessments"] = len(percentages)
        group["average_percentage"] = sum(percentages) / len(percentages)
        result.append(group)
    return sorted(result, key=lambda r: (r["subject_code"], r["student_code"]))


def subject_summary(performance: list) -> list:
    """Per subject: number of students and the average / highest / lowest of the student averages."""
    by_subject = {}
    for row in performance:
        entry = by_subject.setdefault(row["subject_code"], {"subject_name": row["subject_name"], "values": []})
        entry["values"].append(row["average_percentage"])
    summary = []
    for code in sorted(by_subject):
        values = by_subject[code]["values"]
        summary.append({
            "subject_code": code,
            "subject_name": by_subject[code]["subject_name"],
            "students": len(values),
            "average": sum(values) / len(values),
            "highest": max(values),
            "lowest": min(values),
        })
    return summary
