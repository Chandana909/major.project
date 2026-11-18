"""Tamper evidence of the audit record (auditiq/seal.py): what is stored verifies, and any change to it is found."""
from __future__ import annotations

import pytest

from auditiq import db, seal, service
from auditiq.cli import main as cli_main
from auditiq.graph import PRESETS


@pytest.fixture()
def audited(ledger) -> str:
    """The small ledger audited once with the controls, on each backend."""
    conn = db.connect(ledger)
    try:
        service.audit_in_force(conn, PRESETS["C1"], None, db.invoice_ids(conn))
    finally:
        conn.close()
    return ledger


def report(target: str, **options) -> dict:
    conn = db.connect(target)
    try:
        return seal.verify(conn, **options)
    finally:
        conn.close()


def change(target: str, sql: str, params: tuple = ()) -> None:
    conn = db.connect(target)
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def flagged_result(target: str) -> int:
    conn = db.connect(target)
    try:
        return int(conn.scalar("SELECT MIN(result_id) FROM audit_results WHERE flag_count > 0"))
    finally:
        conn.close()


def test_a_fresh_audit_is_sealed_and_verifies(audited):
    r = report(audited)
    assert r["intact"]
    assert r["results"]["checked"] == r["results"]["sealed"] == 1200 and r["results"]["unsealed"] == 0
    assert r["entries"]["checked"] == 3 * 1200 and r["entries"]["broken"] == r["entries"]["unsealed"] == 0
    assert r["runs"]["sealed"] >= 1 and r["runs"]["altered"] == r["runs"]["open"] == 0


@pytest.mark.parametrize("what, sql", [
    ("a finding's severity", "UPDATE audit_flags SET severity = 'low' WHERE result_id = ?"),
    ("a finding removed", "DELETE FROM audit_flags WHERE result_id = ?"),
    ("the route", "UPDATE audit_results SET route = 'approve' WHERE result_id = ?"),
    ("the score", "UPDATE audit_results SET rc = 0 WHERE result_id = ?"),
    ("the audit pack", "UPDATE audit_results SET audit_pack = REPLACE(audit_pack, 'weighted_risk', 'weighted_rizk') "
                       "WHERE result_id = ?"),
])
def test_a_changed_result_is_found(audited, what, sql):
    result_id = flagged_result(audited)
    change(audited, sql, (result_id,))
    r = report(audited)
    assert not r["intact"], what
    assert r["results"]["altered_ids"] == [result_id], what
    assert r["runs"]["altered"] == 0, what               # the stored seal is unchanged; the result's own check fails


def test_a_result_sealed_again_after_a_change_is_found_by_its_run(audited):
    """Whoever changes a result and computes its seal afresh still changes the seal its finished run was made over."""
    result_id = flagged_result(audited)
    conn = db.connect(audited)
    try:
        conn.execute("UPDATE audit_results SET route = 'approve', workflow_status = 'AUTO_APPROVED' WHERE result_id = ?",
                     (result_id,))
        row = conn.execute("SELECT * FROM audit_results WHERE result_id = ?", (result_id,)).fetchone()
        flags = [seal.flag_record(f) for f in conn.execute(
            "SELECT * FROM audit_flags WHERE result_id = ? ORDER BY flag_id", (result_id,)).fetchall()]
        import json
        forged = seal.result_seal(seal.result_record(row), json.loads(row["audit_pack"]), flags)
        conn.execute("UPDATE audit_results SET seal = ? WHERE result_id = ?", (forged, result_id))
        conn.commit()
    finally:
        conn.close()
    r = report(audited)
    assert r["results"]["altered"] == 0 and r["entries"]["broken"] == 3       # its trail hangs from the old seal
    assert r["runs"]["altered"] == 1 and not r["intact"]


def test_a_changed_trail_entry_is_found_and_the_rest_still_verify(audited):
    result_id = flagged_result(audited)
    conn = db.connect(audited)
    try:
        changed = int(conn.scalar("SELECT entry_id FROM audit_trail WHERE result_id = ? AND stage = 'controls'",
                                  (result_id,)))
    finally:
        conn.close()
    change(audited, "UPDATE audit_trail SET detail = '0 flags' WHERE entry_id = ?", (changed,))
    r = report(audited)
    # The changed entry and the one chained to it (scoring) no longer verify; nothing else does not.
    assert not r["intact"] and r["entries"]["broken"] == 2 and r["entries"]["broken_ids"][0] == changed
    assert r["results"]["altered"] == 0 and r["runs"]["altered"] == 0     # the run seal covers results, not trails


def test_a_result_taken_out_of_a_finished_run_breaks_the_run_seal(audited):
    result_id = flagged_result(audited)
    for sql in ("DELETE FROM latest_results WHERE result_id = ?", "DELETE FROM audit_results WHERE result_id = ?"):
        change(audited, sql, (result_id,))
    r = report(audited)
    assert not r["intact"] and r["results"]["altered"] == 0 and r["runs"]["altered"] == 1


