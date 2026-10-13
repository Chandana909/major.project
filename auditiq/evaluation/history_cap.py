"""Does the cap on the vendor history hide the invoices a case depends on?

    python -m evaluation.history_cap                       every dataset under data/
    python -m evaluation.history_cap data/pilot_seed_909

An agent is shown at most ``agents.HISTORY_CAP`` other invoices of the vendor
per selection rule. For a duplicate the invoice it copies must be among them,
for a structuring or same-day group the other members. This script counts, for
every labelled invoice whose vendor history exceeds the cap, whether all the
invoices its case depends on are still shown to each stage that reads the
history. It reads the labels, so it is a check on the selection rule and not
part of the pipeline; the rule itself never sees a label.

Writes results/history_cap.md.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from auditiq import agents
from auditiq.extraction import extract
from auditiq.policy import PROJECT_ROOT

from .metrics import read_labels

# The stage whose remit covers each kind of case.
OWNER = {"R3": "tax_identity", "J1": "tax_identity", "HN_SIMILAR_NUMBER": "tax_identity",
         "HN_RECURRING": "tax_identity", "R6": "vendor_intelligence", "J2": "vendor_intelligence",
         "HN_DAILY_LIMIT": "vendor_intelligence"}
STAGES = {**agents.AGENTS, agents.SINGLE.name: agents.SINGLE}


def coverage(dataset: Path) -> tuple[pd.DataFrame, int, int]:
    """One row per (kind of case, stage): invoices above the cap and how many keep everything they need."""
    labels = read_labels(dataset)
    transactions = {t["invoice"]["invoice_id"]: t for t in extract(dataset)}
    groups = labels[labels["group_id"] != ""].groupby("group_id").groups
    rows = []
    for invoice_id, lab in labels.iterrows():
        txn = transactions[invoice_id]
        if len(txn["vendor_history"]) <= agents.HISTORY_CAP:
            continue
        needed = set(filter(None, lab["related_invoice_id"].split("|")))
        if lab["group_id"]:
            needed |= set(groups[lab["group_id"]]) - {invoice_id}
        needed &= {h["invoice_id"] for h in txn["vendor_history"]}
        if not needed:
            continue
        kind = lab["class_id"] or lab["hard_negative_type"]
        for name, spec in STAGES.items():
            if "history" not in spec.records:
                continue
            shown = {h["invoice_id"] for h in agents.select_history(txn, spec.history_rules)}
            rows.append({"kind": kind, "stage": name, "complete": needed <= shown,
                         "needed": len(needed), "shown": len(needed & shown)})
    capped = sum(len(t["vendor_history"]) > agents.HISTORY_CAP for t in transactions.values())
    return pd.DataFrame(rows, columns=["kind", "stage", "complete", "needed", "shown"]), capped, len(transactions)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("datasets", type=Path, nargs="*")
    ap.add_argument("--out", type=Path, default=PROJECT_ROOT / "results" / "history_cap.md")
    args = ap.parse_args()
    datasets = args.datasets or sorted(p.parent for p in (PROJECT_ROOT / "data").glob("*/labels.csv"))

    lines = ["# Vendor history under the cap", "",
             f"An agent is shown at most {agents.HISTORY_CAP} other invoices of the vendor per selection rule "
             "(`auditiq/agents.py`). The table counts the labelled invoices whose vendor history exceeds the cap "
             "and whose case depends on other invoices, and how many of them still see every one of those "
             "invoices. \"Owning stage\" is the agent whose remit covers the case; the single-prompt auditor "
             "of C2 uses both rules.", "",
             "| Dataset | Invoices above the cap | Kind | Cases | Complete for the owning stage | "
             "Complete for the single auditor |", "|---|---|---|---|---|---|"]
    failures = 0
    for dataset in datasets:
        frame, capped, total = coverage(dataset)
        for kind, part in frame.groupby("kind"):
            owner = part[part["stage"] == OWNER[kind]]
            single = part[part["stage"] == agents.SINGLE.name]
            failures += int((~owner["complete"]).sum() + (~single["complete"]).sum())
            lines.append(f"| `{dataset.name}` | {capped:,} of {total:,} | {kind} | {len(owner)} | "
                         f"{int(owner['complete'].sum())} | {int(single['complete'].sum())} |")
        print(f"{dataset.name}: {capped:,} of {total:,} invoices above the cap, "
              f"{len(frame[frame['stage'] == agents.SINGLE.name])} dependent cases", flush=True)
    lines += ["", f"Cases that lose an invoice they depend on: {failures}.", ""]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"wrote {args.out}; incomplete cases: {failures}")


if __name__ == "__main__":
    main()
