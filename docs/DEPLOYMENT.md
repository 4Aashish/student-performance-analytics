# Deployment, backups and going live

The project is developed and tested for **local use**. Do **not** put real student information on public hosting until
every item in "Before real data" is done.

## 1. Local use (tested)

See the Quick start in the README. `start_app.bat` starts the app, `run_tests.bat` runs the tests.

## 2. Before real data

- [ ] Run the app only behind **HTTPS** (a reverse proxy such as Caddy or nginx with a certificate). Plain HTTP sends passwords in the clear.
- [ ] Create and use the **limited database user** (section 4). Never run the live app as `postgres`.
- [ ] Set up **backups** and test a restore (section 3).
- [ ] Choose a long admin password; do not share accounts.
- [ ] Hide Python error details in Streamlit (check the Streamlit documentation for your version: option `client.showErrorDetails`).
- [ ] Protect `.env`, `logs/` and `backups/` (file permissions on the server). They are ignored by git; keep it that way.
- [ ] Run `pip install pip-audit` and `pip-audit`, and update packages it reports.
- [ ] Review privacy and legal rules for student data with your institution (for example India's Digital Personal Data Protection Act, 2023).
- [ ] Walk through [TEST_CHECKLIST.md](TEST_CHECKLIST.md) on the server, using the limited database user.

## 3. Backup and restore

Backup (creates `backups\<database>_<date>_<time>.dump`; needs the PostgreSQL command line tools):

```bat
python -m scripts.backup_db
```

If it says `pg_dump was not found`, set the folder once, for example:
`set PG_BIN_DIR=C:\Program Files\PostgreSQL\18\bin`

Restore into a **new** database (the script never overwrites an existing one):

```bat
python -m scripts.restore_db backups\student_analytics_20261012_213005.dump student_analytics_restored
```

Then check the data (set `DB_NAME=student_analytics_restored` in a copy of `.env` and start the app).
A backup that was never restored is only a hope: test it. Backups contain **all** student data, so store them privately
(encrypted if they leave the server). Schedule the backup command with Windows Task Scheduler (daily is a sensible start).
Copy backups to a second place; a backup on the same disk does not survive a disk failure.

## 4. Limited database user

By default the app connects as the PostgreSQL superuser. `scripts/create_app_role.sql` creates `student_app`, which can read,
add and change rows, delete only teacher assignments, only read and add to the audit log, and cannot change the structure of the database.

1. In pgAdmin open a Query Tool on the `student_analytics` database as `postgres`, paste `scripts/create_app_role.sql`,
   replace `CHANGE_ME_BEFORE_RUNNING` with a long random password and run it.
2. Check it: `python -m scripts.verify_app_role` (asks for that password; every statement is rolled back). Every line should say `OK`.
3. On the machine that runs the app set `DB_USER=student_app` and its password in `.env`.
4. Keep using `postgres` for development, `python -m app.db.init_db` and `pytest`.

The command-building and name-checking parts of the backup, restore and privilege-check scripts have automated tests. The role script
itself and the real `pg_dump` / `pg_restore` runs need a live server, so they have **no automated test**: run `verify_app_role` and a
test restore on your own server before relying on them.

## 5. Running on a server (outline, not tested)

* Install Python, PostgreSQL and the project; create a virtual environment and `pip install -r requirements.txt`.
* Run Streamlit as a service (for example with NSSM on Windows or systemd on Linux), bound to `localhost` only.
* Put a reverse proxy with HTTPS in front of it and allow only the proxy to reach port 8501.
* Keep PostgreSQL closed to the internet.
* For reproducible installs run `pip freeze > requirements.lock.txt` in the working environment and install from that file on the server.

## 6. Public demo (sample data only)

A public demo is acceptable **only with the synthetic sample data**, never with real records. Streamlit Community Cloud
needs a PostgreSQL database reachable from the internet and the settings given as environment variables or secrets
(check the platform's documentation: this has not been tried here). Use a throw-away database and a throw-away admin account,
and delete both after the demonstration.
