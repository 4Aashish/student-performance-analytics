import io
import uuid
from datetime import date

import pytest

from app.repositories import marks_repository as repo
from app.repositories import student_repository as stu
from app.services.csv_utils import read_csv_required
from app.services.marks_analysis import subject_wise_performance
from app.services.marks_import import REQUIRED_COLUMNS, import_marks, validate_marks_against_database
from app.validation import ValidationError


def setup_class_with_students(cur, count=3):
    tag = uuid.uuid4().hex[:8]
    cur.execute("INSERT INTO departments (name) VALUES (%s) RETURNING id", (f"D{tag}",))
    dept = cur.fetchone()[0]
    cur.execute("INSERT INTO classes (department_id, name, semester) VALUES (%s,%s,3) RETURNING id", (dept, f"C{tag}"))
    cls = cur.fetchone()[0]
    cur.execute("INSERT INTO subjects (code, name, department_id, semester) VALUES (%s,'Subj',%s,3) RETURNING id",
                (f"SB{tag}", dept))
    subj = cur.fetchone()[0]
    ids = [stu.create_student(cur, f"M{tag}{n}", f"Student {n}", cls) for n in range(1, count + 1)]
    return {"tag": tag, "dept": dept, "cls": cls, "subj": subj, "students": ids, "subject_code": f"SB{tag}"}


def make_assessment(cur, s, name="Quiz", max_marks=30):
    return repo.create_assessment(cur, s["cls"], s["subj"], name, max_marks)


def test_create_assessment_and_list(db_cur):
    s = setup_class_with_students(db_cur)
    aid = repo.create_assessment(db_cur, s["cls"], s["subj"], "  Quiz 1 ", 30, date(2026, 8, 10))
    listed = repo.list_assessments(db_cur, s["cls"], s["subj"])
    assert [(a["id"], a["name"], a["max_marks"], a["marks_entered"]) for a in listed] == [(aid, "Quiz 1", 30.0, 0)]


def test_duplicate_assessment_raises_and_transaction_stays_usable(db_cur):
    s = setup_class_with_students(db_cur)
    make_assessment(db_cur, s, "Quiz")
    with pytest.raises(repo.DuplicateAssessmentError):
        make_assessment(db_cur, s, "Quiz")
    make_assessment(db_cur, s, "Quiz 2")  # still works
    assert len(repo.list_assessments(db_cur, s["cls"], s["subj"])) == 2


def test_invalid_assessments_rejected(db_cur):
    s = setup_class_with_students(db_cur)
    for bad_max in (0, -5, "abc", None, 10000, float("nan")):
        with pytest.raises(ValidationError):
            repo.create_assessment(db_cur, s["cls"], s["subj"], "Bad", bad_max)
    with pytest.raises(ValidationError):
        repo.create_assessment(db_cur, s["cls"], s["subj"], "   ", 30)
    other = setup_class_with_students(db_cur)
    with pytest.raises(ValidationError):  # subject of another department
        repo.create_assessment(db_cur, s["cls"], other["subj"], "Quiz", 30)


def test_save_marks_creates_updates_and_writes_history(db_cur):
    s = setup_class_with_students(db_cur)
    aid = make_assessment(db_cur, s)
    a, b, c = s["students"]
    assert repo.save_marks(db_cur, aid, {a: 25, b: 18.5}) == {"created": 2, "updated": 0, "unchanged": 0}
    assert repo.save_marks(db_cur, aid, {a: 25, b: 20, c: 30}) == {"created": 1, "updated": 1, "unchanged": 1}
    rows = {r["student_id"]: r["obtained_marks"] for r in repo.marks_for_assessment(db_cur, aid)}
    assert rows == {a: 25.0, b: 20.0, c: 30.0}
    history = repo.get_marks_history(db_cur, aid)
    updates = [h for h in history if h["action"] == "marks_update"]
    assert len(history) == 4                      # 3 creates + 1 update, unchanged writes nothing
    assert (updates[0]["old_marks"], updates[0]["new_marks"]) == ("18.50", "20.00")


