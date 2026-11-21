"""The risk screen: gradient-boosted trees over features of each invoice, explained with exact SHAP values.

The controls decide the twelve rule-defined clauses; the four judgement clauses (2.1.4 receipt remarks, 2.1.5
description match, 2.2.2 near duplicate, 4.1.2 structuring across days) are left to the language-model agents, which
take minutes per invoice on a laptop and so cannot read a whole ledger. The screen is a learned model that reads
every invoice in microseconds and says which ones deserve that attention, and why:

    any      the probability that the invoice is anomalous at all: a continuous risk index, next to the paper's
             score, which sits on its floors (50, 70) because most anomalous invoices carry one finding
    2.1.4    one head per judgement rule: the probability that the invoice breaks that rule. The largest of
    2.1.5    the four is the screen's suggestion of which rule a reviewer (or an agent) should look at first,
    2.2.2    so the screen also classifies
    4.1.2

Each head is a scikit-learn ``GradientBoostingClassifier`` (150 trees of depth 3), trained once on the labels of
the development ledger (``data/pilot_seed_909``, the only ledger prompts were ever tried on) and stored as plain
arrays in ``models/risk_screen.json``; prediction and explanation read that file with numpy and need no
scikit-learn. The audit never reads a label: the screen was trained on another ledger's labels, and on the store
it sees only the transaction the controls see.

The features (``FEATURES``) are measurements of the transaction, most of them continuous: how far the amount is
from the approver's limit or the PO, the overlap of the invoice's and the PO's wording, whether a receipt remark
states a quantity or a rejection, whether an earlier invoice bills the same receipt, how many invoices of the
vendor sit just under the same limit within the policy's guide window. The thresholds of the policy in force on
the invoice's date enter them (the approver's limit, the round multiple, the guide window and band), so the
screen follows a policy change. Several measure what a control decides; the heads of the judgement rules are
the part the controls cannot give.

A screen's score is not a finding. It changes no result, score or route of the audit (equations 2 to 5 of the
paper are untouched); it ranks invoices for a reviewer or for the agents, and explains the rank. How well it
ranks on ledgers it was not trained on is measured by ``python -m evaluation.screen_eval``
(results/risk_screen/); the limits of that measurement are stated there.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import controls
from .leads import rekeyed
from .policy import PROJECT_ROOT, Policy
from .treeshap import Tree, ensemble_shap, tree_shap

MODEL_FILE = PROJECT_ROOT / "models" / "risk_screen.json"
TRAINING_LEDGER = "pilot_seed_909"
HEADS = {
    "any": "Anomalous (any rule)",
    "2.1.4": "Receipt remarks contradict the billed quantity",
    "2.1.5": "Invoice description does not match the PO",
    "2.2.2": "Near-duplicate invoice",
    "4.1.2": "Structuring across days",
}
JUDGEMENT_HEADS = ("2.1.4", "2.1.5", "2.2.2", "4.1.2")
CLASS_OF_HEAD = {"2.1.4": "J4", "2.1.5": "J3", "2.2.2": "J1", "4.1.2": "J2"}
PARAMS = {"n_estimators": 150, "max_depth": 3, "learning_rate": 0.1, "subsample": 1.0, "min_samples_leaf": 5,
          "random_state": 0}

# (name, what it measures). The order is the column order of the model.
FEATURES: list[tuple[str, str]] = [
    ("log_amount", "log10 of the invoice amount"),
    ("limit_ratio", "the amount divided by the approval limit of the approving role (above 1: over the limit)"),
    ("below_limit_pct", "how far below the approver's limit the amount is, in % of the limit (100 when above it)"),
    ("po_variance_pct", "the difference between the invoice and its PO amount, in % of the PO"),
    ("qty_over_received", "units invoiced beyond the units the goods receipt records"),
    ("missing_reference", "references missing: 0, 1 (PO or GRN) or 2"),
    ("non_business_day", "dated on a day the policy treats as non-business"),
    ("round_amount", "the amount is a multiple of the policy's round multiple"),
    ("gstin_malformed", "the invoice GSTIN is not 15 alphanumerics with a valid state code"),
    ("gstin_mismatch", "the invoice GSTIN differs from the vendor master"),
    ("vendor_blocked", "the vendor is blacklisted or its GSTIN status is blocked"),
    ("same_number_before", "an earlier invoice of the vendor carries the same number"),
    ("rekeyed_before", "an earlier invoice of the vendor carries a re-keyed form of the number"),
    ("same_receipt_before", "an earlier invoice bills the same PO and GRN for the same amount"),
    ("same_amount_before", "earlier invoices of the vendor for exactly this amount"),
    ("same_day_count", "invoices of the vendor dated the same day, this one included"),
    ("window_near_limit", "invoices of the vendor and approving role within the guide window, each in the guide band "
                          "below the role's limit, this one included"),
    ("window_total_ratio", "their total divided by the role's limit (above 1: together over the limit)"),
    ("desc_po_overlap", "word overlap of the invoice description with the PO description (0 to 1)"),
    ("desc_history_overlap", "the largest word overlap of the description with the vendor's other invoices"),
    ("remark_quantity", "the goods-receipt remark states a number"),
    ("remark_adverse", "the goods-receipt remark speaks of rejection, return, damage or shortage"),
    ("amount_z", "the amount against the vendor's other invoices, in standard deviations"),
    ("vendor_invoices", "log10 of the number of the vendor's invoices"),
]
FEATURE_NAMES = [name for name, _ in FEATURES]
WORD = re.compile(r"[a-z]{3,}")
STOP = {"and", "the", "for", "per", "with", "from", "being", "charges", "towards", "against", "order", "purchase",
        "as", "our", "supply", "invoice", "services", "service", "items", "item", "nos", "qty", "inr"}
ADVERSE = re.compile(r"\b(reject\w*|return\w*|damag\w*|short\w*|not\s+(?:accepted|delivered|received)|defect\w*|"
                     r"broken|missing|wrong|balance)\b", re.IGNORECASE)
DIGIT = re.compile(r"\d")


class ScreenUnavailable(RuntimeError):
    """No trained screen: train one with `python -m auditiq model train`."""


# ------------------------------------------------------------------ features
def _day(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


@lru_cache(maxsize=65536)
def _word_set(text: str) -> frozenset[str]:
    return frozenset(w for w in WORD.findall(text.lower()) if w not in STOP)


def _words(text) -> frozenset[str]:
    return _word_set(str(text or ""))


def overlap(a, b) -> float:
    """Jaccard overlap of the content words of two texts; 0 when either has none."""
    x, y = _words(a), _words(b)
    return len(x & y) / len(x | y) if x and y else 0.0


def policy_parameters(policy: Policy) -> dict:
    """The thresholds the features read, from the clause registry (defaults where a clause is absent)."""
    c = policy.clauses

    def param(clause: str, name: str, default):
        return (c.get(clause) or {}).get("params", {}).get(name, default)

    return {"limits": {k: float(v) for k, v in param("5.1.1", "approval_limits", {}).items()},
            "round": param("4.3.1", "round_amount_multiple", 10000),
            "non_business": set(param("4.2.1", "non_business_days", ["Saturday", "Sunday"])),
            "window": int(param("4.1.2", "guide_window_days", 7)),
            "band": float(param("4.1.2", "guide_band_pct", 15)),
            "blocked": set(param("4.4.1", "blocked_gstin_statuses", ["Suspended"])),
            "clauses": c}


def features(txn: dict, params: dict) -> dict[str, float]:
    """The feature values of one transaction (see FEATURES), under the thresholds of ``policy_parameters``."""
    inv, po, grn, vendor = txn["invoice"], txn.get("po"), txn.get("grn"), txn.get("vendor") or {}
    amount = float(inv.get("amount") or 0)
    day = _day(inv.get("date"))
    entry = controls.approving_entry(txn)
    role = entry.get("approver_role") if entry else None
    limit = params["limits"].get(role or "")
    history = list(txn.get("vendor_history") or [])
    earlier = [h for h in history if controls.is_earlier(h, inv)]

    out: dict[str, float] = {name: 0.0 for name in FEATURE_NAMES}
    out["log_amount"] = math.log10(max(amount, 1.0))
    if limit:
        out["limit_ratio"] = amount / limit
        out["below_limit_pct"] = (limit - amount) / limit * 100 if amount <= limit else 100.0
    else:
        out["limit_ratio"], out["below_limit_pct"] = 0.0, 100.0
    if po and po.get("amount"):
        out["po_variance_pct"] = abs(amount - float(po["amount"])) / float(po["amount"]) * 100
    if grn and grn.get("received_quantity") is not None and inv.get("quantity") is not None:
        out["qty_over_received"] = max(0.0, float(inv["quantity"]) - float(grn["received_quantity"]))
    out["missing_reference"] = float((not inv.get("po_id")) + (not inv.get("grn_id")))
    if day is not None:
        out["non_business_day"] = float(controls.DAY_NAMES[day.weekday()] in params["non_business"])
    multiple = params["round"]
    out["round_amount"] = float(bool(multiple) and amount > 0 and controls.paise(amount) % (multiple * 100) == 0)
    _, format_ok, state_ok = controls.gstin_checks(inv.get("gstin"), params["clauses"])
    out["gstin_malformed"] = float(not (format_ok and state_ok))
    official = str(vendor.get("official_gstin") or "")
    out["gstin_mismatch"] = float(bool(official) and str(inv.get("gstin") or "") != official)
    out["vendor_blocked"] = float(controls.is_true(vendor.get("blacklisted"))
                                  or vendor.get("gstin_status") in params["blocked"])

    number = str(inv.get("invoice_number") or "").strip()
    cents = round(amount * 100)
    for h in earlier:
        other = str(h.get("invoice_number") or "").strip()
        if other == number:
            out["same_number_before"] = 1.0
        elif not out["rekeyed_before"] and rekeyed(other, number):
            out["rekeyed_before"] = 1.0
        same_amount = round(float(h.get("amount") or 0) * 100) == cents
        if same_amount:
            out["same_amount_before"] += 1.0
            if inv.get("po_id") and h.get("po_id") == inv.get("po_id") and h.get("grn_id") == inv.get("grn_id"):
                out["same_receipt_before"] = 1.0
    if day is not None:
        out["same_day_count"] = 1.0 + sum(1 for h in history if _day(h.get("date")) == day)

    band, window = params["band"], params["window"]
    if limit and limit * (1 - band / 100) <= amount <= limit and day is not None:
        near = [amount]
        for h in history:
            hd = _day(h.get("date"))
            h_amount = float(h.get("amount") or 0)
            if (hd is not None and abs((hd - day).days) <= window and h.get("approver_role") == role
                    and limit * (1 - band / 100) <= h_amount <= limit):
                near.append(h_amount)
        out["window_near_limit"] = float(len(near))
        out["window_total_ratio"] = sum(near) / limit

    if po:
        out["desc_po_overlap"] = overlap(inv.get("description"), po.get("description"))
    if history:
        out["desc_history_overlap"] = max(overlap(inv.get("description"), h.get("description")) for h in history)
    notes = str((grn or {}).get("notes") or "")
    out["remark_quantity"] = float(bool(DIGIT.search(notes)))
    out["remark_adverse"] = float(bool(ADVERSE.search(notes)))
    amounts = [float(h.get("amount") or 0) for h in history]
    if len(amounts) >= 2:
        mean, sd = float(np.mean(amounts)), float(np.std(amounts))
        out["amount_z"] = (amount - mean) / sd if sd > 0 else 0.0
    out["vendor_invoices"] = math.log10(1 + len(history) + 1)
    return out


def matrix(transactions: list[dict], params_for) -> np.ndarray:
    """The feature matrix of a list of transactions; ``params_for(txn)`` gives the thresholds for each."""
    rows = [features(t, params_for(t)) for t in transactions]
    return np.array([[r[name] for name in FEATURE_NAMES] for r in rows], dtype=float).reshape(len(rows),
                                                                                             len(FEATURE_NAMES))


# ------------------------------------------------------------------ the model
@dataclass
class Head:
    name: str
    base: float                   # the raw output (log-odds) before any tree
    learning_rate: float
    trees: list[Tree]

    def raw(self, X: np.ndarray) -> np.ndarray:
        X = np.atleast_2d(X)
        return self.base + self.learning_rate * sum((t.predict(X) for t in self.trees), np.zeros(X.shape[0]))

    def probability(self, X: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-self.raw(X)))

    def expected_raw(self) -> float:
        """The model's expected output (log-odds) over the training data: the SHAP base value."""
        return self.base + self.learning_rate * sum(t.expected_value() for t in self.trees)

    def shap(self, X: np.ndarray, method: str = "exact") -> np.ndarray:
        return ensemble_shap(self.trees, X, self.learning_rate, method)


