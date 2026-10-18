"""Tests of the REST API, on both database backends.

No model is called: model-backed endpoints are tested for their refusal without
a model, and the model-assisted policy reading with a scripted stand-in.
"""
from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient
from test_policy_llm import client_for, right_reply

from auditiq import api, db, service
from auditiq.graph import PRESETS
from auditiq.policy import POLICY_DIR, load_policy
from evaluation import policy_llm_eval as study


@pytest.fixture()
def client(library, tmp_path, monkeypatch) -> TestClient:
    """The API on a small store with the policy PDFs; 60 invoices audited by the controls (40 escalated)."""
    conn = db.connect(library)
    ids = [r[0] for class_id in ("R7", "R1", "R10") for r in conn.execute(
        "SELECT invoice_id FROM benchmark_labels WHERE class_id = ? ORDER BY invoice_id LIMIT 20", (class_id,))]
    service.audit_invoices(conn, PRESETS["C1"], db.read_policy(conn), None, ids)
    conn.close()
    monkeypatch.setattr(api, "UPLOADS", tmp_path / "uploads")
    monkeypatch.setattr(api, "chat_client", lambda max_tokens=None: None)        # no model is configured
    monkeypatch.setattr(api, "model_name", lambda: None)
    return TestClient(api.create_app(library, token="", frontend=None))


def wait(client: TestClient, job: dict, seconds: float = 120) -> dict:
    deadline = time.time() + seconds
    while time.time() < deadline:
        state = client.get(f"/api/jobs/{job['id']}").json()
        if state["status"] in ("done", "failed"):
            return state
        time.sleep(0.2)
    raise AssertionError(f"job {job['id']} did not finish")


def pdf_bytes(name: str) -> bytes:
    return (POLICY_DIR / "variants" / name).read_bytes()


def test_status_endpoints_describe_the_store(client):
    health = client.get("/api/health").json()
    assert health["status"] == "ok" and health["ledger"] == "small_seed_7" and health["policy_version"] == "2.5"
    overview = client.get("/api/overview").json()
    assert (overview["invoices"], overview["audited"], overview["findings"]) == (1200, 60, 60)
    assert overview["states"] == {"PENDING_REVIEW": 40, "AUTO_APPROVED": 20} and overview["reviewed"] == 0
    assert {f["rule"] for f in overview["findings_by_rule"]} >= {"5.1.1", "2.1.1"}
    assert overview["runs"][0]["invoices"] == 60 and overview["runs"][0]["configuration"] == "C1"
    vendors = client.get("/api/risk-map").json()["vendors"]
    assert len(vendors) == 60 and sum(v["invoices"] for v in vendors) == 1200
    assert sum(v["waiting"] for v in vendors) == 40 and max(v["max_risk"] for v in vendors) == 70
    pipeline = client.get("/api/pipeline").json()
    assert pipeline["configurations"]["C1"] == ["extraction", "controls", "risk_score", "human_review", "audit_pack"]
    assert "single_auditor" in pipeline["configurations"]["C2"] and "controls" not in pipeline["configurations"]["C2"]
    assert client.get("/api/openapi.json").json()["info"]["title"] == "AuditIQ API"


def test_the_review_flow_records_a_decision(client):
    queue = client.get("/api/queue").json()
    assert queue["total"] == 40 and len(queue["items"]) == 40
    first = queue["items"][0]
    assert first["rc"] >= queue["items"][-1]["rc"]                              # highest risk first

    detail = client.get(f"/api/invoices/{first['invoice_id'].lower()}").json()
    assert detail["records"]["invoice"]["invoice_id"] == first["invoice_id"]
    assert detail["result"]["workflow_status"] == "PENDING_REVIEW" and detail["result"]["pack"]["flags"]
    assert [t["stage"] for t in detail["result"]["trail"]] == ["extraction", "controls", "scoring"]
    assert "benchmark_label" not in detail
    assert client.get(f"/api/invoices/{first['invoice_id']}?with_label=true").json()["benchmark_label"]["label"] == "anomalous"

    result_id = detail["result"]["result_id"]
    refused = client.post(f"/api/results/{result_id}/decision", json={"decision": "override", "reviewer": "A. Auditor"})
    assert refused.status_code == 400 and "justification" in refused.json()["detail"]
    assert client.post(f"/api/results/{result_id}/decision", json={"decision": "maybe", "reviewer": "A"}).status_code == 422
    done = client.post(f"/api/results/{result_id}/decision", json={"decision": "reject", "reviewer": "A. Auditor"})
    assert done.status_code == 200 and done.json()["workflow_status"] == "REVIEW_REJECTED"
    assert client.get("/api/queue").json()["total"] == 39
    again = client.post(f"/api/results/{result_id}/decision", json={"decision": "approve", "reviewer": "A. Auditor"})
    assert again.status_code == 400 and "not waiting for review" in again.json()["detail"]
    assert client.post("/api/results/999999/decision", json={"decision": "approve", "reviewer": "A"}).status_code == 404
    trail = client.get(f"/api/invoices/{first['invoice_id']}").json()["result"]["trail"]
    assert trail[-1]["stage"] == "review" and trail[-1]["actor"] == "A. Auditor"


