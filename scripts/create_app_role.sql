-- A database user for the running app that can do only what the app needs.
-- Why: the app currently connects as "postgres" (superuser). If the app were ever attacked, the attacker
-- would own the whole database server. With this role the damage is limited and the audit log stays intact.
--
-- HOW TO RUN (once):
--   1. pgAdmin -> right-click the database "student_analytics" -> Query Tool (you are the postgres user).
--   2. Replace CHANGE_ME_BEFORE_RUNNING below with a long random password.
--      (Use a different name than student_analytics in the GRANT CONNECT line if your database has another name.)
--   3. Run the script. Then do NOT keep the password in this file.
--   4. Verify:  python -m scripts.verify_app_role
--   5. In the .env of the machine that RUNS the app set DB_USER=student_app and its password.
--
-- Keep using "postgres" for development, for python -m app.db.init_db (it needs to change tables) and for pytest
-- (the tests create and roll back tables). The app role cannot change the structure of the database, on purpose.

CREATE ROLE student_app LOGIN PASSWORD 'CHANGE_ME_BEFORE_RUNNING'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;

GRANT CONNECT ON DATABASE student_analytics TO student_app;
GRANT USAGE ON SCHEMA public TO student_app;

-- read, add and change rows ...
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO student_app;
-- ... but delete only where the app really deletes (removing a teacher assignment)
GRANT DELETE ON teacher_assignments TO student_app;
-- the audit log can only be read and added to
REVOKE UPDATE ON audit_logs FROM student_app;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO student_app;

-- tables added later by python -m app.db.init_db (run as postgres) get the same rights
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO student_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO student_app;
