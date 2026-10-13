-- Student Performance Analytics System: database schema (PostgreSQL)
-- Safe to run more than once (uses IF NOT EXISTS / DROP TRIGGER IF EXISTS).

-- ---------- Users ----------
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(50) NOT NULL UNIQUE,
    password_hash TEXT        NOT NULL,
    role          VARCHAR(10) NOT NULL CHECK (role IN ('admin', 'teacher', 'student')),
    is_active     BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Login protection (added in Milestone 7)
ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS locked_until TIMESTAMPTZ;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_lower ON users (lower(username));

-- ---------- Departments, classes, subjects ----------
CREATE TABLE IF NOT EXISTS departments (
    id   SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE CHECK (btrim(name) <> '')
);

CREATE TABLE IF NOT EXISTS classes (
    id            SERIAL PRIMARY KEY,
    department_id INTEGER     NOT NULL REFERENCES departments(id),
    name          VARCHAR(50) NOT NULL CHECK (btrim(name) <> ''),
    semester      SMALLINT    NOT NULL CHECK (semester BETWEEN 1 AND 10),
    UNIQUE (department_id, name)
);

CREATE TABLE IF NOT EXISTS subjects (
    id            SERIAL PRIMARY KEY,
    code          VARCHAR(20)  NOT NULL UNIQUE CHECK (btrim(code) <> ''),
    name          VARCHAR(100) NOT NULL CHECK (btrim(name) <> ''),
    department_id INTEGER      NOT NULL REFERENCES departments(id),
    semester      SMALLINT     NOT NULL CHECK (semester BETWEEN 1 AND 10)
);

