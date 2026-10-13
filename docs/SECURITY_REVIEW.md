# Security review (Milestone 9)

Scope: the whole application as of Milestone 8 (authentication, authorization, data access, CSV import/export,
sessions, error handling, audit log, configuration). Method: reading every module, searching the code for risky
patterns, and adding automated tests for each finding. Nothing here is a certification: it is a student-project
review, and the open items below must be handled before any real student data is used.

## Findings and what was done

| # | Finding | Risk | Status | Verified by |
|---|---------|------|--------|-------------|
| 1 | Raw database errors were shown in the browser (host name, port, pieces of SQL could leak) | Medium | **Fixed**: users now see a short message with a reference number; full details go to `logs/app.log` | `test_hardening.py::test_user_message_hides_database_details...`, `test_security_static.py::test_pages_never_print_raw_database_exceptions`, `test_pages_smoke.py::test_database_errors_never_reach_the_browser` |
| 2 | CSV imports did not record WHO imported (`marks.updated_by`, `attendance_sessions.created_by`, audit `user_id` were empty) | Medium | **Fixed** | `test_audit_trail.py` (attendance/marks import tests) |
| 3 | No audit trail for student create/edit/import and for attendance corrections (attendance decides eligibility, so it matters as much as marks) | Medium | **Fixed**: old and new values are logged | `test_audit_trail.py` |
| 4 | The audit log could be edited or deleted by the application's database user | Medium | **Fixed**: a trigger makes `audit_logs` append-only | `test_audit_trail.py::test_audit_log_rows_cannot_be_edited_or_deleted` |
| 5 | CSV upload had no limits (200 MB default, unlimited rows) | Medium | **Fixed**: 5 MB upload limit (`.streamlit/config.toml`) and 20,000 rows per file | `test_hardening.py`, `test_security_static.py::test_upload_size_is_limited` |
| 6 | No database timeouts: a dead database could hang the page, a slow query could run forever | Low | **Fixed**: 5 s connect timeout, 60 s statement timeout | `test_security_static.py::test_database_connection_has_timeouts` |
| 7 | Very common passwords such as `Password1` passed the letter+digit rule | Low | **Fixed**: small blocklist | `test_hardening.py` |
| 8 | `logs/` was not in `.gitignore` | Low | **Fixed** | `test_security_static.py::test_secrets_and_logs_are_not_committed` |

## Checked and found acceptable

* **SQL injection**: every value goes through query parameters. Only 3 queries use an f-string, and they contain
  only constants written in the source (a fixed column list and a join of hard-coded `column = %s` pieces). A test
  fails if anyone adds another f-string query or uses `.format` / `%` on SQL.
* **Passwords**: stored as bcrypt hashes with a random salt; passwords over 72 bytes are refused (bcrypt ignores the rest).
* **Login**: wrong password, unknown user and disabled account give the same message; unknown users cost the same
  time as real ones; 5 wrong passwords lock the account for 15 minutes; login events are audited.
* **Authorization**: enforced in `app/security/access.py`, which takes the logged-in user in every function. Pages
  cannot reach the repositories (a test scans every page). Teachers are limited to their assigned class + subject,
  looked up in the database on every call, including CSV imports and exports. Student functions have no student-id
  parameter, so changing an ID or URL cannot show another student's data.
* **Sessions**: the account is re-read from the database on every page load (a disabled account or a changed role
  takes effect immediately) and sessions expire after 30 minutes without activity.
* **Exports**: filters are applied before the file is built, teachers only get their own rows, every export with data
  is audited, and text cells that start with `=`, `+`, `-` or `@` are neutralised (CSV/formula injection).
* **XSS**: no `unsafe_allow_html` anywhere (a test checks this), so names are always escaped.
* **Secrets**: none in the code (a test scans for hard-coded passwords); `.env` is ignored by git.
* **Dangerous functions**: no `eval`, `exec`, `pickle`, `subprocess` or `os.system` (a test checks this).

## Open items (NOT fixed - you must decide or handle these)

1. **No HTTPS.** Streamlit runs on plain HTTP locally. Anything outside your own computer needs a TLS-terminating
   reverse proxy, otherwise passwords travel unencrypted.
2. **The database user is the PostgreSQL superuser (`postgres`).** Create a separate limited user for the app
   (planned for Milestone 10). A database superuser can also disable the audit trigger.
3. **No "forgot password" by e-mail.** Only an administrator can reset a password.
4. **Lockout can be abused**: someone who knows a username can lock that account for 15 minutes by guessing wrongly.
   There is no per-IP rate limiting.
5. **Sessions end on browser refresh** (Streamlit keeps them in memory only).
6. **Streamlit may show Python tracebacks for crashes we did not anticipate.** For deployment check the Streamlit
   documentation for your version and set `client.showErrorDetails` to hide them.
7. **Inactive students can still log in** and see their own records. Decide if that is acceptable.
8. **Moving a student to another class** leaves the old attendance and marks under the old class; the dashboards only
   count data of the student's current class.
9. **No automated dependency scan was run.** Run `pip install pip-audit` and then `pip-audit` yourself and update
   any package it reports.
10. **No backups yet** and **no privacy/legal assessment.** Student data is personal data. Before using real data
    check the rules that apply to your institution (for example India's Digital Personal Data Protection Act, 2023).
    Use only the anonymised sample data until then.
11. The audit log has no screen in the app yet; read it with SQL (see `TEST_CHECKLIST.md`).

## How to re-run the checks

```
pytest
pip install pytest-cov
pytest --cov=app --cov-report=term-missing
pip install pip-audit
pip-audit
```
