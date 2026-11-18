"""The judgement-rule leads (auditiq/leads.py) on every benchmark ledger, against each ledger's answer key.

    python -m evaluation.leads_eval [--ledgers final_seed_2025 bench_seed_101 ...] [--out results/leads]

The leads were written and corrected on final_seed_2025 alone (18 November 2026): the first version listed 136 of
its 141 near duplicates (J1) and 35 of its 141 structuring invoices (J2); the misses showed two defects in reading
invoice numbers and that a structuring group's descriptions differ by design, and the method was changed once and
then frozen. The other ledgers were not looked at before this script ran on them: they are the held-out test.
Each ledger is loaded into a new SQLite store in a temporary folder; nothing is audited, since the leads read the
ledger and the policy only. Writes leads.json and leads.md.
"""
from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

from auditiq import db, leads
from auditiq.policy import load_policy

ROOT = Path(__file__).resolve().parents[1]
DEVELOPED_ON = "final_seed_2025"
LEDGERS = ["final_seed_2025", "bench_seed_101", "bench_seed_202", "bench_seed_303", "large_seed_505", "pilot_seed_909"]


def evaluate(ledger: Path, work: Path) -> dict:
    conn = db.connect(work / f"{ledger.name}.db")
    try:
        db.load_dataset(conn, ledger)
        db.store_policy(conn, load_policy("2.5"), active=True)
        start = time.perf_counter()
        found = leads.judgement_leads(conn)
        seconds = time.perf_counter() - start
        invoices = int(conn.scalar("SELECT COUNT(*) FROM invoices"))
    finally:
        conn.close()
    return {"ledger": ledger.name, "invoices": invoices, "held_out": ledger.name != DEVELOPED_ON,
            "seconds": round(seconds, 2), "answer_key": found["answer_key"],
            "near_duplicates": found["near_duplicates"]["count"], "structuring_groups": found["structuring"]["count"],
            "structuring_invoices": found["structuring"]["invoices"]}


def markdown(rows: list[dict]) -> str:
    lines = ["# Judgement-rule leads against the answer keys", "",
             "Source: `python -m evaluation.leads_eval`. A lead is an invoice the code lists for a reviewer under rule "
             "2.2.2 (near duplicate) or 4.1.2 (structuring across days), with the policy's guide values; it is not a "
             "finding. Precision counts every listed invoice that is not labelled for the rule, hard negatives "
             "included. The method was developed on `final_seed_2025` (first version: 136 of 141 near duplicates, "
             "35 of 141 structuring invoices; changed once, then frozen); the other ledgers are held out.", "",
             "| Ledger | Invoices | Held out | Rule | Labelled | Listed | Listed and labelled | Recall | Precision | "
             "Listed otherwise |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        key = r["answer_key"] or {}
        for clause in ("2.2.2", "4.1.2"):
            c = key.get(clause)
            if not c:
                lines.append(f"| {r['ledger']} | {r['invoices']:,} | {'yes' if r['held_out'] else 'no'} | {clause} | "
                             "no answer key | | | | | |")
                continue
            other = ", ".join(f"{k} {v}" for k, v in c["listed_otherwise"].items()) or "none"
            recall = "–" if c["recall"] is None else f"{c['recall']:.1%}"
            precision = "–" if c["precision"] is None else f"{c['precision']:.1%}"
            lines.append(f"| {r['ledger']} | {r['invoices']:,} | {'yes' if r['held_out'] else 'no'} | {clause} | "
                         f"{c['labelled']:,} | {c['listed']:,} | {c['listed_labelled']:,} | {recall} | {precision} | "
                         f"{other} |")
    lines += ["", "The generator plants J1 and J2 in the pattern the policy describes, and keeps clean invoices clear "
              "of the structuring guide with a wider margin, so agreement here shows that the code follows the "
              "policy's wording on these ledgers; it is not an estimate of how real duplicates or split purchases look.",
              ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledgers", nargs="*", default=LEDGERS)
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "leads")
    args = ap.parse_args()
    rows = []
    with tempfile.TemporaryDirectory(prefix="auditiq-leads-") as work:
        for name in args.ledgers:
            path = ROOT / "data" / name
            if not (path / "invoices.csv").exists():
                print(f"{name}: not on disk, skipped")
                continue
            rows.append(evaluate(path, Path(work)))
            print(f"{name}: {json.dumps(rows[-1]['answer_key'])}", flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "leads.json").write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
    (args.out / "leads.md").write_text(markdown(rows), encoding="utf-8")
    print(f"wrote {args.out / 'leads.md'}")


if __name__ == "__main__":
    main()
