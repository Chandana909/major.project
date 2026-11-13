"""Tests of the database: loading, extraction, policy store, results, review queue.

Every test here runs on SQLite and on PostgreSQL (see conftest.py).
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_pipeline import scripted

from auditiq import db, service
from auditiq.extraction import extract
from auditiq.graph import PRESETS
from auditiq.policy import Policy, derive_policy, load_policy


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


def test_the_schema_is_created_once_per_version(backend, make_store, monkeypatch):
    target = make_store(backend)
    db.connect(target).close()                                   # creates the schema and records its stamp
    made = []
    create = db.create_schema
    monkeypatch.setattr(db, "create_schema", lambda conn: (made.append(conn.backend), create(conn)))
    for _ in range(3):
        db.connect(target).close()
    assert made == []                    # up to date: no DDL, so no exclusive lock for others to wait on
    monkeypatch.setattr(db, "SCHEMA_ID", "0123456789abcdef")    # as after a change to the schema
    conn = db.connect(target)
    assert made == [backend] and db.recorded_stamp(conn) == db.schema_stamp(conn)
    conn.close()


def test_connections_opened_at_the_same_time_do_not_deadlock(ledger):
    # The web application opens a connection per request, several at once. When each connection re-created
    # the schema, two of them could deadlock on PostgreSQL (CREATE OR REPLACE VIEW against a SELECT on it).
    def request(_):
        conn = db.connect(ledger)
        try:
            return conn.scalar("SELECT COUNT(*) FROM v_review_queue"), conn.scalar("SELECT COUNT(*) FROM invoices")
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        answers = list(pool.map(request, range(32)))
    assert set(answers) == {(0, 1200)}


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
    # The bulk extraction of a batch run returns the same transactions, in the order asked for.
    ids = sorted(from_files, reverse=True)
    assert db.extract_many(conn, ids) == [from_files[i] for i in ids]
    with pytest.raises(KeyError, match="INV00000"):
        db.extract_many(conn, ["INV00000"])


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


def test_each_invoice_is_governed_by_the_policy_in_force_on_its_date(conn):
    # 2.5 (from 1 April 2025) is active; 2.6 (from 1 April 2026) is stored and governs nothing until it is active.
    assert db.policy_timeline(conn) == [("2025-04-01", "2.5")]
    later = [r[0] for r in conn.execute("SELECT invoice_id FROM invoices ORDER BY invoice_id LIMIT 7")]
    conn.executemany("UPDATE invoices SET date = ? WHERE invoice_id = ?", [("2026-04-15", i) for i in later])
    conn.commit()
    assert set(db.versions_in_force(conn).values()) == {"2.5"}
    db.set_active_policy(conn, "2.6")
    timeline = db.policy_timeline(conn)
    assert timeline == [("2025-04-01", "2.5"), ("2026-04-01", "2.6")]
    assert [db.version_in_force(timeline, d) for d in ("2024-12-31", "2025-04-01", "2026-03-31", "2026-04-01", None)] \
        == ["2.5", "2.5", "2.5", "2.6", "2.6"]          # older than every version: the first; no date: the active one
    governing = db.versions_in_force(conn)
    assert sorted(i for i, v in governing.items() if v == "2.6") == sorted(later)
    expr, params = db.in_force_sql(timeline, "date")          # the same answer in SQL
    assert dict(conn.execute(f"SELECT invoice_id, {expr} FROM invoices", params).fetchall()) == governing
    # A version stored with the active one's date, but not active, governs nothing.
    base = load_policy("2.5")
    db.store_policy(conn, Policy(derive_policy(base.registry, "3.12", "2026-04-01", {}), base.text))
    assert db.policy_timeline(conn) == timeline
    db.set_active_policy(conn, "3.12")
    assert db.policy_timeline(conn) == [("2025-04-01", "2.5"), ("2026-04-01", "3.12")]
    summary = [(t["version"], t["from"], t["until"], t["invoices"], t["under_other_version"], t["unaudited"])
               for t in db.timeline_summary(conn)]
    assert summary == [("2.5", "2025-04-01", "2026-04-01", 1193, 0, 1193), ("3.12", "2026-04-01", None, 7, 0, 7)]
    db.set_active_policy(conn, "2.5")                         # back to 2.5: the later versions govern nothing
    assert db.policy_timeline(conn) == [("2025-04-01", "2.5")]


def test_an_adopted_version_does_not_judge_the_invoices_before_its_date(conn):
    """Adopting a stricter policy must not turn the invoices approved under the old one into breaches."""
    ids = db.invoice_ids(conn)
    first = service.audit_in_force(conn, PRESETS["C1"], None, ids)
    db.set_active_policy(conn, "2.6")                         # takes effect on 1 April 2026, after every invoice
    second = service.audit_in_force(conn, PRESETS["C1"], None, ids)
    assert [conn.scalar("SELECT policy_version FROM audit_runs WHERE run_id = ?", (r,)) for r in first + second] \
        == ["2.5", "2.5"]
    summary = service.runs_summary(conn, first + second)
    assert summary["invoices"] == 2 * len(ids) and [r["policy_version"] for r in summary["runs"]] == ["2.5", "2.5"]
    later = ids[:5]
    conn.executemany("UPDATE invoices SET date = ? WHERE invoice_id = ?", [("2026-05-04", i) for i in later])
    conn.commit()
    runs = service.audit_in_force(conn, PRESETS["C1"], None, ids)
    assert [(r["policy_version"], r["invoices"]) for r in service.runs_summary(conn, runs)["runs"]] == \
        [("2.5", len(ids) - 5), ("2.6", 5)]
    with pytest.raises(KeyError, match="NOT-AN-INVOICE"):
        service.audit_in_force(conn, PRESETS["C1"], None, ["NOT-AN-INVOICE"])


def test_a_write_ahead_log_lets_a_reader_and_a_writer_work_together(tmp_path, monkeypatch):
    """A live run reads the store from the web application while the stream workers write to it."""
    monkeypatch.setattr(db, "LOCK_WAIT", 0.3)

    def writer_commits_during_a_read(journal: str | None) -> bool:
        if journal:
            monkeypatch.setenv("AUDITIQ_SQLITE_JOURNAL", journal)
        else:
            monkeypatch.delenv("AUDITIQ_SQLITE_JOURNAL", raising=False)
        target = str(tmp_path / f"{journal}.db")
        writer, reader = db.connect(target), db.connect(target)
        try:
            writer.execute("INSERT INTO meta (key, value) VALUES ('a', '1')")
            writer.commit()
            cursor = reader.execute("SELECT key FROM meta")            # an open read: the reader holds its lock
            cursor.fetchone()
            writer.execute("INSERT INTO meta (key, value) VALUES ('b', '2')")
            try:
                writer.commit()
            except Exception as error:      # noqa: BLE001 - sqlite3.OperationalError: database is locked
                assert "locked" in str(error)
                return False
            return True
        finally:
            reader.close()
            writer.close()

    assert writer_commits_during_a_read("wal") is True
    assert writer_commits_during_a_read(None) is False               # SQLite's rollback journal: they wait
    monkeypatch.setenv("AUDITIQ_SQLITE_JOURNAL", "fast")
    with pytest.raises(ValueError, match="AUDITIQ_SQLITE_JOURNAL"):
        db.connect(str(tmp_path / "other.db"))


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
    newest = conn.scalar("SELECT MAX(result_id) FROM audit_results WHERE invoice_id = ?", (target,))
    assert db.latest_result(conn, target)["result_id"] == newest
    assert conn.scalar("SELECT result_id FROM latest_results WHERE invoice_id = ?", (target,)) == newest


def test_a_store_made_before_the_latest_results_table_is_filled_when_it_is_opened(backend, make_store, small_dataset,
                                                                                  monkeypatch):
    """The view of the latest results joins through latest_results; an older store gets it on upgrade."""
    target = make_store(backend)
    conn = db.connect(target)
    db.load_dataset(conn, small_dataset)
    db.store_policy(conn, load_policy("2.5"), active=True)
    ids = db.invoice_ids(conn)[:30]
    service.audit_invoices(conn, PRESETS["C1"], db.read_policy(conn), None, ids)
    service.audit_invoices(conn, PRESETS["C1"], db.read_policy(conn), None, ids[:10])
    expected = {r[0]: r[1] for r in conn.execute("SELECT invoice_id, MAX(result_id) FROM audit_results GROUP BY invoice_id")}
    conn.execute("DELETE FROM latest_results")                  # as in a store of the previous schema
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "SCHEMA_ID", "0123456789abcdef")    # the stamp no longer matches: the schema is made again
    conn = db.connect(target)
    assert {r[0]: r[1] for r in conn.execute("SELECT invoice_id, result_id FROM latest_results")} == expected
    assert conn.scalar("SELECT COUNT(*) FROM v_latest_results") == 30
    conn.close()


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
