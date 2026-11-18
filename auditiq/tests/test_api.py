"""Tests of the REST API, on both database backends.

No model is called: model-backed endpoints are tested for their refusal without
a model, and the model-assisted policy reading with a scripted stand-in.
"""
from __future__ import annotations

import json
import time
import zipfile

import numpy as np
import pytest
from fastapi.testclient import TestClient
from test_policy_docs import FakeEmbedder
from test_policy_llm import client_for, right_reply

from auditiq import analytics, api, db, ledger_import, retrieval, service, stream
from auditiq.graph import PRESETS
from auditiq.policy import POLICY_DIR, load_policy
from auditiq.policy_pdf import make_sample_pdfs
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


def test_the_analytics_and_the_rings_describe_the_ledger(client):
    overview = client.get("/api/overview").json()
    assert overview["coverage"]["configurations"] == {"C1": 60}
    assert (overview["coverage"]["controls_run"], overview["coverage"]["judgement_run"]) == (60, 0)
    assert overview["coverage"]["answer_key"]["false_alarms"] == 0
    assert overview["activity"] and overview["activity"][0]["stage"] == "scoring"     # the newest step first
    out = client.get("/api/analytics").json()
    assert out["invoices"] == 1200 and sum(m["invoices"] for m in out["monthly"]) == 1200
    assert out["benford"]["n"] == 1200 and len(out["benford"]["first"]["digits"]) == 9
    assert [n["role"] for n in out["amounts"]["limits"]] == ["Manager", "Senior Manager", "Director", "CFO"]
    found = client.get("/api/rings", params={"limit": 3}).json()
    assert len(found["rings"]) <= 3 and found["identity"]["vendors"] == 60
    assert {n["ring"] for n in found["nodes"]} <= {r["id"] for r in found["rings"]}
    assert found["tests"]["pairs_tested"] > 0 and found["tests"]["fdr"] == 0.01
    assert client.get("/api/rings", params={"limit": "many"}).status_code == 422


def test_the_assurance_endpoints_leads_sampling_and_the_sealed_trail(client, library):
    out = client.get("/api/leads").json()
    for key, clause in (("near_duplicates", "2.2.2"), ("structuring", "4.1.2")):
        assert out[key]["clause"] == clause and out[key]["invoices"] > 0
        assert out["answer_key"][clause]["precision"] == 1.0 and out["answer_key"][clause]["recall"] == 1.0
    assert out["guide"]["window_days"] == 7 and out["guide"]["band_pct"] == 15.0
    sample = client.get("/api/sampling", params={"seed": 5, "tolerable_pct": 5, "confidence": "0.95",
                                                 "expected_pct": "0"}).json()            # as the web page sends it
    assert sample["seed"] == 5 and sample["plan"]["tolerable_pct"] == 5.0 and sample["plan"]["confidence"] == 0.95
    assert client.get("/api/sampling", params={"confidence": "0.99"}).json()["plan"]["confidence"] == 0.99
    assert sample["plan"]["items"] == 20 and sample["drawn"] == len(sample["sample"]) > 0     # the 20 approved
    assert client.get("/api/sampling", params={"seed": 5, "tolerable_pct": 5}).json()["sample"] == sample["sample"]
    assert client.get("/api/sampling", params={"confidence": 0.8}).status_code == 422
    assert client.get("/api/sampling", params={"tolerable_pct": 1, "expected_pct": 1}).status_code == 400
    trail = client.get("/api/trail/verify").json()
    assert trail["intact"] and trail["results"]["sealed"] == 60 and trail["runs"]["sealed"] == 1 and trail["digest"]
    assert trail["evidence"]["current"] and trail["evidence"]["fingerprinted"] == 60
    reliable = client.get("/api/reliability").json()
    assert reliable["summary"]["reliable"] and len(reliable["fingerprint"]["ledger"]) == 64
    assert {c["id"] for c in reliable["checks"]} >= {"approved", "total", "series-invoices", "received-not-invoiced"}
    program = client.get("/api/program").json()
    assert {"2.1.1", "5.1.1", "rings", "sample", "seal"} <= {t["id"] for t in program["tests"]}
    assert program["answer_key"]["compared"] and "bid-rigging" in program["untested"]["schemes"]
    papers = client.get("/api/workpapers")
    assert papers.status_code == 200 and papers.headers["content-type"].startswith(api.XLSX)
    assert papers.content[:2] == b"PK" and len(papers.headers["x-report-digest"]) == 64
    assert client.get("/api/workpapers").headers["x-report-digest"] == papers.headers["x-report-digest"]
    item = client.get("/api/queue").json()["items"][0]
    assert client.get(f"/api/invoices/{item['invoice_id']}").json()["result"]["integrity"] == "intact"
    conn = db.connect(library)                           # a finding changed in the database itself
    conn.execute("UPDATE audit_flags SET severity = 'low' WHERE result_id = ?", (item["result_id"],))
    conn.commit()
    conn.close()
    trail = client.get("/api/trail/verify").json()       # not cached: the change shows at once
    assert not trail["intact"] and trail["results"]["altered_ids"] == [item["result_id"]]
    assert client.get(f"/api/invoices/{item['invoice_id']}").json()["result"]["integrity"] == "altered"
    other = client.get("/api/queue").json()["items"][1]
    conn = db.connect(library)                           # the ledger changed after the audit: intact but stale
    conn.execute("UPDATE invoices SET amount = amount + 1 WHERE invoice_id = ?", (other["invoice_id"],))
    conn.commit()
    conn.close()
    assert client.get(f"/api/invoices/{other['invoice_id']}").json()["result"]["integrity"] == "stale"
    drift = client.get("/api/trail/verify").json()["evidence"]
    assert drift["changed_invoices"] == [{"invoice_id": other["invoice_id"], "changed": ["invoice"]}]


