"""Tests of the policy PDFs, their ingestion, retrieval and the copilot.

Tests that touch the store run on SQLite and on PostgreSQL (fixtures `lib` and
`library` in conftest.py).
"""
from __future__ import annotations

import hashlib
import json

import httpx
import numpy as np
import pytest

from auditiq import copilot, db, policy_ingest, service
from auditiq.graph import PRESETS
from auditiq.llm import ScriptedClient
from auditiq.policy import clause_texts, load_policy
from auditiq.policy_pdf import make_sample_pdfs, review_procedure_markdown, write_pdf
from auditiq.retrieval import EndpointEmbedder, PolicyIndex, embed_chunks
from evaluation.retrieval_eval import GROUPS, evaluate, load_queries


# ----------------------------------------------------------------- the PDFs
def test_sample_pdfs_are_reproducible(pdfs, tmp_path):
    again = make_sample_pdfs(tmp_path)
    assert [p.name for p in pdfs] == ["Procurement_Audit_SOP_v2.5.pdf", "Procurement_Audit_SOP_v2.6.pdf",
                                      "Audit_Review_Procedure_v1.0.pdf"]
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in pdfs] == \
        [hashlib.sha256(p.read_bytes()).hexdigest() for p in again]


def test_the_review_procedure_states_the_numbers_the_scorer_uses():
    text = review_procedure_markdown()
    assert "{{" not in text
    assert "30 for critical, 20 for high, 10 for medium and 5 for low" in text
    assert "count-based score is below 50" in text and "how many of 3 repeated runs" in text


# ---------------------------------------------------------------- ingestion
@pytest.mark.parametrize("version", ["2.5", "2.6"])
def test_every_clause_comes_back_from_the_pdf_word_for_word(lib, version):
    expected = clause_texts(load_policy(version).text)
    assert len(expected) == 16
    rows = lib.execute("SELECT clause_id, text, verified, page FROM policy_chunks WHERE kind = 'clause' AND version = ?",
                       (version,)).fetchall()
    assert {r["clause_id"]: r["text"] for r in rows} == expected
    assert all(r["verified"] == 1 for r in rows) and {r["page"] for r in rows} == {1, 2}


def test_the_policy_swap_is_visible_in_the_ingested_text(lib):
    text = lambda version, clause: lib.scalar(  # noqa: E731
        "SELECT text FROM policy_chunks WHERE version = ? AND clause_id = ?", (version, clause))
    assert "up to 1% of the PO amount" in text("2.5", "2.1.1") and "up to 5% of the PO amount" in text("2.6", "2.1.1")
    table = lambda version: lib.scalar(  # noqa: E731
        "SELECT text FROM policy_chunks WHERE version = ? AND section LIKE '5.1%' AND kind = 'text'", (version,))
    assert "Manager 100,000" in table("2.5") and "Manager 150,000" in table("2.6")


def test_text_chunks_keep_their_section_and_page(lib):
    rows = lib.execute("SELECT c.section, c.page, d.file_name FROM policy_chunks c JOIN policy_documents d "
                       "ON d.doc_id = c.doc_id WHERE c.kind = 'text' ORDER BY d.doc_id, c.position").fetchall()
    sections = [(r["file_name"], r["section"]) for r in rows]
    assert ("Procurement_Audit_SOP_v2.5.pdf", "2.2 Duplicate Invoices") in sections
    assert ("Procurement_Audit_SOP_v2.5.pdf", "6. Next-Best Actions") in sections
    procedure = [s for f, s in sections if f.startswith("Audit_Review")]
    assert procedure == ["1. Purpose", "2. Findings", "3. Confidence", "4. Risk Score", "5. Routing", "6. Review",
                         "7. Audit Pack and Audit Trail"]
    documents = {r["file_name"]: (r["version"], r["pages"]) for r in lib.execute("SELECT * FROM policy_documents")}
    assert documents["Procurement_Audit_SOP_v2.5.pdf"] == ("2.5", 3) and documents["Audit_Review_Procedure_v1.0.pdf"][1] == 2


def test_a_pdf_that_disagrees_with_the_registry_is_reported(lib, tmp_path):
    """The stored policy says 1%; a PDF saying 3% must not pass as verified."""
    altered = load_policy("2.5").text.replace("up to 1% of the PO amount", "up to 3% of the PO amount")
    path = write_pdf(altered, tmp_path / "Procurement_Audit_SOP_v2.5.pdf", "altered", "altered")
    report = policy_ingest.ingest(lib, path)
    assert report["unverified"] == ["2.1.1"] and report["clauses"] == 16
    # Re-ingesting a file replaces its earlier chunks.
    assert lib.scalar("SELECT COUNT(*) FROM policy_documents WHERE file_name = ?", (path.name,)) == 1
    assert lib.scalar("SELECT COUNT(*) FROM policy_chunks WHERE version = '2.5' AND kind = 'clause'") == 16


