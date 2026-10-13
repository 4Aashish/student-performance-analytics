import io
import uuid
from datetime import date, timedelta

import pytest

from app.repositories import attendance_repository as repo
from app.repositories import student_repository as stu
from app.services.attendance_import import REQUIRED_COLUMNS, import_attendance, validate_attendance_against_database
from app.services.attendance_report import build_attendance_report
from app.services.csv_utils import read_csv_required
from app.validation import ValidationError

D1, D2, D3 = date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)


def setup_class_with_students(cur, count=3):
    tag = uuid.uuid4().hex[:8]
    cur.execute("INSERT INTO departments (name) VALUES (%s) RETURNING id", (f"D{tag}",))
    dept = cur.fetchone()[0]
    cur.execute("INSERT INTO classes (department_id, name, semester) VALUES (%s,%s,3) RETURNING id", (dept, f"C{tag}"))
    cls = cur.fetchone()[0]
    cur.execute("INSERT INTO subjects (code, name, department_id, semester) VALUES (%s,'Subj',%s,3) RETURNING id",
                (f"SB{tag}", dept))
    subj = cur.fetchone()[0]
    ids = [stu.create_student(cur, f"A{tag}{n}", f"Student {n}", cls) for n in range(1, count + 1)]
    return {"tag": tag, "dept": dept, "cls": cls, "subj": subj, "students": ids, "subject_code": f"SB{tag}"}


def all_present(ids):
    return {i: "present" for i in ids}


def test_subjects_listed_for_class(db_cur):
    s = setup_class_with_students(db_cur)
    assert [x["id"] for x in repo.list_subjects_for_class(db_cur, s["cls"])] == [s["subj"]]


def test_save_attendance_and_summary_counts(db_cur):
    s = setup_class_with_students(db_cur)
    a, b, c = s["students"]
    repo.save_attendance(db_cur, s["cls"], s["subj"], D1, 1, {a: "present", b: "present", c: "absent"})
    repo.save_attendance(db_cur, s["cls"], s["subj"], D2, 1, {a: "present", b: "absent", c: "absent"})
    rows = {r["student_id"]: r for r in repo.attendance_summary(db_cur, s["cls"], s["subj"])}
    assert (rows[a]["attended"], rows[a]["total_held"]) == (2, 2)
    assert (rows[b]["attended"], rows[b]["total_held"]) == (1, 2)
    assert (rows[c]["attended"], rows[c]["total_held"]) == (0, 2)
    report = {r["student_id"]: r for r in build_attendance_report(list(rows.values()), 75)}
    assert report[b]["percentage"] == 50.0 and report[b]["flag"] == "below_threshold"


def test_zero_sessions_gives_no_data_not_an_error(db_cur):
    s = setup_class_with_students(db_cur)
    report = build_attendance_report(repo.attendance_summary(db_cur, s["cls"], s["subj"]), 75)
    assert len(report) == 3
    assert all(r["total_held"] == 0 and r["percentage"] is None and r["flag"] == "no_data" for r in report)


def test_duplicate_session_rejected_unless_overwrite(db_cur):
    s = setup_class_with_students(db_cur)
    a = s["students"][0]
    repo.save_attendance(db_cur, s["cls"], s["subj"], D1, 1, {a: "present"})
    with pytest.raises(repo.DuplicateSessionError):
        repo.save_attendance(db_cur, s["cls"], s["subj"], D1, 1, {a: "absent"})
    result = repo.save_attendance(db_cur, s["cls"], s["subj"], D1, 1, {a: "absent"}, overwrite=True)
    assert result["created"] is False
    assert repo.get_session_statuses(db_cur, s["cls"], s["subj"], D1, 1) == {a: "absent"}


