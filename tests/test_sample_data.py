import pandas as pd
from scripts.generate_sample_data import generate


def test_generation_is_reproducible(tmp_path):
    generate(tmp_path / "a", seed=1)
    generate(tmp_path / "b", seed=1)
    a = (tmp_path / "a" / "marks.csv").read_text()
    b = (tmp_path / "b" / "marks.csv").read_text()
    assert a == b


def test_marks_within_bounds(tmp_path):
    generate(tmp_path)
    marks = pd.read_csv(tmp_path / "marks.csv")
    assert (marks["obtained_marks"] >= 0).all()
    assert (marks["obtained_marks"] <= marks["max_marks"]).all()
    assert (marks["max_marks"] > 0).all()


def test_no_duplicate_attendance(tmp_path):
    generate(tmp_path)
    att = pd.read_csv(tmp_path / "attendance.csv")
    key = ["student_code", "subject_code", "session_date", "session_no"]
    assert not att.duplicated(subset=key).any()


def test_student_codes_unique_and_no_missing(tmp_path):
    generate(tmp_path)
    st = pd.read_csv(tmp_path / "students.csv")
    assert st["student_code"].is_unique
    assert not st.isnull().any().any()
