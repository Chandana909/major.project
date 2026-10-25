"""Do the computed revisions resolve the findings? (The revision stage of AuditBench, for the controls.)

    python -m evaluation.revisions                  the three benchmark ledgers and the large ledger
    python -m evaluation.revisions --out results/

For every finding the controls raise under policy v2.5, `auditiq.corrections` computes the revision. An
`amend` or `reapprove` revision changes the invoice or its approval; the changed transaction is audited again
with all twelve controls. A revision is right when the finding is gone and no other finding has appeared. The
other kinds (reject, hold, obtain, verify, consolidate) are actions on the invoice, not changes to it: they are
counted, and every one must name its action. Writes results/revisions.json and revisions.md.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from auditiq.controls import run_controls
from auditiq.corrections import apply, correct
from auditiq.extraction import extract
from auditiq.policy import PROJECT_ROOT, load_policy

from .metrics import read_labels

LEDGERS = ["bench_seed_101", "bench_seed_202", "bench_seed_303", "large_seed_505"]
CHANGING = ("amend", "reapprove")


def check(dataset: Path, clauses: dict) -> dict:
    labels = read_labels(dataset)
    rows = Counter()
    by_rule: dict[str, Counter] = {}
    for txn in extract(dataset):
        flags = run_controls(txn, clauses)
        cls = labels.loc[txn["invoice"]["invoice_id"], "class_id"] or "clean"
        for flag in flags:
            revision = correct(flag, txn, clauses)
            counts = by_rule.setdefault(flag["clause"], Counter())
            counts["findings"] += 1
            counts[f"kind:{revision['kind']}"] += 1
            counts["with action"] += bool(revision["action"])
            if revision["kind"] in CHANGING and revision["changes"]:
                after = run_controls(apply(txn, revision), clauses)
                resolved = all(f["clause"] != flag["clause"] for f in after)
                others = {f["clause"] for f in flags if f is not flag}
                new = [f for f in after if f["clause"] not in others and f["clause"] != flag["clause"]]
                counts["changes checked"] += 1
                counts["resolved"] += resolved
                counts["new finding"] += bool(new)
                rows["checked"] += 1
                rows["resolved"] += resolved and not new
            rows["findings"] += 1
            rows[f"class:{cls}"] += 1
    return {"ledger": dataset.name, "findings": rows["findings"], "changes_checked": rows["checked"],
            "resolved_without_new_finding": rows["resolved"],
            "by_rule": {rule: dict(sorted(c.items())) for rule, c in sorted(by_rule.items())}}


def render(out: dict) -> str:
    lines = ["# Revisions of the control findings", "",
             f"Produced by `python -m evaluation.revisions` on {out['produced']}. Policy v{out['policy_version']}. "
             "For every finding of the controls, `auditiq/corrections.py` computes the revision; an invoice amended "
             "or re-approved as the revision says is audited again with all twelve controls.", "",
             "| Ledger | Findings | Revisions that change the invoice | Resolved, no new finding |",
             "|---|---|---|---|"]
    for r in out["ledgers"]:
        lines.append(f"| `{r['ledger']}` | {r['findings']:,} | {r['changes_checked']:,} | "
                     f"{r['resolved_without_new_finding']:,} |")
    total = out["total"]
    lines += [f"| all | {total['findings']:,} | {total['changes_checked']:,} | {total['resolved_without_new_finding']:,} |",
              "", "By rule, all ledgers together:", "",
              "| Rule | Findings | Kind of revision | Checked | Resolved | New finding | With an action |",
              "|---|---|---|---|---|---|---|"]
    for rule, c in out["by_rule"].items():
        kinds = ", ".join(f"{k.split(':')[1]} {n:,}" for k, n in c.items() if k.startswith("kind:"))
        lines.append(f"| {rule} | {c['findings']:,} | {kinds} | {c.get('changes checked', 0):,} | "
                     f"{c.get('resolved', 0):,} | {c.get('new finding', 0):,} | {c['with action']:,} |")
    lines += ["", "Kinds: amend (the invoice is corrected), reapprove (approved again by the role named), consolidate "
              "(the day's invoices are one purchase), reject (a duplicate), hold (blocked vendor), obtain (a "
              "missing document), verify (supporting evidence). Only amend and reapprove change the invoice, so only "
              "they are audited again; a consolidation names the approver the total needs but leaves the invoices "
              "as they are, so rule 4.1.1 still counts them.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=PROJECT_ROOT / "data")
    ap.add_argument("--out", type=Path, default=PROJECT_ROOT / "results")
    args = ap.parse_args(argv)
    policy = load_policy("2.5")
    clauses = policy.registry["clauses"]
    ledgers = [check(args.data / name, clauses) for name in LEDGERS if (args.data / name).exists()]
    by_rule: dict[str, Counter] = {}
    for r in ledgers:
        for rule, c in r["by_rule"].items():
            by_rule.setdefault(rule, Counter()).update(c)
    total = {k: sum(r[k] for r in ledgers) for k in ("findings", "changes_checked", "resolved_without_new_finding")}
    out = {"produced": time.strftime("%Y-%m-%d %H:%M"), "policy_version": policy.version, "ledgers": ledgers,
           "total": total, "by_rule": {rule: dict(sorted(c.items())) for rule, c in sorted(by_rule.items())}}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "revisions.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")
    (args.out / "revisions.md").write_text(render(out), encoding="utf-8", newline="\n")
    print(json.dumps(total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
