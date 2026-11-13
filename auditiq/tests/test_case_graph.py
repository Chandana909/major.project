"""The audited ledger as a graph, and retrieval over it.

    python -m pytest tests/test_case_graph.py
"""
from __future__ import annotations

import pytest

from auditiq.case_graph import CaseGraph


def flag(clause: str, severity: str = "high", message: str = "") -> dict:
    return {"clause": clause, "severity": severity, "message": message or f"finding {clause}"}


@pytest.fixture()
def graph() -> CaseGraph:
    rules = {"5.1.1": {"title": "Approval limit", "severity": "critical"}, "3.1.3": {"title": "GSTIN vendor match", "severity": "high"},
             "4.4.1": {"title": "Blocked vendor", "severity": "critical"}, "2.2.1": {"title": "Exact duplicate", "severity": "critical"}}
    vendors = {
        "VEND1001": {"name": "Acme Traders", "category": "MRO", "pan": "AAAPA1111A", "gstin": "27AAAPA1111A1Z5", "blacklisted": False, "status": "Active"},
        "VEND1002": {"name": "Brightline Supplies", "category": "MRO", "pan": "AAAPA1111A", "gstin": "29AAAPA1111A1Z3", "blacklisted": False, "status": "Active"},
        "VEND1003": {"name": "Crooked Logistics", "category": "Logistics", "pan": "CCCPC3333C", "gstin": "07CCCPC3333C1Z1", "blacklisted": True, "status": "Suspended"},
        "VEND1004": {"name": "Quiet Works", "category": "Utilities", "pan": "DDDPD4444D", "gstin": "33DDDPD4444D1Z9", "blacklisted": False, "status": "Active"},
    }
    totals = {"VEND1001": {"invoices": 10, "amount": 1_000_000.0, "flagged": 2, "flagged_amount": 700_000.0},
              "VEND1002": {"invoices": 6, "amount": 400_000.0, "flagged": 0, "flagged_amount": 0.0},
              "VEND1003": {"invoices": 3, "amount": 300_000.0, "flagged": 1, "flagged_amount": 120_000.0},
              "VEND1004": {"invoices": 20, "amount": 900_000.0, "flagged": 0, "flagged_amount": 0.0}}
    invoices = {
        "INV40001": {"vendor": "VEND1001", "route": "escalate", "level": "CRITICAL", "score": 70.0, "amount": 400_000.0, "date": "2025-06-02",
                 "approver": "Ann", "role": "Manager", "limit": 100_000.0, "flags": [flag("5.1.1", "critical", "Invoice amount 400000 exceeds the Manager approval limit of 100000.")]},
        "INV40002": {"vendor": "VEND1001", "route": "escalate", "level": "CRITICAL", "score": 90.0, "amount": 300_000.0, "date": "2025-06-09",
                 "approver": "Ann", "role": "Manager", "limit": 100_000.0, "flags": [flag("5.1.1", "critical"), flag("3.1.3")]},
        "INV40003": {"vendor": "VEND1003", "route": "escalate", "level": "CRITICAL", "score": 70.0, "amount": 120_000.0, "date": "2025-07-01",
                 "approver": "Bob", "role": "Senior Manager", "limit": 500_000.0, "flags": [flag("4.4.1", "critical")]},
    }
    approvers = {"Ann": {"role": "Manager", "limit": 100_000.0, "approvals": 8}, "Bob": {"role": "Senior Manager", "limit": 500_000.0, "approvals": 12}}
    rings = [
        {"id": 1, "vendors": ["VEND1001", "VEND1004"], "approvers": ["Ann"], "approver_roles": ["Manager"], "links": 3,
         "link_kinds": {"repeated findings": 1, "approver hotspot": 2}, "rules": {"5.1.1": 2}, "flagged_invoices": 2, "flagged_amount": 700_000.0},
        {"id": 2, "vendors": ["VEND1001", "VEND1002"], "approvers": [], "approver_roles": [], "links": 1, "link_kinds": {"shared PAN": 1},
         "rules": {}, "flagged_invoices": 0, "flagged_amount": 0.0},
    ]
    links = [{"source": "a:Ann", "target": "v:VEND1001", "kinds": ["repeated findings", "approver hotspot"], "invoices": 2},
             {"source": "a:Ann", "target": "v:VEND1004", "kinds": ["approver hotspot"], "invoices": 1}]
    return CaseGraph("2.5", rules, vendors, totals, invoices, approvers, rings, links)


def test_an_invoice_fact_gives_the_findings_the_approver_and_the_ring(graph):
    fact = graph.query("Why was INV40002 flagged?").facts[0]
    assert fact.kind == "invoice" and fact.data["rules"] == ["5.1.1", "3.1.3"] and fact.data["approvers"] == ["Ann"]
    assert "Acme Traders" in fact.text and "scored 90" in fact.text and "ring 1" in fact.text
    assert "Manager, limit" in fact.text and "finding 3.1.3" in fact.text


