"""Dashboard calculations. Pure functions: rows in, numbers out (no database, no Streamlit)."""
from typing import Optional

from app.validation import attendance_percentage, marks_percentage

# (label, lower bound inclusive, upper bound exclusive); last bucket includes 100
ATTENDANCE_BUCKETS = [
    ("0-50%", 0, 50), ("50-60%", 50, 60), ("60-70%", 60, 70),
    ("70-80%", 70, 80), ("80-90%", 80, 90), ("90-100%", 90, 100.0001),
]


def _mean(values: list) -> Optional[float]:
    return sum(values) / len(values) if values else None


# ---------- Attendance ----------
def student_attendance(att_rows: list) -> list:
    """Overall attendance per student: all attended sessions / all held sessions (all subjects)."""
    students = {}
    for row in att_rows:
        entry = students.setdefault(row["student_id"], {
            "student_id": row["student_id"], "student_code": row["student_code"], "name": row["name"],
            "class_name": row["class_name"], "semester": row["semester"], "attended": 0, "total_held": 0,
        })
        entry["attended"] += row["attended"]
        entry["total_held"] += row["total_held"]
    result = []
    for entry in students.values():
        entry["percentage"] = attendance_percentage(entry["attended"], entry["total_held"])
        result.append(entry)
    return sorted(result, key=lambda r: r["student_code"])


def attendance_summary(student_att: list, threshold: float) -> dict:
    """Average of the students' attendance percentages (every student counts equally)."""
    values = [s["percentage"] for s in student_att if s["percentage"] is not None]
    return {
        "average": _mean(values),
        "students_with_data": len(values),
        "below_threshold": sum(1 for v in values if v < threshold),
    }


def attendance_distribution(student_att: list) -> list:
    """How many students fall into each attendance range."""
    counts = {label: 0 for label, _, _ in ATTENDANCE_BUCKETS}
    for student in student_att:
        pct = student["percentage"]
        if pct is None:
            continue
        for label, low, high in ATTENDANCE_BUCKETS:
            if low <= pct < high:
                counts[label] += 1
                break
    return [{"range": label, "students": counts[label]} for label, _, _ in ATTENDANCE_BUCKETS]


# ---------- Marks ----------
def student_marks(marks_rows: list) -> list:
    """Overall marks per student: average of that student's subject averages (percent)."""
    students = {}
    for row in marks_rows:
        pct = marks_percentage(row["obtained_marks"], row["max_marks"])
        entry = students.setdefault(row["student_id"], {
            "student_id": row["student_id"], "student_code": row["student_code"], "name": row["name"],
            "class_name": row["class_name"], "semester": row["semester"], "by_subject": {},
        })
        entry["by_subject"].setdefault(row["subject_code"], []).append(pct)
    result = []
    for entry in students.values():
        subject_averages = [sum(p) / len(p) for p in entry.pop("by_subject").values()]
        entry["average_percentage"] = _mean(subject_averages)
        result.append(entry)
    return sorted(result, key=lambda r: r["student_code"])


def marks_extremes(marks_rows: list) -> Optional[dict]:
    """The single highest and lowest score (as percent of its maximum). None if no marks."""
    best = worst = None
    for row in marks_rows:
        pct = marks_percentage(row["obtained_marks"], row["max_marks"])
        item = {
            "student_code": row["student_code"], "name": row["name"], "subject_code": row["subject_code"],
            "assessment_name": row["assessment_name"], "obtained": row["obtained_marks"],
            "max_marks": row["max_marks"], "percentage": pct,
        }
        if best is None or pct > best["percentage"]:
            best = item
        if worst is None or pct < worst["percentage"]:
            worst = item
    return None if best is None else {"highest": best, "lowest": worst}


# ---------- Trends and support ----------
def semester_trends(student_att: list, student_marks_list: list) -> list:
    """Average attendance and average marks for each semester that has data."""
    semesters = {}
    for s in student_att:
        if s["percentage"] is not None:
            semesters.setdefault(s["semester"], {"att": [], "marks": []})["att"].append(s["percentage"])
    for s in student_marks_list:
        semesters.setdefault(s["semester"], {"att": [], "marks": []})["marks"].append(s["average_percentage"])
    return [
        {"semester": sem, "average_attendance": _mean(v["att"]), "average_marks": _mean(v["marks"])}
        for sem, v in sorted(semesters.items())
    ]


def students_needing_support(student_att: list, student_marks_list: list,
                             attendance_threshold: float, marks_threshold: float) -> list:
    """Indicator for follow-up (NOT a judgement): low attendance and/or low average marks.
    A student with no data for a measure is not flagged on that measure."""
    people = {}

    def entry_for(s):
        return people.setdefault(s["student_id"], {
            "student_id": s["student_id"], "student_code": s["student_code"], "name": s["name"],
            "class_name": s["class_name"], "attendance_percentage": None, "marks_percentage": None,
            "reasons": [],
        })

    for s in student_att:
        if s["percentage"] is not None:
            entry = entry_for(s)
            entry["attendance_percentage"] = s["percentage"]
            if s["percentage"] < attendance_threshold:
                entry["reasons"].append(f"Attendance {s['percentage']:.1f}% (below {attendance_threshold:g}%)")
    for s in student_marks_list:
        entry = entry_for(s)
        entry["marks_percentage"] = s["average_percentage"]
        if s["average_percentage"] < marks_threshold:
            entry["reasons"].append(f"Average marks {s['average_percentage']:.1f}% (below {marks_threshold:g}%)")

    flagged = [p for p in people.values() if p["reasons"]]
    for p in flagged:
        p["reasons"] = "; ".join(p["reasons"])
    return sorted(flagged, key=lambda p: p["student_code"])
