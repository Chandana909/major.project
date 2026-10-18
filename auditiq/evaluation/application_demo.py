"""A policy change through the deployed path: the 20,000-invoice ledger in a database.

    python -m evaluation.application_demo

Builds a new SQLite store with the large ledger and the two released policy
versions (2.5 active), audits every invoice with the controls (C1), adopts the
strict policy document of the policy-change experiment
(policy/variants/Company_Policy_v3.12.pdf) as the active version, and audits
every invoice again. Each audit stores every result, finding and trail entry.
Reports what the reviewers would see before and after, and how long adoption
and re-auditing took. No file of the system is edited between the two audits,
and no language model is used.

Writes results/application_demo.md and results/application_demo.json. The store
is .auditiq/application_demo.db and is replaced on each run.
"""
from __future__ import annotations

import argparse
import json
import platform
import time
from pathlib import Path

from auditiq import db, policy_extract, policy_ingest, service
from auditiq.graph import PRESETS
from auditiq.policy import PROJECT_ROOT, load_policy
from auditiq.policy_pdf import make_sample_pdfs

LEDGER = "large_seed_505"
STRICT = PROJECT_ROOT / "policy" / "variants" / "Company_Policy_v3.12.pdf"
RULES = ["5.1.1", "4.1.1", "2.1.1", "4.3.1", "2.1.3", "2.2.1"]


def snapshot(conn: db.Database, run_id: int) -> dict:
    summary = service.run_summary(conn, run_id)
    by_rule = {r["clause"]: int(r["n"]) for r in conn.execute(
        "SELECT f.clause, COUNT(*) AS n FROM audit_flags f JOIN audit_results r ON r.result_id = f.result_id "
        "WHERE r.run_id = ? AND f.status = 'kept' GROUP BY f.clause", (run_id,)).fetchall()}
    return {"invoices": summary["invoices"], "findings": summary["flags"], "states": summary["states"],
            "findings_by_rule": by_rule}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", type=Path, default=PROJECT_ROOT / ".auditiq" / "application_demo.db")
    ap.add_argument("--out", type=Path, default=PROJECT_ROOT / "results")
    args = ap.parse_args()
    if not STRICT.exists():
        raise SystemExit(f"{STRICT} is missing; run python -m evaluation.policy_change first")
    if args.store.exists():
        args.store.unlink()

    conn = db.connect(args.store)
    db.load_dataset(conn, PROJECT_ROOT / "data" / LEDGER)
    for version in ("2.5", "2.6"):
        db.store_policy(conn, load_policy(version), active=version == "2.5")
    for pdf in make_sample_pdfs():
        policy_ingest.ingest(conn, pdf)
    ids = db.invoice_ids(conn)

    began = time.perf_counter()
    before_run = service.audit_invoices(conn, PRESETS["C1"], db.read_policy(conn), None, ids, note="before")
    audit_before = time.perf_counter() - began

    began = time.perf_counter()
    report = policy_extract.adopt(conn, STRICT, activate=True)
    adopt_seconds = time.perf_counter() - began
    if not report["adopted"]:
        raise SystemExit(f"the strict policy was not adopted: {report['problems']}")

    began = time.perf_counter()
    after_run = service.audit_invoices(conn, PRESETS["C1"], db.read_policy(conn), None, ids, note="after")
    audit_after = time.perf_counter() - began

    result = {"produced": time.strftime("%Y-%m-%d %H:%M"), "ledger": LEDGER, "store": "SQLite",
              "machine": f"{platform.processor() or platform.machine()}, Python {platform.python_version()}",
              "adopted_version": report["version"], "changes": report["changes"],
              "seconds": {"audit_before": round(audit_before, 1), "adopt": round(adopt_seconds, 3),
                          "audit_after": round(audit_after, 1)},
              "before": snapshot(conn, before_run), "after": snapshot(conn, after_run)}
    conn.close()
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "application_demo.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8", newline="\n")
    (args.out / "application_demo.md").write_text(markdown(result), encoding="utf-8", newline="\n")
    print(f"wrote {args.out / 'application_demo.md'}")


def markdown(r: dict) -> str:
    b, a = r["before"], r["after"]
    state = lambda s, k: s["states"].get(k, 0)  # noqa: E731
    lines = [
        "# A policy change in the application", "",
        f"Produced by `python -m evaluation.application_demo` on {r['produced']}. Ledger `{r['ledger']}` "
        f"({b['invoices']:,} invoices) in a {r['store']} store; {r['machine']}. Every invoice is audited with the "
        "controls (C1) under version 2.5, the strict policy document (`Company_Policy_v3.12.pdf`) is adopted as the "
        "active version, and every invoice is audited again. No file of the system is edited in between, and no "
        "language model is used.", "",
        "| | Version 2.5 | After adopting the strict policy |", "|---|---|---|",
        f"| Findings stored | {b['findings']:,} | {a['findings']:,} |",
        f"| Invoices waiting for review | {state(b, 'PENDING_REVIEW'):,} | {state(a, 'PENDING_REVIEW'):,} |",
        f"| Invoices approved automatically | {state(b, 'AUTO_APPROVED'):,} | {state(a, 'AUTO_APPROVED'):,} |",
    ]
    for rule in RULES:
        lines.append(f"| Findings under rule {rule} | {b['findings_by_rule'].get(rule, 0):,} | "
                     f"{a['findings_by_rule'].get(rule, 0):,} |")
    s = r["seconds"]
    lines += ["", f"Adopting the document (reading it, storing version {r['adopted_version']} and its passages) took "
                  f"{s['adopt']:.2f} s. Auditing the ledger with storage of every result, finding and trail entry took "
                  f"{s['audit_before']:.0f} s before and {s['audit_after']:.0f} s after the change.", "",
              "Changes the document makes to the active version: "
              + "; ".join(f"{c['clause']} {c['parameter']}: {c['from']} to {c['to']}" for c in r["changes"]) + ".", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