def test_the_analyses_are_kept_until_the_store_changes(client, monkeypatch):
    calls = []
    real = analytics.ledger_analytics
    monkeypatch.setattr(analytics, "ledger_analytics", lambda conn: calls.append(1) or real(conn))
    first = client.get("/api/analytics").json()
    assert client.get("/api/analytics").json() == first and len(calls) == 1               # kept
    reviewed = client.get("/api/overview").json()["reviewed"]
    item = client.get("/api/queue").json()["items"][0]
    assert client.post(f"/api/results/{item['result_id']}/decision", json={"decision": "approve", "reviewer": "A. Auditor"}).status_code == 200
    client.get("/api/analytics")
    assert len(calls) == 2                                                                  # a decision changes the store
    assert client.get("/api/overview").json()["reviewed"] == reviewed + 1


def test_the_policy_graph_and_asking_it(client):
    graph = client.get("/api/policy/graph").json()
    assert graph["version"] == "2.5" and graph["counts"]["clause"] == 16 and graph["counts"]["role"] == 4
    assert {v["version"] for v in graph["versions"]} == {"2.5", "2.6"}
    assert client.get("/api/policy/graph", params={"version": "2.6"}).json()["version"] == "2.6"
    assert client.get("/api/policy/graph", params={"version": "9.9"}).status_code == 404
    asked = client.get("/api/policy/graph/ask", params={"q": "Who has to approve an invoice of ₹30 lakh?"}).json()
    assert asked["recognised"]["amounts"] == [3000000.0]
    assert asked["facts"][0]["data"] == {"amount": 3000000.0, "lowest": "CFO"} and asked["facts"][0]["source"].startswith("5.1 ")
    assert asked["passages"][0]["section"].startswith("5.1 ") and "role:CFO" in asked["nodes"]
    assert client.get("/api/policy/graph/ask", params={"q": "  "}).status_code == 400
    job = client.post("/api/copilot/ask", json={"question": "What changed between version 2.5 and 2.6?"}).json()
    done = wait(client, job)
    assert done["status"] == "done" and done["result"]["answer"] is None                  # no model: facts and passages
    assert len([f for f in done["result"]["facts"] if f["kind"] == "change"]) == 3


def test_the_queue_counts_every_level_and_lists_one_level(client):
    whole = client.get("/api/queue", params={"limit": 5}).json()
    assert whole["total"] == 40 and len(whole["items"]) == 5                  # the list is cut, the counts are not
    assert {lv: x["invoices"] for lv, x in whole["levels"].items()} == {"CRITICAL": 20, "HIGH": 20}
    high = client.get("/api/queue", params={"limit": 2000, "level": "HIGH"}).json()
    assert high["total"] == len(high["items"]) == 20 and {i["risk_level"] for i in high["items"]} == {"HIGH"}
    assert high["levels"] == whole["levels"]
    assert client.get("/api/queue", params={"level": "SEVERE"}).status_code == 422


