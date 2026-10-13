"""Generates SYNTHETIC sample data (no real students). Same seed => same data."""
import csv
import random
import sys
from datetime import date, timedelta
from pathlib import Path

CLASSES = {
    "CSE-S3": {"semester": 3, "subjects": [
        ("CS301", "Data Structures"), ("CS302", "DBMS"), ("CS303", "Discrete Mathematics")]},
    "CSE-S5": {"semester": 5, "subjects": [
        ("CS501", "Operating Systems"), ("CS502", "Computer Networks"), ("CS503", "Software Engineering")]},
}
STUDENTS_PER_CLASS = 15
SESSIONS_PER_SUBJECT = 10
ASSESSMENTS = [("Internal-1", 30), ("Midterm", 50)]


def _weekdays(start: date, count: int):
    days, d = [], start
    while len(days) < count:
        if d.weekday() < 5:  # Monday-Friday
            days.append(d)
        d += timedelta(days=1)
    return days


def _write(path: Path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def generate(out_dir: Path, seed: int = 42) -> dict:
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    students, attendance, marks = [], [], []
    dates = _weekdays(date(2026, 8, 3), SESSIONS_PER_SUBJECT)

    for class_name, info in CLASSES.items():
        for n in range(1, STUDENTS_PER_CLASS + 1):
            code = f"{class_name.replace('-', '')}{n:03d}"
            # Last student of each class is inactive (to test status filters later)
            status = "inactive" if n == STUDENTS_PER_CLASS else "active"
            students.append([code, f"Student {code}", class_name, "CSE", info["semester"], status])
            if status != "active":
                continue

            attend_prob = rng.uniform(0.55, 0.98)
            ability = rng.uniform(0.45, 0.9)
            for subj_code, _ in info["subjects"]:
                for d in dates:
                    st_ = "present" if rng.random() < attend_prob else "absent"
                    attendance.append([code, subj_code, d.isoformat(), 1, st_])
                for a_name, a_max in ASSESSMENTS:
                    pct = min(1.0, max(0.2, rng.gauss(ability, 0.12)))
                    marks.append([code, subj_code, a_name, round(a_max * pct), a_max])

    _write(out_dir / "students.csv",
           ["student_code", "name", "class_name", "department", "semester", "status"], students)
    _write(out_dir / "attendance.csv",
           ["student_code", "subject_code", "session_date", "session_no", "status"], attendance)
    _write(out_dir / "marks.csv",
           ["student_code", "subject_code", "assessment_name", "obtained_marks", "max_marks"], marks)
    return {"students": len(students), "attendance": len(attendance), "marks": len(marks)}


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "data" / "sample"
    counts = generate(target)
    print(f"Sample data written to {target}")
    for k, v in counts.items():
        print(f"  {k}.csv: {v} rows")
    sys.exit(0)
