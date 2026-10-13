# Student Performance Analytics System

A web application for colleges and schools that collects, validates, stores, analyses and visualises student
academic data: attendance, marks, subject-wise performance, student progress reports and CSV exports, with
separate access for **administrators, teachers and students**.

Built as a B.Tech CSE project by Aashish Sharma (THDC-Institute of Hydropower Engineering and Technology),
developed with AI assistance and reviewed and tested by the author.

> **All data in this repository is synthetic.** Do not load real student data until you have read
> [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) and [docs/SECURITY_REVIEW.md](docs/SECURITY_REVIEW.md).

## What it does

| Role | Can do |
|---|---|
| **Admin** | Manage user accounts, assign teachers to class + subject, add/edit/import students, take attendance and enter marks, see the whole dashboard, export CSV reports |
| **Teacher** | Only for the classes and subjects assigned to them: take attendance, create assessments, enter and correct marks (every change is logged), import CSV, see the dashboard, export reports |
| **Student** | Only their own records: attendance by subject with warnings, marks, performance trend, downloadable CSV reports |

Main features

* **Attendance**: per student, subject, date and lecture; duplicates are impossible; percentage = attended / held sessions;
  subjects with no sessions show "No sessions yet" (never a division error); a configurable warning threshold
  (default 75%) that is clearly a *warning*, not an eligibility decision.
* **Marks**: assessments with a maximum score; marks outside 0..maximum are rejected (in Python **and** by a database trigger);
  normalised percentages; subject-wise averages; full change history (old value -> new value, who, when).
* **Dashboard**: active students, average attendance, subject-wise average marks, highest and lowest scores, attendance
  distribution, semester comparison, students who may need academic support; filters by department, class, semester
  and subject. Every number is calculated from the database.
* **CSV import** (students, attendance, marks): all-or-nothing, every problem is reported with its row number, nothing is dropped silently.
* **CSV reports**: filters are applied before the file is built, teachers can only export their own data, every export is audited,
  spreadsheet formula injection is neutralised.
* **Security**: bcrypt password hashes, account lockout, session timeout, authorization enforced in one data-access layer
  (not only in the UI), append-only audit log. Details: [docs/SECURITY_REVIEW.md](docs/SECURITY_REVIEW.md).

## Technology

Python, Streamlit, Pandas, Plotly, PostgreSQL (psycopg2), bcrypt, pytest. Developed and tested on Windows 11 with
Python 3.13.9, PostgreSQL 18.6, Streamlit 1.65, pandas 3.0, Plotly 7.1, bcrypt 5.0 and pytest 9.1.

## Quick start (Windows)

You need Python and PostgreSQL installed (remember the PostgreSQL password you choose during installation).