def test_a_review_extends_the_chain_and_a_forged_state_is_found(audited):
    conn = db.connect(audited)
    try:
        waiting = int(conn.scalar("SELECT MIN(result_id) FROM audit_results WHERE workflow_status = 'PENDING_REVIEW'"))
        db.record_decision(conn, waiting, "reject", "A. Auditor", "the amount was not ordered")
    finally:
        conn.close()
    r = report(audited)
    assert r["intact"] and r["entries"]["checked"] == 3 * 1200 + 1
    change(audited, "UPDATE audit_results SET workflow_status = 'REVIEW_APPROVED' WHERE result_id = ?", (waiting,))
    r = report(audited)
    assert not r["intact"] and r["results"]["review_inconsistent_ids"] == [waiting]
    change(audited, "UPDATE audit_trail SET detail = 'approve' WHERE result_id = ? AND stage = 'review'", (waiting,))
    assert report(audited)["entries"]["broken"] == 1           # rewriting the decision breaks its entry instead


def test_one_result_and_one_run_can_be_checked_alone(audited):
    result_id = flagged_result(audited)
    one = report(audited, result_ids=[result_id])
    assert one["intact"] and one["results"]["checked"] == 1
    conn = db.connect(audited)
    try:
        run_id = int(conn.scalar("SELECT MAX(run_id) FROM audit_runs"))
    finally:
        conn.close()
    assert report(audited, run_id=run_id)["intact"]


def test_results_stored_before_sealing_count_as_unsealed_not_altered(audited):
    change(audited, "UPDATE audit_results SET seal = NULL")
    change(audited, "UPDATE audit_trail SET entry_hash = NULL")
    change(audited, "UPDATE audit_runs SET seal = NULL")
    r = report(audited)
    assert r["intact"] and r["results"]["unsealed"] == 1200 and r["entries"]["unsealed"] == 3 * 1200
    assert r["runs"]["unsealed"] >= 1


def test_an_older_store_gains_the_columns_when_it_is_opened(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    conn = db.connect(path)
    conn.close()
    raw = sqlite3.connect(path)                    # as a store made before sealing: without the three columns
    raw.executescript("DROP VIEW v_review_queue; DROP VIEW v_latest_results; "
                      "ALTER TABLE audit_trail DROP COLUMN entry_hash; ALTER TABLE audit_results DROP COLUMN seal; "
                      "ALTER TABLE audit_runs DROP COLUMN seal; UPDATE meta SET value = 'old' WHERE key = 'schema';")
    raw.close()
    conn = db.connect(path)
    try:
        assert "seal" in conn.columns("audit_results") and "entry_hash" in conn.columns("audit_trail")
        assert "seal" in conn.columns("v_latest_results")
    finally:
        conn.close()


def drift(target: str) -> dict:
    conn = db.connect(target)
    try:
        return seal.evidence_drift(conn)
    finally:
        conn.close()


def test_the_evidence_of_every_result_still_matches_an_unchanged_ledger(audited):
    d = drift(audited)
    assert d["current"] and d["fingerprinted"] == d["unchanged"] == 1200 and d["changed"] == 0


def test_a_ledger_changed_after_the_audit_makes_its_results_stale_though_they_are_intact(audited):
    conn = db.connect(audited)
    try:
        invoice_id, vendor_id = conn.execute("SELECT invoice_id, vendor_id FROM invoices ORDER BY invoice_id LIMIT 1").fetchone()
        others = int(conn.scalar("SELECT COUNT(*) FROM invoices WHERE vendor_id = ?", (vendor_id,)))
    finally:
        conn.close()
    change(audited, "UPDATE invoices SET amount = amount + 1 WHERE invoice_id = ?", (invoice_id,))
    d = drift(audited)
    assert report(audited)["intact"]                         # the results are as stored ...
    assert not d["current"] and d["changed_invoices"] == [{"invoice_id": invoice_id, "changed": ["invoice"]}]
    change(audited, "UPDATE vendor_master SET blacklisted = 1 WHERE vendor_id = ?", (vendor_id,))
    d = drift(audited)                                       # ... but no longer describe their invoices
    assert d["changed_by_record"]["vendor"] == others and d["changed"] == others
    change(audited, "UPDATE audit_results SET evidence = NULL WHERE invoice_id = ?", (invoice_id,))
    assert not report(audited)["intact"]                    # the fingerprint is sealed: removing it is a change too


def test_the_command_line_says_whether_the_record_is_intact(audited, capsys):
    assert cli_main(["--db", audited, "verify"]) == 0
    out = capsys.readouterr().out
    assert "INTACT" in out and "digest" in out
    change(audited, "UPDATE audit_results SET rc = 1 WHERE result_id = ?", (flagged_result(audited),))
    assert cli_main(["--db", audited, "verify"]) == 1
    assert "ALTERED" in capsys.readouterr().out
