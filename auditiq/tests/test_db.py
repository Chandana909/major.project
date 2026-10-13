"""Tests of the database: loading, extraction, policy store, results, review queue.

Every test here runs on SQLite and on PostgreSQL (see conftest.py).
"""
from __future__ import annotations

import json

import pytest
from test_pipeline import scripted

from auditiq import db, service
from auditiq.extraction import extract
from auditiq.graph import PRESETS
from auditiq.policy import load_policy


def test_loading_a_dataset_fills_the_ledger_and_keeps_the_labels_apart(conn):
    count = lambda table: conn.scalar(f"SELECT COUNT(*) FROM {table}")  # noqa: E731
    assert (count("invoices"), count("vendor_master"), count("benchmark_labels")) == (1200, 60, 1200)
    assert count("purchase_orders") == 1120 and count("goods_receipts") == 1110
    assert conn.scalar("SELECT value FROM meta WHERE key = 'dataset'") == "small_seed_7"
    # A missing reference is NULL; a reference to a document that does not exist is kept.
    no_po = conn.scalar("SELECT COUNT(*) FROM invoices WHERE po_id IS NULL")
    dangling = conn.scalar("SELECT COUNT(*) FROM invoices i WHERE po_id IS NOT NULL AND NOT EXISTS "
                           "(SELECT 1 FROM purchase_orders p WHERE p.po_id = i.po_id)")
    assert (no_po, dangling) == (10, 10)


def test_extraction_from_the_database_equals_extraction_from_the_files(conn, small_dataset):
    """Same values and same types on both backends: floats for money, ISO text for dates."""
    from_files = {t["invoice"]["invoice_id"]: t for t in extract(small_dataset)}
    assert db.invoice_ids(conn) == sorted(from_files)
    for invoice_id, expected in from_files.items():
        assert db.extract_one(conn, invoice_id) == expected, invoice_id
    sample = db.extract_one(conn, next(iter(from_files)))
    assert isinstance(sample["invoice"]["amount"], float) and isinstance(sample["invoice"]["date"], str)
    assert isinstance(sample["approvals"][0]["timestamp"], str) and isinstance(sample["vendor"]["blacklisted"], bool)
    assert db.extract_one(conn, "INV00000") is None


def test_extraction_never_reads_the_labels(conn):
    if conn.backend != "sqlite":
        pytest.skip("statement tracing is a SQLite facility; the queries are the same on both backends")
    statements = []
    conn.raw.set_trace_callback(statements.append)
    db.extract_one(conn, "INV40001")
    conn.raw.set_trace_callback(None)
    assert statements and not any("benchmark_labels" in s for s in statements)


def test_policy_store_round_trip_and_active_version(conn):
    assert db.read_policy(conn).version == "2.5"
    stored = db.read_policy(conn, "2.6")
    assert stored.registry == load_policy("2.6").registry and stored.text == load_policy("2.6").text
    limit = conn.scalar("SELECT param_value FROM policy_parameters WHERE version = '2.6' AND clause_id = '5.1.1'")
    assert json.loads(limit)["Manager"] == 150000
    db.set_active_policy(conn, "2.6")
    assert db.read_policy(conn).version == "2.6"
    assert conn.scalar("SELECT COUNT(*) FROM company_policies WHERE is_active = 1") == 1
    with pytest.raises(KeyError):
        db.set_active_policy(conn, "9.9")
    with pytest.raises(KeyError):
        db.read_policy(conn, "9.9")


def test_a_read_only_connection_cannot_write(ledger):
    read_only = db.connect(ledger, read_only=True)
    assert read_only.scalar("SELECT COUNT(*) FROM invoices") == 1200
    with pytest.raises(Exception, match="(?i)read.?only"):
        read_only.execute("DELETE FROM invoices")
    read_only.close()


def test_columns_and_relations_are_reported_the_same_way_on_both_backends(conn):
    kinds = conn.columns("invoices")
    assert (kinds["amount"], kinds["quantity"], kinds["date"], kinds["invoice_id"]) == \
        ("number", "integer", "date" if conn.backend == "postgres" else "text", "text")
    assert conn.columns("policy_chunks")["embedding"] == "blob"
    assert set(db.ALL_TABLES + db.VIEWS) <= conn.relations()