@dataclass
class Screen:
    heads: dict[str, Head]
    training: dict

    @classmethod
    def load(cls, path: Path = MODEL_FILE) -> Screen:
        if not Path(path).exists():
            raise ScreenUnavailable(f"no trained screen at {path}; train one: python -m auditiq model train")
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("features") != FEATURE_NAMES:
            raise ScreenUnavailable(f"{path} was trained on other features; train it again: "
                                    "python -m auditiq model train")
        heads = {name: Head(name, float(h["base"]), float(h["learning_rate"]),
                            [Tree.from_json(t) for t in h["trees"]]) for name, h in data["heads"].items()}
        return cls(heads, data["training"])

    def save(self, path: Path = MODEL_FILE) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"model": "AuditIQ risk screen", "features": FEATURE_NAMES, "training": self.training,
                "heads": {name: {"base": h.base, "learning_rate": h.learning_rate,
                                 "trees": [t.to_json() for t in h.trees]} for name, h in self.heads.items()}}
        path.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
        return path

    def scores(self, X: np.ndarray) -> dict[str, np.ndarray]:
        return {name: head.probability(X) for name, head in self.heads.items()}

    def suggested_rule(self, scores: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
        """For each row, the judgement head with the highest probability and that probability."""
        stacked = np.vstack([scores[h] for h in JUDGEMENT_HEADS])
        best = stacked.argmax(axis=0)
        return np.array(JUDGEMENT_HEADS)[best], stacked.max(axis=0)


def labels_of(dataset: Path) -> dict[str, set[str]]:
    """The positives of each head in a benchmark ledger's answer key (labels.csv), with the secondary classes of a
    compound fraud where the ledger records them."""
    import pandas as pd

    labels = pd.read_csv(Path(dataset) / "labels.csv", dtype=str, keep_default_na=False)
    out: dict[str, set[str]] = {name: set() for name in HEADS}
    for row in labels.to_dict("records"):
        classes = {row["class_id"]} | set(filter(None, (row.get("secondary_class_ids") or "").split(";")))
        classes.discard("")
        if row["label"] != "clean" and classes:
            out["any"].add(row["invoice_id"])
        for head, class_id in CLASS_OF_HEAD.items():
            if class_id in classes:
                out[head].add(row["invoice_id"])
    return out


def train(dataset: Path, policy: Policy, params: dict | None = None) -> Screen:
    """Fit every head on a ledger folder with its answer key. Deterministic for a given ledger and parameters."""
    import sklearn
    from sklearn.ensemble import GradientBoostingClassifier

    from .extraction import extract

    params = {**PARAMS, **(params or {})}
    started = time.time()
    transactions = extract(Path(dataset))
    thresholds = policy_parameters(policy)
    X = matrix(transactions, lambda _t: thresholds)
    ids = [t["invoice"]["invoice_id"] for t in transactions]
    positives = labels_of(dataset)
    heads, fitted = {}, {}
    for name in HEADS:
        y = np.array([i in positives[name] for i in ids], dtype=int)
        model = GradientBoostingClassifier(loss="log_loss", **params).fit(X, y)
        trees = [Tree.from_sklearn(e[0]) for e in model.estimators_]
        lr = float(model.learning_rate)
        tree_sum = sum((t.predict(X) for t in trees), np.zeros(len(ids)))
        base = model.decision_function(X) - lr * tree_sum
        if float(np.ptp(base)) > 1e-8:
            raise RuntimeError("the trees read back do not reproduce the model's output")
        heads[name] = Head(name, float(base[0]), lr, trees)
        fitted[name] = {"positives": int(y.sum()), "training_auc": _auc(y, heads[name].raw(X))}
    manifest = Path(dataset) / "manifest.json"
    training = {"ledger": Path(dataset).name, "policy_version": policy.version, "invoices": len(ids),
                "heads": fitted, "params": params, "scikit_learn": sklearn.__version__,
                "ledger_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest() if manifest.exists() else None,
                "seconds": round(time.time() - started, 1)}
    return Screen(heads, training)


def _auc(y: np.ndarray, score: np.ndarray) -> float | None:
    """The area under the ROC curve (the probability that a positive outranks a negative; ties count half)."""
    y = np.asarray(y, dtype=bool)
    pos, neg = int(y.sum()), int((~y).sum())
    if not pos or not neg:
        return None
    order = np.argsort(score, kind="mergesort")
    ranks = np.empty(len(score))
    sorted_scores = np.asarray(score)[order]
    i = 0
    while i < len(score):                   # average ranks over ties
        j = i
        while j + 1 < len(score) and sorted_scores[j + 1] == sorted_scores[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return round(float((ranks[y].sum() - pos * (pos + 1) / 2) / (pos * neg)), 6)


auc = _auc


# ------------------------------------------------------------------ explanations
def explain_row(screen: Screen, x: np.ndarray, top: int = 8, method: str = "tree") -> dict:
    """Every head's probability for one feature row, and its SHAP values: the base value (log-odds), each feature's
    contribution, the largest ``top`` of them listed with the feature's value and meaning, the rest summed."""
    x = np.asarray(x, dtype=float)
    out = {}
    for name, head in screen.heads.items():
        if method == "tree":
            phi = np.zeros(len(FEATURE_NAMES))
            for tree in head.trees:
                phi += np.asarray(tree_shap(tree, x, len(FEATURE_NAMES)))
            phi *= head.learning_rate
        else:
            phi = head.shap(x[None, :])[0]
        base = head.expected_raw()
        raw = float(head.raw(x[None, :])[0])
        order = sorted(range(len(FEATURE_NAMES)), key=lambda i: -abs(phi[i]))
        shown = [i for i in order[:top] if abs(phi[i]) > 1e-9]
        rest = float(sum(phi[i] for i in range(len(FEATURE_NAMES)) if i not in shown))
        out[name] = {"title": HEADS[name], "probability": round(1 / (1 + math.exp(-raw)), 6), "raw": round(raw, 6),
                     "base": round(base, 6), "base_probability": round(1 / (1 + math.exp(-base)), 6),
                     "contributions": [{"feature": FEATURE_NAMES[i], "meaning": FEATURES[i][1],
                                        "value": round(float(x[i]), 4), "shap": round(float(phi[i]), 6)}
                                       for i in shown],
                     "other": round(rest, 6),
                     "check": round(base + float(phi.sum()) - raw, 9)}      # local accuracy: 0 up to rounding
    return out


def importance(screen: Screen, X: np.ndarray, beeswarm: int = 300, seed: int = 7) -> dict:
    """Mean absolute SHAP value of every feature for every head over the rows of X, and for the dot plot of each
    head a sample of rows: each point a feature's SHAP value and the rank of its value among the rows (0 to 1)."""
    X = np.atleast_2d(X)
    rng = np.random.default_rng(seed)
    pick = np.sort(rng.choice(X.shape[0], size=min(beeswarm, X.shape[0]), replace=False)) if X.shape[0] else []
    ranks = np.zeros_like(X)
    for j in range(X.shape[1]):
        column = X[:, j]
        ranks[:, j] = (np.argsort(np.argsort(column, kind="mergesort"), kind="mergesort") / max(1, len(column) - 1)
                       if np.ptp(column) > 0 else 0.5)
    out = {}
    for name, head in screen.heads.items():
        phi = head.shap(X) if X.shape[0] else np.zeros((0, X.shape[1]))
        mean_abs = np.abs(phi).mean(axis=0) if X.shape[0] else np.zeros(X.shape[1])
        order = list(np.argsort(-mean_abs))
        out[name] = {"title": HEADS[name], "base": round(head.expected_raw(), 6), "rows": int(X.shape[0]),
                     "features": [{"feature": FEATURE_NAMES[i], "meaning": FEATURES[i][1],
                                   "mean_abs_shap": round(float(mean_abs[i]), 6)} for i in order],
                     "points": [{"feature": FEATURE_NAMES[i], "shap": [round(float(phi[r, i]), 4) for r in pick],
                                 "rank": [round(float(ranks[r, i]), 3) for r in pick]} for i in order[:10]]}
    return out
