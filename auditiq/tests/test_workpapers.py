"""Data reliability (auditiq/reliability.py), the audit program (auditiq/audit_program.py) and the working papers
(auditiq/workpapers.py)."""
from __future__ import annotations

import pytest

from auditiq import audit_program, db, leads, reliability, service, workpapers
from auditiq.cli import main as cli_main
from auditiq.graph import PRESETS


def checks_of(target: str) -> dict:
    conn = db.connect(target)
    try:
        return {c["id"]: c for c in reliability.ledger_reliability(conn)["checks"]}
    finally:
        conn.close()


def run_sql(target: str, *statements: tuple) -> None:
    conn = db.connect(target)
    try:
        for sql, params in statements:
            conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def audited(ledger) -> str:
    conn = db.connect(ledger)
    try:
        service.audit_in_force(conn, PRESETS["C1"], None, db.invoice_ids(conn))
    finally:
        conn.close()
    return ledger


# --------------------------------------------------------------- reliability
def test_a_generated_ledger_is_reliable_and_its_fingerprint_is_stable(audited):
    conn = db.connect(audited)
    try:
        first, again = reliability.ledger_reliability(conn), reliability.ledger_reliability(conn)
    finally:
        conn.close()
    assert first["summary"]["reliable"] and not first["summary"]["open"]
    assert first["fingerprint"] == again["fingerprint"]
    checks = {c["id"]: c for c in first["checks"]}
    assert checks["series-invoices"]["exceptions"] == 0 and checks["audited"]["exceptions"] == 0
    # The invoices naming a missing order or receipt are exceptions the rule 2.1.3 decides, not open ones.
    assert all(checks[k]["decided_by"] == "2.1.3" for k in ("po-on-file", "grn-on-file"))
    assert [t["table"] for t in first["totals"]][:3] == ["invoices", "purchase_orders", "goods_receipts"]


def test_the_checks_find_what_is_wrong_with_a_ledger(ledger):
    conn = db.connect(ledger)
    try:
        invoice_id, log_id = conn.execute(
            "SELECT i.invoice_id, a.log_id FROM invoices i JOIN approval_logs a ON a.transaction_id = i.invoice_id "
            "AND a.action_taken = 'Approved' ORDER BY i.invoice_id LIMIT 1").fetchone()
        last = conn.scalar("SELECT MAX(invoice_id) FROM invoices")
        middle = conn.execute("SELECT invoice_id FROM invoices ORDER BY invoice_id LIMIT 1 OFFSET 10").fetchone()[0]
        fingerprint = reliability.fingerprint(conn)["ledger"]
    finally:
        conn.close()
    run_sql(ledger, ("DELETE FROM approval_logs WHERE log_id = ?", (log_id,)),
            ("UPDATE invoices SET total_amount = total_amount + 5 WHERE invoice_id = ?", (last,)),
            ("DELETE FROM invoices WHERE invoice_id = ?", (middle,)))
    checks = checks_of(ledger)
    assert invoice_id in checks["approved"]["examples"]
    assert checks["total"]["examples"] == [last]
    assert checks["series-invoices"]["exceptions"] == 1 and checks["series-invoices"]["examples"] == [middle]
    assert checks["approval-orphans"]["exceptions"] >= 1               # the deleted invoice's approvals remain
    conn = db.connect(ledger)
    try:
        report = reliability.ledger_reliability(conn)
        assert report["fingerprint"]["ledger"] != fingerprint and not report["summary"]["reliable"]
        assert {"approved", "total", "series-invoices"} <= set(report["summary"]["open"])
    finally:
        conn.close()


def test_a_numbered_series_and_one_that_is_not():
    gaps = reliability.series_gaps(["INV0001", "INV0002", "INV0005", "INV0006"])
    assert gaps["numbered"] and gaps["missing"] == 2 and gaps["first_missing"] == ["INV0003", "INV0004"]
    assert not reliability.series_gaps(["A-17", "invoice seventeen"])["numbered"]


# ------------------------------------------------------------------ program
def test_the_program_maps_every_rule_and_scores_each_scheme_against_the_key(audited):
    conn = db.connect(audited)
    try:
        found = leads.judgement_leads(conn)
        out = audit_program.program(conn, leads=found)
        clauses = {r[0] for r in conn.execute("SELECT clause_id FROM policy_clauses WHERE version = '2.5'")}
    finally:
        conn.close()
    mapped = {t["id"] for t in out["tests"]}
    assert clauses <= mapped                                         # every rule of the policy is in the program
    rows = {t["id"]: t for t in out["tests"]}
    assert rows["2.1.4"]["ran"] is False and rows["2.2.2"]["ran"] is True    # C1 ran no agent; the lead ran
    assert "bid-rigging" in out["untested"]["schemes"]
    schemes = out["answer_key"]["schemes"]
    assert schemes["duplicate-billing"]["missed"] == 0 and schemes["duplicate-billing"]["lead_only"] > 0
    assert schemes["personal-purchases"]["found"] == 0               # the description check needs the agents
    assert schemes["override"]["reached"] == 1.0


# --------------------------------------------------------------- working papers
def test_the_working_papers_reproduce_and_say_when_the_store_changed(audited, tmp_path):
    path = tmp_path / "wp.xlsx"
    conn = db.connect(audited)
    try:
        report = workpapers.write(conn, path)
        assert workpapers.check(conn, path)["matches"]               # written again, the same digest
        assert report["seed"] == workpapers.sample_seed(conn) and report["seed"] > 1
        waiting = int(conn.scalar("SELECT MIN(result_id) FROM v_review_queue"))
        db.record_decision(conn, waiting, "approve", "A. Auditor")
        assert not workpapers.check(conn, path)["matches"]           # a decision changes the store's report
    finally:
        conn.close()
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True)
    assert wb.sheetnames == list(workpapers.SHEETS)
    summary = {r[0]: r[1] for r in wb["Summary"].iter_rows(min_row=2, values_only=True)}
    assert summary["Report digest"] == report["digest"] and summary["Audit record"] == "intact"
    assert wb["Findings"].max_row == len(report["data"]["findings"]) + 1


def test_the_command_line_writes_and_checks_the_working_papers(audited, tmp_path, capsys):
    path = tmp_path / "engagement.xlsx"
    assert cli_main(["--db", audited, "workpapers", "--out", str(path)]) == 0
    assert "report digest" in capsys.readouterr().out
    assert cli_main(["--db", audited, "workpapers", "--check", str(path)]) == 0
    assert "MATCHES" in capsys.readouterr().out
    run_sql(audited, ("UPDATE invoices SET amount = amount + 1 WHERE invoice_id = (SELECT MIN(invoice_id) FROM invoices)", ()))
    assert cli_main(["--db", audited, "workpapers", "--check", str(path)]) == 1   # the ledger moved
    assert "DIFFERS" in capsys.readouterr().out