def labelled(conn, class_id: str, n: int = 1) -> list[str]:
    rows = conn.execute("SELECT invoice_id FROM benchmark_labels WHERE class_id = ? ORDER BY invoice_id LIMIT ?",
                        (class_id, n)).fetchall()
    return [r[0] for r in rows]


def test_a_controls_only_run_stores_results_flags_and_trail(conn):
    ids = labelled(conn, "R7") + labelled(conn, "R10") + labelled(conn, "", 2)
    run_id = service.audit_invoices(conn, PRESETS["C1"], db.read_policy(conn), None, ids)
    summary = service.run_summary(conn, run_id)
    assert summary["invoices"] == len(ids) and summary["llm_calls"] == 0
    limit = db.latest_result(conn, ids[0])
    assert (limit["route"], limit["workflow_status"], limit["configuration"]) == ("escalate", db.PENDING_REVIEW, "C1")
    flag = conn.execute("SELECT * FROM audit_flags WHERE result_id = ?", (limit["result_id"],)).fetchone()
    assert (flag["clause"], flag["source"], flag["status"], flag["confidence"]) == ("5.1.1", "D", "kept", 1.0)
    assert json.loads(flag["evidence"])[0]["field"] == "invoice.amount"
    stages = [r["stage"] for r in conn.execute("SELECT stage FROM audit_trail WHERE result_id = ? ORDER BY seq",
                                               (limit["result_id"],))]
    assert stages == ["extraction", "controls", "scoring"]
    assert json.loads(limit["audit_pack"])["flags"][0]["clause"] == "5.1.1"
    run = conn.execute("SELECT * FROM audit_runs WHERE run_id = ?", (run_id,)).fetchone()
    assert run["finished_at"] and run["policy_version"] == "2.5" and run["model"] is None


def test_an_llm_run_stores_agent_flags_removed_flags_and_every_call(conn):
    target = labelled(conn, "J4")[0]
    remark = conn.scalar("SELECT g.notes FROM invoices i JOIN goods_receipts g ON g.grn_id = i.grn_id "
                         "WHERE i.invoice_id = ?", (target,))
    real = {"clause": "2.1.4", "explanation": "Remark reduces the accepted quantity.",
            "evidence": [{"field": "grn.notes", "value": remark}]}
    wrong = {"clause": "4.1.2", "explanation": "Looks like structuring.", "evidence": []}
    client = scripted({"math_approvals": {"flags": [real]}, "vendor_intelligence": {"flags": [wrong]},
                       "challenger": {"verdicts": [{"id": 2, "verdict": "remove", "reason": "A single invoice."}]}})
    run_id = service.audit_invoices(conn, PRESETS["C5"], db.read_policy(conn), client, [target], workers=2)
    result = db.latest_result(conn, target)
    flags = conn.execute("SELECT clause, status, source, agent, g, p, a, removal_reason FROM audit_flags "
                         "WHERE result_id = ? ORDER BY clause", (result["result_id"],)).fetchall()
    assert [tuple(f) for f in flags] == [
        ("2.1.4", "kept", "L", "math_approvals", 1, 1, 1.0, None),
        ("4.1.2", "removed", "L", "vendor_intelligence", None, None, None, "A single invoice."),
    ]
    trail = conn.execute("SELECT stage, actor, prompt_tokens FROM audit_trail WHERE result_id = ? ORDER BY seq",
                         (result["result_id"],)).fetchall()
    assert [t["stage"] for t in trail] == ["extraction", "controls", "agent", "agent", "agent", "challenger",
                                           "rerun", "rerun", "rerun", "scoring"]
    assert all(t["prompt_tokens"] > 0 for t in trail if t["stage"] in ("agent", "challenger", "rerun"))
    assert result["llm_calls"] == 7 and service.run_summary(conn, run_id)["llm_calls"] == 7
    assert conn.scalar("SELECT prompt_hash FROM audit_runs WHERE run_id = ?", (run_id,))


