import uuid

import pytest

from app.security import auth, passwords, users
from app.security.models import AuthorizationError, CurrentUser
from app.validation import ValidationError

PASSWORD = "Sunshine42"
HASH = passwords.hash_password(PASSWORD)  # one hash shared by quick fixtures


def add_user(cur, role, tag, name=None):
    cur.execute("INSERT INTO users (username, password_hash, role) VALUES (%s,%s,%s) RETURNING id",
                (f"{role}-{tag}", HASH, role))
    return cur.fetchone()[0]


@pytest.fixture
def base(db_cur):
    tag = uuid.uuid4().hex[:8]
    admin_id = add_user(db_cur, "admin", tag)
    db_cur.execute("INSERT INTO departments (name) VALUES (%s) RETURNING id", (f"D{tag}",))
    dept = db_cur.fetchone()[0]
    return {"tag": tag, "admin": CurrentUser(admin_id, f"admin-{tag}", "admin"), "dept": dept}


def make_teacher(cur, base, username=None, password=PASSWORD):
    username = username or f"teach{uuid.uuid4().hex[:6]}"
    uid = users.create_account(cur, base["admin"], username, password, "teacher", name="Teach", department_id=base["dept"])
    return uid, username


def test_password_is_stored_only_as_a_bcrypt_hash(db_cur, base):
    uid, _ = make_teacher(db_cur, base)
    db_cur.execute("SELECT password_hash FROM users WHERE id = %s", (uid,))
    stored = db_cur.fetchone()[0]
    assert stored != PASSWORD and PASSWORD not in stored and stored.startswith("$2")


def test_create_account_rules(db_cur, base):
    admin = base["admin"]
    make_teacher(db_cur, base, username="Same.Name")
    with pytest.raises(ValidationError):                       # case-insensitive duplicate
        make_teacher(db_cur, base, username="same.name")
    with pytest.raises(ValidationError):
        users.create_account(db_cur, admin, "weakpw1", "short1", "teacher", name="T", department_id=base["dept"])
    with pytest.raises(ValidationError):
        users.create_account(db_cur, admin, "badrole1", PASSWORD, "superuser")
    with pytest.raises(ValidationError):
        users.create_account(db_cur, admin, "noname1", PASSWORD, "teacher", name=" ", department_id=base["dept"])
    with pytest.raises(ValidationError):
        users.create_account(db_cur, admin, "nodept1", PASSWORD, "teacher", name="T", department_id=999999999)
    with pytest.raises(ValidationError):
        users.create_account(db_cur, admin, "nostudent1", PASSWORD, "student", student_id=999999999)
    teacher = CurrentUser(1, "someone", "teacher", teacher_id=1)
    with pytest.raises(AuthorizationError):
        users.create_account(db_cur, teacher, "hacker1", PASSWORD, "admin")


def test_student_account_links_once(db_cur, base):
    db_cur.execute("INSERT INTO classes (department_id, name, semester) VALUES (%s,%s,3) RETURNING id",
                   (base["dept"], f"C{base['tag']}"))
    cls = db_cur.fetchone()[0]
    db_cur.execute("INSERT INTO students (student_code, name, class_id) VALUES (%s,'S',%s) RETURNING id",
                   (f"S{base['tag']}", cls))
    sid = db_cur.fetchone()[0]
    users.create_account(db_cur, base["admin"], f"stud{base['tag']}", PASSWORD, "student", student_id=sid)
    assert sid not in [s["id"] for s in users.list_unlinked_students(db_cur, base["admin"])]
    with pytest.raises(ValidationError):
        users.create_account(db_cur, base["admin"], f"other{base['tag']}", PASSWORD, "student", student_id=sid)


def test_login_success_and_case_insensitive_username(db_cur, base):
    uid, username = make_teacher(db_cur, base)
    result = auth.authenticate(db_cur, f"  {username.upper()} ", PASSWORD)
    assert result.user is not None
    assert (result.user.user_id, result.user.role) == (uid, "teacher")
    assert result.user.teacher_id is not None and result.user.student_id is None


def test_wrong_password_unknown_user_and_disabled_account_give_the_same_message(db_cur, base):
    uid, username = make_teacher(db_cur, base)
    wrong = auth.authenticate(db_cur, username, "Wrong-pass1")
    unknown = auth.authenticate(db_cur, "nobody-here", PASSWORD)
    assert wrong.user is None and unknown.user is None
    assert wrong.message == unknown.message == auth.GENERIC_FAILURE
    users.set_user_active(db_cur, base["admin"], uid, False)
    disabled = auth.authenticate(db_cur, username, PASSWORD)     # correct password, disabled account
    assert disabled.user is None and disabled.message == auth.GENERIC_FAILURE


