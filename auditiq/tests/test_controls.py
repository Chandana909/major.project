"""Tests of the deterministic controls."""
from __future__ import annotations

import copy
import json
import os
import time

import pytest

from auditiq.controls import run_controls
from auditiq.policy import load_policy

V25 = load_policy("2.5").clauses
V26 = load_policy("2.6").clauses
GSTIN = "36ABCDE1234F1Z5"


def clean_txn() -> dict:
    """A transaction that violates nothing under v2.5. Each test changes one thing."""
    return {
        "invoice": {
            "invoice_id": "INV40100", "vendor_id": "VEND1001", "invoice_number": "ABC/25-26/00123",
            "date": "2025-06-11", "amount": 84250.5, "quantity": 50, "unit_price": 1685.01, "gstin": GSTIN,
            "po_id": "PO20050", "grn_id": "GRN30050", "description": "V-belts, B section",
        },
        "po": {"po_id": "PO20050", "po_date": "2025-05-20", "amount": 84250.5, "quantity": 50,
               "unit_price": 1685.01, "description": "V-belts, B section"},
        "grn": {"grn_id": "GRN30050", "po_id": "PO20050", "receipt_date": "2025-06-09",
                "received_quantity": 50, "ordered_quantity": 50, "notes": ""},
        "vendor": {"vendor_id": "VEND1001", "vendor_name": "Test Vendor", "official_gstin": GSTIN,
                   "blacklisted": False, "gstin_status": "Active"},
        "approvals": [
            {"log_id": "LOG1", "approver_name": "A Manager", "approver_role": "Manager",
             "timestamp": "2025-06-12 15:10:00", "action_taken": "Approved", "amount_limit": 100000},
        ],
        "vendor_history": [
            {"invoice_id": "INV40001", "invoice_number": "ABC/25-26/00101", "date": "2025-04-03", "amount": 12000.4},
            {"invoice_id": "INV40090", "invoice_number": "ABC/25-26/00122", "date": "2025-06-10", "amount": 84250.5},
        ],
    }


def clauses(txn: dict, policy: dict = V25) -> list[str]:
    return sorted(f["clause"] for f in run_controls(txn, policy))


def with_amounts(invoice: float, po: float) -> dict:
    t = clean_txn()
    t["invoice"]["amount"], t["po"]["amount"] = invoice, po
    return t


def test_clean_transaction_raises_no_flag():
    assert run_controls(clean_txn(), V25) == []


def test_every_flag_is_a_control_flag_with_confidence_1_a_known_clause_and_evidence():
    t = with_amounts(120000.37, 100000.37)
    t["invoice"]["gstin"] = "99ABCDE1234F1Z5"
    flags = run_controls(t, V25)
    assert len(flags) >= 2
    for f in flags:
        assert f["source"] == "D" and f["confidence"] == 1.0
        assert f["severity"] == V25[f["clause"]]["severity"]
        assert f["evidence"] and f["message"]


@pytest.mark.parametrize("invoice, po, expected", [
    (61105.0, 60500.0, []),            # exactly 1%
    (61105.01, 60500.0, ["2.1.1"]),    # one paisa more
    (59894.99, 60500.0, ["2.1.1"]),    # below the PO amount
    (59895.0, 60500.0, []),
])
def test_amount_match_tolerance_is_inclusive_and_two_sided(invoice, po, expected):
    assert clauses(with_amounts(invoice, po)) == expected


def test_amount_match_reads_the_tolerance_from_the_policy():
    t = with_amounts(62436.31, 60500.3)      # 3.2% above the PO
    assert clauses(t, V25) == ["2.1.1"]
    assert clauses(t, V26) == []


def test_quantity_match_only_billing_above_received_is_an_exception():
    t = clean_txn()
    t["grn"]["received_quantity"] = 49
    assert clauses(t) == ["2.1.2"]
    t["grn"]["received_quantity"] = 51
    assert clauses(t) == []


def test_missing_reference_absent_or_dangling_without_other_flags():
    none = clean_txn()
    none["invoice"].update(po_id=None, grn_id=None)
    none["po"] = none["grn"] = None
    assert clauses(none) == ["2.1.3"]

    no_grn = clean_txn()
    no_grn["invoice"]["grn_id"] = ""
    no_grn["grn"] = None
    assert clauses(no_grn) == ["2.1.3"]

    dangling = clean_txn()
    dangling["invoice"].update(po_id="PO29999", grn_id=None)
    dangling["po"] = dangling["grn"] = None
    flags = run_controls(dangling, V25)
    assert [f["clause"] for f in flags] == ["2.1.3"]
    assert "PO29999 matches no purchase order" in flags[0]["message"]


