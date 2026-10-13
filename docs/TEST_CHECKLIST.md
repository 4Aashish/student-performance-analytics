# Manual test checklist

Run `pytest` first. This list covers what automated tests cannot see (the real browser, Excel, human reading).
Tick each box. If something is different from "Expected", write down the exact message and the steps.

Setup: database initialised (`python -m app.db.init_db`), sample data imported, one admin created with
`python -m scripts.create_admin`, app running with `streamlit run app\main.py`.

## 1. Login and sessions
- [ ] Open a page from the left menu without logging in. Expected: "Please log in first".
- [ ] Wrong password. Expected: "Invalid username or password." (same text for an unknown username).
- [ ] 5 wrong passwords for one account. Expected: "locked for 15 minutes"; the correct password is refused too.
- [ ] Admin resets that password on the Users page. Expected: the account works again.
- [ ] Log in, press **Log out**. Expected: back to the login form; menu pages ask for login again.
- [ ] Log in, wait 30 minutes without clicking. Expected: "Your session expired".
- [ ] Admin disables a logged-in teacher; the teacher clicks any page. Expected: "no longer active".

## 2. Roles (create one teacher and one student account first)
- [ ] Teacher assigned to CSE-S3 / CS301: Students page shows only CSE-S3 students and only the Search tab.
- [ ] Same teacher: Attendance and Marks show only CS301; Users and My Dashboard say "no permission".
- [ ] Admin removes the assignment. Expected: teacher immediately sees "No classes are assigned to you yet".
- [ ] Student: only Home and My Dashboard work; every other page says "no permission".
- [ ] Student My Dashboard shows only that student's attendance and marks.

## 3. CSV imports (use the sample files in `data/sample`)
- [ ] `*_invalid.csv` files: nothing imported, every problem listed with its row number.
- [ ] Valid files import; importing the same file again reports "already exists".
- [ ] A CSV with more than 20,000 rows is refused with "split it".
- [ ] A teacher importing a file that contains another class: those rows are errors, nothing imported.

## 4. Attendance and marks
- [ ] Take attendance, save, reopen the same lecture: it says "You are editing it" and shows what you saved.
- [ ] Marks above the maximum or negative: "Nothing was saved" and the reason.
- [ ] History of changes shows old and new marks after an edit.
- [ ] A subject with no attendance shows "No sessions yet", not an error or 0%.

## 5. Dashboard and reports
- [ ] Dashboard numbers match the Marks and Attendance pages for the same class and subject.
- [ ] A filter combination with no data shows a message, not an error.
- [ ] Reports: generate, download, open in Excel. Hindi names display correctly; a name starting with `=` shows as `'=...`.
- [ ] A report with no records shows "nothing to download" and no download button.
- [ ] A student has no Reports page access.

## 6. Audit log (pgAdmin -> Query Tool)
- [ ] `SELECT created_at, user_id, action, table_name, new_value FROM audit_logs ORDER BY id DESC LIMIT 30;`
      shows your logins, exports, student edits, attendance and marks changes with the right user.
- [ ] `UPDATE audit_logs SET action = 'x';` fails with "audit_logs is append-only".

## 7. Errors
- [ ] Stop the PostgreSQL service (Services -> postgresql -> Stop) and reload a page. Expected: a short message with a
      reference number, no host name or port. The details are in `logs/app.log`. Start the service again afterwards.
