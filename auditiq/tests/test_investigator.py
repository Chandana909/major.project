"""The trail investigator (auditiq/investigator.py): the audit of the audit record, on both backends."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from auditiq import db, investigator, service
from auditiq.graph import PRESETS, audit

REASON = "Checked the PO, the goods receipt and the approval log against the finding; noted in the file."


@pytest.fixture()
def audited(ledger):
    conn = db.connect(ledger)
    service.audit_in_force(conn, PRESETS["C1"], None, db.invoice_ids(conn))
    yield conn
    conn.close()


class Clock:
    def __init__(self, monkeypatch, start: datetime):
        self.at = start
        monkeypatch.setattr(db, "now", lambda: self.at.strftime("%Y-%m-%d %H:%M:%S"))

    def tick(self, seconds: float) -> None:
        self.at += timedelta(seconds=seconds)


def pending(conn, level: str | None = None) -> list[dict]:
    where, params = ("WHERE risk_level = ?", [level]) if level else ("", [])
    return [dict(zip(r.keys(), tuple(r))) for r in conn.execute(
        f"SELECT result_id, invoice_id, vendor_id, risk_level FROM v_review_queue {where} ORDER BY invoice_id",
        params).fetchall()]


def checks(report: dict) -> dict[str, dict]:
    return {c["key"]: c for c in report["checks"]}


def test_a_store_audited_and_reviewed_properly_passes_every_check(audited, monkeypatch):
    clock = Clock(monkeypatch, datetime.now().replace(microsecond=0) + timedelta(minutes=1))
    for item in pending(audited)[:6]:
        clock.tick(240)
        db.record_decision(audited, int(item["result_id"]), "reject", "Asha Verma (audit)", REASON)
    report = investigator.investigate(audited, now=clock.at + timedelta(hours=1))
    assert report["status"] == {"pass": 12}, [(c["key"], c["summary"]) for c in report["checks"] if c["status"] != "pass"]
    assert report["verdict"].startswith("The audit record holds")
    assert report["scope"]["invoices"] == report["scope"]["audited"] == 1200 and report["scope"]["decisions"] == 6
    assert report["reviewers"][0] == {"reviewer": "Asha Verma (audit)", "decisions": 6, "approve": 0, "reject": 6,
                                      "override": 0, "critical_cleared": 0, "without_reason": 0}
    assert "# Investigation of the audit record" in report["markdown"] and report["timeline"]["by_kind"]["run"] == 1


def test_each_fault_is_found_where_it_was_made(audited, monkeypatch):
    clock = Clock(monkeypatch, datetime.now().replace(microsecond=0) + timedelta(minutes=1))
    critical = pending(audited, "CRITICAL")
    other = [p for p in pending(audited) if p["risk_level"] != "CRITICAL"]
    # a critical invoice cleared with the reason "ok"
    clock.tick(300)
    db.record_decision(audited, int(critical[0]["result_id"]), "approve", "Dev Malhotra (audit)", "ok")
    # six decisions two seconds apart
    for item in other[:6]:
        clock.tick(2)
        db.record_decision(audited, int(item["result_id"]), "reject", "Esha Pillai (audit)", REASON)
    # the invoice's own approver decides
    own = other[6]
    approver = audited.scalar("SELECT approver_name FROM approval_logs WHERE transaction_id = ? AND action_taken = "
                              "'Approved' ORDER BY timestamp DESC LIMIT 1", (own["invoice_id"],))
    clock.tick(300)
    db.record_decision(audited, int(own["result_id"]), "reject", approver, REASON)
    # a result edited, a trail stage deleted, an invoice's record changed after its audit
    edited, gutted, moved = other[7], other[8], other[9]
    audited.execute("UPDATE audit_results SET route = 'approve' WHERE result_id = ?", (int(edited["result_id"]),))
    audited.execute("DELETE FROM audit_trail WHERE result_id = ? AND stage = 'controls'", (int(gutted["result_id"]),))
    audited.execute("UPDATE invoices SET description = description || ' (amended)' WHERE invoice_id = ?",
                    (moved["invoice_id"],))
    audited.commit()

    found = checks(investigator.investigate(audited, now=clock.at + timedelta(hours=1)))
    assert found["documentation"]["status"] == "fail"
    assert [i["invoice_id"] for i in found["documentation"]["items"]] == [critical[0]["invoice_id"]]
    assert found["overrides"]["status"] == "attention" and found["overrides"]["count"] == 1
    assert found["pace"]["status"] == "attention"
    assert [(i["reviewer"], i["decisions"]) for i in found["pace"]["items"]] == [("Esha Pillai (audit)", 6)]
    assert [i["invoice_id"] for i in found["segregation"]["items"]] == [own["invoice_id"]]
    integrity = {i.get("result_id") for i in found["integrity"]["items"]}
    entries = {i["entry_id"] for i in found["integrity"]["items"] if "entry_id" in i}
    assert int(edited["result_id"]) in integrity and found["integrity"]["status"] == "fail"
    owners = {int(r[0]) for r in audited.execute(
        f"SELECT result_id FROM audit_trail WHERE entry_id IN ({', '.join('?' for _ in entries)})", sorted(entries))}
    assert owners == {int(gutted["result_id"])}
    assert [i["result_id"] for i in found["completeness"]["items"]] == [gutted["result_id"]]
    assert [i["invoice_id"] for i in found["evidence"]["items"]] == [moved["invoice_id"]]
    report = investigator.investigate(audited, now=clock.at + timedelta(hours=1))
    assert report["verdict"].startswith("The audit record needs action")


def test_a_rejection_undone_by_an_audit_under_another_version_is_reported_with_its_cause(audited, monkeypatch):
    clock = Clock(monkeypatch, datetime.now().replace(microsecond=0) + timedelta(minutes=1))
    v26 = db.read_policy(audited, "2.6")
    queue = pending(audited)
    relaxed = next(t["invoice"]["invoice_id"] for t in db.extract_many(audited, [p["invoice_id"] for p in queue])
                   if audit(t, PRESETS["C1"], v26)["score"]["route"] == "approve")
    result_id = next(int(p["result_id"]) for p in queue if p["invoice_id"] == relaxed)
    clock.tick(60)
    db.record_decision(audited, result_id, "reject", "Gopal Iyer (audit)", REASON)
    clock.tick(60)
    service.audit_invoices(audited, PRESETS["C1"], v26, None, [relaxed])
    found = checks(investigator.investigate(audited, now=clock.at + timedelta(hours=1)))
    superseded = found["superseded"]["items"]
    assert [i["invoice_id"] for i in superseded] == [relaxed] and "policy v2.5 to v2.6" in superseded[0]["cause"]
    assert found["superseded"]["status"] == "attention"             # a cause: not a failure
    flip = found["flips"]["items"][0]
    assert (flip["invoice_id"], flip["unexplained"]) == (relaxed, False) and flip["to"] == "approve"
    assert found["coverage"]["status"] == "fail"
    assert [i["invoice_id"] for i in found["coverage"]["items"]] == [relaxed]


def test_the_story_of_an_invoice_is_told_in_order(audited, monkeypatch):
    clock = Clock(monkeypatch, datetime.now().replace(microsecond=0) + timedelta(minutes=1))
    item = pending(audited)[0]
    db.record_decision(audited, int(item["result_id"]), "approve", "Asha Verma (audit)", REASON)
    told = investigator.story(audited, item["invoice_id"])
    kinds = [s["kind"] for s in told["steps"]]
    assert kinds[0] == "ledger" and "approval" in kinds and kinds[-2:] == ["audit", "review"]
    assert [s["at"] for s in told["steps"]] == sorted(s["at"] for s in told["steps"])
    assert told["audits"] == 1 and told["state"].startswith("REVIEW_APPROVED") and "intact" in told["state"]
    assert investigator.story(audited, "INV00000") is None
    assert clock.at > datetime(2025, 1, 1)


def test_a_store_without_results_is_reported_as_not_covered(ledger):
    conn = db.connect(ledger)
    try:
        found = checks(investigator.investigate(conn))
    finally:
        conn.close()
    assert found["coverage"]["status"] == "attention" and found["coverage"]["count"] == 1200
    assert found["integrity"]["status"] == "pass" and found["segregation"]["summary"] == "no decisions yet"