def test_exact_duplicate_the_later_invoice_carries_the_flag():
    later = clean_txn()
    later["vendor_history"].append({"invoice_id": "INV40050", "invoice_number": "ABC/25-26/00123",
                                    "date": "2025-05-02", "amount": 84250.5})
    flags = run_controls(later, V25)
    assert [f["clause"] for f in flags] == ["2.2.1"] and "INV40050" in flags[0]["message"]

    original = clean_txn()
    original["vendor_history"].append({"invoice_id": "INV40300", "invoice_number": "ABC/25-26/00123",
                                       "date": "2025-07-01", "amount": 84250.5})
    assert clauses(original) == []


def test_exact_duplicate_same_date_the_higher_invoice_id_is_the_duplicate():
    t = clean_txn()
    t["vendor_history"].append({"invoice_id": "INV40099", "invoice_number": "ABC/25-26/00123",
                                "date": "2025-06-11", "amount": 1})
    assert clauses(t) == ["2.2.1"]
    t["vendor_history"][2]["invoice_id"] = "INV40101"
    assert clauses(t) == []


@pytest.mark.parametrize("number", ["abc/25-26/00123", "ABC25-2600123", "ABC/25-26/123",
                                    "ABC/25-26/00123-A", "ABC/25-26/00132"])
def test_exact_duplicate_does_not_fire_on_a_rekeyed_number(number):
    """A re-keyed number is clause 2.2.2, a judgement."""
    t = clean_txn()
    t["vendor_history"].append({"invoice_id": "INV40050", "invoice_number": number, "date": "2025-05-02", "amount": 84250.5})
    assert clauses(t) == []


@pytest.mark.parametrize("gstin", ["36ABCDE1234F1Z", "36ABCDE1234F1", "36ABCDE1234F1Z55",
                                   "36ABCDE-234F1Z5", "36ABCDE1234F1Z "])
def test_gstin_format_length_and_alphanumeric(gstin):
    t = clean_txn()
    t["invoice"]["gstin"] = gstin
    assert clauses(t) == ["3.1.1"]


def test_missing_gstin_is_a_format_and_a_state_code_exception():
    t = clean_txn()
    t["invoice"]["gstin"] = None
    assert clauses(t) == ["3.1.1", "3.1.2"]


@pytest.mark.parametrize("code, expected", [("00", ["3.1.2"]), ("38", ["3.1.2"]), ("99", ["3.1.2"]),
                                            ("01", ["3.1.3"]), ("37", ["3.1.3"])])
def test_gstin_state_code_01_to_37_only(code, expected):
    t = clean_txn()
    t["invoice"]["gstin"] = code + GSTIN[2:]
    assert clauses(t) == expected


def test_gstin_vendor_match_applies_only_to_a_well_formed_gstin():
    other = clean_txn()
    other["invoice"]["gstin"] = "36ZZZZZ9999Z1Z5"
    assert clauses(other) == ["3.1.3"]
    malformed = clean_txn()
    malformed["invoice"]["gstin"] = "36ZZZZZ9999Z1Z"      # differs from the master, but malformed
    assert clauses(malformed) == ["3.1.1"]


def test_same_day_splitting_counts_the_invoice_itself():
    def same_day(n: int) -> dict:
        t = clean_txn()
        for i in range(n):
            t["vendor_history"].append({"invoice_id": f"INV4020{i}", "invoice_number": f"ABC/25-26/0020{i}",
                                        "date": "2025-06-11", "amount": 5000.5 + i})
        return t
    assert clauses(same_day(2)) == []                 # 3 that day: at the limit
    assert clauses(same_day(3)) == ["4.1.1"]          # 4 that day
    assert clauses(same_day(4), V26) == []            # 5 that day, limit 5 in v2.6
    assert clauses(same_day(5), V26) == ["4.1.1"]


@pytest.mark.parametrize("day, expected", [("2025-06-13", []), ("2025-06-14", ["4.2.1"]),
                                           ("2025-06-15", ["4.2.1"]), ("2025-06-16", [])])