def test_invalid_marks_save_nothing(db_cur):
    s = setup_class_with_students(db_cur)
    aid = make_assessment(db_cur, s)
    a, b, c = s["students"]
    with pytest.raises(ValidationError) as err:
        repo.save_marks(db_cur, aid, {a: 10, b: 31, c: -1})
    assert "cannot be more than" in str(err.value) and "cannot be negative" in str(err.value)
    assert all(r["obtained_marks"] is None for r in repo.marks_for_assessment(db_cur, aid))
    for bad in (None, "abc", float("nan")):
        with pytest.raises(ValidationError):
            repo.save_marks(db_cur, aid, {a: bad})


def test_save_marks_other_rules(db_cur):
    s = setup_class_with_students(db_cur)
    other = setup_class_with_students(db_cur)
    aid = make_assessment(db_cur, s)
    with pytest.raises(ValidationError):
        repo.save_marks(db_cur, aid, {})
    with pytest.raises(ValidationError):  # student from another class
        repo.save_marks(db_cur, aid, {other["students"][0]: 10})
    stu.update_student(db_cur, s["students"][0], status="inactive")
    with pytest.raises(ValidationError):
        repo.save_marks(db_cur, aid, {s["students"][0]: 10})
    with pytest.raises(repo.AssessmentNotFoundError):
        repo.save_marks(db_cur, 999999999, {s["students"][1]: 10})


def test_performance_from_database_rows(db_cur):
    s = setup_class_with_students(db_cur)
    a = s["students"][0]
    quiz = make_assessment(db_cur, s, "Quiz", 30)
    mid = make_assessment(db_cur, s, "Mid", 50)
    repo.save_marks(db_cur, quiz, {a: 15})   # 50%
    repo.save_marks(db_cur, mid, {a: 40})    # 80%
    performance = subject_wise_performance(repo.fetch_marks_rows(db_cur, s["cls"]))
    assert len(performance) == 1
    assert performance[0]["average_percentage"] == pytest.approx(65.0)
    assert len(repo.fetch_marks_rows(db_cur, s["cls"], s["subj"])) == 2


def _csv(s, rows):
    head = "student_code,subject_code,assessment_name,obtained_marks,max_marks\n"
    body = "".join(f"{code},{s['subject_code']},{name},{obtained},{mx}\n" for code, name, obtained, mx in rows)
    return read_csv_required(io.BytesIO((head + body).encode()), REQUIRED_COLUMNS)


def _codes(db_cur, s):
    return [r["student_code"] for r in stu.search_students(db_cur, class_id=s["cls"])]


def test_import_creates_assessments_marks_and_history(db_cur):
    s = setup_class_with_students(db_cur)
    codes = _codes(db_cur, s)
    rows = [(c, name, 20, mx) for c in codes for name, mx in (("Quiz", 30), ("Mid", 50))]
    result = import_marks(db_cur, _csv(s, rows))
    assert result.errors == [] and result.inserted == 6
    assessments = repo.list_assessments(db_cur, s["cls"], s["subj"])
    assert sorted((a["name"], a["max_marks"], a["marks_entered"]) for a in assessments) == [("Mid", 50.0, 3), ("Quiz", 30.0, 3)]
    assert len(repo.get_marks_history(db_cur, assessments[0]["id"])) == 3


def test_import_is_all_or_nothing(db_cur):
    s = setup_class_with_students(db_cur)
    codes = _codes(db_cur, s)
    result = import_marks(db_cur, _csv(s, [(codes[0], "Quiz", 20, 30), (codes[1], "Quiz", 31, 30)]))
    assert result.errors and result.inserted == 0
    assert repo.list_assessments(db_cur, s["cls"], s["subj"]) == []  # no assessment was created either


def test_import_into_existing_assessment_and_duplicates_flagged(db_cur):
    s = setup_class_with_students(db_cur)
    codes = _codes(db_cur, s)
    make_assessment(db_cur, s, "Quiz", 30)
    assert import_marks(db_cur, _csv(s, [(codes[0], "Quiz", 20, 30)])).inserted == 1
    again = validate_marks_against_database(db_cur, _csv(s, [(codes[0], "Quiz", 22, 30)]))
    assert "already exist" in again.errors[0].message
    wrong_max = validate_marks_against_database(db_cur, _csv(s, [(codes[1], "Quiz", 22, 40)]))
    assert "differs from the existing assessment" in wrong_max.errors[0].message