def test_the_review_flow_records_a_decision(client):
    queue = client.get("/api/queue").json()
    assert queue["total"] == 40 and len(queue["items"]) == 40
    first = queue["items"][0]
    assert first["rc"] >= queue["items"][-1]["rc"]                              # highest risk first
    assert all(item["rules"] for item in queue["items"])                      # each waits for a broken rule
    assert set(queue["rules"]) == {c for item in queue["items"] for c in item["rules"]}
    assert all(queue["rules"].values())                                       # titled from the active policy

    detail = client.get(f"/api/invoices/{first['invoice_id'].lower()}").json()
    assert detail["records"]["invoice"]["invoice_id"] == first["invoice_id"]
    assert detail["result"]["workflow_status"] == "PENDING_REVIEW" and detail["result"]["pack"]["flags"]
    assert [t["stage"] for t in detail["result"]["trail"]] == ["extraction", "controls", "scoring"]
    assert "benchmark_label" not in detail
    assert detail["emails"] == []                   # no e-mail has arrived for it
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


def test_the_stream_status_says_when_no_broker_is_configured(client, monkeypatch):
    monkeypatch.delenv("AUDITIQ_KAFKA_BOOTSTRAP", raising=False)
    assert client.get("/api/stream").json() == {"configured": False, "topics": []}


def test_the_console_says_what_runs_and_the_stream_needs_a_broker(client, monkeypatch):
    monkeypatch.delenv("AUDITIQ_KAFKA_BOOTSTRAP", raising=False)
    system = client.get("/api/system").json()
    assert system["kafka"] == {"configured": False, "connected": False}
    assert system["model"] == {"configured": False, "reachable": False}
    assert system["policy_version"] == "2.5" and system["store"]["ledger"]
    embeddings = system["embeddings"]
    assert (embeddings["configured"], embeddings["model"], embeddings["embedded"]) == (False, None, 0) and embeddings["passages"] > 0
    for answer in (client.post("/api/stream/publish", json={"source": "ledger", "name": "small"}),
                   client.post("/api/stream/work", json={}),
                   client.get("/api/stream/peek", params={"kind": "invoice"})):
        assert answer.status_code == 409 and "AUDITIQ_KAFKA_BOOTSTRAP" in answer.json()["detail"]
    assert client.post("/api/stream/publish", json={"source": "ftp", "name": "x"}).status_code == 422
    assert client.post("/api/stream/work", json={"kinds": ["invoice"], "idle_exit": 0}).status_code == 422
    assert client.get("/api/stream/log").json() == {"messages": []}


def test_the_stream_sources_are_the_files_on_the_server(client, monkeypatch, tmp_path):
    ledger = tmp_path / "data" / "ledger_a"
    ledger.mkdir(parents=True)
    (ledger / "invoices.csv").write_text("invoice_id\n", encoding="utf-8")
    (ledger / "manifest.json").write_text(json.dumps({"counts": {"invoices": 12, "vendors": 3}}), encoding="utf-8")
    (tmp_path / "data" / "notes").mkdir()                                     # no invoices: not a ledger
    (tmp_path / ".auditiq").mkdir()
    (tmp_path / ".auditiq" / "mail.mbox").write_bytes(b"From a@b\n")
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    assert client.get("/api/stream/sources").json() == {
        "ledgers": [{"name": "ledger_a", "invoices": 12, "vendors": 3}], "mailboxes": [{"name": "mail.mbox", "bytes": 9}], "policies": []}
    assert stream.source_path(tmp_path, "ledger", "ledger_a") == ledger
    for name in ("notes", "../ledger_a", "ledger_b"):                          # only what is listed
        with pytest.raises(ValueError, match="no ledger named"):
            stream.source_path(tmp_path, "ledger", name)