def test_audit_packs_cite_the_document_and_page_of_each_clause(lib):
    target = lib.scalar("SELECT invoice_id FROM benchmark_labels WHERE class_id = 'R7' ORDER BY invoice_id LIMIT 1")
    service.audit_invoices(lib, PRESETS["C1"], db.read_policy(lib), None, [target])
    pack = json.loads(db.latest_result(lib, target)["audit_pack"])
    assert pack["flags"][0]["citation"] == {"document": "Procurement_Audit_SOP_v2.5.pdf", "page": 2}
    assert policy_ingest.clause_citations(lib, "2.5")["2.1.4"]["page"] == 1


# ---------------------------------------------------------------- retrieval
def test_lexical_retrieval_finds_questions_in_the_policys_wording(lib):
    index = PolicyIndex.from_db(lib)
    assert index.modes == ["lexical"] and len(index.chunks) == 27        # v2.5 and the procedure, not v2.6
    queries = load_queries()
    assert len(queries) == 48 and {q["clause"] for q in queries} == set(load_policy("2.5").clauses)
    # Three groups of 16, one question per clause in each; the test half is never used to choose a ranker.
    for group in GROUPS:
        assert sorted(q["clause"] for q in queries if q["group"] == group) == sorted(load_policy("2.5").clauses)
    results = evaluate(index, queries)
    assert results[("lexical", "wording")]["recall_at_1"] == 1.0 and results[("lexical", "wording")]["n"] == 16
    hit = index.search("how is the risk score of an invoice computed", k=1)[0]
    assert (hit.document, hit.section, hit.clause_id) == ("Audit_Review_Procedure_v1.0.pdf", "4. Risk Score", None)
    assert hit.source == "4. Risk Score (Audit_Review_Procedure_v1.0.pdf, page 1)"


def test_the_index_follows_the_active_policy_version(lib):
    db.set_active_policy(lib, "2.6")
    hit = PolicyIndex.from_db(lib).search("tolerance between invoice amount and PO amount", k=1)[0]
    assert (hit.clause_id, hit.version) == ("2.1.1", "2.6") and "5%" in hit.text
    assert PolicyIndex.from_db(lib, version="2.5").search("tolerance between invoice amount and PO amount", k=1)[0].version == "2.5"


def test_an_index_needs_ingested_documents(conn):
    with pytest.raises(ValueError, match="no policy document"):
        PolicyIndex.from_db(conn)


class FakeEmbedder:
    """Puts a text on an axis by the topic words it contains; used to test the dense path."""
    name = "fake-embedder"
    topics = [("blacklisted", "banned", "blocked"), ("saturday", "sunday", "weekend"), ("gstin", "tax")]

    def embed(self, texts, kind="document"):
        rows = [[float(any(w in t.lower() for w in words)) for words in self.topics] + [0.01] for t in texts]
        m = np.array(rows, dtype=np.float32)
        return m / np.linalg.norm(m, axis=1, keepdims=True)


def test_dense_and_hybrid_ranking_use_the_stored_embeddings(lib):
    embedder = FakeEmbedder()
    assert embed_chunks(lib, embedder) == 47 and embed_chunks(lib, embedder) == 0      # stored once
    index = PolicyIndex.from_db(lib, embedder=embedder)
    assert index.modes == ["lexical", "dense", "hybrid"]
    question = "supplier is on the banned list"
    assert index.search(question, k=1, mode="lexical")[0].clause_id != "4.4.1"            # no shared wording
    assert index.search(question, k=1, mode="dense")[0].clause_id == "4.4.1"
    hybrid = {h.clause_id: h for h in index.search(question, k=3, mode="hybrid")}
    assert hybrid["4.4.1"].dense_rank == 1 and hybrid["4.4.1"].lexical_rank > 1          # fused from both rankings
    # Defaults: dense for a question as asked, hybrid for one the model has restated.
    assert (index.default_mode(), index.default_mode(restated=True)) == ("dense", "hybrid")
    assert index.search(question, k=1)[0].clause_id == "4.4.1"
    assert PolicyIndex.from_db(lib).default_mode(restated=True) == "lexical"            # no embedder, no choice
    # Embeddings from another model are not mixed in.
    other = FakeEmbedder()
    other.name = "another-model"
    assert PolicyIndex.from_db(lib, embedder=other).modes == ["lexical"]
    with pytest.raises(ValueError, match="not available"):
        PolicyIndex.from_db(lib).search(question, mode="dense")


