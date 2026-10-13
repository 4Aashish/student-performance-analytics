import io
import uuid

import pytest

from app.repositories import student_repository as repo
from app.services.student_import import import_students, read_students_csv, validate_against_database
from app.validation import ValidationError


def make_class(cur):
    tag = uuid.uuid4().hex[:8]
    cur.execute("INSERT INTO departments (name) VALUES (%s) RETURNING id", (f"D{tag}",))
    dept = cur.fetchone()[0]
    cur.execute("INSERT INTO classes (department_id, name, semester) VALUES (%s,%s,3) RETURNING id", (dept, f"C{tag}"))
    return {"tag": tag, "dept_name": f"D{tag}", "class_name": f"C{tag}", "class_id": cur.fetchone()[0]}


def csv_df(text):
    return read_students_csv(io.BytesIO(text.encode("utf-8")))


def test_create_and_search_student(db_cur):
    c = make_class(db_cur)
    sid = repo.create_student(db_cur, f"R{c['tag']}1", "  Riya Sharma  ", c["class_id"])
    found = repo.search_students(db_cur, text="riya", class_id=c["class_id"])
    assert [s["id"] for s in found] == [sid]
    assert found[0]["name"] == "Riya Sharma"
    assert found[0]["status"] == "active"


def test_duplicate_student_code_raises_and_transaction_stays_usable(db_cur):
    c = make_class(db_cur)
    repo.create_student(db_cur, f"R{c['tag']}1", "A", c["class_id"])
    with pytest.raises(repo.DuplicateStudentError):
        repo.create_student(db_cur, f"R{c['tag']}1", "B", c["class_id"])
    repo.create_student(db_cur, f"R{c['tag']}2", "C", c["class_id"])  # still works
    assert len(repo.search_students(db_cur, class_id=c["class_id"])) == 2


def test_create_rejects_empty_fields_and_bad_status(db_cur):
    c = make_class(db_cur)
    with pytest.raises(ValidationError):
        repo.create_student(db_cur, "  ", "A", c["class_id"])
    with pytest.raises(ValidationError):
        repo.create_student(db_cur, f"R{c['tag']}1", "   ", c["class_id"])
    with pytest.raises(ValidationError):
        repo.create_student(db_cur, f"R{c['tag']}1", "A", c["class_id"], status="banned")


def test_update_student_and_missing_student(db_cur):
    c = make_class(db_cur)
    sid = repo.create_student(db_cur, f"R{c['tag']}1", "Old", c["class_id"])
    repo.update_student(db_cur, sid, name="New", status="inactive")
    found = repo.search_students(db_cur, status="inactive", class_id=c["class_id"])
    assert found[0]["name"] == "New"
    with pytest.raises(repo.StudentNotFoundError):
        repo.update_student(db_cur, 999999999, name="X")
    with pytest.raises(ValidationError):
        repo.update_student(db_cur, sid, name="  ")


def test_search_filters_and_wildcard_characters_are_literal(db_cur):
    c = make_class(db_cur)
    repo.create_student(db_cur, f"R{c['tag']}1", "Plain", c["class_id"])
    repo.create_student(db_cur, f"R{c['tag']}2", "100% Sure", c["class_id"], status="inactive")
    assert len(repo.search_students(db_cur, class_id=c["class_id"], semester=3)) == 2
    assert len(repo.search_students(db_cur, class_id=c["class_id"], semester=4)) == 0
    assert len(repo.search_students(db_cur, class_id=c["class_id"], status="inactive")) == 1
    assert len(repo.search_students(db_cur, text="%", class_id=c["class_id"])) == 1  # only the name with a real '%'


def test_count_students(db_cur):
    c = make_class(db_cur)
    before_all = repo.count_students(db_cur)
    before_active = repo.count_students(db_cur, status="active")
    repo.create_student(db_cur, f"R{c['tag']}1", "A", c["class_id"])
    repo.create_student(db_cur, f"R{c['tag']}2", "B", c["class_id"], status="inactive")
    assert repo.count_students(db_cur) == before_all + 2
    assert repo.count_students(db_cur, status="active") == before_active + 1


def test_import_is_all_or_nothing(db_cur):
    c = make_class(db_cur)
    head = "student_code,name,class_name,department,semester,status\n"
    good = f"I{c['tag']}1,A,{c['class_name']},{c['dept_name']},3,active\n"
    bad = f"I{c['tag']}2,B,NoSuchClass,{c['dept_name']},3,active\n"
    result = import_students(db_cur, csv_df(head + good + bad))
    assert result.errors and result.inserted == 0
    assert repo.search_students(db_cur, class_id=c["class_id"]) == []  # good row was NOT inserted either


def test_import_valid_file_inserts_everything(db_cur):
    c = make_class(db_cur)
    head = "student_code,name,class_name,department,semester\n"
    body = "".join(f"I{c['tag']}{n},S{n},{c['class_name']},{c['dept_name']},3\n" for n in range(1, 6))
    result = import_students(db_cur, csv_df(head + body))
    assert result.errors == [] and result.inserted == 5
    assert len(repo.search_students(db_cur, class_id=c["class_id"])) == 5


def test_import_same_file_twice_flags_existing(db_cur):
    c = make_class(db_cur)
    text = ("student_code,name,class_name,department,semester\n"
            f"I{c['tag']}1,A,{c['class_name']},{c['dept_name']},3\n")
    assert import_students(db_cur, csv_df(text)).inserted == 1
    second = validate_against_database(db_cur, csv_df(text))
    assert "already exists" in second.errors[0].message
