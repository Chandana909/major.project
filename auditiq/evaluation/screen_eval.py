"""The risk screen on ledgers it was not trained on, against an unsupervised detector and against random choice.

    python -m evaluation.screen_eval                      results/risk_screen/screen.md and screen.json

Protocol, fixed before the held-out ledgers were scored (one exploratory look at bench_seed_101 and final_seed_2025
was taken with the same features and parameters, and nothing was changed after it):

    training     the screen is trained again from scratch on data/pilot_seed_909, the development ledger, and the
                 result is compared with the committed model file (models/risk_screen.json): the same file means
                 the committed model is the one this script measures
    held out     bench_seed_101, bench_seed_202, bench_seed_303, large_seed_505, collusion_seed_707 and
                 final_seed_2025, each scored with the policy version its labels are written for (v2.5)
    per head     ROC AUC; average precision; recall and precision at review budgets of 1 %, 2 % and 5 % of the
                 ledger; for a judgement head, the hard negatives it puts in its top k (k = its positives)
    second       the invoices the controls alone approve (configuration C1: run the twelve controls, score, route):
    opinion      how many of the judgement anomalies among them the screen's judgement score (the largest of the
                 four heads) puts in the top 1 % and 2 % of those invoices. This is the recall ceiling of a cascade
                 that sends only that top slice to the language-model agents, not a measured recall of the agents
    classifies   for every judgement anomaly whose judgement score is at least 0.5, whether the head with the
                 highest probability is a rule the invoice breaks
    baselines    an isolation forest on the 21 generic features of configuration C0 (evaluation/run_c0.py), fitted
                 without labels on each ledger, and random choice (recall at a budget of b is b)
    explanations on 200 invoices of bench_seed_101, the two SHAP implementations (auditiq/treeshap.py) against each
                 other, and local accuracy (base value plus SHAP values against the model's output)

Every ledger here comes from the same generator as the training ledger, with other seeds and sizes. The numbers say
that the screen generalises across ledgers of this generator; on real invoices, with other wording and other kinds
of fraud, they would be different, and the screen would have to be trained on labelled real cases.
"""
from __future__ import annotations

import hashlib
import json
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from auditiq import controls, scoring, screen
from auditiq.extraction import extract
from auditiq.policy import PROJECT_ROOT, load_policy
from auditiq.treeshap import tree_shap

from .run_c0 import features as c0_features

DATA = PROJECT_ROOT / "data"
OUT = PROJECT_ROOT / "results" / "risk_screen"
HELD_OUT = ["bench_seed_101", "bench_seed_202", "bench_seed_303", "large_seed_505", "collusion_seed_707",
            "final_seed_2025"]
BUDGETS = (0.01, 0.02, 0.05)
SECOND_BUDGETS = (0.01, 0.02)


def average_precision(y: np.ndarray, score: np.ndarray) -> float | None:
    y = np.asarray(y, dtype=bool)
    if not y.any():
        return None
    order = np.argsort(-score, kind="mergesort")
    hits = y[order]
    precision = np.cumsum(hits) / np.arange(1, len(hits) + 1)
    return round(float(precision[hits].mean()), 6)


def at_budget(y: np.ndarray, score: np.ndarray, share: float) -> dict:
    k = max(1, int(round(share * len(y))))
    top = np.argsort(-score, kind="mergesort")[:k]
    found = int(y[top].sum())
    return {"budget": share, "k": k, "found": found, "recall": round(found / max(1, int(y.sum())), 4),
            "precision": round(found / k, 4)}


def c1_routes(transactions: list[dict], clauses: dict) -> np.ndarray:
    """The route of configuration C1 for each transaction: the controls, scored and routed by equations 2 to 5."""
    routes = []
    for t in transactions:
        flags = [scoring.normalize_flag(f, clauses) for f in controls.run_controls(t, clauses)]
        routes.append(scoring.score(flags)["route"])
    return np.array(routes)


