"""Metrics of Section VI-C of the paper, with bootstrap confidence intervals.

A prediction file has one JSON object per invoice:
    { invoice_id, anomalous, flags: [{clause, ...}], route, cost: {...} }
A configuration that only decides "anomalous or not" (C0) has no flags and no
route; only the detection metrics are defined for it.

Weights. A configuration may be run on the evaluation subset of a ledger
(eval_subset.csv) instead of the whole ledger. Every invoice of the subset then
carries a weight: the number of ledger invoices it stands for. Every rate below
is a ratio of weighted sums, so a rate computed on the subset estimates the
rate on the whole ledger. On a whole ledger all weights are 1.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from auditiq_bench.taxonomy import CLASSES, CLAUSE_TO_CLASS, JUDGEMENT_CLASSES, RULE_CLASSES

PREVALENCE = 0.02            # realistic anomaly rate used for the adjusted precision
HIGH_SEVERITIES = {"high", "critical"}


def read_labels(dataset: Path) -> pd.DataFrame:
    return pd.read_csv(Path(dataset) / "labels.csv", dtype=str, keep_default_na=False).set_index("invoice_id")


def read_subset(dataset: Path) -> pd.DataFrame:
    """The evaluation subset of a dataset: invoice_id (index), stratum, weight."""
    return pd.read_csv(Path(dataset) / "eval_subset.csv", dtype={"invoice_id": str, "stratum": str}).set_index("invoice_id")


def read_predictions(path: Path) -> dict[str, dict]:
    with Path(path).open(encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return {r["invoice_id"]: r for r in rows}


def clause_set(text: str) -> set[str]:
    return set(filter(None, text.split("|")))


@dataclass
class Frame:
    """Per-invoice arrays from which every metric is a ratio of weighted sums."""
    ids: list[str]
    cols: dict[str, np.ndarray] = field(default_factory=dict)
    has_classes: bool = True
    has_routes: bool = True
    strata: np.ndarray | None = None       # stratum of each invoice, for the stratified bootstrap

    def __len__(self) -> int:
        return len(self.ids)


def build_frame(labels: pd.DataFrame, predictions: dict[str, dict], ids: list[str] | None = None,
                label_column: str = "label", clause_column: str = "clause_ids",
                severity: dict[str, str] | None = None, subset: pd.DataFrame | None = None) -> Frame:
    """Align predictions with labels.

    ``severity`` maps a clause to its severity under the policy the labels refer
    to; it is needed for the routing metrics. ``subset`` restricts the frame to
    an evaluation subset and supplies its weights and strata; ``ids`` restricts
    it without weights.
    """
    if subset is not None:
        ids = [i for i in subset.index if ids is None or i in set(ids)]
    ids = list(labels.index) if ids is None else list(ids)
    missing = [i for i in ids if i not in predictions]
    if missing:
        raise ValueError(f"{len(missing)} invoices have no prediction, e.g. {missing[:3]}")
    n = len(ids)
    c = {name: np.zeros(n, dtype=bool) for name in
         ["anomalous", "ordinary", "hard_negative", "pred_any", "truth_high", "exact",
          "escalate", "sample", "approve"]}
    c.update({f"truth:{k}": np.zeros(n, dtype=bool) for k in CLASSES})
    c.update({f"pred:{k}": np.zeros(n, dtype=bool) for k in CLASSES})
    for name in ["flags_on_anomalous", "flags_correct", "model_flags", "model_flags_correct", "llm_calls", "tokens",
                 "latency_ms"]:
        c[name] = np.zeros(n, dtype=float)
    c["weight"] = np.ones(n) if subset is None else subset.loc[ids, "weight"].to_numpy(dtype=float)
    strata = None if subset is None else subset.loc[ids, "stratum"].to_numpy()
    has_classes = any("flags" in predictions[i] and predictions[i].get("config") != "C0" for i in ids)
    has_routes = any(predictions[i].get("route") for i in ids)

    for row, invoice_id in enumerate(ids):
        lab, pred = labels.loc[invoice_id], predictions[invoice_id]
        truth_clauses = clause_set(lab[clause_column])
        truth_classes = {CLAUSE_TO_CLASS[k] for k in truth_clauses}
        flags = pred.get("flags") or []
        pred_clauses = {f["clause"] for f in flags}
        pred_classes = {CLAUSE_TO_CLASS[k] for k in pred_clauses if k in CLAUSE_TO_CLASS}

        c["anomalous"][row] = lab[label_column] == "anomalous"
        c["hard_negative"][row] = lab[label_column] == "hard_negative"
        c["ordinary"][row] = lab[label_column] == "clean"
        c["pred_any"][row] = bool(pred["anomalous"]) if "anomalous" in pred else bool(flags)
        c["exact"][row] = pred_clauses == truth_clauses
        if severity is not None:
            c["truth_high"][row] = any(severity[k] in HIGH_SEVERITIES for k in truth_clauses)
        for k in truth_classes:
            c[f"truth:{k}"][row] = True
        for k in pred_classes:
            c[f"pred:{k}"][row] = True
        if truth_clauses:
            c["flags_on_anomalous"][row] = len(flags)
            c["flags_correct"][row] = sum(f["clause"] in truth_clauses for f in flags)
        by_model = [f for f in flags if f.get("source") == "L"]
        c["model_flags"][row] = len(by_model)
        c["model_flags_correct"][row] = sum(f["clause"] in truth_clauses for f in by_model)
        route = pred.get("route")
        if route:
            c[route][row] = True
        cost = pred.get("cost") or {}
        c["llm_calls"][row] = cost.get("llm_calls", 0)
        c["tokens"][row] = cost.get("prompt_tokens", 0) + cost.get("completion_tokens", 0)
        c["latency_ms"][row] = cost.get("latency_ms", 0)
    return Frame(ids, c, has_classes, has_routes, strata)


def ratio(num: float, den: float) -> float:
    return float(num) / float(den) if den else float("nan")


def compute(frame: Frame, idx: np.ndarray | None = None) -> dict[str, float]:
    """All metrics for the invoices selected by ``idx`` (default: all)."""
    c = frame.cols if idx is None else {k: v[idx] for k, v in frame.cols.items()}
    w = c["weight"]
    total = float(w.sum())

    def s(values: np.ndarray) -> float:
        """Weighted sum of a mask or of a count."""
        return float((values * w).sum())

    anomalous, clean = c["anomalous"], ~c["anomalous"]
    pred = c["pred_any"]
    m: dict[str, float] = {}

    # Invoice-level detection.
    tp, fp, fn = s(pred & anomalous), s(pred & clean), s(~pred & anomalous)
    tpr, fpr = ratio(tp, s(anomalous)), ratio(fp, s(clean))
    m["detection_recall"] = tpr
    m["detection_precision"] = ratio(tp, tp + fp)
    m["detection_f1"] = ratio(2 * tp, 2 * tp + fp + fn)
    m["detection_accuracy"] = ratio(s(pred == anomalous), total)
    m["flagged_share"] = ratio(s(pred), total)
    m["prevalence"] = ratio(s(anomalous), total)
    m["fpr"] = fpr
    m["fpr_ordinary"] = ratio(s(pred & c["ordinary"]), s(c["ordinary"]))
    m["fpr_hard_negative"] = ratio(s(pred & c["hard_negative"]), s(c["hard_negative"]))
    den = PREVALENCE * tpr + (1 - PREVALENCE) * fpr
    m["precision_at_2pct_prevalence"] = PREVALENCE * tpr / den if den else float("nan")
    # Share of the invoices of each class that are reported at all, whatever the cited clause.
    for k in CLASSES:
        m[f"detected:{k}"] = ratio(s(pred & c[f"truth:{k}"]), s(c[f"truth:{k}"]))

    if frame.has_classes:
        f1 = {}
        for k in CLASSES:
            truth, guess = c[f"truth:{k}"], c[f"pred:{k}"]
            k_tp, k_fp, k_fn = s(truth & guess), s(~truth & guess), s(truth & ~guess)
            m[f"precision:{k}"] = ratio(k_tp, k_tp + k_fp)
            m[f"recall:{k}"] = ratio(k_tp, k_tp + k_fn)
            f1[k] = m[f"f1:{k}"] = ratio(2 * k_tp, 2 * k_tp + k_fp + k_fn)
        # A class that is absent and never predicted has no F1 and is skipped.
        for name, group in (("rule", RULE_CLASSES), ("judgement", JUDGEMENT_CLASSES)):
            values = [f1[k] for k in group if not np.isnan(f1[k])]
            recalls = [m[f"recall:{k}"] for k in group if not np.isnan(m[f"recall:{k}"])]
            m[f"macro_f1_{name}"] = float(np.mean(values)) if values else float("nan")
            m[f"macro_recall_{name}"] = float(np.mean(recalls)) if recalls else float("nan")
        m["citation_correctness"] = ratio(s(c["flags_correct"]), s(c["flags_on_anomalous"]))
        # The findings a model raised (an agent, or the single prompt of C2) that name a rule the invoice
        # violates, among all findings a model raised; one on an invoice without an anomaly counts as wrong.
        m["model_rule_precision"] = ratio(s(c["model_flags_correct"]), s(c["model_flags"]))
        m["exact_match"] = ratio(s(c["exact"]), total)

    if frame.has_routes:
        esc, high = c["escalate"], c["truth_high"]
        m["escalation_precision"] = ratio(s(esc & high), s(esc))
        m["escalation_recall"] = ratio(s(esc & high), s(high))
        m["escalated_share"] = ratio(s(esc), total)
        m["sampled_share"] = ratio(s(c["sample"]), total)
        m["sampled_count"] = s(c["sample"])
        m["sampled_true_anomalies"] = s(c["sample"] & anomalous)
        m["approved_share"] = ratio(s(c["approve"]), total)
        m["approved_high_anomalies"] = s(c["approve"] & high)

    # Cost describes the invoices that were audited, so it is not weighted.
    m["llm_calls_per_invoice"] = float(c["llm_calls"].mean())
    m["tokens_per_invoice"] = float(c["tokens"].mean())
    m["latency_ms_per_invoice"] = float(c["latency_ms"].mean())
    return m


def bootstrap(frame: Frame, n_resamples: int = 1000, seed: int = 0, level: float = 0.95) -> dict[str, tuple[float, float]]:
    """Percentile bootstrap over invoices; within each stratum when the frame has strata."""
    rng = np.random.default_rng(seed)
    n = len(frame)
    groups = None
    if frame.strata is not None:
        groups = [np.flatnonzero(frame.strata == name) for name in sorted(set(frame.strata))]
    samples: dict[str, list[float]] = {}
    for _ in range(n_resamples):
        if groups is None:
            idx = rng.integers(0, n, n)
        else:
            idx = np.concatenate([rng.choice(g, size=len(g)) for g in groups])
        for name, value in compute(frame, idx).items():
            samples.setdefault(name, []).append(value)
    alpha = (1 - level) / 2
    out = {}
    for name, values in samples.items():
        arr = np.array(values, dtype=float)
        if np.isnan(arr).all():
            out[name] = (float("nan"), float("nan"))
        else:
            out[name] = (float(np.nanquantile(arr, alpha)), float(np.nanquantile(arr, 1 - alpha)))
    return out


def evaluate(frame: Frame, n_resamples: int = 1000, seed: int = 0) -> dict[str, dict[str, float]]:
    point = compute(frame)
    ci = bootstrap(frame, n_resamples, seed) if n_resamples else {}
    return {name: {"value": value, "ci_low": ci.get(name, (None, None))[0], "ci_high": ci.get(name, (None, None))[1]}
            for name, value in point.items()}