def test_weekend_date(day, expected):
    t = clean_txn()
    t["invoice"]["date"] = day
    assert clauses(t) == expected


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="the time zone cannot be changed on this platform")
def test_weekend_date_does_not_depend_on_the_time_zone():
    previous = os.environ.get("TZ")
    try:
        for tz in ("America/Los_Angeles", "Asia/Kolkata", "Pacific/Kiritimati"):
            os.environ["TZ"] = tz
            time.tzset()
            saturday, friday = clean_txn(), clean_txn()
            saturday["invoice"]["date"], friday["invoice"]["date"] = "2025-06-14", "2025-06-13"
            assert clauses(saturday) == ["4.2.1"] and clauses(friday) == []
    finally:
        os.environ.pop("TZ", None) if previous is None else os.environ.__setitem__("TZ", previous)
        time.tzset()


@pytest.mark.parametrize("amount, expected", [(50000, ["4.3.1"]), (50000.01, []), (45000, []), (10000, ["4.3.1"])])
def test_round_amount_exact_multiples_only(amount, expected):
    assert clauses(with_amounts(amount, amount)) == expected


def test_blocked_vendor_blacklisted_or_suspended():
    for change in ({"blacklisted": True}, {"blacklisted": "True"}, {"gstin_status": "Suspended"}):
        t = clean_txn()
        t["vendor"].update(change)
        assert clauses(t) == ["4.4.1"], change


def test_approval_limit_an_amount_equal_to_the_limit_is_within_authority():
    assert clauses(with_amounts(99999.99, 99999.99)) == []
    assert clauses(with_amounts(100000.01, 100000.01)) == ["5.1.1"]
    # Exactly at the limit: within authority, but a round amount.
    assert clauses(with_amounts(100000, 100000)) == ["4.3.1"]


def test_approval_limit_comes_from_the_policy_not_from_the_log_row():
    t = with_amounts(131250.75, 131250.75)
    t["approvals"][0]["amount_limit"] = 999999999        # the log row is not the authority
    assert clauses(t, V25) == ["5.1.1"]
    assert clauses(t, V26) == []                          # Manager limit is 150,000 in v2.6


def test_approval_limit_uses_the_latest_approved_entry():
    t = with_amounts(240000.5, 240000.5)
    t["approvals"] = [
        {"approver_name": "A Manager", "approver_role": "Manager", "timestamp": "2025-06-12 10:00:00",
         "action_taken": "Escalated", "amount_limit": 100000},
        {"approver_name": "S Manager", "approver_role": "Senior Manager", "timestamp": "2025-06-12 15:00:00",
         "action_taken": "Approved", "amount_limit": 500000},
    ]
    assert clauses(t) == []
    t["approvals"].reverse()                              # order in the list does not matter
    assert clauses(t) == []
    next(a for a in t["approvals"] if a["action_taken"] == "Approved")["approver_role"] = "Manager"
    assert clauses(t) == ["5.1.1"]


def test_a_control_whose_clause_is_absent_from_the_policy_does_not_run():
    policy = copy.deepcopy(V25)
    del policy["4.3.1"]
    assert clauses(with_amounts(50000, 50000), policy) == []


def test_controls_do_not_change_the_transaction():
    t = with_amounts(120000.37, 100000.37)
    before = json.dumps(t, sort_keys=True)
    run_controls(t, V25)
    assert json.dumps(t, sort_keys=True) == before


@pytest.mark.parametrize("daily_limit", [None, 1])
def test_the_vendor_index_gives_the_findings_of_reading_the_whole_history(small_dataset, daily_limit):
    """Controls 2.2.1 and 4.1.1 look into the vendor's index; on a plain list they read it all. Same findings."""
    from auditiq.extraction import extract
    from auditiq.history import History

    clauses = copy.deepcopy(V25)
    if daily_limit is not None:                 # one invoice a day: control 4.1.1 fires on every shared day
        clauses["4.1.1"]["params"]["max_invoices_per_vendor_per_day"] = daily_limit
    transactions = extract(small_dataset)
    assert all(isinstance(t["vendor_history"], History) for t in transactions)
    indexed = [run_controls(t, clauses) for t in transactions]
    plain = [run_controls({**t, "vendor_history": list(t["vendor_history"])}, clauses) for t in transactions]
    assert indexed == plain
    fired = {f["clause"] for flags in indexed for f in flags}
    assert {"2.2.1", "4.1.1"} <= fired


def test_a_history_is_a_list_to_everything_else(small_dataset):
    import pickle

    from auditiq.extraction import extract

    t = next(t for t in extract(small_dataset) if len(t["vendor_history"]) > 3)
    history = t["vendor_history"]
    assert json.loads(json.dumps(history)) == [dict(h) for h in history] and type(history[1:3]) is list
    again = pickle.loads(pickle.dumps(history))
    assert again == history and again.vendor_index.by_date.keys() == history.vendor_index.by_date.keys()