def evaluate_ledger(name: str, model: screen.Screen, thresholds: dict, clauses: dict, seed: int = 7) -> dict:
    dataset = DATA / name
    started = time.perf_counter()
    transactions = extract(dataset)
    X = screen.matrix(transactions, lambda _t: thresholds)
    feature_seconds = time.perf_counter() - started
    ids = [t["invoice"]["invoice_id"] for t in transactions]
    labels = pd.read_csv(dataset / "labels.csv", dtype=str, keep_default_na=False).set_index("invoice_id")
    positives = screen.labels_of(dataset)
    started = time.perf_counter()
    scores = model.scores(X)
    predict_seconds = time.perf_counter() - started
    suggested, best = model.suggested_rule(scores)
    forest = IsolationForest(n_estimators=200, random_state=seed).fit(c0_features(transactions).fillna(0.0).to_numpy())
    forest_score = -forest.score_samples(c0_features(transactions).fillna(0.0).to_numpy())
    hn = labels["hard_negative_type"].reindex(ids).fillna("").to_numpy()
    heads = {}
    for head in screen.HEADS:
        y = np.array([i in positives[head] for i in ids])
        k = int(y.sum())
        top = np.argsort(-scores[head], kind="mergesort")[:max(1, k)]
        heads[head] = {"positives": k, "auc": screen.auc(y, scores[head]), "average_precision": average_precision(y, scores[head]),
                       "budgets": [at_budget(y, scores[head], b) for b in BUDGETS],
                       "recall_at_positives": round(float(y[top].sum()) / max(1, k), 4),
                       "hard_negatives_in_top": dict(pd.Series(hn[top][hn[top] != ""]).value_counts().sort_index()
                                                     .astype(int)) if head != "any" else None,
                       "isolation_forest": {"auc": screen.auc(y, forest_score),
                                            "average_precision": average_precision(y, forest_score),
                                            "budgets": [at_budget(y, forest_score, b) for b in BUDGETS]}}
    routes = c1_routes(transactions, clauses)
    judgement = np.array([any(i in positives[h] for h in screen.JUDGEMENT_HEADS) for i in ids])
    passed = routes == "approve"
    second = {"approved_by_c1": int(passed.sum()), "judgement_anomalies_among_them": int((judgement & passed).sum()),
              "budgets": []}
    for b in SECOND_BUDGETS:
        sub_scores, sub_y = best[passed], judgement[passed]
        second["budgets"].append(at_budget(sub_y, sub_scores, b))
        forest_at = at_budget(sub_y, forest_score[passed], b)
        second["budgets"][-1]["isolation_forest_recall"] = forest_at["recall"]
    classified = [(i, suggested[k]) for k, i in enumerate(ids) if judgement[k] and best[k] >= 0.5]
    correct = sum(1 for i, rule in classified if i in positives[rule])
    return {"ledger": name, "invoices": len(ids), "heads": heads, "second_opinion": second,
            "classification": {"judgement_anomalies": int(judgement.sum()), "scored_at_least_half": len(classified),
                               "suggested_rule_right": correct,
                               "accuracy": round(correct / len(classified), 4) if classified else None},
            "microseconds_per_invoice": {"features": round(feature_seconds / len(ids) * 1e6, 1),
                                         "prediction": round(predict_seconds / len(ids) * 1e6, 2)}}


