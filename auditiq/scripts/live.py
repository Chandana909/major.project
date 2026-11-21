"""AuditIQ, live: the mock ledger goes through Kafka into the audit, with the web application on top.

    python scripts/live.py                  a fresh run: an empty store, new topics, everything streamed and audited
    python scripts/live.py --keep           open the last run again; nothing is published
    python scripts/live.py --ledger bench_seed_202 --limit 1000
    python scripts/live.py stop             stop the Kafka broker
    python scripts/live.py reset            stop it and delete the topics and messages of every run

`start.bat` in the project folder runs this file. A run

    1. checks what it needs: Kafka installed, the ledger, the built web application
    2. starts the local Kafka broker (scripts/kafka_local.py) unless one is listening
    3. creates an empty store with the policy versions and documents, and four topics of its own
    4. starts the web application and the stream workers
    5. publishes the policy documents, the ledger (vendors, then invoices with their purchase orders, goods
       receipts and approvals) and the vendor e-mails written about it
    6. reports the progress until every message is processed, and keeps the pipeline running until Ctrl+C

Nothing reaches the store through the audit except the topics; the ground truth of the ledger (labels.csv) is
loaded beside it, after the ledger is published, so that the application can score the audit against it. The audit
never reads it. The store and the logs of a run are kept outside the
project (AUDITIQ_LIVE_HOME, default %LOCALAPPDATA%/auditiq/live): the store uses a write-ahead log, so that the
web application reads while the workers write, and that does not belong in a folder a sync client rewrites.
Every run has topics of its own (live-<time>.invoice, ...), because a topic cannot be emptied reliably on
Windows; `reset` removes them all.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(Path(__file__).resolve().parent)]

import kafka_local  # noqa: E402  (the script beside this one)

DEFAULT_LEDGER = "final_seed_2025"
PORT = 8000
SETTLE = 6.0            # seconds a broker just started is given before the first client connects
KINDS = ("vendor", "invoice", "email", "compliance")
NAMES = {"vendor": "vendors", "invoice": "invoices", "email": "e-mails", "compliance": "policies"}


@dataclass
class Run:
    """What a run is made of: its topics, its store, the ledger it streams."""
    prefix: str
    db: str
    ledger: str
    port: int
    started: str


def home() -> Path:
    base = os.environ.get("AUDITIQ_LIVE_HOME")
    return Path(base) if base else kafka_local.BASE / "live"


def listening(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def ledger_path(name: str) -> Path:
    """A ledger by its name under data/, or by the path of its folder."""
    direct = Path(name)
    return direct if (direct / "invoices.csv").exists() else ROOT / "data" / name


def problems(ledger: Path, port: int, bootstrap: str) -> list[str]:
    """What stops a run, each with what to do about it."""
    found = []
    try:
        import confluent_kafka  # noqa: F401
    except ImportError:
        found.append('the Python packages are not installed: run  pip install -e ".[dev]"  in the project folder')
    host, _, broker_port = bootstrap.rpartition(":")
    local = host in ("127.0.0.1", "localhost") and int(broker_port) == kafka_local.PORT
    if local and not listening(kafka_local.PORT) and not kafka_local.CONFIG.exists():
        found.append("Kafka is not installed. Download kafka_2.13-4.3.2.tgz from https://kafka.apache.org/downloads "
                     "and run  python scripts\\kafka_local.py init <the .tgz>  (Java 17 or later is needed)")
    if not (ledger / "invoices.csv").exists():
        found.append(f"the ledger {ledger} does not exist: generate the datasets with  python -m auditiq_bench")
    if listening(port):
        found.append(f"port {port} is in use (another AuditIQ server?): close it, or choose another with --port")
    return found


def new_run(ledger: Path, port: int, now: datetime | None = None) -> Run:
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return Run(prefix=f"live-{stamp}", db=str(home() / f"live-{stamp}.db"), ledger=str(ledger), port=port,
               started=stamp)


def save_run(run: Run) -> None:
    home().mkdir(parents=True, exist_ok=True)
    (home() / "run.json").write_text(json.dumps(asdict(run), indent=1) + "\n", encoding="utf-8")


def load_run() -> Run | None:
    path = home() / "run.json"
    if not path.exists():
        return None
    run = Run(**json.loads(path.read_text(encoding="utf-8")))
    return run if Path(run.db).exists() else None


def remove_earlier_stores(keep: str | None = None) -> int:
    """The stores of earlier runs: files this script made (live-*.db with their logs), and nothing else."""
    removed = 0
    for path in home().glob("live-*.db*"):
        if keep is None or not path.name.startswith(Path(keep).name):
            with contextlib.suppress(OSError):          # still open in a run that is going on: leave it
                path.unlink()
                removed += 1
    return removed


def environment(run: Run, bootstrap: str) -> dict[str, str]:
    """The settings of a run, for this process and the ones it starts. They win over .env."""
    env = dict(os.environ)
    env.update(AUDITIQ_KAFKA_BOOTSTRAP=bootstrap, AUDITIQ_KAFKA_PREFIX=run.prefix, AUDITIQ_DB=run.db,
               AUDITIQ_DATABASE_URL="", AUDITIQ_SQLITE_JOURNAL="wal", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    return env


def spawn(argv: list[str], env: dict[str, str], log: Path) -> subprocess.Popen:
    """A process of the run, writing to its log file."""
    out = log.open("a", encoding="utf-8")
    return subprocess.Popen([sys.executable, "-m", "auditiq", *argv], cwd=ROOT, env=env, stdout=out,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)


def tail(log: Path, lines: int = 15) -> str:
    if not log.exists():
        return ""
    return "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


def wait_for_server(port: int, process: subprocess.Popen, seconds: float = 120.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and process.poll() is None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as reply:
                if reply.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    return False


def build_frontend() -> str | None:
    """Build the web application when it has not been built; a message when that cannot be done."""
    if (ROOT / "frontend" / "dist" / "index.html").exists():
        return None
    npm = shutil.which("npm")
    if not npm:
        return ("the web application is not built and Node.js is not installed (https://nodejs.org): "
                "the API runs, the pages do not")
    print("      building the web application (once; a minute or two)")
    for command in (["ci"] if not (ROOT / "frontend" / "node_modules").exists() else []) + ["run build"]:
        done = subprocess.run([npm, *command.split()], cwd=ROOT / "frontend", capture_output=True, text=True, check=False)
        if done.returncode:
            return f"building the web application failed (npm {command}):\n{done.stdout[-800:]}{done.stderr[-800:]}"
    return None


def mailbox_of(ledger: Path) -> Path:
    """The vendor e-mails written about a ledger: generated once (seeded), then kept."""
    from auditiq_bench import correspondence
    out = home() / "mail" / f"{ledger.name}.mbox"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        messages, labels = correspondence.generate(ledger, seed=7)
        correspondence.write(messages, labels, out)
    return out


def publish(ledger: Path, limit: int | None, emails: bool) -> dict[str, int]:
    """Everything of a run into its topics: the policy documents, the ledger, the e-mails."""
    from auditiq import stream
    from auditiq.policy_pdf import make_sample_pdfs

    settings = stream.StreamSettings.from_env()
    stream.ensure_topics(settings)
    publisher = stream.Publisher(settings)
    for pdf in make_sample_pdfs():
        if pdf.name.startswith("Procurement_Audit_SOP"):        # the documents the controls can execute
            stream.publish_policy(publisher, pdf)
    stream.publish_ledger(publisher, ledger, limit=limit)
    if emails:
        stream.publish_mailbox(publisher, mailbox_of(ledger))
    return {kind: n for kind, n in publisher.close().items() if n}


def load_answer_key(conn, ledger: Path) -> int:
    """The ground truth of the ledger into ``benchmark_labels``, so that the application can score the audit against
    it (coverage, missed frauds, false alarms). Only for display and verification: the audit never reads the table.
    Returns the rows loaded; none when the ledger has no ``labels.csv`` or the key is already there."""
    import pandas as pd

    path = ledger / "labels.csv"
    if not path.exists() or conn.scalar("SELECT COUNT(*) FROM benchmark_labels"):
        return 0
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    columns = [c for c in frame.columns if c in conn.columns("benchmark_labels")]
    conn.executemany(f"INSERT INTO benchmark_labels ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                     frame[columns].values.tolist())
    manifest = json.loads((ledger / "manifest.json").read_text(encoding="utf-8"))
    for key, value in (("dataset", ledger.name), ("labels_policy", manifest.get("policy_version"))):
        if value:
            conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                         (key, value))
    conn.commit()
    return len(frame)


def snapshot(conn) -> dict:
    """Where the run stands: per topic the messages and those processed, and what the audit has decided."""
    from auditiq import stream

    topics = {t["kind"]: t for t in stream.status(stream.StreamSettings.from_env(), conn, timeout=5)}
    routes = dict(conn.execute("SELECT route, COUNT(*) FROM v_latest_results GROUP BY route").fetchall())
    levels = dict(conn.execute("SELECT risk_level, COUNT(*) FROM v_latest_results GROUP BY risk_level").fetchall())
    waiting = int(conn.scalar("SELECT COUNT(*) FROM v_review_queue") or 0)
    conn.rollback()                                             # no read is left open on the store
    return {"topics": topics, "routes": routes, "levels": levels, "waiting": waiting,
            "lag": sum(t["lag"] for t in topics.values()), "messages": sum(t["messages"] for t in topics.values())}


def progress(state: dict) -> str:
    """One line of where the run stands: processed/published per topic, and the review queue."""
    parts = [f"{NAMES[kind]} {state['topics'][kind]['processed']:,}/{state['topics'][kind]['messages']:,}"
             for kind in KINDS if kind in state["topics"] and state["topics"][kind]["messages"]]
    return "   ".join([*parts, f"waiting for review {state['waiting']:,}"])


def summary(state: dict, seconds: float, rings: int | None) -> str:
    audited = sum(state["routes"].values())
    person = state["routes"].get("escalate", 0) + state["routes"].get("sample", 0)
    levels = state["levels"]
    lines = [f"Every message is processed, {seconds:.0f} s after publishing. {audited:,} invoices audited:",
             f"  sent to a person     {person:,}" + (f" ({person / audited:.1%})" if audited else ""),
             f"  approved             {state['routes'].get('approve', 0):,}",
             "  risk levels          " + ", ".join(f"{name.lower()} {levels.get(name, 0):,}"
                                                   for name in ("CRITICAL", "HIGH", "MEDIUM", "LOW"))]
    if rings is not None:
        lines.append(f"  collusion rings      {rings:,}")
    return "\n".join(lines)


WARM = ("/api/overview", "/api/analytics", "/api/rings?limit=40", "/api/leads", "/api/process", "/api/mail",
        "/api/model")


def warm(url: str) -> None:
    """Ask once, in the background, for the analyses the server keeps until the store changes, so that their pages
    open at once (the risk screen scores every invoice the first time: half a minute on 25,000)."""
    import threading

    def run() -> None:
        for path in WARM:
            with contextlib.suppress(OSError):
                urllib.request.urlopen(url + path, timeout=600).read()

    threading.Thread(target=run, name="warm-pages", daemon=True).start()


def stop(children: list[tuple[str, subprocess.Popen]], grace: float = 15.0) -> None:
    """End the processes of the run: they were asked to stop (Ctrl+C reaches them too); those still running after
    the grace period are ended."""
    deadline = time.monotonic() + grace
    for _, process in children:
        if process.poll() is None:
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=max(0.1, deadline - time.monotonic()))
    for _, process in children:
        if process.poll() is None:
            process.terminate()
    for _, process in children:
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=10)


def run_live(args: argparse.Namespace) -> int:
    bootstrap = args.bootstrap or f"127.0.0.1:{kafka_local.PORT}"
    earlier = load_run() if args.keep else None
    if args.keep and earlier is None:
        print("There is no earlier run to open: start without --keep.", file=sys.stderr)
        return 2
    ledger = Path(earlier.ledger) if earlier else ledger_path(args.ledger)

    print("AuditIQ, live\n")
    print("[1/6] Checking what the run needs")
    found = problems(ledger, args.port, bootstrap)
    if found:
        for problem in found:
            print(f"      - {problem}", file=sys.stderr)
        return 1
    note = build_frontend()
    if note:
        print(f"      {note}")

    print("[2/6] Kafka broker")
    if listening(int(bootstrap.rpartition(":")[2]), bootstrap.rpartition(":")[0]):
        print(f"      listening on {bootstrap}")
    else:
        kafka_local.start()
        time.sleep(SETTLE)       # it listens before its coordinators have loaded; a client then warns and retries

    run = earlier or new_run(ledger, args.port)
    run.port = args.port
    env = environment(run, bootstrap)
    os.environ.update({k: env[k] for k in ("AUDITIQ_KAFKA_BOOTSTRAP", "AUDITIQ_KAFKA_PREFIX", "AUDITIQ_DB",
                                           "AUDITIQ_DATABASE_URL", "AUDITIQ_SQLITE_JOURNAL")})
    logs = home() / "logs"
    logs.mkdir(parents=True, exist_ok=True)

    from auditiq import db, stream
    from auditiq.cli import main as auditiq

    print("[3/6] Store and topics")
    if earlier:
        print(f"      the run of {run.started}: {run.db}")
    else:
        remove_earlier_stores()
        with (logs / "setup.log").open("w", encoding="utf-8") as out, contextlib.redirect_stdout(out):
            code = auditiq(["--db", run.db, "setup"])
        if code:
            print(f"      the store could not be set up:\n{tail(logs / 'setup.log')}", file=sys.stderr)
            return 1
        save_run(run)
        print(f"      an empty store with the policy versions and documents: {run.db}")
    topics = stream.ensure_topics(stream.StreamSettings.from_env())
    print(f"      topics: {', '.join(topics)}")

    children: list[tuple[str, subprocess.Popen]] = []
    conn, interrupted = None, False
    try:
        print("[4/6] Web application and workers")
        server = spawn(["--db", run.db, "serve", "--port", str(run.port)], env, logs / "server.log")
        children.append(("the web application", server))
        workers = [kind for kind in KINDS for _ in range(args.workers if kind == "invoice" else 1)]
        for kind in workers:
            children.append((f"the {kind} worker", spawn(
                ["--db", run.db, "stream", "work", "--topic", kind, "--config", args.config, "--batch", str(args.batch)],
                env, logs / f"worker-{kind}.log")))
        if not wait_for_server(run.port, server):
            print(f"      the web application did not start:\n{tail(logs / 'server.log')}", file=sys.stderr)
            return 1
        url = f"http://127.0.0.1:{run.port}"
        print(f"      {url}  (Kafka streams: {url}/kafka)   {len(workers)} workers, configuration {args.config}")
        if not args.no_browser:
            webbrowser.open(f"{url}/kafka")

        conn = db.connect(run.db)
        started = time.monotonic()
        if earlier:
            print("[5/6] Nothing is published: the run is opened as it was left")
        else:
            print(f"[5/6] Publishing {ledger.name} to Kafka")
            sent = publish(ledger, args.limit, emails=not args.no_emails)
            print("      " + ", ".join(f"{n:,} {NAMES[kind]}" for kind, n in sent.items()))
            if not args.no_answer_key:
                keyed = load_answer_key(conn, ledger)
                if keyed:
                    print(f"      the answer key of the ledger ({keyed:,} labels) is loaded for the verification page; "
                          "the audit does not read it")

        print("[6/6] The workers audit what arrives")
        shown, done = "", False
        while True:
            dead = [name for name, process in children if process.poll() is not None]
            if dead:
                log_name = "server.log" if dead[0] == "the web application" else f"worker-{dead[0].split()[1]}.log"
                print(f"\n{dead[0]} stopped:\n{tail(logs / log_name)}", file=sys.stderr)
                return 1
            if not done:
                try:
                    state = snapshot(conn)
                except stream.StreamUnavailable as error:
                    print(f"      (the broker did not answer: {error})")
                    time.sleep(2)
                    continue
                if progress(state) != shown:
                    shown = progress(state)
                    print(f"  {time.monotonic() - started:5.0f} s   {shown}", flush=True)
                if state["messages"] and state["lag"] == 0:
                    done = True
                    from auditiq import rings
                    found_rings = rings.find_rings(conn)["total_rings"]
                    conn.rollback()
                    print("\n" + summary(state, time.monotonic() - started, found_rings))
                    print(f"\nThe pipeline stays live: publish more from {url}/kafka.\n"
                          f"Overview {url}/   Review queue {url}/review   Vendor collusion {url}/rings\n"
                          f"Explainable AI {url}/explain   Audit agent {url}/agent   Trail investigator "
                          f"{url}/investigator   Process mining {url}/process\n"
                          "Press Ctrl+C to stop (the Kafka broker keeps running: `./run.sh stop` or `start.bat stop` ends it).")
                    if args.exit_when_done:
                        return 0
                    warm(url)
            time.sleep(1.5 if not done else 3)
    except KeyboardInterrupt:
        interrupted = True
        print("\nStopping the web application and the workers")
        return 0
    finally:
        if conn is not None:
            conn.close()
        stop(children, grace=15.0 if interrupted else 0.0)      # Ctrl+C reached them too: let them finish a batch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", nargs="?", choices=["run", "stop", "reset"], default="run")
    parser.add_argument("--keep", action="store_true", help="open the last run again instead of streaming a new one")
    parser.add_argument("--ledger", default=DEFAULT_LEDGER, help="a ledger under data/, or the path of its folder")
    parser.add_argument("--limit", type=int, help="only the first N invoices, in ledger order")
    parser.add_argument("--no-emails", action="store_true", help="do not publish the vendor e-mails")
    parser.add_argument("--no-answer-key", action="store_true", help="do not load the ledger's labels for verification")
    parser.add_argument("--workers", type=int, default=2, help="invoice workers (default 2)")
    parser.add_argument("--config", default="C1", choices=["C1", "C2", "C3", "C4", "C5"],
                        help="the configuration invoices are audited with (C2 to C5 need a model)")
    parser.add_argument("--batch", type=int, default=100, help="messages a worker stores per transaction")
    parser.add_argument("--port", type=int, default=PORT, help="port of the web application")
    parser.add_argument("--bootstrap", help="a Kafka broker to use instead of the local one (host:port)")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--exit-when-done", action="store_true", help="stop when every message is processed")
    args = parser.parse_args(argv)
    if args.action == "stop":
        kafka_local.stop()
        return 0
    if args.action == "reset":
        kafka_local.reset()
        removed = remove_earlier_stores()
        (home() / "run.json").unlink(missing_ok=True)
        print(f"{removed} store file(s) of earlier runs removed")
        return 0
    return run_live(args)


if __name__ == "__main__":
    sys.exit(main())