def test_a_question_is_traced_through_every_step_of_retrieval(client, library, monkeypatch):
    question = "Who has to approve an invoice of ₹30 lakh?"
    trace = client.get("/api/rag/trace", params={"q": question, "k": 4}).json()
    assert (trace["mode"], trace["embedding_model"], trace["query_point"], trace["explained"]) == ("lexical", None, None, [])
    assert trace["recognised"]["amounts"] == [3000000.0] and trace["facts"][0]["data"]["lowest"] == "CFO"
    assert {p["version"] for p in trace["passages"]} == {"2.5", None}           # the active version, and documents of every version
    assert sorted(p["lexical_rank"] for p in trace["passages"]) == list(range(1, len(trace["passages"]) + 1))
    assert "dense" not in trace["passages"][0]
    graph = [c for c in trace["context"] if c["from"] == "graph"]
    assert graph and trace["context"][:len(graph)] == graph and any(c["section"].startswith("5.1 ") for c in graph)
    assert len(trace["context"]) == max(4, len(graph) + 2)                      # the graph's passages first, then two retrieved
    assert client.get("/api/rag/trace", params={"q": "  "}).status_code == 400

    conn = db.connect(library)                                                  # with embeddings: dense, fused and drawn
    retrieval.embed_chunks(conn, FakeEmbedder())
    conn.close()
    monkeypatch.setattr(retrieval.EndpointEmbedder, "from_env", classmethod(lambda cls: FakeEmbedder()))
    dense = client.get("/api/rag/trace", params={"q": "Can a supplier bill us on a weekend?"}).json()
    assert (dense["mode"], dense["embedding_model"], dense["dense_error"]) == ("dense", "fake-embedder", None)
    best = min(dense["passages"], key=lambda p: p["dense_rank"])
    assert any(w in best["text"].lower() for w in ("saturday", "sunday", "weekend"))
    for p in dense["passages"]:
        assert p["hybrid"] == pytest.approx(1 / (60 + p["lexical_rank"]) + 1 / (60 + p["dense_rank"]), abs=1e-6)
        assert len(p["point"]) == 3 and max(abs(x) for x in p["point"]) <= 1
    assert len(dense["query_point"]) == 3 and len(dense["explained"]) == 3

    class Down(FakeEmbedder):
        def embed(self, texts, kind="document"):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(retrieval.EndpointEmbedder, "from_env", classmethod(lambda cls: Down()))
    down = client.get("/api/rag/trace", params={"q": "Can a supplier bill us on a weekend?"}).json()
    assert down["mode"] == "lexical" and down["dense_error"] == "RuntimeError: connection refused"   # wording alone


def test_the_knowledge_layer_lists_documents_passages_and_the_registry(client, library):
    k = client.get("/api/knowledge").json()
    assert {"2.5", "2.6"} <= {d["version"] for d in k["documents"]}
    assert sum(d["passages"] for d in k["documents"]) == len(k["passages"])
    assert (k["embedding_model"], k["explained"]) == (None, []) and not any("point" in p for p in k["passages"])
    assert set(k["registry"]) == {"2.5", "2.6"} and len(k["registry"]["2.5"]) == 16
    limits = [k["registry"][v]["5.1.1"]["params"]["approval_limits"]["Manager"] for v in ("2.5", "2.6")]
    assert limits == [100000, 150000]
    rules = [p for p in k["passages"] if p["kind"] == "clause"]
    assert rules and all(p["verified"] for p in rules)
    conn = db.connect(library)
    retrieval.embed_chunks(conn, FakeEmbedder())
    conn.close()
    mapped = client.get("/api/knowledge").json()
    assert mapped["embedding_model"] == "fake-embedder" and len(mapped["explained"]) == 3
    assert all(len(p["point"]) == 3 and max(abs(x) for x in p["point"]) <= 1 for p in mapped["passages"])


def test_the_ai_layer_describes_the_agents_and_what_the_stored_runs_cost(client):
    ai = client.get("/api/ai").json()
    assert ai["policy_version"] == "2.5" and ai["model"] is None
    assert {a["name"]: a["judges"] for a in ai["agents"]} == {
        "math_approvals": ["2.1.4", "2.1.5"], "tax_identity": ["2.2.2"], "vendor_intelligence": ["4.1.2"]}
    assert set(ai["configurations"]) == set(PRESETS) and ai["configurations"]["C5"]["reruns"] == 3
    controls = next(s for s in ai["stages"] if s["stage"] == "controls")
    assert (controls["steps"], controls["model_calls"], controls["mean_latency_ms"]) == (60, 0, None)
    assert ai["traced"] == []                                                   # only the controls ran: nothing to replay