def test_account_locks_after_five_wrong_passwords_and_unlocks_later(db_cur, base):
    uid, username = make_teacher(db_cur, base)
    for _ in range(auth.MAX_FAILED_ATTEMPTS - 1):
        assert auth.authenticate(db_cur, username, "Wrong-pass1").message == auth.GENERIC_FAILURE
    last = auth.authenticate(db_cur, username, "Wrong-pass1")
    assert "locked" in last.message
    refused = auth.authenticate(db_cur, username, PASSWORD)      # correct password, but locked
    assert refused.user is None and "Too many failed attempts" in refused.message
    db_cur.execute("UPDATE users SET locked_until = now() - interval '1 minute' WHERE id = %s", (uid,))
    assert auth.authenticate(db_cur, username, PASSWORD).user is not None


def test_successful_login_resets_the_failure_counter(db_cur, base):
    uid, username = make_teacher(db_cur, base)
    for _ in range(3):
        auth.authenticate(db_cur, username, "Wrong-pass1")
    assert auth.authenticate(db_cur, username, PASSWORD).user is not None
    db_cur.execute("SELECT failed_attempts FROM users WHERE id = %s", (uid,))
    assert db_cur.fetchone()[0] == 0


def test_login_events_are_audited(db_cur, base):
    uid, username = make_teacher(db_cur, base)
    auth.authenticate(db_cur, username, "Wrong-pass1")
    auth.authenticate(db_cur, username, PASSWORD)
    db_cur.execute("SELECT action FROM audit_logs WHERE user_id = %s AND action LIKE 'login%%' ORDER BY id", (uid,))
    assert [r[0] for r in db_cur.fetchall()] == ["login_failed", "login_success"]


def test_disabled_account_cannot_be_reloaded_and_admin_cannot_disable_self(db_cur, base):
    uid, _ = make_teacher(db_cur, base)
    assert auth.load_current_user(db_cur, uid).role == "teacher"
    users.set_user_active(db_cur, base["admin"], uid, False)
    assert auth.load_current_user(db_cur, uid) is None
    with pytest.raises(ValidationError):
        users.set_user_active(db_cur, base["admin"], base["admin"].user_id, False)


def test_change_password(db_cur, base):
    uid, username = make_teacher(db_cur, base)
    me = auth.load_current_user(db_cur, uid)
    with pytest.raises(ValidationError):
        auth.change_password(db_cur, me, "Wrong-pass1", "Brand-new9")
    with pytest.raises(ValidationError):
        auth.change_password(db_cur, me, PASSWORD, "weak")
    with pytest.raises(ValidationError):
        auth.change_password(db_cur, me, PASSWORD, PASSWORD)
    auth.change_password(db_cur, me, PASSWORD, "Brand-new9")
    assert auth.authenticate(db_cur, username, PASSWORD).user is None
    assert auth.authenticate(db_cur, username, "Brand-new9").user is not None


def test_admin_reset_password_also_unlocks(db_cur, base):
    uid, username = make_teacher(db_cur, base)
    db_cur.execute("UPDATE users SET locked_until = now() + interval '10 minutes' WHERE id = %s", (uid,))
    users.reset_password(db_cur, base["admin"], uid, "Reset-pass7")
    assert auth.authenticate(db_cur, username, "Reset-pass7").user is not None


def test_only_admins_manage_users(db_cur, base):
    uid, _ = make_teacher(db_cur, base)
    teacher = auth.load_current_user(db_cur, uid)
    for call in (lambda: users.list_users(db_cur, teacher),
                 lambda: users.reset_password(db_cur, teacher, uid, "Hacked-pass1"),
                 lambda: users.set_user_active(db_cur, teacher, uid, False),
                 lambda: users.list_teachers(db_cur, teacher),
                 lambda: users.assign_teacher(db_cur, teacher, 1, 1, 1),
                 lambda: users.list_assignments(db_cur, teacher),
                 lambda: users.remove_assignment(db_cur, teacher, 1)):
        with pytest.raises(AuthorizationError):
            call()


def test_first_admin_can_only_be_created_when_no_admin_exists(db_cur, base):
    with pytest.raises(ValidationError):                       # base already has an admin
        users.create_first_admin(db_cur, "second-admin", PASSWORD)
