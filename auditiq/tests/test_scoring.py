"""Tests of confidence, scores and routing."""
from __future__ import annotations

import math
import random

import pytest

from auditiq import scoring as s
from auditiq.policy import load_policy

CLAUSES = load_policy("2.5").clauses

TXN = {
    "invoice": {"invoice_id": "INV40100", "invoice_number": "ABC/25-26/00123", "date": "2025-06-11",
                "amount": 84250.5, "quantity": 50, "po_id": "PO20050", "grn_id": None},
    "po": {"po_id": "PO20050", "amount": 84250.5, "description": "V-belts, B section"},
    "grn": {"grn_id": "GRN30050", "received_quantity": 50,
            "notes": "5 pieces rejected at QC and returned to the vendor."},
    "vendor": {"vendor_id": "VEND1001", "official_gstin": "36ABCDE1234F1Z5", "blacklisted": False},
    "approvals": [
        {"approver_role": "Manager", "approver_name": "A Manager", "timestamp": "2025-06-12 10:00:00", "action_taken": "Escalated"},
        {"approver_role": "Senior Manager", "approver_name": "S Manager", "timestamp": "2025-06-12 15:00:00", "action_taken": "Approved"},
    ],
    "vendor_history": [{"invoice_id": "INV40050", "invoice_number": "ABC/25-26/123", "date": "2025-05-02", "amount": 84250.5}],
}


def flag(severity: str, confidence: float = 1.0, source: str = "D") -> dict:
    return {"severity": severity, "confidence": confidence, "source": source}


def test_evidence_paths_resolve_against_the_transaction():
    assert s.resolve(TXN, "invoice.amount") == 84250.5
    assert s.resolve(TXN, "grn.received_quantity") == 50
    assert s.resolve(TXN, "approval.approver_role") == "Senior Manager"
    assert s.resolve(TXN, "approvals[0].action_taken") == "Escalated"
    assert s.resolve(TXN, "history.INV40050.invoice_number") == "ABC/25-26/123"
    assert s.resolve(TXN, "invoice.grn_id") is None
    for missing in ("invoice.colour", "history.INV49999.amount", "ledger.amount", "invoice", "",
                    "approvals[7].approver_role", "history.INV40050", None):
        assert s.resolve(TXN, missing) is s._MISSING, missing


@pytest.mark.parametrize("evidence, expected", [
    ([{"field": "invoice.amount", "value": 84250.5}, {"field": "po.amount", "value": 84250.5}], 1),
    ([{"field": "invoice.amount", "value": "84,250.50"}], 1),              # formatted number
    ([{"field": "invoice.amount", "value": "₹84250.5"}], 1),
    ([{"field": "po.description", "value": "v-belts, b section "}], 1),    # case and spaces
    ([{"field": "invoice.grn_id", "value": None}], 1),
    ([{"field": "vendor.blacklisted", "value": "false"}], 1),
    ([{"field": "invoice.amount", "value": 84250.5}, {"field": "po.amount", "value": 80000}], 0),
    ([{"field": "history.INV49999.invoice_number", "value": "ABC/25-26/00123"}], 0),   # no such invoice
    ([{"field": "invoice.amount", "value": "about eighty thousand"}], 0),
    ([{"field": "history.INV40050.invoice_number", "value": "ABC/25-26/00123"}], 0),   # not the stored number
    ([{"field": "invoice.quantity", "value": True}], 0),
    (["invoice.amount is 84250.5"], 0),                                     # not a field/value pair
])
def test_grounding_every_evidence_field_must_exist_with_the_stated_value(evidence, expected):
    assert s.grounding({"evidence": evidence}, TXN) == expected


@pytest.mark.parametrize("flag_", [{"evidence": []}, {}, {"evidence": "invoice looks wrong"}, {"evidence": None}])
def test_a_flag_without_evidence_is_not_grounded(flag_):
    assert s.grounding(flag_, TXN) == 0


def test_clause_validity_the_cited_clause_must_exist_in_the_active_policy():
    assert s.clause_validity({"clause": "2.1.4"}, CLAUSES) == 1
    assert s.clause_validity({"clause": "Rule 2.1.4"}, CLAUSES) == 1
    for bad in ({"clause": "9.9.9"}, {"clause": ""}, {}):
        assert s.clause_validity(bad, CLAUSES) == 0


def test_confidence_is_1_for_a_control_flag_and_the_mean_of_three_terms_for_an_llm_flag():
    assert s.confidence({"source": "D"}, TXN, CLAUSES) == {"g": 1, "p": 1, "a": 1.0, "c": 1.0}
    grounded = {"source": "L", "clause": "2.1.4", "evidence": [{"field": "grn.received_quantity", "value": 50}]}
    assert s.confidence(grounded, TXN, CLAUSES, 1)["c"] == 1
    assert math.isclose(s.confidence(grounded, TXN, CLAUSES, 0)["c"], 2 / 3)
    invented = {"source": "L", "clause": "7.7.7", "evidence": [{"field": "invoice.amount", "value": 1}]}
    assert s.confidence(invented, TXN, CLAUSES, 0)["c"] == 0
    for bad in (None, 1.5, -0.1, True, "1"):
        with pytest.raises(TypeError):
            s.confidence(grounded, TXN, CLAUSES, bad)