-- ---------- Students and teachers ----------
CREATE TABLE IF NOT EXISTS students (
    id           SERIAL PRIMARY KEY,
    student_code VARCHAR(30)  NOT NULL UNIQUE CHECK (btrim(student_code) <> ''),
    user_id      INTEGER      UNIQUE REFERENCES users(id),
    name         VARCHAR(100) NOT NULL CHECK (btrim(name) <> ''),
    class_id     INTEGER      NOT NULL REFERENCES classes(id),
    status       VARCHAR(10)  NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS teachers (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER      NOT NULL UNIQUE REFERENCES users(id),
    name          VARCHAR(100) NOT NULL CHECK (btrim(name) <> ''),
    department_id INTEGER      NOT NULL REFERENCES departments(id)
);

-- Which teacher teaches which subject to which class
CREATE TABLE IF NOT EXISTS teacher_assignments (
    id         SERIAL PRIMARY KEY,
    teacher_id INTEGER NOT NULL REFERENCES teachers(id),
    subject_id INTEGER NOT NULL REFERENCES subjects(id),
    class_id   INTEGER NOT NULL REFERENCES classes(id),
    UNIQUE (teacher_id, subject_id, class_id)
);

-- ---------- Attendance ----------
CREATE TABLE IF NOT EXISTS attendance_sessions (
    id           SERIAL PRIMARY KEY,
    class_id     INTEGER  NOT NULL REFERENCES classes(id),
    subject_id   INTEGER  NOT NULL REFERENCES subjects(id),
    session_date DATE     NOT NULL,
    session_no   SMALLINT NOT NULL DEFAULT 1 CHECK (session_no >= 1),
    created_by   INTEGER  REFERENCES users(id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (class_id, subject_id, session_date, session_no)
);

CREATE TABLE IF NOT EXISTS attendance_records (
    id         SERIAL PRIMARY KEY,
    session_id INTEGER     NOT NULL REFERENCES attendance_sessions(id) ON DELETE CASCADE,
    student_id INTEGER     NOT NULL REFERENCES students(id),
    status     VARCHAR(10) NOT NULL CHECK (status IN ('present', 'absent')),
    UNIQUE (session_id, student_id)
);

-- ---------- Assessments and marks ----------
CREATE TABLE IF NOT EXISTS assessments (
    id              SERIAL PRIMARY KEY,
    class_id        INTEGER      NOT NULL REFERENCES classes(id),
    subject_id      INTEGER      NOT NULL REFERENCES subjects(id),
    name            VARCHAR(100) NOT NULL CHECK (btrim(name) <> ''),
    max_marks       NUMERIC(6,2) NOT NULL CHECK (max_marks > 0),
    assessment_date DATE,
    UNIQUE (class_id, subject_id, name)
);

CREATE TABLE IF NOT EXISTS marks (
    id             SERIAL PRIMARY KEY,
    assessment_id  INTEGER      NOT NULL REFERENCES assessments(id),
    student_id     INTEGER      NOT NULL REFERENCES students(id),
    obtained_marks NUMERIC(6,2) NOT NULL CHECK (obtained_marks >= 0),
    updated_by     INTEGER      REFERENCES users(id),
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (assessment_id, student_id)
);

-- ---------- Audit log (modification history) ----------
CREATE TABLE IF NOT EXISTS audit_logs (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER     REFERENCES users(id),
    action     VARCHAR(50) NOT NULL,
    table_name VARCHAR(50) NOT NULL,
    record_id  INTEGER,
    old_value  JSONB,
    new_value  JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- Indexes ----------
CREATE INDEX IF NOT EXISTS idx_students_class        ON students(class_id);
CREATE INDEX IF NOT EXISTS idx_att_records_student   ON attendance_records(student_id);
CREATE INDEX IF NOT EXISTS idx_att_sessions_lookup   ON attendance_sessions(class_id, subject_id, session_date);
CREATE INDEX IF NOT EXISTS idx_marks_student         ON marks(student_id);
CREATE INDEX IF NOT EXISTS idx_assessments_lookup    ON assessments(class_id, subject_id);
CREATE INDEX IF NOT EXISTS idx_audit_table_record    ON audit_logs(table_name, record_id);

-- ---------- Triggers ----------
-- 1) obtained_marks must never exceed the assessment's max_marks
CREATE OR REPLACE FUNCTION check_marks_within_max() RETURNS trigger AS $$
DECLARE
    max_allowed NUMERIC;
BEGIN
    SELECT max_marks INTO max_allowed FROM assessments WHERE id = NEW.assessment_id;
    IF NEW.obtained_marks > max_allowed THEN
        RAISE EXCEPTION 'obtained_marks (%) cannot exceed max_marks (%)',
            NEW.obtained_marks, max_allowed
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_marks_within_max ON marks;
CREATE TRIGGER trg_marks_within_max
    BEFORE INSERT OR UPDATE ON marks
    FOR EACH ROW EXECUTE FUNCTION check_marks_within_max();

-- 2) max_marks cannot be lowered below marks that are already stored
CREATE OR REPLACE FUNCTION check_max_not_below_existing() RETURNS trigger AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM marks
               WHERE assessment_id = NEW.id AND obtained_marks > NEW.max_marks) THEN
        RAISE EXCEPTION 'max_marks (%) is lower than marks already recorded', NEW.max_marks
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_assessment_max_check ON assessments;
CREATE TRIGGER trg_assessment_max_check
    BEFORE UPDATE OF max_marks ON assessments
    FOR EACH ROW EXECUTE FUNCTION check_max_not_below_existing();

-- 3) keep updated_at fresh
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_students_updated ON students;
CREATE TRIGGER trg_students_updated
    BEFORE UPDATE ON students
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_marks_updated ON marks;
CREATE TRIGGER trg_marks_updated
    BEFORE UPDATE ON marks
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 4) the audit log can only grow: nobody can edit or delete a row (added in Milestone 9)
CREATE OR REPLACE FUNCTION audit_logs_are_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_logs is append-only: rows cannot be changed or deleted'
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audit_logs_append_only ON audit_logs;
CREATE TRIGGER trg_audit_logs_append_only
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION audit_logs_are_append_only();
