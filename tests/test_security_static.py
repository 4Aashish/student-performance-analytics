"""Source-code checks. They fail if someone later adds a risky pattern."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_FILES = sorted((ROOT / "app").rglob("*.py")) + sorted((ROOT / "scripts").rglob("*.py"))


def code_of(path):
    return path.read_text(encoding="utf-8")


def test_sql_built_with_f_strings_only_uses_known_safe_fragments():
    """f-string SQL is dangerous when it contains user input. Only these fixed fragments are allowed:
    a constant list of column names, and a join of hard-coded 'column = %s' pieces."""
    allowed = {"_GROUP_COLUMNS", "', '.join(sets)"}
    found = []
    for path in APP_FILES:
        for literal in re.findall(r'execute\(\s*f"([^"]*)"', code_of(path)):
            for expression in re.findall(r"\{([^}]*)\}", literal):
                found.append((path.name, expression))
                assert expression in allowed, f"{path.name}: unexpected f-string SQL part {{{expression}}}"
    assert len(found) == 3


def test_no_str_format_or_percent_formatting_in_sql_layers():
    for folder in ("repositories", "security", "services"):
        for path in sorted((ROOT / "app" / folder).glob("*.py")):
            text = code_of(path)
            assert ".format(" not in text, f"{path.name} uses str.format"
            assert not re.search(r'execute\(\s*["\'][^"\']*["\']\s*%\s', text), f"{path.name} formats SQL with %"


# These two scripts must start pg_dump / pg_restore. They pass a list of arguments (never a shell string),
# and a test below checks that the password is never part of that list.
SUBPROCESS_ALLOWED = {"backup_db.py", "restore_db.py"}


def test_no_dangerous_calls_anywhere():
    for path in APP_FILES:
        text = code_of(path)
        for pattern in (r"\beval\(", r"\bexec\(", r"\bpickle\b", r"\bos\.system\(",
                        r"unsafe_allow_html", r"\bshell=True\b"):
            assert not re.search(pattern, text), f"{path.name} contains {pattern}"
        if path.name not in SUBPROCESS_ALLOWED:
            assert not re.search(r"\bsubprocess\b", text), f"{path.name} uses subprocess"


def test_no_hard_coded_passwords_or_keys():
    for path in APP_FILES:
        text = code_of(path)
        assert not re.search(r"""(?i)\b(password|secret|api_key|token)\s*=\s*["'][^"']+["']""", text), path.name
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "DB_PASSWORD=\n" in example + "\n"


def test_secrets_and_logs_are_not_committed():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for entry in (".env", "logs/", "venv/", "backups/"):
        assert entry in ignore


def test_upload_size_is_limited():
    config = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    assert re.search(r"maxUploadSize\s*=\s*\d+", config)
    assert int(re.search(r"maxUploadSize\s*=\s*(\d+)", config).group(1)) <= 10


def test_database_connection_has_timeouts():
    text = code_of(ROOT / "app" / "db" / "connection.py")
    assert "connect_timeout" in text and "statement_timeout" in text


def test_pages_never_print_raw_database_exceptions():
    """An 'except ... psycopg2 ... as e' block may only show user_message(e), never str(e) or {e}."""
    checked = 0
    files = sorted((ROOT / "app" / "pages").glob("*.py")) + [ROOT / "app" / "main.py", ROOT / "app" / "ui_auth.py"]
    for path in files:
        lines = code_of(path).splitlines()
        for i, line in enumerate(lines):
            if re.match(r"\s*except .*psycopg2.*as e:", line):
                checked += 1
                block = "\n".join(lines[i + 1:i + 4])
                assert "{e}" not in block and "str(e)" not in block, f"{path.name} line {i + 1} shows a raw exception"
                assert "user_message(e)" in block, f"{path.name} line {i + 1} must use user_message(e)"
    assert checked >= 10