def test_the_projection_keeps_three_coordinates():
    matrix = np.random.default_rng(1).normal(size=(10, 8))
    coords, projected, explained = retrieval.projection(matrix, matrix[:2])
    assert coords.shape == (10, 3) and np.abs(coords).max() == pytest.approx(1.0)
    assert np.allclose(projected, coords[:2])                                   # the same projection for added vectors
    assert explained == sorted(explained, reverse=True) and 0 < sum(explained) <= 1
    two, _, _ = retrieval.projection(matrix[:2])                                # fewer than three components
    assert two.shape == (2, 3) and np.allclose(two[:, 1:], 0)


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


def test_a_policy_document_is_previewed_adopted_and_applied_to_the_ledger(client, library):
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
    assert policy["active"] == "3.06"
    limits = next(r for r in policy["rules"] if r["rule"] == "5.1.1")["params"]["approval_limits"]
    assert limits["Manager"] == 50000
    # Each invoice is judged by the version in force on its date. 3.06 takes effect on 1 April 2026, after every
    # invoice of this ledger: the 60 results under 2.5 stand.
    assert [(t["version"], t["from"], t["until"], t["invoices"]) for t in policy["timeline"]] == [
        ("2.5", "2025-04-01", "2026-04-01", 1200), ("3.06", "2026-04-01", None, 0)]
    assert (policy["under_other_version"], policy["unaudited"]) == (0, 1140)

    conn = db.connect(library)                                  # ten audited invoices, now dated after the change
    later = [r[0] for r in conn.execute("SELECT invoice_id FROM latest_results ORDER BY invoice_id LIMIT 10")]
    conn.executemany("UPDATE invoices SET date = ? WHERE invoice_id = ?", [("2026-04-15", i) for i in later])
    conn.commit()
    conn.close()
    state = wait(client, client.post("/api/policy/apply").json(), seconds=300)
    result = state["result"]
    assert state["status"] == "done" and (result["invoices"], result["unchanged"]) == (1150, 50)
    assert [(r["policy_version"], r["invoices"]) for r in result["runs"]] == [("2.5", 1140), ("3.06", 10)]
    policy = client.get("/api/policy").json()
    assert (policy["under_other_version"], policy["unaudited"]) == (0, 0)
    assert [t["invoices"] for t in policy["timeline"]] == [1190, 10]
    again = wait(client, client.post("/api/policy/apply").json(), seconds=300)["result"]
    assert (again["invoices"], again["unchanged"]) == (10, 1190)              # only the active version's own invoices
    assert client.post("/api/policy/activate", json={"version": "2.5"}).json() == {"active": "2.5"}
    assert client.get("/api/policy").json()["under_other_version"] == 10     # 3.06 governs nothing any more
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


def test_a_ledger_is_uploaded_checked_and_then_replaces_the_old_one(client, small_dataset, tmp_path):
    book = ledger_import.export_workbook(small_dataset, tmp_path / "new ledger.xlsx").read_bytes()
    sheet = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    upload = {"file": ("new ledger.xlsx", book, sheet)}
    assert client.post("/api/ledger", files=upload).status_code == 400              # replacing was not confirmed
    assert client.post("/api/ledger", files={"file": ("ledger.csv", b"a,b", "text/csv")},
                       data={"replace": "true"}).status_code == 415

    # A ledger with problems replaces nothing.
    broken = tmp_path / "broken.zip"
    with zipfile.ZipFile(broken, "w") as archive:
        archive.write(small_dataset / "invoices.csv", "invoices.csv")
    before = client.get("/api/overview").json()
    job = wait(client, client.post("/api/ledger", files={"file": ("broken.zip", broken.read_bytes(), "application/zip")},
                                   data={"replace": "true"}).json())
    assert job["status"] == "done" and not job["result"]["loaded"]
    assert "the table vendor_master is missing" in job["result"]["problems"]
    assert client.get("/api/overview").json()["audited"] == before["audited"] == 60

    # A sound workbook replaces the ledger and everything derived from it.
    job = wait(client, client.post("/api/ledger", files=upload, data={"replace": "true"}).json())
    assert job["status"] == "done" and job["result"]["loaded"], job
    assert job["result"]["counts"]["invoices"] == 1200
    overview = client.get("/api/overview").json()
    assert (overview["ledger"], overview["invoices"], overview["audited"]) == ("new_ledger", 1200, 0)


