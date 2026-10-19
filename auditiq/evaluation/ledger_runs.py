"""Every ledger of the project run through the deployed system, as an organisation would use it.

    python -m evaluation.ledger_runs

For each of the six datasets in data/: the ledger is written as an Excel
workbook and loaded from it through the checked import (auditiq.ledger_import),
policy versions 2.5 (active) and 2.6 are stored, and every invoice is audited
with the controls (C1) through the data store, which keeps every result,
finding and trail entry. The outcome is then read back from the store, as the
review queue and the dashboard read it: routes, findings by rule, the review
queue and the amount it holds, and how the outcome compares with the answer key
of the synthetic ledger (which the audit never reads). No language model is used.

Writes results/ledger_runs.md and results/ledger_runs.json.
"""
from __future__ import annotations

import argparse
import json
import platform
import tempfile
import time
from pathlib import Path

from auditiq import db, ledger_import, service
from auditiq.graph import PRESETS
from auditiq.policy import PROJECT_ROOT, load_policy

DATA = PROJECT_ROOT / "data"
OUT = PROJECT_ROOT / "results"


def run_ledger(folder: Path, work: Path) -> dict:
    book = ledger_import.export_workbook(folder, work / f"{folder.name}.xlsx")
    conn = db.connect(str(work / f"{folder.name}.db"))
    try:
        began = time.perf_counter()
        ledger = ledger_import.read(book, conn)
        if not ledger.usable:
            raise SystemExit(f"{folder.name}: the workbook was refused: {ledger.problems}")
        ledger.name = folder.name
        counts = ledger_import.load(conn, ledger)
        load_seconds = time.perf_counter() - began
        db.store_policy(conn, load_policy("2.5"), active=True)
        db.store_policy(conn, load_policy("2.6"))

        began = time.perf_counter()
        run_id = service.audit_invoices(conn, PRESETS["C1"], db.read_policy(conn), None, db.invoice_ids(conn),
                                        note="evaluation.ledger_runs")
        audit_seconds = time.perf_counter() - began
        return {"ledger": folder.name, "workbook_kb": book.stat().st_size // 1024, "records": counts,
                "seconds": {"load": round(load_seconds, 1), "audit": round(audit_seconds, 1)},
                **outcome(conn, run_id)}
    finally:
        conn.close()


def outcome(conn: db.Database, run_id: int) -> dict:
    summary = service.run_summary(conn, run_id)
    by_rule = {r[0]: int(r[1]) for r in conn.execute(
        "SELECT f.clause, COUNT(*) FROM audit_flags f JOIN audit_results r ON r.result_id = f.result_id "
        "WHERE r.run_id = ? AND f.status = 'kept' GROUP BY f.clause ORDER BY f.clause", (run_id,)).fetchall()}
    flagged = int(conn.scalar("SELECT COUNT(*) FROM audit_results WHERE run_id = ? AND flag_count > 0", (run_id,)))
    queue = conn.execute("SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM v_review_queue").fetchone()
    levels = {r[0]: int(r[1]) for r in conn.execute(
        "SELECT risk_level, COUNT(*) FROM v_review_queue GROUP BY risk_level").fetchall()}
    top = [{"vendor": r[0], "waiting": int(r[1]), "amount": round(float(r[2]), 2)} for r in conn.execute(
        "SELECT vendor_name, COUNT(*), SUM(amount) FROM v_review_queue GROUP BY vendor_name "
        "ORDER BY COUNT(*) DESC, SUM(amount) DESC LIMIT 3").fetchall()]
    # The answer key of the synthetic ledger, against the stored routes.
    groups = conn.execute("""
        SELECT CASE WHEN b.label = 'anomalous' AND b.class_id LIKE 'R%' THEN 'rule-defined anomaly'
                    WHEN b.label = 'anomalous' THEN 'judgement anomaly'
                    WHEN b.label = 'hard_negative' THEN 'hard negative'
                    ELSE 'ordinary clean' END AS kind,
               COUNT(*) AS invoices,
               SUM(CASE WHEN r.flag_count > 0 THEN 1 ELSE 0 END) AS with_finding,
               SUM(CASE WHEN r.workflow_status = 'PENDING_REVIEW' THEN 1 ELSE 0 END) AS escalated
        FROM benchmark_labels b JOIN audit_results r ON r.invoice_id = b.invoice_id AND r.run_id = ?
        GROUP BY kind""", (run_id,)).fetchall()
    key = {g[0]: {"invoices": int(g[1]), "with_finding": int(g[2]), "escalated": int(g[3])} for g in groups}
    return {"invoices": summary["invoices"], "findings": summary["flags"], "invoices_with_a_finding": flagged,
            "states": summary["states"], "findings_by_rule": by_rule,
            "review_queue": {"invoices": int(queue[0]), "amount": round(float(queue[1]), 2), "risk_levels": levels,
                             "top_vendors": top},
            "answer_key": key}


