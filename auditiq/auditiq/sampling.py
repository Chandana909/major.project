"""Monetary-unit sampling (ISA 530) of the invoices the audit approved without a person.

The controls and agents decide what they can; an invoice they approve is paid without anyone looking at it. An
auditor who relies on that approval tests it with a statistical sample: monetary-unit sampling, where every rupee of
the approved population has the same chance to be drawn, so that large invoices are more likely to be examined and
an invoice of at least the sampling interval always is.

    plan        the sample size n = BV x R(0, c) / (TM - E x EF(c)) for the population's book value BV, the
                tolerable misstatement TM, the expected misstatement E and the confidence c; the sampling interval
                J = BV / n. R(k, c) is the Poisson reliability factor for k misstatements, chi2.ppf(c, 2(k+1)) / 2
                (3.00, 4.74, 6.30, ... at 95 %), EF the AICPA expansion factor for the expected misstatement
    select      systematic selection with a random start r in [0, J): the invoices holding the monetary units r,
                r + J, r + 2J, ... of the population in invoice order; an invoice of J or more is drawn with certainty
    evaluate    the Stringer bound on the misstatement of the population from the misstatements the auditor finds in
                the sample: the actual misstatement of the invoices of J or more, plus J x (R(0) + sum over the other
                misstatements, largest tainting first, of (R(k) - R(k-1)) x tainting), where the tainting is the share
                of an invoice's amount that is misstated

Nothing here is audited: the sample is the list the auditor examines. On a benchmark ledger its answer key can
stand in for that examination (an anomalous invoice counted as misstated in full: the whole payment is at risk),
which shows what the auditor would conclude and whether the bound holds against the truth.
"""
from __future__ import annotations

import math
import random
from functools import lru_cache

import numpy as np

from . import analytics, db

# AICPA expansion factors for the expected misstatement, by confidence (Audit Guide, Audit Sampling).
EXPANSION = {0.90: 1.5, 0.95: 1.6, 0.99: 1.9}
CONFIDENCES = tuple(EXPANSION)


@lru_cache(maxsize=4096)
def reliability(k: int, confidence: float) -> float:
    """The Poisson reliability factor for k misstatements: the upper confidence limit of their expected number."""
    from scipy.stats import chi2  # imported when first needed: SciPy's statistics take a second to load

    return float(chi2.ppf(confidence, 2 * (k + 1)) / 2)


def plan(book_value: float, items: int, confidence: float = 0.95, tolerable_pct: float = 2.0,
         expected_pct: float = 0.0) -> dict:
    """Sample size and sampling interval for a population of ``items`` invoices worth ``book_value``."""
    if confidence not in EXPANSION:
        raise ValueError(f"confidence must be one of {', '.join(str(c) for c in CONFIDENCES)}")
    if book_value <= 0 or items <= 0:
        raise ValueError("the population is empty")
    tolerable = book_value * tolerable_pct / 100
    expected = book_value * expected_pct / 100
    room = tolerable - expected * EXPANSION[confidence]
    if tolerable_pct <= 0 or room <= 0:
        raise ValueError("the tolerable misstatement must exceed the expected misstatement times its expansion factor")
    size = min(items, math.ceil(book_value * reliability(0, confidence) / room))
    return {"book_value": round(book_value, 2), "items": items, "confidence": confidence,
            "tolerable_pct": tolerable_pct, "tolerable": round(tolerable, 2), "expected_pct": expected_pct,
            "expected": round(expected, 2), "reliability_factor": round(reliability(0, confidence), 4),
            "expansion_factor": EXPANSION[confidence], "size": size, "interval": book_value / size}


def select(amounts: np.ndarray, interval: float, start: float) -> tuple[np.ndarray, np.ndarray]:
    """Indices of the items holding the monetary units start, start + J, ... and how many units each holds."""
    cumulative = np.cumsum(amounts)
    units = start + interval * np.arange(int(math.floor((cumulative[-1] - start) / interval)) + 1)
    units = units[units < cumulative[-1]]
    picked = np.searchsorted(cumulative, units, side="right")
    return np.unique(picked, return_counts=True)


def stringer(amounts: np.ndarray, misstated: np.ndarray, interval: float, confidence: float) -> dict:
    """The projected misstatement and its upper limit from the sampled items' amounts and misstatements."""
    top = amounts >= interval
    top_actual = float(misstated[top].sum())
    taints = np.sort(np.clip(misstated[~top] / np.where(amounts[~top] > 0, amounts[~top], 1), 0, 1))[::-1]
    taints = taints[taints > 0]
    factors = [reliability(k, confidence) for k in range(len(taints) + 1)]
    increments = float(sum((factors[k] - factors[k - 1]) * float(t) for k, t in enumerate(taints, start=1)))
    return {"misstatements": int((misstated > 0).sum()), "top_stratum_actual": round(top_actual, 2),
            "projected": round(top_actual + float(taints.sum()) * interval, 2),
            "basic_precision": round(factors[0] * interval, 2),
            "upper_limit": round(float(top_actual + interval * (factors[0] + increments)), 2)}


