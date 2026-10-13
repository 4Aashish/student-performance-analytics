"""CSV import for marks: validate everything first, then insert all or nothing.
Assessments that do not exist yet are created from the CSV (name + max_marks)."""
import math

import pandas as pd

from app.services.student_import import ImportResult, RowError
from app.validation import ValidationError, missing_required_fields, validate_marks

REQUIRED_COLUMNS = ["student_code", "subject_code", "assessment_name", "obtained_marks", "max_marks"]
MAX_ALLOWED_MARKS = 9999.99
MAX_NAME_LEN = 100


def _positive_number(raw):
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def validate_marks_df(df: pd.DataFrame, students: dict, subjects: dict,
                      assessments: dict, existing_marks: set) -> ImportResult:
    """students: {code: {id, class_id, semester, department_id, status}}
    subjects: {code: {id, semester, department_id}}
    assessments (already in DB): {(class_id, subject_id, name): {id, max_marks}}
    existing_marks: {(assessment_id, student_id)} already in DB."""
    records = df.to_dict("records")
    result = ImportResult(total_rows=len(records))

    def assessment_key(rec):
        student = students.get(rec.get("student_code", ""))
        subject = subjects.get(rec.get("subject_code", ""))
        name = rec.get("assessment_name", "")
        if student and subject and name:
            return (student["class_id"], subject["id"], name)
        return None

    max_values = {}      # assessment -> set of max_marks used in this file
    rows_by_entry = {}   # (student, subject, assessment) -> row numbers
    for i, rec in enumerate(records):
        key = assessment_key(rec)
        mx = _positive_number(rec.get("max_marks", ""))
        if key and mx is not None:
            max_values.setdefault(key, set()).add(mx)
        entry = (rec.get("student_code", ""), rec.get("subject_code", ""), rec.get("assessment_name", ""))
        if all(entry):
            rows_by_entry.setdefault(entry, []).append(i + 2)

    for i, rec in enumerate(records):
        row_no = i + 2
        code = rec.get("student_code", "")
        subject_code = rec.get("subject_code", "")
        name = rec.get("assessment_name", "")
        obtained_raw, max_raw = rec.get("obtained_marks", ""), rec.get("max_marks", "")
        problems = []

        for missing in missing_required_fields(rec, REQUIRED_COLUMNS):
            problems.append(f"'{missing}' is required but empty.")

        student = students.get(code) if code else None
        if code and student is None:
            problems.append(f"Student '{code}' does not exist.")
        elif student is not None and student["status"] != "active":
            problems.append(f"Student '{code}' is inactive.")

        subject = subjects.get(subject_code) if subject_code else None
        if subject_code and subject is None:
            problems.append(f"Subject '{subject_code}' does not exist.")
        elif subject is not None and student is not None and (
            subject["semester"] != student["semester"] or subject["department_id"] != student["department_id"]
        ):
            problems.append(f"Subject '{subject_code}' is not taught in the class of student '{code}'.")

        if name and len(name) > MAX_NAME_LEN:
            problems.append(f"assessment_name is too long (maximum {MAX_NAME_LEN} characters).")

        # numbers
        numbers_ok = False
        if obtained_raw and max_raw:
            try:
                validate_marks(obtained_raw, max_raw)
                numbers_ok = True
            except ValidationError as e:
                problems.append(str(e))
        elif max_raw:
            try:
                validate_marks(0, max_raw)
            except ValidationError as e:
                problems.append(str(e))
        if max_raw and _positive_number(max_raw) is not None and _positive_number(max_raw) > MAX_ALLOWED_MARKS:
            problems.append(f"max_marks cannot be more than {MAX_ALLOWED_MARKS:g}.")
            numbers_ok = False

        key = assessment_key(rec)
        if key and len(max_values.get(key, ())) > 1:
            values = ", ".join(f"{v:g}" for v in sorted(max_values[key]))
            problems.append(f"Assessment '{name}' has different max_marks in this file ({values}).")

        entry = (code, subject_code, name)
        if all(entry) and len(rows_by_entry[entry]) > 1:
            rows = ", ".join(str(r) for r in rows_by_entry[entry])
            problems.append(f"Duplicate marks for this student, subject and assessment (rows {rows}).")

        existing_assessment = assessments.get(key) if key else None
        if existing_assessment is not None and student is not None:
            mx = _positive_number(max_raw)
            if mx is not None and mx != float(existing_assessment["max_marks"]):
                problems.append(
                    f"max_marks {mx:g} differs from the existing assessment '{name}' "
                    f"(max {float(existing_assessment['max_marks']):g})."
                )
            if (existing_assessment["id"], student["id"]) in existing_marks:
                problems.append("Marks for this student and assessment already exist. Edit them on the Marks page.")

        if problems:
            result.errors.extend(RowError(row_no, code, p) for p in problems)
        elif numbers_ok:
            result.valid_rows.append({
                "row_number": row_no, "student_code": code, "student_id": student["id"], "class_id": student["class_id"], "subject_id": subject["id"],
                "assessment_name": name, "obtained": float(obtained_raw), "max_marks": float(max_raw),
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
        "SELECT id, class_id, subject_id, name, max_marks FROM assessments "
        "WHERE class_id = ANY(%s) AND subject_id = ANY(%s)",
        (sorted({v["class_id"] for v in students.values()}), [v["id"] for v in subjects.values()]),
    )
    assessments = {(cid, sid, name): {"id": aid, "max_marks": float(mx)} for aid, cid, sid, name, mx in cur.fetchall()}
    cur.execute("SELECT assessment_id, student_id FROM marks WHERE assessment_id = ANY(%s)",
                ([a["id"] for a in assessments.values()],))
    existing_marks = {tuple(row) for row in cur.fetchall()}
    return students, subjects, assessments, existing_marks


def validate_marks_against_database(cur, df: pd.DataFrame) -> ImportResult:
    """Validates against the real database. Writes NOTHING."""
    return validate_marks_df(df, *_load_lookups(cur, df))


def import_marks(cur, df: pd.DataFrame, user_id=None) -> ImportResult:
    """All or nothing: one bad row means NO marks and NO assessments are inserted."""
    from psycopg2.extras import Json, execute_values

    from app.repositories.marks_repository import to_decimal

    result = validate_marks_against_database(cur, df)
    if result.errors:
        return result

    _, _, assessments, _ = _load_lookups(cur, df)
    assessment_ids = {}
    for row in result.valid_rows:
        key = (row["class_id"], row["subject_id"], row["assessment_name"])
        if key in assessment_ids:
            continue
        if key in assessments:
            assessment_ids[key] = assessments[key]["id"]
        else:
            cur.execute(
                "INSERT INTO assessments (class_id, subject_id, name, max_marks) VALUES (%s, %s, %s, %s) RETURNING id",
                (*key, to_decimal(row["max_marks"])),
            )
            assessment_ids[key] = cur.fetchone()[0]

    inserted = execute_values(
        cur,
        "INSERT INTO marks (assessment_id, student_id, obtained_marks, updated_by) VALUES %s "
        "RETURNING id, obtained_marks",
        [(assessment_ids[(r["class_id"], r["subject_id"], r["assessment_name"])],
          r["student_id"], to_decimal(r["obtained"]), user_id) for r in result.valid_rows],
        fetch=True,
    )
    execute_values(
        cur,
        "INSERT INTO audit_logs (user_id, action, table_name, record_id, old_value, new_value) VALUES %s",
        [(user_id, "marks_import", "marks", marks_id, None, Json({"obtained_marks": str(obtained)}))
         for marks_id, obtained in inserted],
    )
    result.inserted = len(result.valid_rows)
    return result
