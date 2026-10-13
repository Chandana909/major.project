"""Evaluation of the configurations that need no LLM.

    python -m evaluation.run_all

For every benchmark ledger (data/bench_seed_*) and the large ledger (data/large_seed_*):
    C1      deterministic controls, count-based score
    C0-IF   isolation forest, cross-fitted threshold
    C0-SVM  one-class SVM, cross-fitted threshold
each evaluated on the whole ledger and, with weights, on its evaluation subset.
For the policy-swap ledger (data/swap_seed_*): C1 under policy v2.5 and v2.6.

Writes results/<dataset>/{C1,C0-IF,C0-SVM}.jsonl and metrics.json, and
results/summary.md. Every number in summary.md is read from a metrics.json
written in the same run.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np

from auditiq.extraction import extract
from auditiq.graph import PRESETS
from auditiq.policy import PROJECT_ROOT, Policy, load_policy

from . import run_c0, run_config
from .metrics import (
    CLASSES,
    JUDGEMENT_CLASSES,
    RULE_CLASSES,
    build_frame,
    evaluate,
    read_labels,
    read_predictions,
    read_subset,
)
from .stats import holm, mcnemar_test

DETECTORS = ["C0-IF", "C0-SVM"]
CONFIGS = DETECTORS + ["C1"]


def severities(policy: Policy) -> dict[str, str]:
    return {k: v["severity"] for k, v in policy.clauses.items()}


def run_c1(transactions: list[dict], version: str, out: Path) -> None:
    """Controls only: the C1 graph, which has no LLM stage."""
    run_config.run(transactions, PRESETS["C1"], load_policy(version), None, out,
                   workers=1, fresh=True, progress=False)


def clean_json(obj):
    """NaN is not valid JSON; write null instead."""
    if isinstance(obj, dict):
        return {k: clean_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_json(v) for v in obj]
    if isinstance(obj, (float, np.floating)):
        return None if math.isnan(obj) else float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    return obj


def construction_checks(m: dict) -> dict[str, bool]:
    """Outcomes fixed by construction (Section VII-A): they test the code, not a hypothesis."""
    v = lambda name: m[name]["value"]  # noqa: E731
    return {
        "C1 reports every invoice of R1-R10 under the labelled clause":
            all(v(f"recall:{k}") == 1.0 for k in RULE_CLASSES),
        "C1 reports no invoice of J1-J4":
            all(v(f"detected:{k}") == 0.0 for k in JUDGEMENT_CLASSES),
        "C1 raises no flag on ordinary clean invoices": v("fpr_ordinary") == 0.0,
        "C1 raises no flag on hard negatives": v("fpr_hard_negative") == 0.0,
        "every clause cited by C1 on an anomalous invoice is the labelled clause": v("citation_correctness") == 1.0,
        "C1 routes no transaction to sampled review": v("sampled_count") == 0.0,
    }


def evaluate_ledger(dataset: Path, out: Path, n_resamples: int) -> dict:
    """C0 and C1 on one ledger: whole-ledger metrics, and the same on the weighted evaluation subset."""
    seed = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))["seed"]
    policy = load_policy("2.5")
    labels, subset = read_labels(dataset), read_subset(dataset)
    out.mkdir(parents=True, exist_ok=True)

    transactions = extract(dataset)
    run_c1(transactions, "2.5", out / "C1.jsonl")
    run_c0.write(run_c0.run(transactions, labels, seed), out)

    sev = severities(policy)
    predictions = {c: read_predictions(out / f"{c}.jsonl") for c in CONFIGS}
    whole = {c: build_frame(labels, p, severity=sev) for c, p in predictions.items()}
    part = {c: build_frame(labels, p, severity=sev, subset=subset) for c, p in predictions.items()}
    result = {
        "dataset": dataset.name, "seed": seed, "policy_version": policy.version,
        "n_invoices": len(labels), "n_subset": len(subset), "bootstrap_resamples": n_resamples,
        "metrics": {c: evaluate(f, n_resamples, seed) for c, f in whole.items()},
        "metrics_on_weighted_subset": {c: evaluate(f, n_resamples, seed) for c, f in part.items()},
    }
    result["construction_checks"] = construction_checks(result["metrics"]["C1"])

    # Paired comparison with the classical detectors on the whole ledger:
    # an invoice is correct when "reported or not" equals "anomalous or not".
    correct = {c: f.cols["pred_any"] == f.cols["anomalous"] for c, f in whole.items()}
    tests = {f"C1 vs {d}": mcnemar_test(correct["C1"], correct[d]) for d in DETECTORS}
    adjusted = holm({k: t["p_value"] for k, t in tests.items()})
    result["mcnemar_detection"] = {k: {**tests[k], **adjusted[k]} for k in tests}

    (out / "metrics.json").write_text(json.dumps(clean_json(result), indent=1) + "\n", encoding="utf-8")
    return result


def evaluate_swap(dataset: Path, out: Path, n_resamples: int) -> dict:
    """C1 on the policy-swap ledger under both policy versions."""
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    labels = read_labels(dataset)
    out.mkdir(parents=True, exist_ok=True)
    boundary = (labels["label"] == "anomalous").to_numpy()
    versions = {
        manifest["policy_version"]: ("label", "clause_ids"),
        manifest["alt_policy_version"]: ("alt_label", "alt_clause_ids"),
    }
    result = {"dataset": dataset.name, "seed": manifest["seed"], "n_invoices": len(labels),
              "n_boundary": int(boundary.sum()), "bootstrap_resamples": n_resamples, "metrics": {}}
    transactions = extract(dataset)
    for version, (label_column, clause_column) in versions.items():
        pred_path = out / f"C1_v{version}.jsonl"
        run_c1(transactions, version, pred_path)
        frame = build_frame(labels, read_predictions(pred_path), label_column=label_column,
                            clause_column=clause_column, severity=severities(load_policy(version)))
        m = evaluate(frame, n_resamples, manifest["seed"])
        flagged = frame.cols["pred_any"]
        # Policy adherence: share of invoices whose cited clauses equal the
        # ground truth of the active version.
        result["metrics"][f"C1 under v{version}"] = {
            "policy_adherence": m["exact_match"],
            "boundary_flagged": {"value": float((flagged & boundary).sum())},
            "others_flagged": {"value": float((flagged & ~boundary).sum())},
        }
    (out / "metrics.json").write_text(json.dumps(clean_json(result), indent=1) + "\n", encoding="utf-8")
    return result


# ------------------------------------------------------------------ summary
def fmt(entry: dict | None, digits: int = 3) -> str:
    if entry is None or entry["value"] is None or (isinstance(entry["value"], float) and math.isnan(entry["value"])):
        return "n/a"
    text = f"{entry['value']:.{digits}f}"
    lo, hi = entry.get("ci_low"), entry.get("ci_high")
    if lo is not None and hi is not None and not (math.isnan(lo) or math.isnan(hi)):
        text += f" [{lo:.{digits}f}, {hi:.{digits}f}]"
    return text


def mean_of(results: list[dict], config: str, metric: str, block: str = "metrics") -> str:
    values = [r[block][config][metric]["value"] for r in results]
    values = [v for v in values if v is not None and not math.isnan(v)]
    return f"{np.mean(values):.3f}" if values else "n/a"


def table(header: list[str], rows: list[list[str]]) -> list[str]:
    return ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|",
            *("| " + " | ".join(r) + " |" for r in rows), ""]


DETECTION = [("Recall", "detection_recall"), ("Precision", "detection_precision"), ("F1", "detection_f1"),
             ("Share of invoices flagged", "flagged_share"), ("FPR, ordinary clean", "fpr_ordinary"),
             ("FPR, hard negatives", "fpr_hard_negative")]


def write_summary(bench: list[dict], swap: dict | None, large: list[dict], path: Path) -> None:
    first = bench[0]
    share = first["metrics"]["C1"]["prevalence"]["value"]
    lines = [
        "# AuditIQ-Bench: results of the configurations that need no LLM",
        "",
        f"Produced by `python -m evaluation.run_all` on {datetime.now():%Y-%m-%d %H:%M}. Policy v{first['policy_version']}. "
        f"Benchmark ledgers: seeds {', '.join(str(r['seed']) for r in bench)}, {first['n_invoices']:,} invoices each, "
        f"of which 420 are anomalous ({share:.1%}) and 120 are hard negatives.",
        f"Intervals are 95% percentile bootstrap intervals over invoices, {first['bootstrap_resamples']} resamples.",
        "C0 is the pair of classical detectors (isolation forest, one-class SVM) with cross-fitted thresholds;",
        "C1 is the deterministic controls alone.",
        "",
        "Configurations C2 to C5 use an LLM and are not in this file. Nothing here is evidence for or",
        "against hypotheses H1 to H6 of the paper.",
        "",
        "## 1. Construction checks (Section VII-A)",
        "",
        "These outcomes follow from the design. A failure means a defect in the generator, the controls or",
        "the scorer.",
        "",
    ]
    everything = bench + large
    checks = list(first["construction_checks"])
    lines += table(["Check"] + [r["dataset"] for r in everything],
                   [[c] + ["pass" if r["construction_checks"][c] else "**FAIL**" for r in everything] for c in checks])

    lines += [
        "## 2. Invoice-level detection on the whole benchmark ledgers",
        "",
        "An invoice counts as detected when the configuration reports it at all. The classical detectors",
        "name no clause, so this is the only level at which they can be compared with C1. Every invoice is",
        "decided with a threshold chosen on the other four folds.",
        "",
    ]
    for r in bench:
        lines += [f"Seed {r['seed']}:", ""]
        lines += table(["Metric"] + CONFIGS,
                       [[label] + [fmt(r["metrics"][c][key]) for c in CONFIGS] for label, key in DETECTION])
    lines += ["Mean over the seeds:", ""]
    lines += table(["Metric"] + CONFIGS, [[label] + [mean_of(bench, c, key) for c in CONFIGS] for label, key in DETECTION])
    lines += ["McNemar's exact test on per-invoice detection correctness, Holm-adjusted over the two comparisons",
              "of each seed:", ""]
    lines += table(["Seed", "Comparison", "Only C1 correct", "Only C0 correct", "Holm-adjusted p"],
                   [[str(r["seed"]), name, str(t["only_a_correct"]), str(t["only_b_correct"]), f"{t['p_holm']:.2e}"]
                    for r in bench for name, t in r["mcnemar_detection"].items()])

    lines += [
        "## 3. Share of each class that is reported (mean over the seeds)",
        "",
        "C1 reports the rule-defined classes because its controls implement the definitions used to inject",
        "them; that part is circular and is not a finding. The judgement classes are the ones the specialist",
        "agents are meant to add.",
        "",
    ]
    lines += table(["Class", "Anomaly"] + CONFIGS,
                   [[k, CLASSES[k].name] + [mean_of(bench, c, f"detected:{k}") for c in CONFIGS] for k in CLASSES])

    lines += [
        "## 4. Routing of the controls-only configuration",
        "",
        "The escalation tier is judged against the invoices that carry a high or critical ground-truth",
        "anomaly (330 per ledger: eight rule-defined classes, and J1, J2 and J4).",
        "",
    ]
    routing = [("Escalation precision", "escalation_precision", 3), ("Escalation recall", "escalation_recall", 3),
               ("Share escalated", "escalated_share", 3), ("Share auto-approved", "approved_share", 3),
               ("High or critical anomalies auto-approved", "approved_high_anomalies", 0),
               ("Macro-F1, rule-defined classes", "macro_f1_rule", 3),
               ("Macro-F1, judgement classes", "macro_f1_judgement", 3)]
    lines += table(["Metric"] + [f"seed {r['seed']}" for r in bench],
                   [[label] + [fmt(r["metrics"]["C1"][key], digits) for r in bench] for label, key, digits in routing])

    lines += [
        "## 5. The weighted evaluation subset reproduces the whole ledger",
        "",
        f"The LLM configurations audit the evaluation subset of each ledger ({first['n_subset']:,} of "
        f"{first['n_invoices']:,} invoices: every anomalous invoice, every hard negative, every original of a",
        "duplicate, and a weighted sample of the other clean invoices). The table compares, for the configurations",
        "that can be run on everything, the metric on the whole ledger with its weighted estimate from the subset",
        "(mean over the seeds). Rates over complete strata agree exactly; rates over the sampled stratum agree",
        "within sampling error.",
        "",
    ]
    rows = []
    for label, key in DETECTION:
        row = [label]
        for c in CONFIGS:
            row += [mean_of(bench, c, key), mean_of(bench, c, key, "metrics_on_weighted_subset")]
        rows.append(row)
    lines += table(["Metric"] + [f"{c}, {scope}" for c in CONFIGS for scope in ("whole", "subset")], rows)

    if swap:
        lines += [
            "## 6. Policy swap, controls only",
            "",
            f"The policy-swap ledger (seed {swap['seed']}) has {swap['n_invoices']:,} invoices. {swap['n_boundary']} boundary "
            "invoices violate one clause under v2.5 and none under v2.6, which differs in the amount tolerance, the",
            "daily invoice count and the Manager approval limit; the others are clean under both. The same controls",
            "are run with each policy file. The paper's experiment (H6) is this comparison for the full pipeline C4.",
            "",
        ]
        lines += table(["Configuration", "Policy adherence", "Boundary invoices flagged", "Other invoices flagged"],
                       [[cfg, fmt(m["policy_adherence"]), fmt(m["boundary_flagged"], 0), fmt(m["others_flagged"], 0)]
                        for cfg, m in swap["metrics"].items()])

    for r in large:
        share = r["metrics"]["C1"]["prevalence"]["value"]
        lines += [
            f"## 7. A ledger at a realistic anomaly rate ({r['n_invoices']:,} invoices, seed {r['seed']})",
            "",
            f"The same 420 anomalous invoices as in a benchmark ledger, in a ledger of {r['n_invoices']:,}: "
            f"{share:.1%} of the invoices are anomalous. Here precision is measured, not computed from the formula",
            "of Section VI-C.",
            "",
        ]
        lines += table(["Metric"] + CONFIGS,
                       [[label] + [fmt(r["metrics"][c][key]) for c in CONFIGS] for label, key in DETECTION])
        lines += ["Share of each judgement class that is reported:", ""]
        lines += table(["Class"] + CONFIGS,
                       [[k] + [fmt({"value": r["metrics"][c][f"detected:{k}"]["value"]}) for c in CONFIGS]
                        for k in JUDGEMENT_CLASSES])
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=PROJECT_ROOT / "data")
    ap.add_argument("--out", type=Path, default=PROJECT_ROOT / "results")
    ap.add_argument("--resamples", type=int, default=1000)
    args = ap.parse_args()

    bench = [evaluate_ledger(d, args.out / d.name, args.resamples) for d in sorted(args.data.glob("bench_seed_*"))]
    if not bench:
        raise SystemExit(f"no benchmark ledger under {args.data}; run `python -m auditiq_bench` first")
    swaps = sorted(args.data.glob("swap_seed_*"))
    swap = evaluate_swap(swaps[0], args.out / swaps[0].name, args.resamples) if swaps else None
    large = [evaluate_ledger(d, args.out / d.name, args.resamples) for d in sorted(args.data.glob("large_seed_*"))]
    write_summary(bench, swap, large, args.out / "summary.md")
    failed = [(r["dataset"], c) for r in bench + large for c, ok in r["construction_checks"].items() if not ok]
    print(f"wrote {args.out / 'summary.md'}")
    if failed:
        print("CONSTRUCTION CHECKS FAILED:", *failed, sep="\n  ")
        raise SystemExit(1)
    print("all construction checks passed")


if __name__ == "__main__":
    main()