def test_a_token_protects_everything_but_the_health_check(library, monkeypatch):
    monkeypatch.setattr(api, "model_name", lambda: None)
    guarded = TestClient(api.create_app(library, token="s3cret", frontend=None))
    assert guarded.get("/api/health").status_code == 200 and guarded.get("/api/health").json()["auth"]
    assert guarded.get("/api/overview").status_code == 401
    assert guarded.get("/api/overview", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert guarded.get("/api/overview", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_users_get_what_their_role_allows_and_a_decision_carries_the_users_name(client, library):
    conn = db.connect(library)
    tokens = {role: db.add_user(conn, f"{role.title()} One", role) for role in db.ROLES}
    leaver = db.add_user(conn, "Left Already", "admin")
    db.disable_user(conn, "Left Already")
    conn.close()
    auth = {role: {"Authorization": f"Bearer {token}"} for role, token in tokens.items()}
    assert client.get("/api/health").json()["auth"] is True              # users exist: the server is no longer open
    assert client.get("/api/overview").status_code == 401
    assert client.get("/api/overview", headers={"Authorization": f"Bearer {leaver}"}).status_code == 401
    assert client.get("/api/me", headers=auth["viewer"]).json() == {"name": "Viewer One", "role": "viewer",
                                                                   "via": "account"}
    result_id = client.get("/api/queue", headers=auth["viewer"]).json()["items"][0]["result_id"]
    decide = lambda who, body: client.post(f"/api/results/{result_id}/decision", json=body, headers=auth[who])  # noqa: E731
    refused = decide("viewer", {"decision": "approve"})
    assert refused.status_code == 403 and "needs the role reviewer" in refused.json()["detail"]
    assert client.post("/api/policy/activate", json={"version": "2.6"}, headers=auth["reviewer"]).status_code == 403
    assert decide("reviewer", {"decision": "approve", "reviewer": "Someone Else"}).status_code == 200
    conn = db.connect(library)
    assert conn.scalar("SELECT reviewer FROM review_decisions WHERE result_id = ?", (result_id,)) == "Reviewer One"
    conn.close()
    assert client.post("/api/policy/activate", json={"version": "2.6"}, headers=auth["admin"]).status_code == 200


def test_the_shared_token_acts_as_an_admin_beside_the_users(library, monkeypatch):
    monkeypatch.setattr(api, "model_name", lambda: None)
    conn = db.connect(library)
    viewer = db.add_user(conn, "Read Only", "viewer")
    conn.close()
    guarded = TestClient(api.create_app(library, token="s3cret", frontend=None))
    assert guarded.get("/api/me", headers={"Authorization": "Bearer s3cret"}).json()["role"] == "admin"
    assert guarded.get("/api/me", headers={"Authorization": f"Bearer {viewer}"}).json()["role"] == "viewer"
    assert guarded.post("/api/policy/activate", json={"version": "2.6"},
                        headers={"Authorization": f"Bearer {viewer}"}).status_code == 403


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
    assert "immutable" in web.get("/assets/app.js").headers["cache-control"]          # named by their content's hash
    assert web.get("/").headers["cache-control"] == "no-cache"                         # a new build reaches the browser
    assert web.get("/favicon.svg").text == "<svg/>"
    assert web.get("/api/nothing-here").status_code == 404
    assert "AuditIQ" not in web.get("/../../.env").text or web.get("/../../.env").status_code in (200, 404)
    assert load_policy("2.5").version == "2.5"


def test_a_job_that_would_change_the_ledger_under_another_is_refused():
    """Loading a ledger deletes every result, so it may not run beside an audit; two whole-ledger audits neither."""
    import threading

    jobs, release = api.Jobs(keep=2), threading.Event()
    applying = jobs.start("apply-policy", lambda job: release.wait(10))
    for kind in ("load-ledger", "apply-policy"):
        with pytest.raises(api.JobConflict, match=f"the apply-policy job {applying.id} is still running"):
            jobs.start(kind, lambda job: None)
    single = jobs.start("audit", lambda job: "one invoice")        # one invoice beside a whole-ledger run is fine
    copilot = [jobs.start("copilot", lambda job: None) for _ in range(3)]
    time.sleep(0.2)
    assert jobs.get(applying.id) is applying                        # kept past `keep` while it runs
    release.set()
    for job in [applying, single, *copilot]:
        for _ in range(100):
            if jobs.get(job.id) is None or job.status in ("done", "failed"):
                break
            time.sleep(0.05)
    assert applying.status == "done" and single.result == "one invoice"
    assert jobs.start("load-ledger", lambda job: None).kind == "load-ledger"


def test_a_conflicting_job_is_answered_with_409(client, monkeypatch):
    def refuse(self, kind, work):
        raise api.JobConflict("a load-ledger job (abc) is running; wait for it to finish")
    monkeypatch.setattr(api.Jobs, "start", refuse)
    response = client.post("/api/policy/apply")
    assert response.status_code == 409 and "load-ledger" in response.json()["detail"]


def test_every_answer_carries_the_security_headers(client):
    for path in ("/api/health", "/api/no-such-endpoint"):
        headers = client.get(path).headers
        assert headers["x-content-type-options"] == "nosniff" and headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "no-referrer"
    page = client.get("/review").headers                     # the web application, not the API
    assert "script-src 'self'" in page["content-security-policy"] and "frame-ancestors 'none'" in page["content-security-policy"]
    assert "content-security-policy" not in client.get("/api/health").headers      # /api/docs loads its viewer from a CDN


def test_a_large_answer_is_compressed_for_a_client_that_accepts_it(client):
    plain = client.get("/api/risk-map", headers={"Accept-Encoding": "identity"})
    packed = client.get("/api/risk-map", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in plain.headers and packed.headers["content-encoding"] == "gzip"
    assert packed.json() == plain.json()
    assert int(packed.headers["content-length"]) < int(plain.headers["content-length"]) / 3
    assert packed.headers["x-content-type-options"] == "nosniff"                     # still with the security headers
    assert "content-encoding" not in client.get("/api/health", headers={"Accept-Encoding": "gzip"}).headers   # small


def test_the_api_simulates_a_previewed_document_as_a_job(client, tmp_path):
    pdf = next(p for p in make_sample_pdfs(tmp_path) if "v2.6" in p.name)
    upload = client.post("/api/policy/preview", files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")}).json()
    job = client.post("/api/policy/simulate", json={"upload_id": upload["upload_id"]})
    assert job.status_code == 202 and job.json()["kind"] == "simulate"
    for _ in range(200):
        state = client.get(f"/api/jobs/{job.json()['id']}").json()
        if state["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert state["status"] == "done", state["error"]
    assert state["result"]["new_version"] == "2.6" and state["result"]["invoices"] == 1200
    refused = client.post("/api/policy/simulate", json={"upload_id": "not-an-id"})
    assert refused.status_code == 400



def test_the_audited_ledger_is_served_as_a_graph_and_asked_questions(client):
    view = client.get("/api/case-graph").json()
    assert view["counts"]["invoices_with_findings"] == 60 and view["focus"] is None and view["policy_version"] == "2.5"
    focused = client.get("/api/case-graph", params={"focus": "5.1.1"}).json()
    assert focused["focus_kind"] == "rule" and any(n["kind"] == "vendor" for n in focused["nodes"])
    invoice = next(i for i in client.get("/api/queue", params={"limit": 1}).json()["items"])["invoice_id"]
    one = client.get("/api/case-graph", params={"focus": invoice}).json()
    assert one["focus_kind"] == "invoice" and {"vendor", "rule", "invoice"} <= {n["kind"] for n in one["nodes"]}
    assert client.get("/api/case-graph", params={"focus": "nobody"}).status_code == 404

    asked = client.get("/api/case-graph/ask", params={"q": "How many invoices break rule 5.1.1?"}).json()
    assert asked["facts"][0]["kind"] == "rule" and asked["facts"][0]["data"]["flagged"] == focused["nodes"][0]["invoices"]
    assert client.get("/api/case-graph/ask", params={"q": f"Why was {invoice} flagged?"}).json()["facts"][0]["kind"] == "invoice"
    assert client.get("/api/case-graph/ask", params={"q": "  "}).status_code == 400

    done = wait(client, client.post("/api/copilot/ask", json={"question": f"Why was {invoice} flagged?"}).json())
    assert done["status"] == "done" and done["result"]["answer"] is None                  # no model: the facts are the answer
    assert done["result"]["case_facts"][0]["kind"] == "invoice" and f"i:{invoice}" in done["result"]["case_nodes"]
