"""CSV import for attendance: validate everything first, then insert all or nothing."""
from datetime import date, datetime

import pandas as pd

from app.services.student_import import ImportResult, RowError
from app.validation import missing_required_fields

REQUIRED_COLUMNS = ["student_code", "subject_code", "session_date", "session_no", "status"]
VALID_STATUS = ("present", "absent")


def validate_attendance_df(df: pd.DataFrame, students: dict, subjects: dict, existing: set) -> ImportResult:
    """students: {code: {id, class_id, semester, department_id, status}}
    subjects: {code: {id, semester, department_id}}
    existing: {(student_id, subject_id, session_date, session_no)} already in the database."""
    records = df.to_dict("records")
    result = ImportResult(total_rows=len(records))

    def key_of(rec):
        return (rec.get("student_code", ""), rec.get("subject_code", ""),
                rec.get("session_date", ""), rec.get("session_no", ""))

    rows_by_key = {}
    for i, rec in enumerate(records):
        rows_by_key.setdefault(key_of(rec), []).append(i + 2)

    for i, rec in enumerate(records):
        row_no = i + 2
        code = rec.get("student_code", "")
        problems = []

        for missing in missing_required_fields(rec, REQUIRED_COLUMNS):
            problems.append(f"'{missing}' is required but empty.")

        student = students.get(code) if code else None
        if code and student is None:
            problems.append(f"Student '{code}' does not exist.")
        elif student is not None and student["status"] != "active":
            problems.append(f"Student '{code}' is inactive.")

        subject_code = rec.get("subject_code", "")
        subject = subjects.get(subject_code) if subject_code else None
        if subject_code and subject is None:
            problems.append(f"Subject '{subject_code}' does not exist.")
        elif subject is not None and student is not None and (
            subject["semester"] != student["semester"] or subject["department_id"] != student["department_id"]
        ):
            problems.append(f"Subject '{subject_code}' is not taught in the class of student '{code}'.")

        session_date = None
        date_raw = rec.get("session_date", "")
        if date_raw:
            try:
                session_date = datetime.strptime(date_raw, "%Y-%m-%d").date()
            except ValueError:
                problems.append(f"session_date must look like 2026-08-03 (YYYY-MM-DD), got '{date_raw}'.")
            else:
                if session_date > date.today():
                    problems.append(f"session_date {date_raw} is in the future.")

        session_no = None
        no_raw = rec.get("session_no", "")
        if no_raw:
            try:
                session_no = int(no_raw)
            except ValueError:
                problems.append(f"session_no must be a whole number, got '{no_raw}'.")
            else:
                if session_no < 1:
                    problems.append(f"session_no must be 1 or more, got {session_no}.")
                    session_no = None

        status = rec.get("status", "").lower()
        if rec.get("status", "") and status not in VALID_STATUS:
            problems.append(f"status must be present or absent, got '{rec.get('status', '')}'.")

        if len(rows_by_key[key_of(rec)]) > 1 and code and subject_code and date_raw and no_raw:
            rows = ", ".join(str(r) for r in rows_by_key[key_of(rec)])
            problems.append(f"Duplicate attendance entry for this student, subject, date and lecture (rows {rows}).")

        if student and subject and session_date and session_no:
            if (student["id"], subject["id"], session_date, session_no) in existing:
                problems.append("Attendance for this student, subject, date and lecture is already in the database.")

        if problems:
            result.errors.extend(RowError(row_no, code, p) for p in problems)
        else:
            result.valid_rows.append({
                "row_number": row_no, "student_code": code, "student_id": student["id"], "class_id": student["class_id"], "subject_id": subject["id"],
                "session_date": session_date, "session_no": session_no, "status": status,
            })
    return result


def _load_lookups(cur, df: pd.DataFrame):
    cur.execute(
        "SELECT s.student_code, s.id, s.class_id, c.semester, c.department_id, s.status "
        "FROM students s JOIN classes c ON c.id = s.class_id WHERE s.student_code = ANY(%s)",
        ([c for c in df["student_code"] if c],),
    )
    students = {code: {"id": sid, "class_id": cid, "semester": sem, "department_id": dep, "status": st}
                for code, sid, cid, sem, dep, st in cur.fetchall()}
    cur.execute("SELECT code, id, semester, department_id FROM subjects WHERE code = ANY(%s)",
                ([c for c in df["subject_code"] if c],))
    subjects = {code: {"id": sid, "semester": sem, "department_id": dep} for code, sid, sem, dep in cur.fetchall()}
    cur.execute(
        "SELECT ar.student_id, s.subject_id, s.session_date, s.session_no "
        "FROM attendance_records ar JOIN attendance_sessions s ON s.id = ar.session_id "
        "WHERE ar.student_id = ANY(%s)",
        ([v["id"] for v in students.values()],),
    )
    existing = {tuple(row) for row in cur.fetchall()}
    return students, subjects, existing


def validate_attendance_against_database(cur, df: pd.DataFrame) -> ImportResult:
    """Validates against the real database. Writes NOTHING."""
    students, subjects, existing = _load_lookups(cur, df)
    return validate_attendance_df(df, students, subjects, existing)


def import_attendance(cur, df: pd.DataFrame, created_by=None) -> ImportResult:
    """All or nothing: one bad row means NO attendance is inserted."""
    from psycopg2.extras import execute_values

    from app.repositories import attendance_repository as repo

    result = validate_attendance_against_database(cur, df)
    if result.errors:
        return result

    sessions = {}
    for row in result.valid_rows:
        key = (row["class_id"], row["subject_id"], row["session_date"], row["session_no"])
        sessions.setdefault(key, []).append(row)
    for key, rows in sessions.items():
        session_id = repo.get_or_create_session(cur, *key, created_by)
        execute_values(
            cur,
            "INSERT INTO attendance_records (session_id, student_id, status) VALUES %s",
            [(session_id, r["student_id"], r["status"]) for r in rows],
        )
    result.inserted = len(result.valid_rows)
    return result
