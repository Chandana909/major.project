"""Compare prediction files of several configurations on one dataset.

    python -m evaluation.report --dataset data/seed_101 results/seed_101/C2.jsonl results/seed_101/C4.jsonl
    python -m evaluation.report --dataset data/seed_101 results/seed_101/C*.jsonl --compare C3:C2 C4:C3 C5:C4

The files are compared on the invoices that all of them contain, so a pilot on
a subset can be reported with the same command. ``--compare A:B`` adds
McNemar's exact test on per-invoice correctness (cited clauses equal the
labelled clauses), Holm-adjusted over the listed pairs.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

from auditiq.policy import load_policy

from .metrics import build_frame, evaluate, read_labels, read_predictions, read_subset
from .stats import holm, mcnemar_test

ROWS = [
    ("Macro-F1, rule-defined classes", "macro_f1_rule"),
    ("Macro-F1, judgement classes", "macro_f1_judgement"),
    ("Macro-recall, judgement classes", "macro_recall_judgement"),
    ("Recall, J1 near-duplicate", "recall:J1"),
    ("Recall, J2 structuring across days", "recall:J2"),
    ("Recall, J3 description against the PO", "recall:J3"),
    ("Recall, J4 goods-receipt remark", "recall:J4"),
    ("Invoice-level recall", "detection_recall"),
    ("Invoice-level precision", "detection_precision"),
    ("FPR, ordinary clean", "fpr_ordinary"),
    ("FPR, hard negatives", "fpr_hard_negative"),
    ("Precision at 2% prevalence", "precision_at_2pct_prevalence"),
    ("Citation correctness", "citation_correctness"),
    ("Model findings naming a violated rule", "model_rule_precision"),
    ("Exact match of cited clauses", "exact_match"),
    ("Escalation precision", "escalation_precision"),
    ("Escalation recall", "escalation_recall"),
    ("Invoices in sampled review", "sampled_count"),
    ("True anomalies in sampled review", "sampled_true_anomalies"),
    ("High or critical anomalies auto-approved", "approved_high_anomalies"),
    ("LLM calls per invoice", "llm_calls_per_invoice"),
    ("Tokens per invoice", "tokens_per_invoice"),
]
COUNTS = {"sampled_count", "sampled_true_anomalies", "approved_high_anomalies", "tokens_per_invoice"}


def cell(entry: dict | None, key: str) -> str:
    if entry is None or entry["value"] is None or math.isnan(entry["value"]):
        return "n/a"
    digits = 0 if key in COUNTS else (2 if key == "llm_calls_per_invoice" else 3)
    text = f"{entry['value']:.{digits}f}"
    lo, hi = entry.get("ci_low"), entry.get("ci_high")
    if key not in COUNTS and lo is not None and hi is not None and not (math.isnan(lo) or math.isnan(hi)):
        text += f" [{lo:.{digits}f}, {hi:.{digits}f}]"
    return text


def build(dataset: Path, files: list[Path], policy_version: str, resamples: int,
          comparisons: list[str]) -> str:
    labels = read_labels(dataset)
    severity = {k: v["severity"] for k, v in load_policy(policy_version).clauses.items()}
    predictions = {f.stem: read_predictions(f) for f in files}
    ids = sorted(set(labels.index).intersection(*(set(p) for p in predictions.values())))
    if not ids:
        raise SystemExit("the prediction files have no invoice in common with the labels")
    # Weights apply when the files cover exactly the evaluation subset of the ledger.
    subset = read_subset(dataset) if (dataset / "eval_subset.csv").exists() else None
    if subset is not None and set(ids) == set(subset.index) and len(ids) < len(labels):
        frames = {name: build_frame(labels, p, severity=severity, subset=subset) for name, p in predictions.items()}
        scope = "the evaluation subset, weighted to the whole ledger"
    else:
        frames = {name: build_frame(labels, p, ids=ids, severity=severity) for name, p in predictions.items()}
        scope = "the whole ledger" if len(ids) == len(labels) else "an unweighted sample: rates describe the sample only"
    metrics = {name: evaluate(frame, resamples) for name, frame in frames.items()}

    names = list(frames)
    lines = [f"Dataset `{dataset.name}`, policy v{policy_version}, {len(ids)} invoices "
             f"({int(frames[names[0]].cols['anomalous'].sum())} anomalous); {scope}. "
             f"Intervals: 95% bootstrap, {resamples} resamples.", "",
             "| Metric | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for label, key in ROWS:
        lines.append(f"| {label} | " + " | ".join(cell(metrics[n].get(key), key) for n in names) + " |")
    if comparisons:
        tests = {}
        for pair in comparisons:
            a, b = pair.split(":")
            tests[pair] = mcnemar_test(frames[a].cols["exact"], frames[b].cols["exact"])
        adjusted = holm({k: t["p_value"] for k, t in tests.items()})
        lines += ["", "| Comparison | Only first correct | Only second correct | p | Holm-adjusted p |", "|---|---|---|---|---|"]
        for pair, t in tests.items():
            lines.append(f"| {pair.replace(':', ' vs ')} | {t['only_a_correct']} | {t['only_b_correct']} | "
                         f"{t['p_value']:.3g} | {adjusted[pair]['p_holm']:.3g} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", type=Path, nargs="+", help="prediction files (.jsonl)")
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--policy", default="2.5")
    ap.add_argument("--resamples", type=int, default=1000)
    ap.add_argument("--compare", nargs="*", default=[], metavar="A:B")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    text = build(args.dataset, args.files, args.policy, args.resamples, args.compare)
    if args.out:
        args.out.write_text(text, encoding="utf-8", newline="\n")
    print(text)


if __name__ == "__main__":
    main()