def test_confidence_weights_are_configurable_for_the_sensitivity_analysis():
    f = {"source": "L", "clause": "2.1.4", "evidence": []}          # g = 0, p = 1
    options = s.ScoringOptions(confidence_weights=(2, 1, 1))
    assert math.isclose(s.confidence(f, TXN, CLAUSES, 0.5, options)["c"], (0 + 1 + 0.5) / 4)


def test_normalize_flag_a_valid_clause_fixes_the_severity():
    assert s.normalize_flag({"clause": "Rule 2.2.2", "severity": "LOW", "source": "agent"}, CLAUSES) == \
        {"clause": "2.2.2", "severity": "critical", "source": "L"}
    assert s.normalize_flag({"clause": "9.9.9", "severity": "HIGH"}, CLAUSES)["severity"] == "high"
    assert s.normalize_flag({"clause": "none", "severity": "severe"}, CLAUSES)["severity"] == "medium"
    assert s.normalize_flag({"clause": "2.1.1", "severity": "high", "source": "D"}, CLAUSES)["source"] == "D"


@pytest.mark.parametrize("flags, expected", [
    ([], 0),
    ([("low",)], 5),
    ([("medium",), ("low",)], 15),
    ([("high",)], 50),                                   # 20, raised by the floor
    ([("critical",)], 70),                               # 30, raised by the floor
    ([("high",)] * 3, 60),
    ([("critical",)] * 3 + [("high",)], 100),
    ([("medium",)] * 6, 60),                             # no floor needed
])
def test_count_based_score(flags, expected):
    assert s.count_score([flag(*f) for f in flags]) == expected


def test_weighted_score_floors_apply_only_to_flags_with_confidence_at_least_theta():
    assert s.weighted_score([flag("critical", 1)]) == 70
    assert s.weighted_score([flag("critical", 2 / 3, "L")]) == 70            # exactly theta
    assert math.isclose(s.weighted_score([flag("critical", 0.6, "L")]), 18)
    assert s.weighted_score([flag("critical", 0.3, "L"), flag("high", 1)]) == 50   # 9 + 20, high floor
    assert s.weighted_score([]) == 0


@pytest.mark.parametrize("r0, rc, expected", [(70, 70, "escalate"), (50, 50, "escalate"), (70, 23.3, "sample"),
                                              (49.9, 49.9, "approve"), (0, 0, "approve")])
def test_routing_follows_equation_5(r0, rc, expected):
    assert s.route(r0, rc) == expected


def test_the_worked_illustration_of_the_paper():
    """Section IV-C: a medium control flag and a critical agent flag with g = 0, p = 1, a = 1/3."""
    c = (0 + 1 + 1 / 3) / 3
    assert math.isclose(c, 4 / 9)
    result = s.score([flag("medium", 1, "D"), flag("critical", c, "L")])
    assert result["r0"] == 70                                    # 40, raised by the critical floor
    assert math.isclose(result["rc"], 10 + 30 * 4 / 9)           # 23.3, no floor since 4/9 < theta
    assert result["route"] == "sample"


def test_without_the_confidence_feature_the_count_based_score_decides_alone():
    result = s.score([flag("critical", 0.2, "L")], s.ScoringOptions(use_confidence=False))
    assert (result["r0"], result["rc"], result["route"]) == (70, 70, "escalate")


def test_by_construction_rc_never_exceeds_r0_and_the_approved_set_is_the_same():
    rng = random.Random(20261011)
    levels = [0, 1 / 3, 1 / 2, 2 / 3, 1]
    count_only = s.ScoringOptions(use_confidence=False)
    routes = {"approve": 0, "sample": 0, "escalate": 0}
    for _ in range(20000):
        flags = []
        for _ in range(rng.randrange(7)):
            is_control = rng.random() < 0.4
            c = 1.0 if is_control else sum(rng.choice(levels) for _ in range(3)) / 3
            flags.append(flag(rng.choice(s.SEVERITIES), c, "D" if is_control else "L"))
        result = s.score(flags)
        assert result["rc"] <= result["r0"] + 1e-9, flags
        assert 0 <= result["rc"] and result["r0"] <= 100
        # Approved exactly when the count-based score is below the threshold.
        assert (result["route"] == "approve") == (result["r0"] < 50), flags
        assert (result["route"] == "approve") == (s.score(flags, count_only)["route"] == "approve")
        routes[result["route"]] += 1
    assert min(routes.values()) > 500, routes        # the check needs all three routes to occur


def test_a_transaction_with_control_flags_only_is_never_sampled():
    rng = random.Random(7)
    for _ in range(2000):
        flags = [flag(rng.choice(s.SEVERITIES)) for _ in range(rng.randrange(5))]
        result = s.score(flags)
        assert result["rc"] == result["r0"] and result["route"] != "sample"
