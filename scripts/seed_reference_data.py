"""Creates the department, classes and subjects that the sample CSVs refer to.
Safe to run many times.   Run:  python -m scripts.seed_reference_data
"""
from app.db.connection import transaction
from scripts.generate_sample_data import CLASSES

DEPARTMENT = "CSE"


def seed() -> dict:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO departments (name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (DEPARTMENT,))
            cur.execute("SELECT id FROM departments WHERE name = %s", (DEPARTMENT,))
            dept_id = cur.fetchone()[0]
            for class_name, info in CLASSES.items():
                cur.execute(
                    "INSERT INTO classes (department_id, name, semester) VALUES (%s, %s, %s) "
                    "ON CONFLICT (department_id, name) DO NOTHING",
                    (dept_id, class_name, info["semester"]),
                )
                for code, name in info["subjects"]:
                    cur.execute(
                        "INSERT INTO subjects (code, name, department_id, semester) VALUES (%s, %s, %s, %s) "
                        "ON CONFLICT (code) DO NOTHING",
                        (code, name, dept_id, info["semester"]),
                    )
            cur.execute("SELECT count(*) FROM classes")
            classes = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM subjects")
            subjects = cur.fetchone()[0]
    return {"classes": classes, "subjects": subjects}


if __name__ == "__main__":
    counts = seed()
    print(f"Reference data ready: {counts['classes']} classes, {counts['subjects']} subjects in the database.")
