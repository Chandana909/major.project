"""Configuration C0: classical anomaly detectors on tabular features.

    python -m evaluation.run_c0 <dataset dir> <output dir> [--seed N]

Two detectors, the family used by the first base paper:
    C0-IF   isolation forest, fitted without labels on all invoices
    C0-SVM  one-class SVM, fitted on clean invoices

Both output an anomaly score, and a threshold turns the score into a decision.
The threshold is set by five-fold cross-fitting: the invoices are split into
five folds, stratified by class, and each fold is decided with the threshold
that maximizes F1 on the other four. Every invoice therefore gets a decision
from a threshold that never saw its label, and the detectors can be compared
with the other configurations on the whole ledger. The one-class SVM is fitted
the same way, on (a sample of) the clean invoices of the other four folds.

The detectors decide only whether an invoice is anomalous: they name no clause.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler
from sklearn.svm import OneClassSVM

from auditiq.extraction import extract

from .metrics import read_labels

FOLDS = 5
SVM_MAX_TRAIN = 4000        # clean invoices used to fit one one-class SVM


def features(transactions: list[dict]) -> pd.DataFrame:
    """Generic tabular features. None of them encodes a policy threshold."""
    rows = []
    for t in transactions:
        inv, po, grn, vendor = t["invoice"], t["po"], t["grn"], t["vendor"]
        history = t["vendor_history"]
        day = date.fromisoformat(inv["date"])
        approved = [a for a in t["approvals"] if a["action_taken"] == "Approved"]
        limit = approved[-1]["amount_limit"] if approved else np.nan
        whole = str(int(round(inv["amount"])))
        log_history = np.log([h["amount"] for h in history]) if history else np.array([])
        rows.append({
            "invoice_id": inv["invoice_id"],
            "log_amount": np.log(inv["amount"]),
            "amount_to_po": inv["amount"] / po["amount"] if po else np.nan,
            "quantity_minus_received": inv["quantity"] - grn["received_quantity"] if grn else np.nan,
            "ordered_minus_received": grn["ordered_quantity"] - grn["received_quantity"] if grn else np.nan,
            "missing_po": float(po is None),
            "missing_grn": float(grn is None),
            "weekday": day.weekday(),
            "weekend": float(day.weekday() >= 5),
            "vendor_same_day": sum(h["date"] == inv["date"] for h in history),
            "vendor_within_week": sum(abs((date.fromisoformat(h["date"]) - day).days) <= 7 for h in history),
            "vendor_same_number": sum(h["invoice_number"] == inv["invoice_number"] for h in history),
            "vendor_same_amount": sum(h["amount"] == inv["amount"] for h in history),
            "vendor_same_po": sum(inv["po_id"] is not None and h["po_id"] == inv["po_id"] for h in history),
            "amount_to_approver_limit": inv["amount"] / limit if limit else np.nan,
            "approval_entries": len(t["approvals"]),
            "gstin_equals_master": float(inv["gstin"] == vendor["official_gstin"]),
            "gstin_length": len(inv["gstin"] or ""),
            "vendor_blacklisted": float(bool(vendor["blacklisted"])),
            "vendor_registration_active": float(vendor["gstin_status"] == "Active"),
            "amount_trailing_zeros": len(whole) - len(whole.rstrip("0")),
            "log_amount_vs_vendor": ((np.log(inv["amount"]) - log_history.mean()) / (log_history.std() + 1e-9)
                                     if len(log_history) >= 3 else 0.0),
        })
    frame = pd.DataFrame(rows).set_index("invoice_id")
    # A missing document is carried by its indicator; the ratio takes the neutral value.
    return frame.fillna({"amount_to_po": 1.0, "quantity_minus_received": 0.0,
                         "ordered_minus_received": 0.0, "amount_to_approver_limit": 0.0})


def assign_folds(labels: pd.DataFrame, seed: int, folds: int = FOLDS) -> pd.Series:
    """Fold number of every invoice; the stratum is the class or hard-negative type."""
    strata = labels["class_id"].where(labels["class_id"] != "", labels["hard_negative_type"])
    strata = strata.where(strata != "", "clean")
    fold = np.zeros(len(labels), dtype=int)
    splitter = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
    for number, (_, held_out) in enumerate(splitter.split(np.zeros(len(labels)), strata)):
        fold[held_out] = number
    return pd.Series(fold, index=labels.index, name="fold")


def best_threshold(scores: np.ndarray, anomalous: np.ndarray) -> float:
    """Score threshold with the highest F1 (predict anomalous when score >= threshold)."""
    order = np.argsort(-scores, kind="stable")
    sorted_scores, hits = scores[order], anomalous[order].astype(float)
    tp = np.cumsum(hits)
    predicted = np.arange(1, len(scores) + 1)
    f1 = 2 * tp / (predicted + hits.sum())
    # A threshold can only sit between two different scores.
    last_of_value = np.r_[sorted_scores[1:] != sorted_scores[:-1], True]
    f1 = np.where(last_of_value, f1, -1.0)
    return float(sorted_scores[int(np.argmax(f1))])


def run(transactions: list[dict], labels: pd.DataFrame, seed: int, folds: int = FOLDS) -> dict[str, pd.DataFrame]:
    """Out-of-fold decisions of both detectors for every invoice."""
    x = features(transactions).loc[labels.index]
    fold = assign_folds(labels, seed, folds).to_numpy()
    anomalous = (labels["label"] == "anomalous").to_numpy()
    rng = np.random.default_rng(seed)

    forest_scores = -IsolationForest(n_estimators=300, random_state=seed).fit(
        StandardScaler().fit_transform(x)).score_samples(StandardScaler().fit_transform(x))
    out = {name: pd.DataFrame({"score": np.zeros(len(x)), "anomalous": False, "threshold": 0.0, "fold": fold},
                              index=labels.index) for name in ("C0-IF", "C0-SVM")}
    for k in range(folds):
        held_out, others = fold == k, fold != k
        threshold = best_threshold(forest_scores[others], anomalous[others])
        out["C0-IF"].loc[held_out, ["score", "threshold"]] = np.c_[forest_scores[held_out],
                                                                   np.full(held_out.sum(), threshold)]
        out["C0-IF"].loc[held_out, "anomalous"] = forest_scores[held_out] >= threshold

        clean = np.flatnonzero(others & ~anomalous)
        if len(clean) > SVM_MAX_TRAIN:
            clean = rng.choice(clean, size=SVM_MAX_TRAIN, replace=False)
        scaler = StandardScaler().fit(x.iloc[clean])
        svm = OneClassSVM(kernel="rbf", gamma="scale", nu=0.1).fit(scaler.transform(x.iloc[clean]))
        scores = -svm.decision_function(scaler.transform(x))
        threshold = best_threshold(scores[others], anomalous[others])
        out["C0-SVM"].loc[held_out, ["score", "threshold"]] = np.c_[scores[held_out], np.full(held_out.sum(), threshold)]
        out["C0-SVM"].loc[held_out, "anomalous"] = scores[held_out] >= threshold
    return out


def write(predictions: dict[str, pd.DataFrame], out: Path) -> None:
    """Write one prediction file per detector."""
    out.mkdir(parents=True, exist_ok=True)
    for name, frame in predictions.items():
        with (out / f"{name}.jsonl").open("w", encoding="utf-8", newline="\n") as f:
            for invoice_id, row in frame.iterrows():
                f.write(json.dumps({
                    "invoice_id": invoice_id, "config": "C0", "detector": name, "fold": int(row["fold"]),
                    "anomalous": bool(row["anomalous"]), "score": round(float(row["score"]), 6),
                    "threshold": round(float(row["threshold"]), 6),
                    "cost": {"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0},
                }) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dataset", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    predictions = run(extract(args.dataset), read_labels(args.dataset), args.seed)
    write(predictions, args.out)
    for name, frame in predictions.items():
        print(f"{name}: {int(frame['anomalous'].sum())} of {len(frame)} invoices predicted anomalous "
              f"-> {args.out / (name + '.jsonl')}")


if __name__ == "__main__":
    main()
