"""Kafka ingestion, measured: a ledger and its vendor e-mails through the four topics into the store.

    python -m evaluation.stream_eval --dataset data/bench_seed_202 --backend postgres --workers 1 2 4 --repeats 3

For each number of invoice workers, with fresh topics (a prefix of their own, 4 partitions each) and a fresh
store holding only the policy versions:

1. the workers are started (one process each on the invoice topic, one each on the other three topics) and
   wait until they have joined their consumer groups;
2. the vendor feed, the invoices in ledger order and the vendor e-mails are published as one burst;
3. the time is taken until every invoice is audited and every e-mail stored.

Each setting is run `--repeats` times (3 by default); the table gives the median run by time, and the file keeps
the time of every run: on one laptop the times vary with what else it is doing.

Then the stream's results are compared with a batch audit of the same ledger (`run --config C1`): the findings
per invoice, and detection against the ledger's labels for both. The e-mails come from
`auditiq_bench.correspondence` (seed 7) and are checked against the invoice each was written about.

Needs a broker (AUDITIQ_KAFKA_BOOTSTRAP) and, for `--backend postgres`, the test database
(AUDITIQ_TEST_DATABASE_URL); each run works in a schema of its own, dropped afterwards. Writes
results/stream/<dataset>.json and .md.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import pandas as pd
from dotenv import dotenv_values

from auditiq import db, policy_ingest, service, stream
from auditiq.config import load_env
from auditiq.graph import preset
from auditiq.policy import load_policy
from auditiq.policy_pdf import make_sample_pdfs
from auditiq_bench import correspondence

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "stream"
PARTITIONS = 4


def fresh_store(backend: str, folder: Path, pdfs: list[Path]) -> tuple[str, callable]:
    """A new store with the policy versions and the policy documents, and a function that removes it."""
    if backend == "sqlite":
        target = str(folder / f"store_{uuid.uuid4().hex[:8]}.db")
        drop = lambda: None  # noqa: E731
    else:
        import psycopg
        url = os.environ.get("AUDITIQ_TEST_DATABASE_URL") or dotenv_values(ROOT / ".env").get("AUDITIQ_TEST_DATABASE_URL")
        if not url:
            raise SystemExit("--backend postgres needs AUDITIQ_TEST_DATABASE_URL")
        schema = f"stream_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(url, autocommit=True) as admin:
            admin.execute(f"CREATE SCHEMA {schema}")
        target = f"{url}{'&' if '?' in url else '?'}options=-csearch_path%3D{schema}"

        def drop():
            with psycopg.connect(url, autocommit=True) as admin:
                admin.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    conn = db.connect(target)
    db.store_policy(conn, load_policy("2.5"), active=True)
    db.store_policy(conn, load_policy("2.6"))
    for pdf in pdfs:
        policy_ingest.ingest(conn, pdf)
    conn.commit()
    conn.close()
    return target, drop


def wait_for_members(settings: stream.StreamSettings, expected: dict[str, int], timeout: float = 120) -> None:
    from confluent_kafka.admin import AdminClient
    admin = AdminClient(settings.client())
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        groups = {settings.group(k): n for k, n in expected.items()}
        described = admin.describe_consumer_groups(list(groups))
        ready = 0
        for group, future in described.items():
            try:
                info = future.result()
                ready += len(info.members) >= groups[group] and str(info.state).endswith("STABLE")
            except Exception:       # noqa: BLE001 - the group does not exist yet
                pass
        if ready == len(groups):
            return
        time.sleep(0.5)
    raise SystemExit("the workers did not join their consumer groups in time")


def kept_findings(target: str) -> dict[str, frozenset]:
    conn = db.connect(target)
    try:
        latest = {r[0]: r[1] for r in conn.execute("SELECT invoice_id, result_id FROM latest_results").fetchall()}
        flags: dict[int, set] = {}
        for result_id, clause in conn.execute("SELECT result_id, clause FROM audit_flags WHERE status = 'kept'"):
            flags.setdefault(int(result_id), set()).add(clause)
        return {i: frozenset(flags.get(int(r), ())) for i, r in latest.items()}
    finally:
        conn.close()


def detection(findings: dict[str, frozenset], labels: pd.DataFrame) -> dict:
    anomalous = labels["label"] == "anomalous"
    flagged = pd.Series({i: bool(findings.get(i)) for i in labels.index})
    tp, fp, fn = int((flagged & anomalous).sum()), int((flagged & ~anomalous).sum()), int((~flagged & anomalous).sum())
    return {"tp": tp, "fp": fp, "fn": fn, "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None, "f1": 2 * tp / (2 * tp + fp + fn) if tp else 0.0}


def batch(dataset: Path, folder: Path, pdfs: list[Path]) -> tuple[dict[str, frozenset], float]:
    target = str(folder / "batch.db")
    conn = db.connect(target)
    db.load_dataset(conn, dataset)
    db.store_policy(conn, load_policy("2.5"), active=True)
    for pdf in pdfs:
        policy_ingest.ingest(conn, pdf)
    conn.commit()
    started = time.perf_counter()
    service.audit_invoices(conn, preset("C1"), db.read_policy(conn), None, db.invoice_ids(conn))
    seconds = time.perf_counter() - started
    conn.close()
    return kept_findings(target), seconds


def one_run(dataset: Path, mbox: Path, backend: str, workers: int, folder: Path, pdfs: list[Path],
            n_invoices: int, n_emails: int) -> dict:
    base = stream.StreamSettings.from_env()
    settings = stream.StreamSettings(base.bootstrap, f"auditiq-eval-{uuid.uuid4().hex[:8]}", PARTITIONS)
    stream.ensure_topics(settings, PARTITIONS)
    target, drop = fresh_store(backend, folder, pdfs)
    env = {**os.environ, "AUDITIQ_KAFKA_PREFIX": settings.prefix, "AUDITIQ_LOG_LEVEL": "WARNING"}
    command = [sys.executable, "-m", "auditiq", "--db", target, "stream", "work", "--topic", "all",
               "--processes", str(workers), "--idle-exit", "8"]
    # The workers' output goes to a file: a pipe nobody reads until the end fills up and stops them.
    log_file = folder / f"workers_{settings.prefix}.log"
    with log_file.open("w", encoding="utf-8") as sink:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=sink, stderr=subprocess.STDOUT)
    try:
        wait_for_members(settings, {"invoice": workers, "vendor": 1, "email": 1, "compliance": 1})
        started = time.perf_counter()
        publisher = stream.Publisher(settings)
        stream.publish_ledger(publisher, dataset)
        stream.publish_mailbox(publisher, mbox)
        publisher.close()
        published = time.perf_counter() - started
        conn = db.connect(target)
        try:
            while True:
                audited = conn.scalar("SELECT COUNT(*) FROM latest_results")
                stored = conn.scalar("SELECT COUNT(*) FROM emails")
                conn.rollback()
                if audited >= n_invoices and stored >= n_emails:
                    break
                if process.poll() is not None:
                    raise SystemExit(f"the workers stopped early:\n{log_file.read_text(encoding='utf-8')[-3000:]}")
                if time.perf_counter() - started > 3600:
                    raise SystemExit("not done after an hour")
                time.sleep(0.2)
            done = time.perf_counter() - started
            log = conn.execute("SELECT partition_no, produced_ms, processed_ms, outcome FROM stream_log "
                               "WHERE topic = ?", (settings.topic("invoice"),)).fetchall()
            linked = dict(conn.execute("SELECT message_id, invoice_id FROM emails").fetchall())
            errors = conn.scalar("SELECT COUNT(*) FROM stream_log WHERE outcome = 'error'")
        finally:
            conn.close()
        process.wait(timeout=120)
        output = log_file.read_text(encoding="utf-8")
        findings = kept_findings(target)
    finally:
        if process.poll() is None:
            process.kill()
        drop()
    latencies = sorted(int(p) - int(q) for _, q, p, _ in log if q)
    per_partition: dict[int, int] = {}
    for partition, *_ in log:
        per_partition[int(partition)] = per_partition.get(int(partition), 0) + 1
    return {"workers": workers, "partitions": PARTITIONS, "published_seconds": round(published, 2),
            "seconds": round(done, 2), "invoices_per_second": round(n_invoices / done, 1),
            "latency_ms": {"median": statistics.median(latencies), "p95": latencies[int(0.95 * (len(latencies) - 1))],
                           "max": latencies[-1]},
            "invoices_per_partition": [per_partition.get(p, 0) for p in range(PARTITIONS)],
            "errors": int(errors), "worker_exit_code": process.returncode, "findings": findings, "linked": linked,
            "worker_output_tail": output[-500:] if process.returncode else ""}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, default=ROOT / "data" / "bench_seed_202")
    ap.add_argument("--backend", choices=["sqlite", "postgres"], default="postgres")
    ap.add_argument("--workers", type=int, nargs="+", default=[1, 2, 4])
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args(argv)
    load_env()
    dataset = args.dataset.resolve()
    labels = pd.read_csv(dataset / "labels.csv", dtype=str, keep_default_na=False).set_index("invoice_id")
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        pdfs = make_sample_pdfs(folder / "pdf")
        messages, mail_labels = correspondence.generate(dataset, seed=7)
        mbox = folder / "mail.mbox"
        correspondence.write(messages, mail_labels, mbox)
        print(f"{len(labels):,} invoices, {len(messages):,} e-mails; batch audit (C1) for comparison")
        batch_findings, batch_seconds = batch(dataset, folder, pdfs)
        runs = []
        for workers in args.workers:
            repeats = []
            for repeat in range(args.repeats):
                print(f"{workers} invoice worker(s) on {PARTITIONS} partitions, {args.backend}, run {repeat + 1} "
                      f"of {args.repeats} ...", flush=True)
                run = one_run(dataset, mbox, args.backend, workers, folder, pdfs, len(labels), len(messages))
                findings, linked = run.pop("findings"), run.pop("linked")
                differ = sorted(i for i in labels.index
                                if findings.get(i, frozenset()) != batch_findings.get(i, frozenset()))
                clauses: dict[str, int] = {}
                for i in differ:
                    for c in findings.get(i, frozenset()) ^ batch_findings.get(i, frozenset()):
                        clauses[c] = clauses.get(c, 0) + 1
                run.update(detection=detection(findings, labels), same_findings_as_batch=len(labels) - len(differ),
                           differing_invoices=len(differ), differing_clauses=clauses, differing_examples=differ[:10],
                           emails_linked_right=sum(linked.get(m["message_id"]) == m["invoice_id"]
                                                   for m in mail_labels))
                print(f"  {run['seconds']} s, {run['invoices_per_second']} invoices/s, median latency "
                      f"{run['latency_ms']['median']} ms; same findings as batch: {run['same_findings_as_batch']:,}; "
                      f"F1 {run['detection']['f1']:.3f}")
                repeats.append(run)
            # The median run by time stands for the setting; every run must agree with the batch audit.
            median = sorted(repeats, key=lambda r: r["seconds"])[len(repeats) // 2]
            runs.append({**median, "seconds_of_each_run": [r["seconds"] for r in repeats],
                         "same_findings_as_batch": min(r["same_findings_as_batch"] for r in repeats),
                         "emails_linked_right": min(r["emails_linked_right"] for r in repeats),
                         "errors": sum(r["errors"] for r in repeats)})
    result = {"dataset": dataset.name, "invoices": len(labels), "emails": len(messages), "backend": args.backend,
              "partitions": PARTITIONS, "repeats": args.repeats, "machine": f"{platform.processor() or platform.machine()}, {os.cpu_count()} "
              f"logical CPUs, {platform.system()} {platform.release()}",
              "kafka": stream.StreamSettings.from_env().bootstrap, "batch": {
                  "seconds": round(batch_seconds, 2), "detection": detection(batch_findings, labels)},
              "runs": runs, "measured_at": time.strftime("%Y-%m-%d %H:%M")}
    RESULTS.mkdir(parents=True, exist_ok=True)
    stem = f"{dataset.name}_{args.backend}"
    (RESULTS / f"{stem}.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    (RESULTS / f"{stem}.md").write_text(report(result), encoding="utf-8")
    print(f"wrote {RESULTS / (stem + '.md')}")
    return 0


def report(r: dict) -> str:
    b = r["batch"]["detection"]
    lines = [f"# Kafka ingestion: {r['dataset']} on {r['backend']}", "",
             f"{r['invoices']:,} invoices of `{r['dataset']}` and {r['emails']:,} vendor e-mails "
             f"(`auditiq_bench.correspondence`, seed 7) published as one burst to four topics of {r['partitions']} "
             f"partitions on a local broker ({r['kafka']}); invoice workers audit with C1. Machine: {r['machine']}. "
             f"Measured {r['measured_at']} by `python -m evaluation.stream_eval`.", "",
             f"Each setting was run {r.get('repeats', 1)} times: the table gives the median run by time (the "
             "times of every run in brackets); the findings and e-mail columns give the worst of the runs and the "
             "errors their sum.", "",
             "| Invoice workers | Seconds to the last result | Invoices/s | Latency median / p95 (ms) | "
             "Invoices per partition | Same findings as batch | F1 | E-mails linked right | Errors |",
             "|---:|---:|---:|---:|---|---:|---:|---:|---:|"]
    for run in r["runs"]:
        each = ", ".join(str(x) for x in run.get("seconds_of_each_run", []))
        lines.append(f"| {run['workers']} | {run['seconds']} ({each}) | {run['invoices_per_second']:,} | "
                     f"{run['latency_ms']['median']:,} / {run['latency_ms']['p95']:,} | "
                     f"{' / '.join(str(n) for n in run['invoices_per_partition'])} | "
                     f"{run['same_findings_as_batch']:,} of {r['invoices']:,} | {run['detection']['f1']:.3f} | "
                     f"{run['emails_linked_right']:,} of {r['emails']:,} | {run['errors']} |")
    lines += ["", f"Batch audit of the same ledger (C1, one process): {r['batch']['seconds']} s, F1 {b['f1']:.3f} "
              f"(precision {b['precision']:.3f}, recall {b['recall']:.3f}).", ""]
    differing = {c: n for run in r["runs"] for c, n in run["differing_clauses"].items()}
    if differing:
        lines += ["Where the stream and the batch differ, by clause (an invoice on the stream is audited against the "
                  "vendor's earlier invoices only; the batch audit sees the whole ledger): "
                  + ", ".join(f"{c}: {n}" for c, n in sorted(differing.items())) + ".", ""]
    lines += ["Latency is the time from publication to the stored result, for a burst published at once: it is "
              "mostly time spent waiting in the topic, and falls as workers are added.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
