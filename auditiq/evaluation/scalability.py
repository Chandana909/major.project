"""Scalability of the control stage: throughput against worker processes and ledger size.

    python -m evaluation.scalability

Every transaction carries the records it needs (invoice, PO, GRN, vendor,
approval log, the vendor's other invoices), so auditing one invoice needs
nothing from another audit. The work can therefore be split across worker
processes without coordination. This script measures what that gives on one
machine:

1. Workers. The 20,000 invoices of `large_seed_505` are audited under 15 policy
   versions (300,000 invoice audits) by 1, 2, 4 and 8 worker processes. Each
   worker loads the ledger once; the time measured is the audit itself. The
   total number of findings must be the same for every number of workers.
2. Ledger size. One process audits ledgers of 5,000, 20,000 and 40,000 invoices
   under the reference policy.

Writes results/scalability.md and results/scalability.json. All workers run on
one machine; nothing here measures a deployment on several machines.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import time
from multiprocessing import Pool
from pathlib import Path

from auditiq.controls import run_controls
from auditiq.extraction import extract
from auditiq.policy import PROJECT_ROOT, derive_policy, load_policy

from .policy_change import LEDGERS, VARIANTS

CHUNK = 1000
_transactions: list[dict] = []
_registries: list[dict] = []


def registries() -> list[dict]:
    base = load_policy("2.5").registry
    return [base] + [derive_policy(base, version, "2026-04-01", overrides) for version, _, _, overrides in VARIANTS]


def load(dataset: str) -> None:
    """Run once in each worker process."""
    global _transactions, _registries
    _transactions = extract(Path(dataset))
    _registries = registries()


def audit_chunk(task: tuple[int, int, int]) -> int:
    """Audit transactions [start, end) under one policy; return the number of findings."""
    policy, start, end = task
    clauses = _registries[policy]["clauses"]
    return sum(len(run_controls(t, clauses)) for t in _transactions[start:end])


def ready(_: int) -> int:
    return len(_transactions)


def measure_workers(dataset: Path, workers: int, repeats: int) -> dict:
    with Pool(workers, initializer=load, initargs=(str(dataset),)) as pool:
        n = pool.map(ready, range(workers * 4))[0]                  # every worker has loaded the ledger
        tasks = [(p, s, min(s + CHUNK, n)) for p in range(len(registries())) for s in range(0, n, CHUNK)]
        times, findings = [], None
        for _ in range(repeats):
            began = time.perf_counter()
            total = sum(pool.map(audit_chunk, tasks, chunksize=1))
            times.append(time.perf_counter() - began)
            assert findings in (None, total)
            findings = total
    audits = n * len(registries())
    seconds = statistics.median(times)
    return {"workers": workers, "audits": audits, "seconds": round(seconds, 2), "findings": findings,
            "invoices_per_second": round(audits / seconds), "runs": [round(t, 2) for t in times]}


def measure_size(datasets: list[Path], repeats: int) -> dict:
    transactions = [t for d in datasets for t in extract(d)]
    clauses = load_policy("2.5").registry["clauses"]
    times = []
    for _ in range(repeats):
        began = time.perf_counter()
        findings = sum(len(run_controls(t, clauses)) for t in transactions)
        times.append(time.perf_counter() - began)
    seconds = statistics.median(times)
    return {"invoices": len(transactions), "seconds": round(seconds, 3), "findings": findings,
            "invoices_per_second": round(len(transactions) / seconds),
            "microseconds_per_invoice": round(1e6 * seconds / len(transactions), 1)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=PROJECT_ROOT / "data")
    ap.add_argument("--workers", type=int, nargs="+", default=[1, 2, 4, 8])
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--out", type=Path, default=PROJECT_ROOT / "results")
    args = ap.parse_args()

    by_workers = []
    for workers in args.workers:
        by_workers.append(measure_workers(args.data / "large_seed_505", workers, args.repeats))
        print(by_workers[-1], flush=True)
    assert len({row["findings"] for row in by_workers}) == 1, "the number of findings depends on the number of workers"
    by_size = [measure_size([args.data / name for name in names], args.repeats)
               for names in (["bench_seed_101"], ["large_seed_505"], LEDGERS)]
    for row in by_size:
        print(row, flush=True)

    result = {"produced": time.strftime("%Y-%m-%d %H:%M"), "logical_cpus": os.cpu_count(),
              "machine": f"{platform.processor() or platform.machine()}, Python {platform.python_version()}",
              "repeats": args.repeats, "by_workers": by_workers, "by_size": by_size}
    base = by_workers[0]["seconds"]
    lines = ["# Scalability of the control stage", "",
             f"Produced by `python -m evaluation.scalability` on {result['produced']}. Machine: {result['machine']}, "
             f"{result['logical_cpus']} logical CPUs. Each figure is the median of {args.repeats} runs. All worker "
             "processes run on this one machine.", "",
             "## 1. Worker processes", "",
             f"{by_workers[0]['audits']:,} invoice audits: the 20,000 invoices of `large_seed_505` under "
             f"{len(registries())} policy versions. Every row produced {by_workers[0]['findings']:,} findings.", "",
             "| Worker processes | Seconds | Invoices per second | Speed-up |", "|---|---|---|---|"]
    lines += [f"| {r['workers']} | {r['seconds']:.2f} | {r['invoices_per_second']:,} | {base / r['seconds']:.2f} |"
              for r in by_workers]
    lines += ["", "## 2. Ledger size, one process, reference policy", "",
              "| Invoices | Seconds | Invoices per second | Microseconds per invoice |", "|---|---|---|---|"]
    lines += [f"| {r['invoices']:,} | {r['seconds']:.3f} | {r['invoices_per_second']:,} | {r['microseconds_per_invoice']} |"
              for r in by_size]
    lines += ["", "The time measured is the control stage in memory. Loading a ledger and storing results in the "
                  "database are not included; with storage of every result, finding and trail entry, one process "
                  "audits 20,000 invoices in about one minute (see `policy_change.md`).", ""]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "scalability.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8", newline="\n")
    (args.out / "scalability.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"wrote {args.out / 'scalability.md'}")


if __name__ == "__main__":
    main()