def test_endpoint_embedder_request_and_configuration(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"index": 1, "embedding": [0.0, 2.0]},
                                                  {"index": 0, "embedding": [3.0, 4.0]}]})
    embedder = EndpointEmbedder("http://test/v1/", "embed-1", query_prefix="search_query: ",
                                transport=httpx.MockTransport(handler))
    vectors = embedder.embed(["a", "b"], kind="query")
    assert seen == [{"model": "embed-1", "input": ["search_query: a", "search_query: b"]}]
    assert np.allclose(vectors, [[0.6, 0.8], [0.0, 1.0]])                 # ordered by index, unit length
    assert EndpointEmbedder.from_env(env_file=None) is None
    monkeypatch.setenv("AUDITIQ_EMBED_MODEL", "nomic-embed-text")
    monkeypatch.setenv("AUDITIQ_LLM_BASE_URL", "http://localhost:11434/v1")
    assert EndpointEmbedder.from_env(env_file=None).name == "nomic-embed-text"


def test_question_rewriting_adds_the_models_restatement_to_the_search(lib):
    index = PolicyIndex.from_db(lib)
    assert "blocked vendor" in index.titles and "Risk Score" in index.titles
    client = ScriptedClient(lambda messages, temperature, sample: json.dumps(
        {"restatement": "An invoice from a blacklisted vendor.", "titles": ["blocked vendor"]}))
    question = "supplier is on the banned list"
    assert index.search(question, k=1, client=client)[0].clause_id == "4.4.1"
    system = client.calls[0]["messages"][0]["content"]
    assert "- blocked vendor" in system and "master record is marked" not in system     # titles, not the policy text
    # A reply that is not JSON leaves the question as it was.
    broken = ScriptedClient(lambda *_: "I cannot help with that.")
    assert index.rewrite(question, broken) == question


# ------------------------------------------------------------------ copilot
def test_copilot_without_a_model_returns_the_passages(lib):
    out = copilot.answer("invoice dated on a Saturday or Sunday", lib, PolicyIndex.from_db(lib))
    assert out["answer"] is None and out["passages"][0].clause_id == "4.2.1" and out["calls"] == []


def test_copilot_answers_from_the_passages_and_the_audit_pack_and_cites_them(lib):
    target = lib.scalar("SELECT invoice_id FROM benchmark_labels WHERE class_id = 'R7' ORDER BY invoice_id LIMIT 1")
    service.audit_invoices(lib, PRESETS["C1"], db.read_policy(lib), None, [target])
    client = ScriptedClient(lambda messages, temperature, sample: json.dumps(
        {"answer": "It exceeds the approver's limit [1].", "passages_used": [1, 1, 9, "2", True]}))
    out = copilot.answer(f"Why is {target.lower()} escalated for exceeding the approval limit?", lib,
                         PolicyIndex.from_db(lib), client)
    assert "You help an auditor search" in client.calls[0]["messages"][0]["content"]      # the question is restated first
    user = client.calls[1]["messages"][1]["content"]
    assert out["invoice_id"] == target and f"# Audit pack: {target}" in user and "[1] Rule 5.1.1" in user
    assert out["answer"] == "It exceeds the approver's limit [1]."
    assert [h.clause_id for h in out["sources"]] == ["5.1.1"]            # only a passage that was shown, once
    unaudited = copilot.answer("Why is INV49999 high risk?", lib, PolicyIndex.from_db(lib), client)
    assert "INV49999 has not been audited." in client.calls[-1]["messages"][1]["content"]
    assert unaudited["audit_pack"] is None


def test_for_an_audited_invoice_the_rules_its_findings_cite_come_first(lib):
    """A question that names no rule must still show the model the rule the invoice was flagged under."""
    target = lib.scalar("SELECT invoice_id FROM benchmark_labels WHERE class_id = 'R7' ORDER BY invoice_id LIMIT 1")
    service.audit_invoices(lib, PRESETS["C1"], db.read_policy(lib), None, [target])
    index = PolicyIndex.from_db(lib)
    question = f"Why was {target} flagged?"
    assert "5.1.1" not in [h.clause_id for h in index.search(question, k=4)]          # wording alone misses it
    client = ScriptedClient(lambda messages, temperature, sample: json.dumps({"answer": "x [1]", "passages_used": [1]}))
    out = copilot.answer(question, lib, index, client)
    assert out["passages"][0].clause_id == "5.1.1" and len(out["passages"]) == 4
    assert [h.clause_id for h in out["passages"]].count("5.1.1") == 1
    system, user = client.calls[-1]["messages"][0]["content"], client.calls[-1]["messages"][1]["content"]
    assert "The AUDIT RECORD is the authority" in system and "[1] Rule 5.1.1" in user


