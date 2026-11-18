"""The judgement-rule leads (auditiq/leads.py) and monetary-unit sampling (auditiq/sampling.py)."""
from __future__ import annotations

import math

import numpy as np
import pytest

from auditiq import db, leads, sampling, service
from auditiq.graph import PRESETS


# ------------------------------------------------------------------ numbers
@pytest.mark.parametrize("earlier, later", [
    ("GSG00620", "gsg00620"),                      # case
    ("INV-UGW-0590", "INV-UGW-0590-R"),           # an added suffix
    ("SEM/INV/0429", "SEM/INV/0429A"),
    ("EAO/25-26/00445", "EAO/25-26/445"),         # leading zeros of one group, the others kept apart
    ("BVG-000185", "BVG-00O185"),                 # a letter O keyed for a zero
    ("AB-1234", "AB-1243"),                        # two neighbours transposed
    ("AB-1234", "AB-1284"),                        # one substituted
])
def test_a_re_keyed_number_is_recognised(earlier, later):
    assert leads.rekeyed(earlier, later)


@pytest.mark.parametrize("earlier, later", [
    ("INV-0590", "INV-0590"),                      # the same number is an exact duplicate (2.2.1), not a lead
    ("INV-0590", "INV-7712"),                      # an unrelated number
    ("AB-1234", "AB-4321"),
])
def test_an_unrelated_or_identical_number_is_not_re_keyed(earlier, later):
    assert leads.rekeyed(earlier, later) is None


def inv(invoice_id, day, amount, number="N-1", po="PO1", grn="GRN1", vendor="V1", description="Goods"):
    return {"invoice_id": invoice_id, "vendor_id": vendor, "vendor_name": vendor, "invoice_number": number,
            "date": day, "amount": amount, "po_id": po, "grn_id": grn, "description": description}


def test_a_near_duplicate_needs_the_same_receipt_and_amount():
    ledger = [inv("I1", "2025-04-01", 5000.0, "AB-100"), inv("I2", "2025-04-09", 5000.0, "ab100"),
              inv("I3", "2025-04-10", 5000.0, "AB-101", po="PO2", grn="GRN2"),       # consecutive, separate delivery
              inv("I4", "2025-04-11", 5000.01, "AB-100/R")]                          # another amount
    pairs = leads.near_duplicates(ledger)
    assert [(p["invoice_id"], p["original_id"]) for p in pairs] == [("I2", "I1")]


def test_structuring_needs_different_days_the_band_and_a_total_above_the_limit():
    limits = {"Manager": 100000.0, "Senior Manager": 500000.0}
    ledger = [inv("A1", "2025-04-01", 92000.0), inv("A2", "2025-04-03", 95000.0, description="Other wording"),
              inv("B1", "2025-04-01", 92000.0, vendor="V2"), inv("B2", "2025-04-01", 93000.0, vendor="V2"),
              inv("C1", "2025-04-01", 92000.0, vendor="V3"), inv("C2", "2025-04-20", 93000.0, vendor="V3"),
              inv("D1", "2025-04-01", 70000.0, vendor="V4"), inv("D2", "2025-04-02", 71000.0, vendor="V4")]
    approver = {i["invoice_id"]: ("Manager", "M") for i in ledger}
    groups = leads.structuring(ledger, approver, limits, window_days=7, band_pct=15)
    # V1: listed, and the differing descriptions are shown for the reviewer; V2: one day only; V3: outside the
    # window; V4: below the band.
    assert [g["invoices"] for g in groups] == [["A1", "A2"]]
    assert groups[0]["same_description"] is False and groups[0]["total"] == 187000.0


def test_the_leads_of_a_benchmark_ledger_match_its_answer_key(ledger):
    conn = db.connect(ledger)
    try:
        out = leads.judgement_leads(conn)
    finally:
        conn.close()
    key = out["answer_key"]
    assert key["compared"] and out["guide"] == {"window_days": 7, "band_pct": 15.0, "limits": out["guide"]["limits"]}
    for clause in ("2.2.2", "4.1.2"):
        assert key[clause]["labelled"] > 0, clause
        assert key[clause]["recall"] == 1.0 and key[clause]["precision"] == 1.0, (clause, key[clause])
    assert out["near_duplicates"]["unaudited"] == out["near_duplicates"]["invoices"]       # nothing audited yet


