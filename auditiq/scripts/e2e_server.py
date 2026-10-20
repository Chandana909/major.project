"""Start the application for the browser tests (frontend/e2e): a new SQLite store, set up from the command line
with benchmark ledger 202, a workbook of ledger 909 for the tests to upload, then the API with the built web
application.

    python scripts/e2e_server.py --port 8011

The local .env is ignored and every AUDITIQ_ variable is cleared, so the tests see the same application here
and in CI: SQLite, no model, no embedding model, no token. Everything is written under .auditiq/e2e/, which
is replaced at every start. Build the web application first (npm run build in frontend/).
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

for name in [n for n in os.environ if n.startswith("AUDITIQ_")]:
    del os.environ[name]
os.environ["AUDITIQ_NO_DOTENV"] = "1"

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".auditiq" / "e2e"
sys.path.insert(0, str(ROOT))

from auditiq.cli import main  # noqa: E402  (after the environment is set)


def run(*argv: str) -> None:
    code = main(list(argv))
    if code:
        raise SystemExit(f"auditiq {' '.join(argv)} failed with exit status {code}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="8011")
    args = ap.parse_args()
    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        raise SystemExit("frontend/dist is missing: run npm run build in frontend/ first")
    os.chdir(ROOT)
    WORK.mkdir(parents=True, exist_ok=True)       # on Windows a removed folder can linger: empty it instead
    for item in WORK.iterdir():
        shutil.rmtree(item) if item.is_dir() else item.unlink()
    store = str(WORK / "e2e.db")
    run("--db", store, "setup", "--dataset", "data/bench_seed_202")
    run("ledger", "export", "data/pilot_seed_909", str(WORK / "pilot_seed_909.xlsx"))
    print("e2e: store ready, serving", flush=True)
    run("--db", store, "serve", "--host", "127.0.0.1", "--port", args.port)