def population(conn: db.Database) -> list[tuple]:
    """The invoices whose latest result approved them, in invoice order: (id, amount, vendor, findings, date)."""
    return [(r[0], float(r[1] or 0), r[2], int(r[3] or 0), r[4]) for r in conn.execute(
        "SELECT l.invoice_id, i.amount, v.vendor_name, l.flag_count, CAST(i.date AS TEXT) FROM v_latest_results l "
        "JOIN invoices i ON i.invoice_id = l.invoice_id LEFT JOIN vendor_master v ON v.vendor_id = i.vendor_id "
        "WHERE l.route = 'approve' AND i.amount > 0 ORDER BY l.invoice_id")]


def monetary_unit_sample(conn: db.Database, confidence: float = 0.95, tolerable_pct: float = 2.0,
                         expected_pct: float = 0.0, seed: int | None = None) -> dict:
    """A sample of the approved invoices to examine, with its plan, and on a benchmark ledger what the answer key
    says the examination would find."""
    items = population(conn)
    amounts = np.array([a for _, a, *_ in items])
    the_plan = plan(float(amounts.sum()) if len(items) else 0.0, len(items), confidence, tolerable_pct, expected_pct)
    seed = random.SystemRandom().randrange(1, 10**9) if seed is None else int(seed)
    start = random.Random(seed).random() * the_plan["interval"]
    index, hits = select(amounts, the_plan["interval"], start)
    sample = [{"invoice_id": items[i][0], "amount": items[i][1], "vendor_name": items[i][2], "findings": items[i][3],
               "date": items[i][4], "units": int(h), "certain": bool(items[i][1] >= the_plan["interval"])}
              for i, h in zip(index, hits)]
    out = {"plan": {**the_plan, "interval": round(the_plan["interval"], 2)}, "seed": seed, "start": round(start, 2),
           "drawn": len(sample), "certain": sum(s["certain"] for s in sample), "sample": sample,
           "answer_key": None}
    misstated = _answer_key_misstatement(conn)
    if misstated is not None:
        m = np.array([misstated.get(i[0], 0.0) for i in items])
        found = stringer(amounts[index], m[index], the_plan["interval"], confidence)
        truth = float(m.sum())
        out["answer_key"] = {**found, "true_misstatement": round(truth, 2),
                             "bound_holds": bool(found["upper_limit"] >= truth),
                             "conclusion": ("the approved population is not misstated by more than the tolerable "
                                            "misstatement, at this confidence" if found["upper_limit"] <= the_plan["tolerable"]
                                            else "the upper limit exceeds the tolerable misstatement: the approval "
                                                 "cannot be relied on without further work"),
                             "sampled_anomalous": [s["invoice_id"] for s, k in zip(sample, index) if m[k] > 0]}
    return out


def _answer_key_misstatement(conn: db.Database) -> dict[str, float] | None:
    """Invoice id -> its amount if the answer key labels it anomalous (the whole payment at risk), for labels written
    for the policy that governs the ledger."""
    if not conn.scalar("SELECT COUNT(*) FROM benchmark_labels"):
        return None
    key_policy = conn.scalar("SELECT value FROM meta WHERE key = 'labels_policy'") or analytics.BENCHMARK_POLICY
    if key_policy != analytics.governing_version(conn):
        return None
    return {i: float(a or 0) for i, a in conn.execute(
        "SELECT b.invoice_id, i.amount FROM benchmark_labels b JOIN invoices i ON i.invoice_id = b.invoice_id "
        "WHERE b.label = 'anomalous'")}


def repeated(amounts: np.ndarray, misstated: np.ndarray, the_plan: dict, starts: int = 1000, seed: int = 0) -> dict:
    """The sample drawn from ``starts`` random starts: how often the upper limit covers the true misstatement (it
    should at least at the confidence), and the spread of what the samples find."""
    rng = random.Random(seed)
    truth = float(misstated.sum())
    limits, counts = [], []
    for _ in range(starts):
        index, _hits = select(amounts, the_plan["interval"], rng.random() * the_plan["interval"])
        found = stringer(amounts[index], misstated[index], the_plan["interval"], the_plan["confidence"])
        limits.append(found["upper_limit"])
        counts.append(found["misstatements"])
    limits_a = np.array(limits)
    return {"starts": starts, "true_misstatement": round(truth, 2),
            "bound_holds_share": round(float((limits_a >= truth).sum()) / starts, 4),
            "upper_limit_median": round(float(np.median(limits_a)), 2),
            "upper_limit_p05": round(float(np.percentile(limits_a, 5)), 2),
            "misstatements_found_mean": round(float(np.mean(counts)), 2),
            "misstatements_found_range": [int(min(counts)), int(max(counts))],
            "within_tolerable_share": round(float((limits_a <= the_plan["tolerable"]).sum()) / starts, 4)}