def test_the_review_queue_holds_escalated_results_until_a_decision_is_recorded(conn):
    escalated, approved = labelled(conn, "R7")[0], labelled(conn, "R10")[0]
    service.audit_invoices(conn, PRESETS["C1"], db.read_policy(conn), None, [escalated, approved])
    queue = db.review_queue(conn)
    assert [q["invoice_id"] for q in queue] == [escalated] and queue[0]["vendor_name"]
    result_id = queue[0]["result_id"]

    with pytest.raises(ValueError, match="justification"):
        db.record_decision(conn, result_id, "override", "A. Auditor")
    with pytest.raises(ValueError, match="reviewer"):
        db.record_decision(conn, result_id, "approve", "  ")
    with pytest.raises(ValueError, match="one of"):
        db.record_decision(conn, result_id, "maybe", "A. Auditor")

    db.record_decision(conn, result_id, "override", "A. Auditor", "CFO counter-signed on paper.")
    assert db.review_queue(conn) == []
    stored = db.latest_result(conn, escalated)
    assert stored["workflow_status"] == "REVIEW_OVERRIDDEN"
    review = json.loads(stored["audit_pack"])["review"]
    assert (review["decision"], review["reviewer"], review["queue"]) == ("override", "A. Auditor", "escalate")
    assert conn.scalar("SELECT COUNT(*) FROM review_decisions WHERE result_id = ?", (result_id,)) == 1
    # The decision is the last entry of the result's audit trail.
    last = conn.execute("SELECT seq, stage, actor, detail FROM audit_trail WHERE result_id = ? ORDER BY seq DESC",
                        (result_id,)).fetchone()
    assert tuple(last) == (4, "review", "A. Auditor", "override: CFO counter-signed on paper.")
    with pytest.raises(ValueError, match="not waiting for review"):
        db.record_decision(conn, result_id, "approve", "A. Auditor")
    with pytest.raises(ValueError, match="not waiting for review"):
        db.record_decision(conn, db.latest_result(conn, approved)["result_id"], "approve", "A. Auditor")


def test_the_queue_survives_a_restart(ledger):
    first = db.connect(ledger)
    target = labelled(first, "R7")[0]
    service.audit_invoices(first, PRESETS["C1"], db.read_policy(first), None, [target])
    first.close()
    second = db.connect(ledger)
    assert [q["invoice_id"] for q in db.review_queue(second)] == [target]
    second.close()


def test_a_newer_audit_of_an_invoice_replaces_its_place_in_the_queue(conn):
    target = labelled(conn, "R7")[0]
    policy = db.read_policy(conn)
    service.audit_invoices(conn, PRESETS["C1"], policy, None, [target])
    service.audit_invoices(conn, PRESETS["C1"], policy, None, [target])
    assert len(db.review_queue(conn)) == 1
    assert conn.scalar("SELECT COUNT(*) FROM audit_results WHERE invoice_id = ?", (target,)) == 2
    unaudited = db.invoice_ids(conn, only_unaudited=True)
    assert len(unaudited) == 1199 and target not in unaudited


def test_sampled_results_are_queued_at_the_configured_rate():
    assert service.workflow_status("approve", "INV1", 1.0) == db.AUTO_APPROVED
    assert service.workflow_status("escalate", "INV1", 0.0) == db.PENDING_REVIEW
    assert service.workflow_status("sample", "INV1", 1.0) == db.PENDING_REVIEW
    assert service.workflow_status("sample", "INV1", 0.0) == db.NOT_SAMPLED


def test_loading_another_dataset_replaces_the_ledger_and_its_results(conn, boundary_dataset):
    service.audit_invoices(conn, PRESETS["C1"], db.read_policy(conn), None, labelled(conn, "R7"))
    counts = db.load_dataset(conn, boundary_dataset)
    assert counts["invoices"] == 150 and counts["benchmark_labels"] == 150
    assert conn.scalar("SELECT COUNT(*) FROM audit_results") == 0
    assert db.read_policy(conn).version == "2.5"                # the policy store is kept


def test_every_table_exports_to_csv(conn, tmp_path):
    service.audit_invoices(conn, PRESETS["C1"], db.read_policy(conn), None, labelled(conn, "R7", 3))
    counts = db.export_tables(conn, tmp_path / "export")
    assert counts["invoices"] == 1200 and counts["audit_results"] == 3 and counts["audit_trail"] == 9
    assert {p.stem for p in (tmp_path / "export").glob("*.csv")} == set(db.ALL_TABLES)
    header = (tmp_path / "export" / "policy_chunks.csv").read_text(encoding="utf-8").splitlines()[0]
    assert "embedding" not in header.split(",") and "embed_model" in header.split(",")
