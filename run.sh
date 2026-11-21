#!/usr/bin/env bash
# AuditIQ in one command: installs what it needs, starts Kafka, streams the ledger through it into the audit,
# starts the web application and opens it in the browser.
#
#   ./run.sh                  the final ledger (25,000 invoices) through Kafka; the dashboard opens when it is ready
#   ./run.sh --huge           the 500,000-invoice ledger instead (unpacked once; streaming it takes about an hour)
#   ./run.sh --limit 2000     only the first 2,000 invoices (a quick demonstration)
#   ./run.sh --keep           open the last run again, without streaming anything
#   ./run.sh stop             stop the Kafka broker
#   ./run.sh reset            stop it and delete the topics and messages of every run
#
# Every other option of auditiq/scripts/live.py is passed on (python auditiq/scripts/live.py --help).
#
# Needs Python 3.11 or later and an internet connection the first time. Everything else is fetched by
# auditiq/scripts/bootstrap.py into auditiq/.tools/ when it is not already installed: Java 17 (for Kafka), Node.js 20
# (to build the web application once) and Kafka 4.3.2, each checked against its published checksum. The Python
# packages go into auditiq/.venv. The store is a SQLite database the run creates (no database server is needed); it
# and the Kafka data are kept outside the project (~/.local/share/auditiq on Linux and macOS, %LOCALAPPDATA%\auditiq
# on Windows). Works in bash on Linux, macOS and Windows (Git Bash). Stop the run with Ctrl+C.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$ROOT/auditiq/pyproject.toml" ]; then APP="$ROOT/auditiq"; else APP="$ROOT"; fi
cd "$APP"

say() { printf '[auditiq] %s\n' "$*"; }

# ---- Python 3.11 or later (python3, then python; the Windows Store stub of python3 does not count)
PYTHON=""
for candidate in "${AUDITIQ_PYTHON:-}" python3 python py; do
    [ -n "$candidate" ] || continue
    command -v "$candidate" >/dev/null 2>&1 || continue
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
        PYTHON="$candidate"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    say "Python 3.11 or later is needed: https://www.python.org/downloads/ (then run ./run.sh again)"
    exit 1
fi

# ---- the Python environment, made once; the packages are installed again only when pyproject.toml changes
case "${1:-}" in
    stop|reset) ;;                          # nothing to install to stop the broker
    *)
    if [ ! -d .venv ]; then
        say "creating the Python environment in $APP/.venv"
        if ! "$PYTHON" -m venv .venv; then
            rm -rf .venv
            say "could not create it; on Debian or Ubuntu install the venv module first:"
            say "  sudo apt install python3-venv     (then run ./run.sh again)"
            exit 1
        fi
    fi
    if [ -x .venv/bin/python ]; then VENV_PY=.venv/bin/python; else VENV_PY=.venv/Scripts/python.exe; fi
    STAMP=".venv/.auditiq-installed"
    WANT="$("$VENV_PY" -c 'import hashlib, pathlib; print(hashlib.sha256(pathlib.Path("pyproject.toml").read_bytes()).hexdigest())')"
    if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$WANT" ]; then
        say "installing the Python packages (the first time takes a few minutes)"
        "$VENV_PY" -m pip install --upgrade pip >/dev/null
        "$VENV_PY" -m pip install -e ".[dev]"
        printf '%s' "$WANT" > "$STAMP"
    fi
    PYTHON="$VENV_PY"
    ;;
esac

# ---- Java, Kafka, Node.js and the ledger, then the live run (auditiq/scripts/live.py)
exec "$PYTHON" scripts/bootstrap.py "$@"