def test_second_lecture_same_day_is_allowed(db_cur):
    s = setup_class_with_students(db_cur)
    a = s["students"][0]
    repo.save_attendance(db_cur, s["cls"], s["subj"], D1, 1, {a: "present"})
    repo.save_attendance(db_cur, s["cls"], s["subj"], D1, 2, {a: "absent"})
    assert len(repo.list_sessions(db_cur, s["cls"], s["subj"])) == 2


def test_get_session_statuses_none_when_missing(db_cur):
    s = setup_class_with_students(db_cur)
    assert repo.get_session_statuses(db_cur, s["cls"], s["subj"], D3, 1) is None


def test_invalid_input_rejected(db_cur):
    s = setup_class_with_students(db_cur)
    a = s["students"][0]
    cls, subj = s["cls"], s["subj"]
    with pytest.raises(ValidationError):
        repo.save_attendance(db_cur, cls, subj, date.today() + timedelta(days=1), 1, {a: "present"})
    with pytest.raises(ValidationError):
        repo.save_attendance(db_cur, cls, subj, D1, 0, {a: "present"})
    with pytest.raises(ValidationError):
        repo.save_attendance(db_cur, cls, subj, D1, 1, {a: "late"})
    with pytest.raises(ValidationError):
        repo.save_attendance(db_cur, cls, subj, D1, 1, {})
    with pytest.raises(ValidationError):
        repo.save_attendance(db_cur, cls, subj, D1, 1, {999999999: "present"})


def test_inactive_student_and_foreign_subject_rejected(db_cur):
    s = setup_class_with_students(db_cur)
    a = s["students"][0]
    stu.update_student(db_cur, a, status="inactive")
    with pytest.raises(ValidationError):
        repo.save_attendance(db_cur, s["cls"], s["subj"], D1, 1, {a: "present"})
    other = setup_class_with_students(db_cur)
    with pytest.raises(ValidationError):  # subject of another department
        repo.save_attendance(db_cur, s["cls"], other["subj"], D1, 1, {s["students"][1]: "present"})


def test_student_from_another_class_rejected(db_cur):
    s = setup_class_with_students(db_cur)
    other = setup_class_with_students(db_cur)
    with pytest.raises(ValidationError):
        repo.save_attendance(db_cur, s["cls"], s["subj"], D1, 1, {other["students"][0]: "present"})


def _csv(s, rows):
    head = "student_code,subject_code,session_date,session_no,status\n"
    body = "".join(f"{code},{s['subject_code']},{day},{no},{status}\n" for code, day, no, status in rows)
    return read_csv_required(io.BytesIO((head + body).encode()), REQUIRED_COLUMNS)


def _codes(db_cur, s):
    return [r["student_code"] for r in stu.search_students(db_cur, class_id=s["cls"])]


def test_import_valid_creates_sessions_and_records(db_cur):
    s = setup_class_with_students(db_cur)
    codes = _codes(db_cur, s)
    rows = [(c, d, 1, "present") for c in codes for d in ("2026-08-03", "2026-08-04")]
    result = import_attendance(db_cur, _csv(s, rows))
    assert result.errors == [] and result.inserted == 6
    assert len(repo.list_sessions(db_cur, s["cls"], s["subj"])) == 2


def test_import_is_all_or_nothing(db_cur):
    s = setup_class_with_students(db_cur)
    codes = _codes(db_cur, s)
    rows = [(codes[0], "2026-08-03", 1, "present"), (codes[1], "2026-08-03", 1, "late")]
    result = import_attendance(db_cur, _csv(s, rows))
    assert result.errors and result.inserted == 0
    assert repo.list_sessions(db_cur, s["cls"], s["subj"]) == []


def test_import_same_file_twice_flags_existing(db_cur):
    s = setup_class_with_students(db_cur)
    codes = _codes(db_cur, s)
    df = _csv(s, [(codes[0], "2026-08-03", 1, "present")])
    assert import_attendance(db_cur, df).inserted == 1
    second = validate_attendance_against_database(db_cur, df)
    assert "already in the database" in second.errors[0].message