def test_an_invoice_without_findings_is_not_invented(graph):
    fact = graph.query("What is wrong with INV99999?").facts[0]
    assert fact.data["findings"] == 0 and "No findings are held" in fact.text


def test_a_vendor_is_found_by_name_or_id_and_its_numbers_come_from_the_totals(graph):
    for question in ("Tell me about Acme Traders", "what about v1?".replace("v1", "VEND1001")):
        fact = next(f for f in graph.query(question).facts if f.kind == "vendor")
        assert fact.data["flagged"] == 2 and "10 invoices" in fact.text and "shares an identity with Brightline Supplies" in fact.text
    blocked = next(f for f in graph.query("Crooked Logistics").facts if f.kind == "vendor")
    assert "blacklisted" in blocked.text


def test_an_approver_fact_counts_what_was_approved_above_the_limit(graph):
    fact = next(f for f in graph.query("What do we know about Ann?").facts if f.kind == "approver")
    assert fact.data["over_limit"] == 2 and fact.data["flagged"] == 2 and fact.data["rings"] == [1]
    assert fact.data["vendors"] == ["VEND1001"]                     # the vendor with a tested ring link, not every vendor she touched


def test_a_rule_fact_counts_its_invoices_and_names_the_worst_vendors_and_approvers(graph):
    fact = next(f for f in graph.query("How many invoices break rule 5.1.1?").facts if f.kind == "rule")
    assert fact.data["flagged"] == 2 and fact.data["vendors"] == ["VEND1001"] and fact.data["approvers"] == ["Ann"]


def test_everyday_words_point_to_rules(graph):
    rec = graph.recognise("Which invoices were approved above their approver's limit and which came from blacklisted vendors?")
    assert set(rec["rule_words"]) == {"5.1.1", "4.4.1"}
    assert graph.recognise("any duplicate invoices?")["rule_words"] == ["2.2.1"]


def test_a_collusion_question_names_the_core_of_a_ring_and_counts_the_rest(graph):
    answer = graph.query("Which vendors are in collusion rings?")
    ring = next(f for f in answer.facts if f.kind == "ring" and f.data["rings"] == [1])
    assert ring.data["vendors"] == ["VEND1001"] and "1 more vendors are in the ring through the approver's hotspot link only" in ring.text
    assert "g:1" in answer.nodes


def test_an_identity_question_gets_the_pairs_and_not_the_approver_rings(graph):
    answer = graph.query("Which vendors share the same PAN?")
    kinds = [f.kind for f in answer.facts]
    assert "identity" in kinds and "ring" not in kinds
    assert set(next(f for f in answer.facts if f.kind == "identity").data["vendors"]) == {"VEND1001", "VEND1002"}


def test_a_question_that_names_nothing_gets_no_facts_and_a_fraud_question_gets_the_overview(graph):
    assert graph.query("What is the weather?").facts == []
    overview = graph.query("Give me a summary of the findings").facts[0]
    assert overview.kind == "overview" and overview.data["flagged"] == 3 and "3 of 39 invoices" in overview.text


def test_facts_are_numbered_for_the_prompt(graph):
    text = graph.query("Which vendors are in collusion rings?").facts_text()
    assert text.startswith("[C1] ") and "\n[C2] " in text


@pytest.mark.parametrize("focus, kind, must", [
    ("Acme Traders", "vendor", {"v:VEND1001", "i:INV40001", "r:5.1.1", "a:Ann", "g:1"}),
    ("INV40003", "invoice", {"i:INV40003", "v:VEND1003", "r:4.4.1", "a:Bob"}),
    ("Ann", "approver", {"a:Ann", "i:INV40001", "i:INV40002", "v:VEND1001"}),
    ("g:1", "ring", {"g:1", "v:VEND1001", "a:Ann"}),
    ("5.1.1", "rule", {"r:5.1.1", "v:VEND1001", "a:Ann"}),
    ("v:VEND1002", "vendor", {"v:VEND1002", "v:VEND1001"}),
])
def test_the_neighbourhood_of_a_node(graph, focus, kind, must):
    view = graph.public(focus)
    ids = {n["id"] for n in view["nodes"]}
    assert view["focus_kind"] == kind and must <= ids
    assert all(e["source"] in ids and e["target"] in ids for e in view["edges"])


def test_the_overview_is_the_rings_and_an_unknown_node_resolves_to_nothing(graph):
    view = graph.public()
    assert view["focus"] is None and {"g:1", "g:2"} <= {n["id"] for n in view["nodes"]}
    assert any(e["kind"] == "shares PAN" for e in view["edges"])
    assert graph.resolve("nobody") is None and graph.resolve("g:99") is None and graph.resolve("r:9.9.9") is None
    assert view["counts"]["rings"] == 2 and view["counts"]["findings"] == 4


def test_the_view_is_cut_to_the_limit_and_says_so(graph):
    view = graph.public("Acme Traders", limit=3)
    assert len(view["nodes"]) == 3 and view["truncated"] is True
    assert all(e["source"] in {n["id"] for n in view["nodes"]} for e in view["edges"])