def test_invoices_are_found_and_audited_on_request(client):
    found = client.get("/api/invoices", params={"q": "INV4000"}).json()["items"]
    assert found and all(i["invoice_id"].startswith("INV4000") for i in found)
    unaudited = next(i["invoice_id"] for i in client.get("/api/invoices", params={"limit": 500}).json()["items"]
                     if i["route"] is None)
    job = client.post(f"/api/invoices/{unaudited}/audit", json={"config": "C1"})
    assert job.status_code == 202
    state = wait(client, job.json())
    assert state["status"] == "done" and state["result"]["invoice_id"] == unaudited
    assert client.get(f"/api/invoices/{unaudited}").json()["result"]["configuration"] == "C1"
    needs_model = client.post(f"/api/invoices/{unaudited}/audit", json={"config": "C5"})
    assert needs_model.status_code == 400 and "needs a model" in needs_model.json()["detail"]
    assert client.get("/api/invoices/INV00000").status_code == 404
    assert client.get("/api/invoices/bad id!").status_code == 400
    assert client.get("/api/jobs/nope").status_code == 404


def test_a_policy_document_is_previewed_adopted_and_applied_to_the_ledger(client):
    refused = client.post("/api/policy/preview", files={"file": ("notes.pdf", b"not a pdf", "application/pdf")})
    assert refused.status_code == 415
    preview = client.post("/api/policy/preview",
                          files={"file": ("Company Policy v3.06.pdf", pdf_bytes("Company_Policy_v3.06.pdf"), "application/pdf")})
    assert preview.status_code == 200
    body = preview.json()
    assert body["usable"] and body["version"] == "3.06" and body["file"] == "Company_Policy_v3.06.pdf"
    assert [(c["clause"], c["parameter"]) for c in body["changes"]] == [("5.1.1", "approval_limits")]
    assert client.get("/api/policy").json()["active"] == "2.5"                  # nothing stored by a preview

    assert client.post("/api/policy/adopt", json={"upload_id": "../../etc"}).status_code == 400
    assert client.post("/api/policy/adopt", json={"upload_id": "0" * 16}).status_code == 404
    adopted = client.post("/api/policy/adopt", json={"upload_id": body["upload_id"], "activate": True})
    assert adopted.status_code == 200 and adopted.json()["adopted"] and adopted.json()["active"]
    policy = client.get("/api/policy").json()
    assert policy["active"] == "3.06" and policy["results_under_other_versions"] == 60
    limits = next(r for r in policy["rules"] if r["rule"] == "5.1.1")["params"]["approval_limits"]
    assert limits["Manager"] == 50000

    state = wait(client, client.post("/api/policy/apply").json(), seconds=300)
    assert state["status"] == "done" and state["result"]["invoices"] == 1200 and state["done"] == 1200
    assert client.get("/api/policy").json()["results_under_other_versions"] == 0
    assert client.post("/api/policy/activate", json={"version": "2.5"}).json() == {"active": "2.5"}
    assert client.post("/api/policy/activate", json={"version": "9.9"}).status_code == 404


