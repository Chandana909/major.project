"""Tests of the evaluation harness.

    python -m pytest tests/test_eval.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from auditiq.extraction import extract
from auditiq.graph import PRESETS
from auditiq.policy import load_policy
from evaluation import history_cap, run_c0, run_config
from evaluation.metrics import bootstrap, build_frame, compute, read_labels, read_predictions, read_subset
from evaluation.stats import consistency, holm, mcnemar_test, non_inferior

ROOT = Path(__file__).resolve().parents[1]

SEVERITY = {k: v["severity"] for k, v in
            json.loads((ROOT / "policy" / "policy_v2.5.json").read_text(encoding="utf-8"))["clauses"].items()}


# ---------------------------------------------------------------- metrics
def tiny():
    """Six invoices whose metrics can be checked by hand."""
    labels = pd.DataFrame(
        [("A", "anomalous", "R1", "2.1.1", ""),
         ("B", "anomalous", "J4", "2.1.4", ""),
         ("C", "anomalous", "R10", "4.3.1", ""),
         ("D", "hard_negative", "", "", "HN_TOLERANCE"),
         ("E", "clean", "", "", ""),
         ("F", "clean", "", "", "")],
        columns=["invoice_id", "label", "class_id", "clause_ids", "hard_negative_type"],
    ).set_index("invoice_id")

    def pred(invoice_id, clauses, route):
        return {"invoice_id": invoice_id, "config": "C1", "anomalous": bool(clauses),
                "flags": [{"clause": c} for c in clauses], "route": route,
                "cost": {"llm_calls": 2, "prompt_tokens": 100, "completion_tokens": 20, "latency_ms": 5}}

    predictions = {p["invoice_id"]: p for p in [
        pred("A", ["2.1.1"], "escalate"),     # correct clause
        pred("B", ["2.1.2"], "escalate"),     # reported, wrong clause
        pred("C", [], "approve"),             # missed
        pred("D", ["4.3.1"], "approve"),      # false positive on a hard negative
        pred("E", [], "approve"),
        pred("F", [], "approve"),
    ]}
    return labels, predictions


def test_metrics_on_a_hand_checked_example():
    labels, predictions = tiny()
    m = compute(build_frame(labels, predictions, severity=SEVERITY))
    close = lambda a, b: math.isclose(a, b, rel_tol=1e-12)  # noqa: E731

    assert close(m["detection_recall"], 2 / 3)
    assert close(m["detection_precision"], 2 / 3)
    assert close(m["detection_f1"], 2 / 3)
    assert close(m["detection_accuracy"], 4 / 6)
    assert close(m["fpr"], 1 / 3)
    assert m["fpr_ordinary"] == 0.0 and m["fpr_hard_negative"] == 1.0
    assert close(m["precision_at_2pct_prevalence"], (0.02 * 2 / 3) / (0.02 * 2 / 3 + 0.98 * 1 / 3))

    assert m["f1:R1"] == 1.0 and m["precision:R1"] == 1.0 and m["recall:R1"] == 1.0
    assert m["f1:R2"] == 0.0 and math.isnan(m["recall:R2"])          # predicted once, never true
    assert m["f1:R10"] == 0.0 and m["f1:J4"] == 0.0
    assert math.isnan(m["f1:R3"])                                    # absent and never predicted
    assert close(m["macro_f1_rule"], 1 / 3)                          # mean over R1, R2, R10
    assert m["macro_f1_judgement"] == 0.0
    assert m["detected:J4"] == 1.0 and m["detected:R10"] == 0.0      # B is reported, under the wrong clause

    assert close(m["citation_correctness"], 1 / 2)
    assert close(m["exact_match"], 3 / 6)
    assert m["escalation_precision"] == 1.0 and m["escalation_recall"] == 1.0   # A and B are the high ones
    assert m["approved_high_anomalies"] == 0.0 and m["sampled_count"] == 0.0
    assert close(m["approved_share"], 4 / 6)
    assert m["llm_calls_per_invoice"] == 2.0 and m["tokens_per_invoice"] == 120.0


def test_findings_of_a_model_are_scored_apart_from_the_controls():
    labels, predictions = tiny()
    predictions["A"]["flags"] = [{"clause": "2.1.1", "source": "D"}, {"clause": "2.1.4", "source": "L"}]
    predictions["B"]["flags"] = [{"clause": "2.1.4", "source": "L"}]
    predictions["D"]["flags"] = [{"clause": "2.2.2", "source": "L"}]
    m = compute(build_frame(labels, predictions, severity=SEVERITY))
    assert math.isclose(m["model_rule_precision"], 1 / 3)       # only B's finding names a rule it violates
    assert math.isnan(compute(build_frame(*tiny(), severity=SEVERITY))["model_rule_precision"])   # no model finding


def test_detector_without_flags_has_only_detection_metrics():
    labels, predictions = tiny()
    c0 = {i: {"invoice_id": i, "config": "C0", "anomalous": p["anomalous"]} for i, p in predictions.items()}
    m = compute(build_frame(labels, c0, severity=SEVERITY))
    assert math.isclose(m["detection_recall"], 2 / 3)
    assert "macro_f1_rule" not in m and "escalation_precision" not in m and "citation_correctness" not in m


def test_metrics_on_a_subset_and_missing_predictions():
    labels, predictions = tiny()
    m = compute(build_frame(labels, predictions, ids=["A", "E"], severity=SEVERITY))
    assert m["detection_recall"] == 1.0 and m["fpr"] == 0.0 and m["exact_match"] == 1.0
    del predictions["F"]
    with pytest.raises(ValueError, match="no prediction"):
        build_frame(labels, predictions, severity=SEVERITY)


def test_alternative_label_columns_for_the_policy_swap():
    labels, predictions = tiny()
    labels["alt_label"], labels["alt_clause_ids"] = "clean", ""
    nothing = {i: {**p, "flags": [], "anomalous": False, "route": "approve"} for i, p in predictions.items()}
    m = compute(build_frame(labels, nothing, label_column="alt_label", clause_column="alt_clause_ids", severity=SEVERITY))
    assert m["exact_match"] == 1.0 and m["fpr"] == 0.0


def test_bootstrap_is_reproducible_and_brackets_the_estimate():
    labels, predictions = tiny()
    frame = build_frame(labels, predictions, severity=SEVERITY)
    first, second = bootstrap(frame, 200, seed=3), bootstrap(frame, 200, seed=3)
    assert first == second or all(
        (math.isnan(first[k][0]) and math.isnan(second[k][0])) or first[k] == second[k] for k in first)
    lo, hi = first["detection_recall"]
    assert lo <= compute(frame)["detection_recall"] <= hi and lo < hi


# ------------------------------------------------------------------ stats
def test_mcnemar_counts_discordant_pairs():
    a = np.array([1, 1, 1, 1, 1, 1, 1, 1, 0, 0], dtype=bool)
    b = np.array([0, 0, 0, 0, 0, 0, 0, 1, 1, 0], dtype=bool)
    t = mcnemar_test(a, b)
    assert (t["only_a_correct"], t["only_b_correct"]) == (7, 1)
    # Exact two-sided binomial: 2 * P(X <= 1 | n = 8, p = 0.5) = 2 * 9 / 256.
    assert math.isclose(t["p_value"], 2 * 9 / 256)
    assert mcnemar_test(a, a)["p_value"] == 1.0
    with pytest.raises(ValueError):
        mcnemar_test(a, b[:5])


def test_holm_correction():
    out = holm({"H1": 0.01, "H2": 0.04, "H3": 0.03})
    assert math.isclose(out["H1"]["p_holm"], 0.03)       # 0.01 * 3
    assert math.isclose(out["H3"]["p_holm"], 0.06)       # 0.03 * 2
    assert math.isclose(out["H2"]["p_holm"], 0.06)       # max(0.04 * 1, 0.06)
    assert [out[h]["reject"] for h in ("H1", "H2", "H3")] == [True, False, False]


def test_consistency_is_mean_pairwise_jaccard():
    runs = [
        {"X": {"2.1.1"}, "Y": set(), "Z": {"2.1.4", "2.1.5"}},
        {"X": {"2.1.1"}, "Y": set(), "Z": {"2.1.4"}},
        {"X": set(), "Y": set(), "Z": {"2.1.4"}},
    ]
    # X: (1 + 0 + 0) / 3;  Y: 1;  Z: (1/2 + 1/2 + 1) / 3
    assert math.isclose(consistency(runs), (1 / 3 + 1 + 2 / 3) / 3)
    assert consistency([runs[0], runs[0]]) == 1.0
    with pytest.raises(ValueError):
        consistency([runs[0]])


def test_non_inferiority_margin():
    assert non_inferior(0.90, 0.915) and not non_inferior(0.89, 0.915)


# ------------------------------------------------------ weighted subsets
def test_weights_turn_subset_rates_into_ledger_rates():
    """Ten invoices; the subset keeps both anomalies and one of four clean invoices of each kind."""
    labels = pd.DataFrame(
        [(f"I{n}", "anomalous" if n < 2 else "clean", "R1" if n < 2 else "", "2.1.1" if n < 2 else "", "")
         for n in range(10)],
        columns=["invoice_id", "label", "class_id", "clause_ids", "hard_negative_type"]).set_index("invoice_id")
    flagged = {"I0", "I2", "I3"}                       # one anomaly found, two of the eight clean invoices flagged
    predictions = {i: {"invoice_id": i, "config": "C1", "anomalous": i in flagged,
                       "flags": [{"clause": "2.1.1"}] if i in flagged else [], "route": "approve"} for i in labels.index}
    whole = compute(build_frame(labels, predictions, severity=SEVERITY))
    assert (whole["detection_recall"], whole["fpr"], whole["prevalence"]) == (0.5, 0.25, 0.2)

    subset = pd.DataFrame({"invoice_id": ["I0", "I1", "I2", "I5"], "stratum": ["anomalous"] * 2 + ["ordinary"] * 2,
                           "weight": [1.0, 1.0, 4.0, 4.0]}).set_index("invoice_id")
    frame = build_frame(labels, predictions, severity=SEVERITY, subset=subset)
    part = compute(frame)
    assert len(frame) == 4 and frame.cols["weight"].sum() == 10
    assert part["detection_recall"] == 0.5 and part["prevalence"] == 0.2          # complete stratum: exact
    assert part["fpr"] == 0.5                                                    # 1 of the 2 sampled clean invoices
    assert math.isclose(part["detection_precision"], 1 / (1 + 4))               # one flagged clean invoice stands for four
    unweighted = compute(build_frame(labels, predictions, ids=list(subset.index), severity=SEVERITY))
    assert unweighted["prevalence"] == 0.5                                       # without weights the subset misleads


def test_the_bootstrap_resamples_within_strata(small_dataset):
    labels, subset = read_labels(small_dataset), read_subset(small_dataset)
    predictions = {i: {"invoice_id": i, "config": "C0", "anomalous": labels.at[i, "label"] == "anomalous"}
                   for i in labels.index}
    frame = build_frame(labels, predictions, severity=SEVERITY, subset=subset)
    assert set(frame.strata) == {"anomalous", "hard_negative", "duplicate_original", "ordinary"}
    intervals = bootstrap(frame, 50, seed=1)
    # Every resample keeps all 420 anomalous invoices, so the prevalence does not vary.
    assert intervals["prevalence"][0] == intervals["prevalence"][1] == compute(frame)["prevalence"]


def test_the_evaluation_subset_reproduces_the_ledger_for_the_controls(small_dataset, tmp_path):
    run_config.run(extract(small_dataset), PRESETS["C1"], load_policy("2.5"), None, tmp_path / "C1.jsonl",
                   workers=1, progress=False)
    labels, predictions = read_labels(small_dataset), read_predictions(tmp_path / "C1.jsonl")
    whole = compute(build_frame(labels, predictions, severity=SEVERITY))
    part = compute(build_frame(labels, predictions, severity=SEVERITY, subset=read_subset(small_dataset)))
    for name in ("detection_recall", "detection_precision", "fpr", "macro_f1_rule", "escalation_recall", "prevalence"):
        assert math.isclose(whole[name], part[name]), name


# ------------------------------------------------- extraction and runners
def test_extraction_links_the_records(small_dataset):
    transactions = {t["invoice"]["invoice_id"]: t for t in extract(small_dataset)}
    labels = read_labels(small_dataset)
    assert set(transactions) == set(labels.index)
    for invoice_id, t in transactions.items():
        inv = t["invoice"]
        assert isinstance(inv["amount"], float) and isinstance(inv["quantity"], int)
        assert isinstance(t["vendor"]["blacklisted"], bool)
        assert all(h["invoice_id"] != invoice_id for h in t["vendor_history"])
        assert t["approvals"] and t["approvals"][-1]["action_taken"] == "Approved"
        assert (t["po"] is None) or t["po"]["po_id"] == inv["po_id"]
        assert (t["grn"] is None) or t["grn"]["grn_id"] == inv["grn_id"]
    missing = labels.index[labels["class_id"] == "R8"]
    assert all(transactions[i]["po"] is None or transactions[i]["grn"] is None for i in missing)
    assert sum(transactions[i]["invoice"]["po_id"] is None for i in missing) == 10
    # The label never reaches the transaction.
    assert not any(key in json.dumps(next(iter(transactions.values()))) for key in ("class_id", "clause_ids", "hard_negative"))


def test_controls_reproduce_the_rule_labels_on_an_unseen_seed(small_dataset, tmp_path):
    run_config.run(extract(small_dataset), PRESETS["C1"], load_policy("2.5"), None, tmp_path / "C1.jsonl",
                   workers=1, progress=False)
    labels = read_labels(small_dataset)
    predictions = read_predictions(tmp_path / "C1.jsonl")
    judgement = labels["class_id"].isin(["J1", "J2", "J3", "J4"])
    for invoice_id, lab in labels.iterrows():
        cited = {f["clause"] for f in predictions[invoice_id]["flags"]}
        expected = set() if judgement[invoice_id] else set(filter(None, lab["clause_ids"].split("|")))
        assert cited == expected, (invoice_id, lab["class_id"], cited)
    m = compute(build_frame(labels, predictions, severity=SEVERITY))
    assert m["macro_f1_rule"] == 1.0 and m["macro_f1_judgement"] == 0.0
    assert m["fpr"] == 0.0 and m["citation_correctness"] == 1.0
    assert m["escalation_precision"] == 1.0 and math.isclose(m["escalation_recall"], 240 / 330)


def test_classical_detectors_decide_each_fold_without_its_labels(small_dataset):
    labels = read_labels(small_dataset)
    transactions = extract(small_dataset)
    folds = run_c0.assign_folds(labels, seed=7)
    assert sorted(folds.unique()) == [0, 1, 2, 3, 4] and (folds == 0).sum() == 240
    assert all(((labels["class_id"] == "J3") & (folds == k)).sum() == 6 for k in range(5))     # stratified

    predictions = run_c0.run(transactions, labels, seed=7)
    assert set(predictions) == {"C0-IF", "C0-SVM"} and all(len(p) == 1200 for p in predictions.values())
    # Changing the labels of one fold must not change that fold's decisions.
    shuffled = labels.copy()
    held_out = folds.index[folds == 2]
    rng = np.random.default_rng(0)
    shuffled.loc[held_out, "label"] = rng.permutation(shuffled.loc[held_out, "label"].to_numpy())
    again = run_c0.run(transactions, shuffled, seed=7)
    for name in predictions:
        assert predictions[name].loc[held_out, "anomalous"].equals(again[name].loc[held_out, "anomalous"]), name
    features = run_c0.features(transactions)
    assert not features.isna().any().any() and len(features) == len(labels)


def test_best_threshold_maximizes_f1():
    rng = np.random.default_rng(3)
    for _ in range(100):
        scores, truth = rng.integers(0, 10, 30).astype(float), rng.random(30) < 0.3

        def f1(threshold: float, scores=scores, truth=truth) -> float:
            guess = scores >= threshold
            tp = (guess & truth).sum()
            den = 2 * tp + (guess & ~truth).sum() + (~guess & truth).sum()
            return 2 * tp / den if den else 0.0
        assert math.isclose(f1(run_c0.best_threshold(scores, truth)), max(f1(t) for t in np.unique(scores)))


def test_stratified_ids_come_from_the_evaluation_subset(small_dataset):
    labels, subset = read_labels(small_dataset), read_subset(small_dataset)
    chosen = run_config.stratified_ids(labels, 50, seed=1, within=set(subset.index))
    assert 45 <= len(chosen) <= 55 and set(chosen) <= set(subset.index)
    assert set(labels.loc[chosen, "class_id"]) - {""} == {f"R{n}" for n in range(1, 11)} | {"J1", "J2", "J3", "J4"}
    assert chosen == run_config.stratified_ids(labels, 50, seed=1, within=set(subset.index))


def test_the_history_cap_keeps_every_invoice_a_labelled_case_depends_on(small_dataset):
    frame, capped, total = history_cap.coverage(small_dataset)
    assert total == 1200 and capped > 0 and len(frame) > 0
    owners = frame[[row.stage == history_cap.OWNER[row.kind] for row in frame.itertuples()]]
    assert len(owners) > 0 and owners["complete"].all()
    assert frame.loc[frame["stage"] == "single_auditor", "complete"].all()
    assert set(frame["kind"]) <= set(history_cap.OWNER)
