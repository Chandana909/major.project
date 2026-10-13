"""A local PostgreSQL server for development and tests, without installing a service.

    python scripts/pg_local.py init      create the cluster and the databases; write the URLs to .env
    python scripts/pg_local.py start
    python scripts/pg_local.py stop
    python scripts/pg_local.py status

Needs the PostgreSQL binaries (bin, lib, share) unpacked somewhere; the official
Windows zip from EnterpriseDB works without installation. Locations:

    AUDITIQ_PG_HOME   the unpacked `pgsql` folder   (default: %LOCALAPPDATA%/auditiq/pgsql)
    AUDITIQ_PG_DATA   the cluster's data directory  (default: %LOCALAPPDATA%/auditiq/pgdata)
    AUDITIQ_PG_PORT   port, on localhost only       (default: 5544)

`init` creates a superuser `auditiq` with a random password (SCRAM), the
databases `auditiq` and `auditiq_test`, and the role `auditiq_reader` that the
copilot's queries run as. It writes AUDITIQ_DATABASE_URL and
AUDITIQ_TEST_DATABASE_URL to .env, which is not versioned. The password is
never printed.
"""
from __future__ import annotations

import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "auditiq"
PG_HOME = Path(os.environ.get("AUDITIQ_PG_HOME") or BASE / "pgsql")
PG_DATA = Path(os.environ.get("AUDITIQ_PG_DATA") or BASE / "pgdata")
PORT = int(os.environ.get("AUDITIQ_PG_PORT", "5544"))
USER = "auditiq"
ENV_FILE = PROJECT_ROOT / ".env"


def tool(name: str) -> str:
    path = PG_HOME / "bin" / (name + (".exe" if os.name == "nt" else ""))
    if not path.exists():
        raise SystemExit(f"{path} not found; set AUDITIQ_PG_HOME to the unpacked PostgreSQL folder")
    return str(path)


def run(args: list[str], env: dict | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, env={**os.environ, **(env or {})}, capture_output=True, text=True, check=check)


def read_env() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    pairs = (line.split("=", 1) for line in ENV_FILE.read_text(encoding="utf-8").splitlines()
             if "=" in line and not line.lstrip().startswith("#"))
    return {k.strip(): v.strip() for k, v in pairs}


def write_env(values: dict[str, str]) -> None:
    """Set keys in .env, keeping every other line as it is."""
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    kept = [line for line in lines if line.split("=", 1)[0].strip() not in values]
    kept += [f"{key}={value}" for key, value in values.items()]
    ENV_FILE.write_text("\n".join(kept) + "\n", encoding="utf-8")


def running() -> bool:
    return run([tool("pg_ctl"), "-D", str(PG_DATA), "status"], check=False).returncode == 0


def start() -> None:
    if running():
        print("already running")
        return
    # pg_ctl detaches the server; its log goes to a file in the data directory.
    result = subprocess.run([tool("pg_ctl"), "-D", str(PG_DATA), "-l", str(PG_DATA / "server.log"), "-w", "start"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode != 0:
        raise SystemExit(f"the server did not start; see {PG_DATA / 'server.log'}")
    print(f"started on localhost:{PORT}")


def stop() -> None:
    if not running():
        print("not running")
        return
    run([tool("pg_ctl"), "-D", str(PG_DATA), "-m", "fast", "-w", "stop"])
    print("stopped")


def psql(password: str, database: str, sql: str) -> subprocess.CompletedProcess:
    return run([tool("psql"), "-h", "localhost", "-p", str(PORT), "-U", USER, "-d", database, "-v",
                "ON_ERROR_STOP=1", "-At", "-c", sql], env={"PGPASSWORD": password})


def init() -> None:
    if (PG_DATA / "PG_VERSION").exists():
        print(f"cluster already exists in {PG_DATA}")
        start()
        return
    password = secrets.token_urlsafe(24)
    PG_DATA.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        pwfile = Path(tmp) / "pw"
        pwfile.write_text(password, encoding="utf-8")
        run([tool("initdb"), "-D", str(PG_DATA), "-U", USER, f"--pwfile={pwfile}", "-A", "scram-sha-256",
             "-E", "UTF8", "--locale=C"])
    with (PG_DATA / "postgresql.conf").open("a", encoding="utf-8") as conf:
        conf.write(f"\n# AuditIQ local development\nport = {PORT}\nlisten_addresses = 'localhost'\n")
    start()
    for database in ("auditiq", "auditiq_test"):
        psql(password, "postgres", f"CREATE DATABASE {database}")
    psql(password, "postgres", "CREATE ROLE auditiq_reader NOLOGIN")
    url = f"postgresql://{USER}:{password}@localhost:{PORT}"
    write_env({"AUDITIQ_DATABASE_URL": f"{url}/auditiq", "AUDITIQ_TEST_DATABASE_URL": f"{url}/auditiq_test"})
    print(f"cluster created in {PG_DATA}; databases auditiq and auditiq_test; URLs written to {ENV_FILE.name}")


def status() -> None:
    print(f"binaries  {PG_HOME}\ndata      {PG_DATA}\nport      {PORT}\nserver    {'running' if running() else 'stopped'}")
    configured = read_env().get("AUDITIQ_DATABASE_URL", "")
    print(f".env      AUDITIQ_DATABASE_URL {'set' if configured else 'not set'}")


if __name__ == "__main__":
    commands = {"init": init, "start": start, "stop": stop, "status": status}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        raise SystemExit(__doc__)
    commands[sys.argv[1]]()
