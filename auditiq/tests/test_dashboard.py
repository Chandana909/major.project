"""Tests of the dashboard, run headless with Streamlit's test harness, on both backends."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from auditiq import db, service
from auditiq.graph import PRESETS

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def app(library, monkeypatch) -> AppTest:
    """The dashboard on a small store: one ledger, both policies, PDFs, a few audited invoices."""
    conn = db.connect(library)
    # Twenty invoices each of R7 (critical), R1 (high) and R10 (low or medium): 40 escalated, 20 approved.
    ids = [r[0] for class_id in ("R7", "R1", "R10") for r in conn.execute(
        "SELECT invoice_id FROM benchmark_labels WHERE class_id = ? ORDER BY invoice_id LIMIT 20", (class_id,))]
    service.audit_invoices(conn, PRESETS["C1"], db.read_policy(conn), None, ids)
    conn.close()
    # No model is configured (conftest removes the settings): the pages must work without one.
    monkeypatch.setenv("AUDITIQ_DATABASE_URL" if db.is_postgres(library) else "AUDITIQ_DB", library)
    test = AppTest.from_file(str(ROOT / "app" / "dashboard.py"), default_timeout=120)
    test.db_path = library
    return test


def open_page(app: AppTest, page: str) -> AppTest:
    app.run()
    app.sidebar.radio[0].set_value(page).run()
    assert not app.exception, app.exception
    return app


def test_overview_shows_the_counts_of_the_database(app):
    app.run()
    assert not app.exception, app.exception
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["Invoices in the ledger"] == "1,200" and metrics["Audited"] == "60"
    assert metrics["Waiting for review"] == "40" and metrics["Auto-approved"] == "20"
    assert metrics["Findings"] == "60" and metrics["Reviewed"] == "0"
    assert "small_seed_7" in app.caption[0].value and "version 2.5" in app.caption[0].value
    findings = next(d.value for d in app.dataframe if "findings" in d.value.columns)
    by_rule = dict(zip(findings["rule"], findings["findings"]))
    assert by_rule["5.1.1"] == 20 and by_rule["2.1.1"] == 20 and by_rule["4.2.1"] + by_rule["4.3.1"] == 20
    assert set(findings["source"]) == {"control"}


def test_review_queue_records_a_decision_and_the_invoice_leaves_the_queue(app):
    open_page(app, "Review queue")
    assert "40 invoices are waiting" in app.caption[0].value
    target = app.selectbox[0].value
    assert any(f"### Audit pack: {target}" in m.value for m in app.markdown)

    # An override without a justification is refused.
    app.radio[0].set_value("override")
    app.text_input[0].set_value("A. Auditor")
    app.button[0].click().run()
    assert "justification" in app.error[0].value

    app.radio[0].set_value("reject")
    app.text_input[0].set_value("A. Auditor")
    app.text_area[0].set_value("Approver had no authority for this amount.")
    app.button[0].click().run()
    assert not app.exception, app.exception
    assert f"Recorded: reject on {target} by A. Auditor." in app.success[0].value
    assert "39 invoices are waiting" in app.caption[0].value

    conn = db.connect(app.db_path)
    stored = db.latest_result(conn, target)
    assert stored["workflow_status"] == "REVIEW_REJECTED"
    assert json.loads(stored["audit_pack"])["review"]["justification"] == "Approver had no authority for this amount."
    conn.close()


def test_invoice_page_shows_records_and_audits_on_request(app):
    open_page(app, "Invoice")
    conn = db.connect(app.db_path)
    unaudited = db.invoice_ids(conn, only_unaudited=True, limit=1)[0]
    conn.close()
    app.text_input[0].set_value(unaudited).run()
    assert "has not been audited" in app.info[0].value
    assert [o for o in app.selectbox[0].options] == ["C1"]            # no model configured
    app.button[0].click().run()
    assert not app.exception, app.exception
    assert any(f"### Audit pack: {unaudited}" in m.value for m in app.markdown)
    app.text_input[0].set_value("INV00000").run()
    assert "not in the ledger" in app.error[0].value


def test_policy_page_searches_and_switches_the_active_version(app):
    open_page(app, "Policy")
    assert "wording only" in app.caption[0].value and "27 passages" in app.caption[0].value
    app.text_input[0].set_value("invoice dated on a Saturday or Sunday").run()
    assert any("[1] Rule 4.2.1 (Procurement_Audit_SOP_v2.5.pdf, page 2)" in m.value for m in app.markdown)
    documents = next(d.value for d in app.dataframe if "document" in d.value.columns)
    assert list(documents["rules_matching_the_registry"]) == [0, 16, 16]

    app.selectbox[0].set_value("2.6").run()
    app.button[0].click().run()
    assert not app.exception, app.exception
    conn = db.connect(app.db_path)
    assert db.read_policy(conn).version == "2.6"
    conn.close()
    rules = next(d.value for d in app.dataframe if "decided_by" in d.value.columns)
    assert "amount_tolerance_pct = 5.0" in rules.set_index("rule").at["2.1.1", "parameters"]


def test_copilot_page_without_a_model_shows_the_passages(app):
    open_page(app, "Copilot")
    assert "No model is configured" in app.warning[0].value
    app.text_input[0].set_value("vendor marked blacklisted").run()
    assert not app.exception, app.exception
    assert any("Rule 4.4.1" in m.value for m in app.markdown)