def test_a_policy_in_its_own_wording_is_proposed_then_confirmed(client, monkeypatch, tmp_path):
    made = {d["path"].name: d for d in study.documents(tmp_path / "freeform")}
    doc = made["handbook_strict_v5.5.pdf"]
    reply = right_reply(doc["path"], "handbook", doc["intended"])
    next(r for r in reply["rules"] if r["clause"] == "2.1.1")["values"]["amount_tolerance_pct"] = 2.0   # not the document's
    preview = client.post("/api/policy/preview", files={"file": (doc["path"].name, doc["path"].read_bytes(), "application/pdf")})
    assert not preview.json()["usable"]                                         # not in the template's wording
    upload_id = preview.json()["upload_id"]
    assert client.post("/api/policy/propose", json={"upload_id": upload_id}).status_code == 400   # no model

    monkeypatch.setattr(api, "chat_client", lambda max_tokens=None: client_for(reply))
    state = wait(client, client.post("/api/policy/propose", json={"upload_id": upload_id}).json())
    assert state["status"] == "done"
    held = [i for i in state["result"]["items"] if i["status"] != "verified"]
    assert [(i["clause"], i["parameter"]) for i in held] == [("2.1.1", "amount_tolerance_pct")]

    nobody = client.post("/api/policy/confirm", json={"upload_id": upload_id, "accept_verified": True})
    assert nobody.status_code == 422 and any("supply the value" in p for p in nobody.json()["detail"]["problems"])
    confirmed = client.post("/api/policy/confirm", json={
        "upload_id": upload_id, "accept_verified": True, "reviewer": "A. Auditor",
        "values": {"2.1.1.amount_tolerance_pct": 0.5}})
    assert confirmed.status_code == 200, confirmed.json()
    assert confirmed.json()["values_supplied_by_the_person"] == ["2.1.1.amount_tolerance_pct"]
    policy = client.get("/api/policy").json()
    assert policy["active"] == "5.5"
    stored = next(v for v in policy["versions"] if v["version"] == "5.5")
    assert stored["adoption"]["confirmed_by"] == "A. Auditor"
    assert {r["rule"]: r["params"] for r in policy["rules"]} == {
        k: v["params"] for k, v in doc["intended"]["clauses"].items()}


def test_policy_search_and_the_copilot_without_a_model(client):
    found = client.get("/api/search", params={"q": "invoice dated on a Saturday or Sunday"}).json()
    assert found["mode"] == "lexical" and found["hits"][0]["clause_id"] == "4.2.1"
    assert found["hits"][0]["source"] == "Rule 4.2.1 (Procurement_Audit_SOP_v2.5.pdf, page 2)"
    state = wait(client, client.post("/api/copilot/ask", json={"question": "vendor marked blacklisted"}).json())
    assert state["status"] == "done" and state["result"]["answer"] is None
    assert any(p["clause_id"] == "4.4.1" for p in state["result"]["passages"])
    assert client.post("/api/copilot/data", json={"question": "how many vendors?"}).status_code == 400
    assert client.post("/api/copilot/ask", json={"question": ""}).status_code == 422


def test_the_measured_results_are_served(client):
    results = client.get("/api/results").json()
    assert {"benchmark", "policy_swap", "policy_change", "scalability", "policy_reading", "pilots"} <= set(results)
    if results["policy_change"]:
        assert len(results["policy_change"]["variants"]) == 14
    for ledger in results["benchmark"].values():
        assert ledger["metrics"]["C1"]["detection_precision"]["value"] == 1.0
    # The sample of benchmark ledger 101 is served with the pilots, marked by its ledger.
    for meta in api.RESULTS.glob("bench_seed_101/*-sample34.meta.json"):
        assert results["pilots"][meta.name.removesuffix(".meta.json")]["dataset"] == "bench_seed_101"


def test_a_token_protects_everything_but_the_health_check(library, monkeypatch):
    monkeypatch.setattr(api, "model_name", lambda: None)
    guarded = TestClient(api.create_app(library, token="s3cret", frontend=None))
    assert guarded.get("/api/health").status_code == 200 and guarded.get("/api/health").json()["auth"]
    assert guarded.get("/api/overview").status_code == 401
    assert guarded.get("/api/overview", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert guarded.get("/api/overview", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_an_unreachable_database_answers_503(monkeypatch):
    monkeypatch.setattr(api, "model_name", lambda: None)
    broken = TestClient(api.create_app("postgresql://nobody:x@127.0.0.1:1/none", token="", frontend=None))
    response = broken.get("/api/health")
    assert response.status_code == 503 and "cannot connect to PostgreSQL" in response.json()["detail"]
    assert "x@" not in json.dumps(response.json())


def test_the_built_frontend_is_served_with_client_side_routes(library, tmp_path, monkeypatch):
    monkeypatch.setattr(api, "model_name", lambda: None)
    site = tmp_path / "dist"
    (site / "assets").mkdir(parents=True)
    (site / "index.html").write_text("<!doctype html><title>AuditIQ</title>", encoding="utf-8")
    (site / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    (site / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    web = TestClient(api.create_app(library, token="", frontend=site))
    assert "<title>AuditIQ</title>" in web.get("/").text
    assert "<title>AuditIQ</title>" in web.get("/review/INV40001").text          # a route of the single-page app
    assert web.get("/assets/app.js").text == "console.log('ok')"
    assert web.get("/favicon.svg").text == "<svg/>"
    assert web.get("/api/nothing-here").status_code == 404
    assert "AuditIQ" not in web.get("/../../.env").text or web.get("/../../.env").status_code in (200, 404)
    assert load_policy("2.5").version == "2.5"