```bat
git clone https://github.com/<your-github-name>/student-performance-analytics.git
cd student-performance-analytics
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

1. Open `.env` in a text editor and set `DB_PASSWORD=` to your PostgreSQL password (no spaces, no quotes).
2. Create an empty database called `student_analytics` (pgAdmin: Databases -> Create -> Database).
3. Then:

```bat
python -m app.db.init_db                 REM creates the 12 tables, constraints and triggers
python -m scripts.seed_reference_data    REM department, classes and subjects used by the sample data
python -m scripts.create_admin           REM asks for an admin username and password (typing is hidden)
streamlit run app\main.py
```

Open http://localhost:8501 and log in with the admin account you just created.
After the first setup you can also start the app by double-clicking `start_app.bat`.

### Load the sample data

Log in as admin, then use the **Import CSV** tab of each page, in this order:

1. **Students**: `data/sample/students.csv` (30 students, 2 of them inactive)
2. **Attendance**: `data/sample/attendance.csv` (840 records)
3. **Marks**: `data/sample/marks.csv` (168 marks, creates 12 assessments)
4. Open **Dashboard**.

The `*_invalid.csv` files in the same folder contain deliberate mistakes so you can see how errors are reported.
`python -m scripts.generate_sample_data` recreates the sample files (the data is random and synthetic).

### Try the other roles

On the **Users** page create a teacher account and assign it a class and subject (Teacher assignments tab), and a
student account linked to a student. Log out and log in as each of them. A walk-through with screenshots to take is in
[docs/DEMO.md](docs/DEMO.md).

## Tests

```bat
pytest                                                 REM all tests
pytest --cov=app --cov-report=term-missing             REM with coverage (pip install pytest-cov)
```

The tests need a running PostgreSQL (they use the database from `.env`, but run inside a transaction that is rolled
back, so your data is not changed; they need the `postgres` owner account because they apply the database schema inside that transaction).
At the end of Milestone 9 the author measured **340 passing tests and 91% line coverage** (12 October 2026).
The lines that are not covered are mostly the file-upload tabs of the pages, which the test tool cannot simulate;
they are covered by the manual checklist in [docs/TEST_CHECKLIST.md](docs/TEST_CHECKLIST.md).

## Project structure

```
app/
  main.py                 Home page: login, password change
  pages/                  Streamlit pages (Students, Attendance, Marks, Dashboard, Users, My Dashboard, Reports)
  ui_auth.py              Login/session helper used by every page
  security/               passwords, login + lockout, users, and access.py = the only door to the data
  repositories/           all SQL (students, attendance, marks, analytics)
  services/               CSV import, validation, calculations, reports, charts (no SQL)
  db/                     schema.sql, connection, init_db
  validation.py           shared rules (attendance %, marks checks)
  errors.py               safe error messages + log file
scripts/                  create_admin, seed_reference_data, generate_sample_data, backup_db, restore_db, role scripts
data/sample/              synthetic CSV files (valid and deliberately invalid)
tests/                    340+ automated tests
docs/                     architecture, database, deployment, demo, security review, manual test checklist
```

## Documentation

* [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): layers, request flow, design decisions (with diagrams)
* [docs/DATABASE.md](docs/DATABASE.md): tables, relationships, constraints, triggers, how to upgrade the schema
* [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md): backups, limited database user, what must be done before real data
* [docs/SECURITY_REVIEW.md](docs/SECURITY_REVIEW.md): findings, fixes and open items
* [docs/TEST_CHECKLIST.md](docs/TEST_CHECKLIST.md): manual tests
* [docs/DEMO.md](docs/DEMO.md): demo script and screenshots to take

## Known limitations

* **No screen to create departments, classes and subjects.** They are created with `scripts/seed_reference_data.py`
  (for the sample data) or directly in pgAdmin. An admin screen for them is the next planned feature.
* No HTTPS, no e-mail password reset, no per-IP rate limiting; sessions end when the browser page is refreshed.
  The full list of open security items is in [docs/SECURITY_REVIEW.md](docs/SECURITY_REVIEW.md).
* The app connects as the PostgreSQL superuser unless you create the limited role (see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)).
* Schema upgrades use one idempotent script (`python -m app.db.init_db`), not a versioned migration tool.
* Lists show at most 1000 students; CSV files are limited to 20,000 rows and 5 MB.
* If a student is moved to another class, old attendance and marks stay with the old class and are not shown in the dashboards.
* No legal or privacy assessment has been done (for example India's Digital Personal Data Protection Act, 2023).

## Future enhancements

* Admin screens for departments, classes and subjects
* **Academic risk prediction (not implemented, deliberately).** The sample data cannot support it: attendance and marks
  are generated independently at random (see `scripts/generate_sample_data.py`), so there is nothing real to learn, there are no
  legitimate outcome labels such as final results, and there are only 28 active students. A model trained on this would
  produce meaningless numbers. It should be added only with real historical, labelled data from past semesters, a
  time-based train/test split, protection against target leakage, a comparison with a simple baseline, and
  precision, recall, F1 and a confusion matrix reported from actual measurements. Its output must be shown as a
  decision-support indicator, never as a judgement about a student.
* Versioned database migrations (Alembic), Docker, continuous integration (GitHub Actions)
* Pagination, multiple academic years, notifications, password reset by e-mail, two-factor login

## Licence

No licence has been chosen yet. Add one (for example MIT) before others reuse the code.
