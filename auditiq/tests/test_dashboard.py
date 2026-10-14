"""Tests of the dashboard, run headless with Streamlit's test harness, on both backends."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from test_policy_llm import client_for, right_reply

from auditiq import db, policy_llm, service
from auditiq.graph import PRESETS
from auditiq.policy import load_policy
from evaluation import policy_llm_eval as study

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
    assert any("wording only" in c.value and "27 passages" in c.value for c in app.caption)
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


def button(app: AppTest, label: str):
    return next(b for b in app.button if b.label.startswith(label))


def test_policy_page_adopts_a_document_and_applies_it_to_the_ledger(app):
    open_page(app, "Policy")
    assert not app.warning                                                       # every result follows version 2.5
    document = next(o for o in app.selectbox[1].options if o.endswith("Company_Policy_v3.06.pdf"))
    app.selectbox[1].set_value(document).run()
    assert not app.exception, app.exception
    assert any("version 3.06, 3 page(s)" in m.value for m in app.markdown)
    changes = next(d.value for d in app.dataframe if "this document" in d.value.columns)
    assert changes.to_dict("records") == [{"rule": "5.1.1", "parameter": "approval_limits: Manager",
                                           "version 2.5": "100000", "this document": "50000"}]

    button(app, "Adopt version 3.06").click().run()
    assert not app.exception, app.exception
    assert "Policy version 3.06 adopted from Company_Policy_v3.06.pdf and made active." in app.success[0].value
    conn = db.connect(app.db_path)
    assert db.read_policy(conn).version == "3.06"
    assert conn.scalar("SELECT COUNT(*) FROM policy_chunks WHERE version = '3.06' AND verified = 1") == 16
    conn.close()

    # The stored results were produced under version 2.5; the page says so and offers to audit again.
    assert "60 of 60 audited invoices" in app.warning[0].value
    button(app, "Audit the ledger under version 3.06").click().run()
    assert not app.exception, app.exception
    assert "1,200 invoices audited under version 3.06" in app.success[0].value
    conn = db.connect(app.db_path)
    latest = dict(conn.execute("SELECT policy_version, COUNT(*) FROM v_latest_results GROUP BY policy_version").fetchall())
    assert latest == {"3.06": 1200}
    limit_findings = conn.scalar("SELECT COUNT(*) FROM audit_flags f JOIN v_latest_results l ON l.result_id = f.result_id "
                                 "WHERE f.clause = '5.1.1'")
    assert limit_findings > 30                                                   # 30 under version 2.5 in this ledger
    conn.close()
    assert not app.warning                                                       # nothing is stale any more


def test_policy_page_adopts_a_policy_in_its_own_wording_after_confirmation(app, monkeypatch):
    """The model's reading is replaced by a prepared proposal; the page must verify, wait for the person, then store."""
    base = load_policy("2.5").registry
    made = {d["path"].name: d for d in study.documents(ROOT / "policy" / "freeform" / "pdf")}
    doc = made["memo_strict_v5.2.pdf"]
    reply = right_reply(doc["path"], "memo", doc["intended"])
    next(r for r in reply["rules"] if r["clause"] == "2.1.1")["values"]["amount_tolerance_pct"] = 2.0   # not the document's
    prepared = policy_llm.propose(doc["path"], base, client_for(reply))
    monkeypatch.setattr(policy_llm, "propose", lambda path, reference, client: prepared)
    monkeypatch.setenv("AUDITIQ_LLM_BASE_URL", "http://127.0.0.1:1/v1")           # a model is configured; none is called
    monkeypatch.setenv("AUDITIQ_LLM_MODEL", "scripted")

    open_page(app, "Policy")
    app.selectbox[1].set_value(next(o for o in app.selectbox[1].options if o.endswith("memo_strict_v5.2.pdf"))).run()
    assert any("not in the wording the system reads by pattern" in w.value for w in app.warning)
    button(app, "Let the model read this document").click().run()
    assert not app.exception, app.exception
    table = next(d.value for d in app.dataframe if "proposed" in d.value.columns)
    held = table[table["status"] != "verified"]
    assert list(held["parameter"]) == ["amount_tolerance_pct"] and len(table) == 11

    def field(label: str):
        return next(i for i in app.text_input if i.label.startswith(label))

    def accept_box():
        return next(c for c in app.checkbox if c.label.startswith("I have compared"))

    # Accepting the verified values is not enough: one value is held back, and nobody is named.
    accept_box().check()
    button(app, "Adopt the confirmed policy").click().run()
    assert any("supply the value" in e.value for e in app.error)
    field("Rule 2.1.1 amount_tolerance_pct").set_value("0.5")
    accept_box().check()
    button(app, "Adopt the confirmed policy").click().run()
    assert any("name of the person who confirmed" in e.value for e in app.error)
    field("Rule 2.1.1 amount_tolerance_pct").set_value("0.5")
    field("Your name").set_value("A. Auditor")
    accept_box().check()
    button(app, "Adopt the confirmed policy").click().run()
    assert not app.exception, app.exception
    assert "Policy version 5.2 adopted from memo_strict_v5.2.pdf, confirmed by A. Auditor and made active." in app.success[0].value
    conn = db.connect(app.db_path)
    stored = db.read_policy(conn)
    assert stored.version == "5.2" and stored.clauses == doc["intended"]["clauses"]
    assert stored.registry["adoption"]["values_supplied_by_the_person"] == ["2.1.1.amount_tolerance_pct"]
    conn.close()
    assert any("confirmed by A. Auditor" in c.value and "2.1.1.amount_tolerance_pct" in c.value for c in app.caption)


def test_copilot_page_without_a_model_shows_the_passages(app):
    open_page(app, "Copilot")
    assert "No model is configured" in app.warning[0].value
    app.text_input[0].set_value("vendor marked blacklisted").run()
    assert not app.exception, app.exception
    assert any("Rule 4.4.1" in m.value for m in app.markdown)
