# Architecture

The application is a small layered design. Each layer has one job, and the security checks live in one place.

## Layers

```mermaid
flowchart TD
    B["Browser: admin, teacher or student"] --> P["Streamlit pages<br/>app/main.py and app/pages"]
    P --> A["Security layer: the only door to the data<br/>app/security/access.py, users.py, auth.py"]
    P --> H["Pure helpers: charts, calculations, CSV builders<br/>app/services (no SQL)"]
    A --> S["Import and report services<br/>app/services"]
    A --> R["Repositories: all SQL<br/>app/repositories"]
    S --> R
    R --> D[("PostgreSQL<br/>12 tables, constraints, triggers")]
```

| Layer | Folder | Does | Never does |
|---|---|---|---|
| Pages | `app/main.py`, `app/pages` | Show forms, tables and charts; call the security layer | Talk to the database, contain business rules |
| Security layer | `app/security` | Check who the user is and what they may touch, then call repositories; write audit rows | Build screens |
| Services | `app/services` | CSV validation, calculations, reports, charts | Decide permissions |
| Repositories | `app/repositories` | Run SQL with parameters, validate input before saving | Know about users or screens |
| Database | `app/db/schema.sql` | Last line of defence: unique keys, checks, foreign keys, triggers | Business workflows |

A test scans every page and fails if a page imports a repository or an importer directly, so the UI can never bypass the security layer.

## One request: a teacher saves marks

```mermaid
sequenceDiagram
    participant T as Teacher browser
    participant P as Marks page
    participant A as access.save_marks
    participant R as marks_repository
    participant DB as PostgreSQL
    T->>P: press Save marks
    P->>A: save_marks with the logged-in user
    A->>DB: is this teacher assigned to this class and subject
    A->>R: validate and save
    R->>DB: insert or update marks, trigger checks the maximum
    R->>DB: insert audit row with old and new value
    A-->>P: counts or an error message
    P-->>T: success or error shown
```

If any value is wrong, nothing is saved: everything is validated first and runs in one transaction.

## Roles and authorization

* The logged-in user is re-read from the database on **every page load**, so a disabled account or a changed role works immediately.
* **Admin**: no limit. **Teacher**: only the (class, subject) pairs in `teacher_assignments`, looked up fresh on every call, also for CSV imports and exports.
  **Student**: only their own records; the student functions (`my_profile`, `my_attendance`, `my_marks`) have no student-id parameter at all, so changing an ID or a URL cannot show another student's data.
* A test checks that every function in `access.py` takes the user as its second parameter.

## Design decisions

* **Validate twice**: friendly checks in Python (clear messages), and database constraints/triggers as the last line of defence.
* **All-or-nothing CSV import**: any bad row means nothing is imported and every problem is listed, so no record is silently lost.
* **Audit log is append-only** (database trigger): who changed what, with old and new values. The limited database role cannot edit it either.
* **One definition of each rule**: attendance % and marks % are calculated in `app/validation.py` and reused everywhere (screens, reports, dashboard).
* **Safe errors**: users see a short message and a reference number; details go to `logs/app.log`.
* **Secrets in environment variables** (`.env`, ignored by git); no passwords in code.