# ----------------------------------------------------------------- sampling
def test_the_plan_follows_the_formula_and_its_factors():
    assert round(sampling.reliability(0, 0.95), 4) == 2.9957 and round(sampling.reliability(1, 0.95), 2) == 4.74
    p = sampling.plan(1_000_000.0, 5000, confidence=0.95, tolerable_pct=5.0)
    assert p["size"] == math.ceil(1_000_000 * sampling.reliability(0, 0.95) / 50_000) == 60
    assert p["interval"] == pytest.approx(1_000_000 / 60)
    with_expected = sampling.plan(1_000_000.0, 5000, confidence=0.95, tolerable_pct=5.0, expected_pct=1.0)
    assert with_expected["size"] == math.ceil(1_000_000 * sampling.reliability(0, 0.95) / (50_000 - 10_000 * 1.6))
    with pytest.raises(ValueError):
        sampling.plan(1_000_000.0, 5000, tolerable_pct=1.0, expected_pct=1.0)
    with pytest.raises(ValueError):
        sampling.plan(1_000_000.0, 5000, confidence=0.8)


def test_selection_takes_every_large_item_and_one_unit_per_interval():
    amounts = np.array([10.0, 500.0, 20.0, 30.0, 40.0, 400.0])        # 1,000 in all
    index, hits = sampling.select(amounts, interval=100.0, start=50.0)
    assert hits.sum() == 10                                            # units 50, 150, ... 950
    assert {1, 5} <= set(index.tolist()) and dict(zip(index.tolist(), hits.tolist()))[1] == 5


def test_the_stringer_bound_with_and_without_misstatements():
    interval = 100.0
    none = sampling.stringer(np.array([50.0, 60.0]), np.array([0.0, 0.0]), interval, 0.95)
    assert none["upper_limit"] == pytest.approx(sampling.reliability(0, 0.95) * interval, abs=0.01)
    # One item misstated in full, one by half, one of the interval or more misstated by 30 (taken as it is).
    found = sampling.stringer(np.array([50.0, 80.0, 250.0]), np.array([50.0, 40.0, 30.0]), interval, 0.95)
    r = [sampling.reliability(k, 0.95) for k in range(3)]
    assert found["upper_limit"] == pytest.approx(30 + interval * (r[0] + (r[1] - r[0]) * 1.0 + (r[2] - r[1]) * 0.5),
                                                 abs=0.01)
    assert found["projected"] == pytest.approx(30 + interval * 1.5) and found["misstatements"] == 3


def test_the_bound_covers_the_truth_at_least_at_its_confidence():
    rng = np.random.default_rng(3)
    amounts = rng.lognormal(10, 1.2, 4000)
    misstated = np.where(rng.random(4000) < 0.02, amounts, 0.0)
    p = sampling.plan(float(amounts.sum()), len(amounts), confidence=0.95, tolerable_pct=5.0)
    out = sampling.repeated(amounts, misstated, p, starts=400, seed=1)
    assert out["bound_holds_share"] >= 0.95


def test_a_sample_of_an_audited_benchmark_ledger(ledger):
    conn = db.connect(ledger)
    try:
        service.audit_in_force(conn, PRESETS["C1"], None, db.invoice_ids(conn))
        first = sampling.monetary_unit_sample(conn, seed=11)
        again = sampling.monetary_unit_sample(conn, seed=11)
        approved = int(conn.scalar("SELECT COUNT(*) FROM v_latest_results WHERE route = 'approve'"))
    finally:
        conn.close()
    assert first["sample"] == again["sample"] and first["seed"] == 11              # the seed draws the same sample
    assert first["plan"]["items"] == approved and first["drawn"] <= first["plan"]["size"]
    key = first["answer_key"]
    assert key is not None and key["true_misstatement"] > 0                       # C1 approves the judgement classes
    assert set(key["sampled_anomalous"]) <= {s["invoice_id"] for s in first["sample"]}
