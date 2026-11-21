"""Process mining of procure-to-pay (auditiq/process_mining.py)."""
from __future__ import annotations

from datetime import datetime

from auditiq import db, process_mining, service
from auditiq.graph import PRESETS


def at(text: str) -> datetime:
    return datetime.fromisoformat(text)


def test_a_case_that_leaves_the_reference_path_says_how():
    good = [("PO raised", at("2025-04-01")), ("Goods received", at("2025-04-10")), ("Invoice dated", at("2025-04-12")),
            ("Approved", at("2025-04-12 15:00")), ("Due", at("2025-05-12"))]
    assert process_mining.deviations(good) == []                         # an approval on the invoice's day is in order
    early = [("PO raised", at("2025-04-01")), ("Invoice dated", at("2025-04-05")), ("Goods received", at("2025-04-10")),
             ("Approved", at("2025-06-20")), ("Due", at("2025-05-05"))]
    assert process_mining.deviations(early) == ["invoice dated before the goods were received", "approved after the due date"]
    bare = [("Invoice dated", at("2025-04-05")), ("Due", at("2025-05-05"))]
    assert process_mining.deviations(bare) == ["no po raised", "no goods received", "no approved"]


def test_the_ledger_is_mined_and_its_deviations_are_the_ones_the_audit_flags(ledger):
    conn = db.connect(ledger)
    try:
        service.audit_in_force(conn, PRESETS["C1"], None, db.invoice_ids(conn))
        mined = process_mining.mine(conn)
        missing = int(conn.scalar("SELECT COUNT(*) FROM invoices WHERE po_id IS NULL OR grn_id IS NULL OR po_id = '' "
                                  "OR grn_id = ''") or 0)
    finally:
        conn.close()
    assert mined["cases"] == 1200 and mined["conformant"] + (1200 - mined["conformant"]) == 1200
    assert mined["variants"][0]["follows_reference"] and sum(v["cases"] for v in mined["variants"]) <= 1200
    assert sum(a["cases"] for a in mined["activities"]) == mined["events"]
    # the deviations of the generated ledger are its invoices without a PO or a goods receipt, and the audit flags them
    assert {d["kind"] for d in mined["deviations"]} <= {"no po raised", "no goods received"}
    assert 1200 - mined["conformant"] == missing > 0
    assert all(d["flagged_by_audit"] == d["cases"] for d in mined["deviations"])
    stages = {c["stage"]: c for c in mined["cycle_times"]}
    assert stages["Invoice dated -> Approved"]["cases"] == 1200 and stages["Invoice dated -> Approved"]["median"] >= 0
    assert {r["role"] for r in mined["approval_by_role"]} <= {"Manager", "Senior Manager", "Director", "CFO"}
    assert sum(e["cases"] for e in mined["escalations"]) == 1200