def shap_checks(model: screen.Screen, thresholds: dict, n: int = 200) -> dict:
    transactions = extract(DATA / "bench_seed_101")[:n]
    X = screen.matrix(transactions, lambda _t: thresholds)
    worst_diff, worst_local = 0.0, 0.0
    started = time.perf_counter()
    for head in model.heads.values():
        exact = head.shap(X)
        tree = np.zeros_like(X)
        for r in range(X.shape[0]):
            for t in head.trees:
                tree[r] += np.asarray(tree_shap(t, X[r], X.shape[1]))
        tree *= head.learning_rate
        worst_diff = max(worst_diff, float(np.abs(exact - tree).max()))
        local = head.expected_raw() + exact.sum(axis=1) - head.raw(X)
        worst_local = max(worst_local, float(np.abs(local).max()))
    seconds = time.perf_counter() - started
    return {"invoices": n, "heads": len(model.heads), "max_difference_between_implementations": worst_diff,
            "max_local_accuracy_error": worst_local,
            "milliseconds_per_invoice_both_methods_all_heads": round(seconds / n * 1000, 2)}


def summary(ledgers: list[dict]) -> dict:
    """The figures the model page and the documents quote: per head, the mean and range over the held-out ledgers."""
    out = {"ledgers": [entry["ledger"] for entry in ledgers], "heads": {}}
    for head in screen.HEADS:
        aucs = [entry["heads"][head]["auc"] for entry in ledgers]
        forest = [entry["heads"][head]["isolation_forest"]["auc"] for entry in ledgers]
        r2 = [entry["heads"][head]["budgets"][1]["recall"] for entry in ledgers]
        out["heads"][head] = {"title": screen.HEADS[head], "auc_mean": round(float(np.mean(aucs)), 4),
                              "auc_min": min(aucs), "auc_max": max(aucs),
                              "isolation_forest_auc_mean": round(float(np.mean(forest)), 4),
                              "recall_at_2pct_mean": round(float(np.mean(r2)), 4)}
    found = sum(e["second_opinion"]["budgets"][1]["found"] for e in ledgers)
    hidden = sum(e["second_opinion"]["judgement_anomalies_among_them"] for e in ledgers)
    out["second_opinion_at_2pct"] = {"found": found, "of": hidden, "recall": round(found / hidden, 4) if hidden else None}
    right = sum(e["classification"]["suggested_rule_right"] for e in ledgers)
    tried = sum(e["classification"]["scored_at_least_half"] for e in ledgers)
    out["classification"] = {"right": right, "of": tried, "accuracy": round(right / tried, 4) if tried else None}
    return out


