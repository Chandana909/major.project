"""Statistical tests of Section VI-D of the paper."""
from __future__ import annotations

from itertools import combinations

import numpy as np
from statsmodels.stats.contingency_tables import mcnemar
from statsmodels.stats.multitest import multipletests


def mcnemar_test(correct_a: np.ndarray, correct_b: np.ndarray) -> dict[str, float]:
    """Exact McNemar test on paired per-invoice correctness of two configurations."""
    a, b = np.asarray(correct_a, dtype=bool), np.asarray(correct_b, dtype=bool)
    if a.shape != b.shape:
        raise ValueError("the two configurations must be scored on the same invoices")
    only_a, only_b = int((a & ~b).sum()), int((~a & b).sum())
    table = [[int((a & b).sum()), only_a], [only_b, int((~a & ~b).sum())]]
    result = mcnemar(table, exact=True)
    return {"only_a_correct": only_a, "only_b_correct": only_b, "p_value": float(result.pvalue)}


def holm(p_values: dict[str, float], alpha: float = 0.05) -> dict[str, dict[str, float | bool]]:
    """Holm's step-down correction over a family of hypotheses."""
    names = list(p_values)
    reject, adjusted, _, _ = multipletests([p_values[n] for n in names], alpha=alpha, method="holm")
    return {n: {"p_value": p_values[n], "p_holm": float(p), "reject": bool(r)}
            for n, p, r in zip(names, adjusted, reject)}


def jaccard(a: set, b: set) -> float:
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def consistency(runs: list[dict[str, set[str]]]) -> float:
    """Mean pairwise Jaccard similarity of the flag sets of repeated runs.

    ``runs`` holds, per run, the set of cited clauses of every invoice.
    """
    if len(runs) < 2:
        raise ValueError("consistency needs at least two runs")
    ids = set(runs[0])
    if any(set(r) != ids for r in runs):
        raise ValueError("every run must cover the same invoices")
    per_invoice = [np.mean([jaccard(x[i], y[i]) for x, y in combinations(runs, 2)]) for i in sorted(ids)]
    return float(np.mean(per_invoice))


def non_inferior(value_new: float, value_ref: float, margin: float = 0.02) -> bool:
    """True if the new value is not worse than the reference by more than the margin."""
    return value_new >= value_ref - margin
