# Demo script and screenshots

About 10 minutes. Use the sample data (README: "Load the sample data") and create one teacher and one student account first.

## Demo script

1. **Login** (admin). Show a wrong password -> generic message. Mention lockout after 5 wrong passwords.
2. **Students** -> Import CSV -> upload `students_invalid.csv`: every problem is listed with its row number and nothing is imported. Then upload `students.csv`.
3. **Attendance** -> import `attendance.csv`. Open **Summary** (CSE / CSE-S3, CS301): percentages, "Below threshold (warning)" flags; point out the "not an eligibility decision" note.
4. **Marks** -> import `marks.csv`. Open **Enter / edit marks**, change a mark, open **History of changes**. Try a mark above the maximum: "Nothing was saved".
5. **Dashboard**: metrics, subject-wise chart, attendance distribution, semester chart, "students who may need support". Change the Semester filter.
6. **Reports**: generate an attendance report, download it, open it in Excel. Generate one with no records: "nothing to download".
7. **Users**: show the teacher account and its assignment. **Log out**, log in as the **teacher**: only the assigned class and subject appear, Users page says "no permission".
8. Log in as the **student**: **My Dashboard** with attendance warnings, marks trend and downloads; every other page is refused.
9. (Optional) pgAdmin: `SELECT created_at, user_id, action, table_name, new_value FROM audit_logs ORDER BY id DESC LIMIT 20;` and show that `UPDATE audit_logs ...` is refused.

## Screenshots to take

Save them in `docs/screenshots/` and then link them from the README. Use sample data only (no real names).

| File name | What to show |
|---|---|
| `01-login.png` | Login form |
| `02-import-errors.png` | Students import with the list of problems (invalid CSV) |
| `03-attendance-summary.png` | Attendance summary with warning flags |
| `04-marks-history.png` | Marks entry and the history of changes |
| `05-dashboard.png` | Dashboard (whole page) |
| `06-reports.png` | Reports page with a preview |
| `07-teacher-view.png` | Students page as a teacher (only assigned classes) |
| `08-student-dashboard.png` | My Dashboard as a student |
| `09-users.png` | Users page (accounts and assignments) |
| `10-tests.png` | Terminal with the passing `pytest` result and coverage |