def test_copilot_reports_a_model_that_gives_no_usable_answer(lib):
    out = copilot.answer("weekend", lib, PolicyIndex.from_db(lib), ScriptedClient(lambda *_: "no idea"))
    assert "did not return a usable answer" in out["answer"] and out["sources"] == [] and len(out["calls"]) == 2


@pytest.mark.parametrize("sql", [
    "DELETE FROM invoices", "SELECT 1; DROP TABLE invoices", "PRAGMA table_info(invoices)", "",
    "UPDATE invoices SET amount = 0", "ATTACH DATABASE 'x.db' AS x",
])
def test_only_a_single_select_passes_the_check(sql):
    with pytest.raises(copilot.UnsafeQuery):
        copilot.check_sql(sql)


def test_a_checked_select_runs_read_only_and_cannot_see_the_labels(library):
    columns, rows = copilot.run_select(library, "SELECT COUNT(*) AS n FROM invoices;")
    assert (columns, rows) == (["n"], [(1200,)])
    columns, rows = copilot.run_select(library, "WITH v AS (SELECT vendor_id, COUNT(*) AS n FROM invoices GROUP BY 1) "
                                                "SELECT COUNT(*) FROM v")
    assert rows == [(60,)]
    assert len(copilot.run_select(library, "SELECT invoice_id FROM invoices")[1]) == copilot.ROW_LIMIT
    for forbidden in ("SELECT * FROM benchmark_labels", "SELECT text FROM policy_chunks",
                      "SELECT i.invoice_id FROM invoices i JOIN benchmark_labels b USING (invoice_id)",
                      "SELECT invoice_id FROM invoices WHERE invoice_id IN (SELECT invoice_id FROM Benchmark_Labels)",
                      "SELECT COUNT(*) FROM benchmark_labels", "SELECT value FROM meta",
                      "SELECT * FROM sqlite_master", "SELECT * FROM pg_catalog.pg_tables",
                      "SELECT * FROM information_schema.tables", "SELECT pg_read_file('x')",
                      "SELECT * FROM no_such_table"):
        with pytest.raises(copilot.UnsafeQuery):
            copilot.run_select(library, forbidden)


def test_the_reader_role_enforces_the_allow_list_inside_postgresql(library):
    """Without the name check, PostgreSQL itself must still refuse the labels table."""
    conn = db.connect(library, read_only=True)
    if conn.backend != "postgres" or not conn.scalar("SELECT 1 FROM pg_roles WHERE rolname = ?", (db.READER_ROLE,)):
        conn.close()
        pytest.skip("needs PostgreSQL with the auditiq_reader role")
    conn.execute(f"SET ROLE {db.READER_ROLE}")
    assert conn.scalar("SELECT COUNT(*) FROM invoices") == 1200
    with pytest.raises(Exception, match="permission denied"):
        conn.execute("SELECT COUNT(*) FROM benchmark_labels")
    conn.close()


def test_a_data_question_runs_the_models_select_and_repairs_a_rejected_one(library):
    writable = db.connect(library)
    ids = [r[0] for r in writable.execute("SELECT invoice_id FROM benchmark_labels WHERE class_id IN ('R7', 'R9') "
                                          "ORDER BY invoice_id LIMIT 6")]
    service.audit_invoices(writable, PRESETS["C1"], db.read_policy(writable), None, ids)
    writable.close()

    replies = iter([
        {"sql": ["SELECT class_id, COUNT(*) FROM benchmark_labels GROUP BY 1"], "explanation": "labels"},
        {"sql": ["SELECT route, COUNT(*) AS n FROM v_latest_results GROUP BY route"], "explanation": "Results by route."},
    ])
    client = ScriptedClient(lambda *_: json.dumps(next(replies)))
    out = copilot.data_question("How many invoices are escalated?", library, client)
    assert out["error"] is None and out["columns"] == ["route", "n"] and out["rows"] == [("escalate", 6)]
    assert out["sql"].startswith("SELECT route") and out["explanation"] == "Results by route."
    system = client.calls[0]["messages"][0]["content"]
    assert "v_latest_results(" in system and "benchmark_labels" not in system and "audit_pack" not in system
    assert "rejected" in client.calls[1]["messages"][-1]["content"]

    stubborn = ScriptedClient(lambda *_: json.dumps({"sql": ["DROP TABLE invoices"]}))
    out = copilot.data_question("Delete everything", library, stubborn)
    assert out["rows"] == [] and "SELECT" in out["error"] and len(stubborn.calls) == 2
    check = db.connect(library, read_only=True)
    assert check.scalar("SELECT COUNT(*) FROM invoices") == 1200
    check.close()
