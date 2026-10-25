"""Tests of the computed revisions: each control finding comes with what the invoice needs, and an amended or
re-approved invoice passes the rule it failed."""
from __future__ import annotations

from test_controls import V25, clean_txn, with_amounts

from auditiq.audit_pack import build_pack, render_markdown
from auditiq.controls import run_controls
from auditiq.corrections import apply, correct


def revision(txn: dict, clause: str) -> dict:
    flag = next(f for f in run_controls(txn, V25) if f["clause"] == clause)
    return correct(flag, txn, V25)


def resolves(txn: dict, r: dict) -> bool:
    return all(f["clause"] != r["clause"] for f in run_controls(apply(txn, r), V25))


def test_an_overbilled_invoice_is_amended_to_the_po_amount_with_a_credit_note():
    t = with_amounts(90000.0, 84250.5)
    r = revision(t, "2.1.1")
    assert r["kind"] == "amend" and r["changes"] == [{"field": "invoice.amount", "from": 90000.0, "to": 84250.5}]
    assert r["amount_at_issue"] == 5749.5 and "credit note" in r["action"] and resolves(t, r)


def test_raising_an_underbilled_invoice_names_the_approver_the_po_amount_needs():
    t = with_amounts(95000.0, 120500.0)                          # a Manager may approve 100,000
    r = revision(t, "2.1.1")
    assert [c["to"] for c in r["changes"]] == [120500.0, "Senior Manager"] and "Senior Manager" in r["action"]
    fixed = apply(t, r)
    assert run_controls(fixed, V25) == []                          # neither 2.1.1 nor 5.1.1 any more


def test_billed_quantity_above_receipt_is_amended_to_the_received_quantity():
    t = clean_txn()
    t["grn"]["received_quantity"] = 45
    r = revision(t, "2.1.2")
    assert r["changes"] == [{"field": "invoice.quantity", "from": 50, "to": 45}]
    assert r["amount_at_issue"] == 8425.05 and resolves(t, r)


def test_a_gstin_error_is_amended_to_the_registered_gstin():
    for wrong, clause in (("36ABCDE1234F1Z", "3.1.1"), ("99ABCDE1234F1Z5", "3.1.2"), ("36ABCDE9999F1Z5", "3.1.3")):
        t = clean_txn()
        t["invoice"]["gstin"] = wrong
        r = revision(t, clause)
        assert r["kind"] == "amend" and r["changes"][0]["to"] == t["vendor"]["official_gstin"] and resolves(t, r)


def test_an_approval_above_the_limit_is_sent_to_the_lowest_role_that_covers_it():
    t = with_amounts(150000.0, 150000.0)
    r = revision(t, "5.1.1")
    assert r["kind"] == "reapprove" and r["changes"][0]["to"] == "Senior Manager" and resolves(t, r)


def test_actions_that_do_not_change_the_invoice():
    t = clean_txn()
    t["vendor_history"][0]["invoice_number"] = t["invoice"]["invoice_number"]
    assert revision(t, "2.2.1")["kind"] == "reject" and "INV40001" in revision(t, "2.2.1")["action"]
    t = clean_txn()
    t["vendor"]["blacklisted"] = True
    assert revision(t, "4.4.1")["kind"] == "hold"
    t = clean_txn()
    t["invoice"]["po_id"], t["po"] = None, None
    assert revision(t, "2.1.3")["kind"] == "obtain" and "purchase order" in revision(t, "2.1.3")["action"]
    t = clean_txn()
    t["vendor_history"] += [{"invoice_id": f"INV4009{i}", "invoice_number": f"X{i}", "date": "2025-06-11",
                             "amount": 30000.0} for i in range(3)]
    r = revision(t, "4.1.1")
    assert r["kind"] == "consolidate" and r["amount_at_issue"] == 174250.5 and r["changes"][0]["to"] == "Senior Manager"


def test_an_agent_finding_gets_no_computed_revision_and_the_pack_shows_the_controls_revision():
    t = with_amounts(90000.0, 84250.5)
    assert correct({"clause": "2.2.2", "source": "L", "severity": "high"}, t, V25) is None
    flags = run_controls(t, V25)
    score = {"route": "escalate", "risk_level": "HIGH", "r0": 50, "rc": 50, "threshold": 50}
    pack = build_pack(t, flags, [], score, None, V25, policy_version="2.5", configuration="C1", model=None)
    assert pack["flags"][0]["revision"]["kind"] == "amend"
    assert "Revision (amend): Bill the PO amount of 84250.50" in render_markdown(pack)
