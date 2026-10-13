"""Backs up the whole database with pg_dump.     Run:  python -m scripts.backup_db

Needs the PostgreSQL command line tools (they are installed together with PostgreSQL).
The password is given to pg_dump through the PGPASSWORD environment variable of that one child
process only, so it never appears in a command line, a log or the process list.
A backup contains ALL student data: keep the backups folder private (it is ignored by git)."""
import glob
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import ConfigError, Settings, get_settings

BACKUP_DIR = Path(__file__).resolve().parents[1] / "backups"


def find_pg_tool(name: str) -> Optional[str]:
    """Looks for pg_dump / pg_restore: PG_BIN_DIR, then PATH, then the usual Windows install folders."""
    exe = f"{name}.exe" if os.name == "nt" else name
    configured = os.getenv("PG_BIN_DIR")
    if configured and (Path(configured) / exe).is_file():
        return str(Path(configured) / exe)
    found = shutil.which(name)
    if found:
        return found
    pattern = rf"C:\Program Files\PostgreSQL\*\bin\{exe}"
    matches = sorted(glob.glob(pattern), reverse=True)           # newest version first
    return matches[0] if matches else None


def backup_filename(db_name: str, now: datetime) -> str:
    return f"{db_name}_{now.strftime('%Y%m%d_%H%M%S')}.dump"


def build_dump_command(pg_dump: str, settings: Settings, out_file: Path) -> list:
    """No password in here on purpose."""
    return [pg_dump, "-h", settings.db_host, "-p", str(settings.db_port), "-U", settings.db_user,
            "-F", "c", "-f", str(out_file), settings.db_name]


def build_env(settings: Settings, base: Optional[dict] = None) -> dict:
    env = dict(os.environ if base is None else base)
    env["PGPASSWORD"] = settings.db_password
    return env


def main() -> int:
    try:
        settings = get_settings()
        settings.require_db_password()
    except ConfigError as e:
        print(f"Configuration problem: {e}")
        return 1
    pg_dump = find_pg_tool("pg_dump")
    if pg_dump is None:
        print("pg_dump was not found. Install the PostgreSQL command line tools, or set the environment "
              "variable PG_BIN_DIR to the folder that contains pg_dump.exe "
              r"(for example C:\Program Files\PostgreSQL\18\bin).")
        return 1

    BACKUP_DIR.mkdir(exist_ok=True)
    out_file = BACKUP_DIR / backup_filename(settings.db_name, datetime.now())
    result = subprocess.run(build_dump_command(pg_dump, settings, out_file), env=build_env(settings),
                            capture_output=True, text=True)
    if result.returncode != 0:
        out_file.unlink(missing_ok=True)
        print("Backup FAILED:")
        print(result.stderr.strip() or "(no message from pg_dump)")
        return 1
    print(f"Backup created: {out_file}  ({out_file.stat().st_size / 1024:.0f} KB)")
    print("It contains all student data. Keep it private and, if you copy it elsewhere, protect it.")
    print("A backup you never tested is only a hope: restore it into a NEW database now and again "
          "(python -m scripts.restore_db).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