def render(report: dict) -> str:
    lines = ["# The risk screen on ledgers it was not trained on", "",
             f"Generated by `python -m evaluation.screen_eval` on {report['date']}. Trained on "
             f"`{report['training']['ledger']}` ({report['training']['invoices']:,} invoices; policy "
             f"v{report['training']['policy_version']}; {screen.PARAMS['n_estimators']} trees of depth "
             f"{screen.PARAMS['max_depth']} per head, learning rate {screen.PARAMS['learning_rate']}). "
             f"The model trained here {'is' if report['reproduces_committed_model'] else 'is NOT'} the committed "
             "`models/risk_screen.json`.", "",
             "Every ledger comes from the same generator as the training ledger, with other seeds and sizes: these "
             "numbers show generalisation across ledgers of this generator, not accuracy on real invoices.", "",
             "## Summary over the six held-out ledgers", "",
             "| Head | Rule | AUC, mean (min to max) | Isolation forest AUC, mean | Recall at a 2 % budget, mean |",
             "|---|---|---|---|---|"]
    for head, s in report["summary"]["heads"].items():
        lines.append(f"| {head} | {s['title']} | {s['auc_mean']:.4f} ({s['auc_min']:.4f} to {s['auc_max']:.4f}) | "
                     f"{s['isolation_forest_auc_mean']:.4f} | {s['recall_at_2pct_mean']:.3f} |")
    so, cl = report["summary"]["second_opinion_at_2pct"], report["summary"]["classification"]
    lines += ["", f"**Second opinion.** Of the {so['of']:,} judgement anomalies that the controls alone (C1) approve on "
                  f"the six ledgers, the screen puts {so['found']:,} ({so['recall']:.1%}) in the top 2 % of the "
                  "invoices C1 approves: the recall ceiling of a cascade that sends that slice to the agents.", "",
              f"**Classification.** Of the {cl['of']:,} judgement anomalies scored at least 0.5, the head with the "
              f"highest probability names a rule the invoice breaks for {cl['right']:,} ({cl['accuracy']:.1%}).", ""]
    s = report["shap"]
    lines += ["**Explanations.** On " f"{s['invoices']} invoices and all {s['heads']} heads, the two SHAP implementations "
              f"differ by at most {s['max_difference_between_implementations']:.2e} and the SHAP values add up to the "
              f"model's output within {s['max_local_accuracy_error']:.2e} (log-odds).", ""]
    for entry in report["ledgers"]:
        lines += [f"## {entry['ledger']} ({entry['invoices']:,} invoices)", "",
                  "| Head | Positives | AUC | Avg. precision | Recall @1% | @2% | @5% | Precision @2% | IF AUC | "
                  "Hard negatives in top k |", "|---|---|---|---|---|---|---|---|---|---|"]
        for head, h in entry["heads"].items():
            b = h["budgets"]
            hn = ", ".join(f"{k} {v}" for k, v in (h["hard_negatives_in_top"] or {}).items()) or ("-" if head == "any" else "none")
            lines.append(f"| {head} | {h['positives']} | {h['auc']:.4f} | {h['average_precision']:.4f} | {b[0]['recall']:.3f} | "
                         f"{b[1]['recall']:.3f} | {b[2]['recall']:.3f} | {b[1]['precision']:.3f} | "
                         f"{h['isolation_forest']['auc']:.4f} | {hn} |")
        so = entry["second_opinion"]
        lines += ["", f"C1 approves {so['approved_by_c1']:,} invoices, {so['judgement_anomalies_among_them']} of them "
                      "judgement anomalies; the screen's top slices of those invoices hold: "
                  + "; ".join(f"{b['budget']:.0%} ({b['k']:,} invoices) {b['found']} ({b['recall']:.1%}; isolation forest "
                              f"{b['isolation_forest_recall']:.1%})" for b in so["budgets"]) + ".",
                  f"Suggested rule right for {entry['classification']['suggested_rule_right']} of "
                  f"{entry['classification']['scored_at_least_half']} judgement anomalies scored at least 0.5. "
                  f"Features {entry['microseconds_per_invoice']['features']} µs and prediction "
                  f"{entry['microseconds_per_invoice']['prediction']} µs per invoice (all heads).", ""]
    return "\n".join(lines)


def main() -> None:
    policy = load_policy("2.5")
    thresholds = screen.policy_parameters(policy)
    trained = screen.train(DATA / screen.TRAINING_LEDGER, policy)
    probe = OUT / "_trained.json"
    OUT.mkdir(parents=True, exist_ok=True)
    trained.save(probe)
    committed = screen.MODEL_FILE.read_bytes() if screen.MODEL_FILE.exists() else b""

    def without_time(raw: bytes) -> str:
        data = json.loads(raw)
        data["training"].pop("seconds", None)
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    same = bool(committed) and without_time(committed) == without_time(probe.read_bytes())
    probe.unlink()
    model = screen.Screen.load() if same else trained
    ledgers = []
    for name in HELD_OUT:
        print(f"scoring {name}")
        ledgers.append(evaluate_ledger(name, model, thresholds, policy.clauses))
    report = {"date": time.strftime("%Y-%m-%d"), "training": {k: v for k, v in trained.training.items() if k != "seconds"},
              "reproduces_committed_model": same, "ledgers": ledgers, "shap": shap_checks(model, thresholds)}
    report["summary"] = summary(ledgers)
    (OUT / "screen.json").write_text(json.dumps(report, indent=1, default=int) + "\n", encoding="utf-8")
    (OUT / "screen.md").write_text(render(report), encoding="utf-8", newline="\n")
    print(f"wrote {OUT / 'screen.md'}")


if __name__ == "__main__":
    main()