def markdown(result: dict) -> str:
    rows = result["ledgers"]
    rules = sorted({rule for r in rows for rule in r["findings_by_rule"]})
    kinds = ["rule-defined anomaly", "judgement anomaly", "hard negative", "ordinary clean"]
    lines = [
        "# Every ledger through the deployed system", "",
        f"Produced by `python -m evaluation.ledger_runs` on {result['produced']}; {result['machine']}. Each ledger "
        "is written as an Excel workbook and loaded from it through the checked import, policy version 2.5 is "
        "active, and every invoice is audited with the controls (C1) through a SQLite store that keeps every "
        "result, finding and trail entry. The outcome below is read back from the store. No language model is "
        "used.", "",
        "## 1. Outcome of the audit", "",
        "| Ledger | Invoices | Findings | Invoices with a finding | Escalated to review | Approved automatically "
        "| Amount waiting for review (INR) | Load from workbook (s) | Audit (s) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['ledger']} | {r['invoices']:,} | {r['findings']:,} | {r['invoices_with_a_finding']:,} | "
                     f"{r['states'].get(db.PENDING_REVIEW, 0):,} | {r['states'].get(db.AUTO_APPROVED, 0):,} | "
                     f"{r['review_queue']['amount']:,.2f} | {r['seconds']['load']} | {r['seconds']['audit']} |")
    lines += ["", "## 2. Findings by rule", "",
              "| Rule | " + " | ".join(r["ledger"] for r in rows) + " |", "|---|" + "---|" * len(rows)]
    for rule in rules:
        lines.append(f"| {rule} | " + " | ".join(f"{r['findings_by_rule'].get(rule, 0):,}" for r in rows) + " |")
    lines += ["", "## 3. Against the answer key", "",
              "The answer key of each synthetic ledger (`labels.csv`) is never read by the audit. Each cell is "
              "*escalated / with a finding / invoices* of that kind.", "",
              "| Ledger | " + " | ".join(kinds) + " |", "|---|" + "---|" * len(kinds)]
    for r in rows:
        cells = []
        for kind in kinds:
            k = r["answer_key"].get(kind)
            cells.append(f"{k['escalated']:,} / {k['with_finding']:,} / {k['invoices']:,}" if k else "-")
        lines.append(f"| {r['ledger']} | " + " | ".join(cells) + " |")
    lines += ["", "Reading the table: every rule-defined anomaly gets a finding; those whose findings are all of "
              "low or medium severity (a weekend date, a round amount, a GSTIN format) score below the "
              "escalation threshold of 50 and are approved with the finding recorded. Judgement anomalies get no "
              "finding from the controls: they are the task of the language-model agents. No hard negative and "
              "no ordinary invoice gets a finding.", "",
              "## 4. The review queue", "",
              "| Ledger | Waiting | By risk level | Vendors with the most invoices waiting |", "|---|---|---|---|"]
    for r in rows:
        q = r["review_queue"]
        levels = ", ".join(f"{level} {n:,}" for level, n in sorted(q["risk_levels"].items()))
        top = "; ".join(f"{t['vendor']} ({t['waiting']})" for t in q["top_vendors"])
        lines.append(f"| {r['ledger']} | {q['invoices']:,} | {levels} | {top} |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=DATA)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    folders = sorted(f for f in args.data.iterdir() if (f / "invoices.csv").exists())
    ledgers = []
    with tempfile.TemporaryDirectory() as work:
        for folder in folders:
            ledgers.append(run_ledger(folder, Path(work)))
            r = ledgers[-1]
            print(f"{r['ledger']}: {r['invoices']:,} invoices, {r['findings']:,} findings, "
                  f"{r['review_queue']['invoices']:,} waiting for review", flush=True)
    result = {"produced": time.strftime("%Y-%m-%d %H:%M"),
              "machine": f"{platform.processor() or platform.machine()}, Python {platform.python_version()}",
              "policy_version": "2.5", "configuration": "C1", "ledgers": ledgers}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "ledger_runs.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8", newline="\n")
    (args.out / "ledger_runs.md").write_text(markdown(result), encoding="utf-8", newline="\n")
    print(f"wrote {args.out / 'ledger_runs.md'}")


if __name__ == "__main__":
    main()
