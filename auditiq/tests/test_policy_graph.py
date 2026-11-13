"""Tests of the policy graph (auditiq/policy_graph.py), its use by Ask AI and its evaluation."""
from __future__ import annotations

import json

import pytest

from auditiq import controls, copilot
from auditiq.agents import AGENTS
from auditiq.llm import ScriptedClient
from auditiq.policy_graph import PolicyGraph, parse_amounts
from auditiq.retrieval import PolicyIndex
from evaluation import graph_eval


@pytest.fixture()
def graph(lib) -> PolicyGraph:
    return PolicyGraph.from_db(lib)


def test_the_graph_holds_every_rule_with_what_checks_it(graph):
    nodes, edges = graph.nodes, graph.edges
    clauses = [n for n in nodes.values() if n["kind"] == "clause"]
    assert len(clauses) == 16 and graph.version == "2.5"
    functions = {fn.__name__ for fn in controls.CONTROLS}
    for clause in clauses:
        checked = [e["target"] for e in edges if e["source"] == clause["id"] and e["kind"] == "checked by"]
        assert len(checked) == 1, clause["id"]
        kind, name = checked[0].split(":")
        if clause["clause_kind"] == "control":
            assert kind == "control" and name in functions                      # a real function of controls.py
        else:
            assert kind == "agent" and clause["label"].startswith(AGENTS[name].sections)
        assert any(e["source"] == clause["id"] and e["kind"] == "stated on" for e in edges)    # its page
    limits = {n["label"]: n["limit"] for n in nodes.values() if n["kind"] == "role"}
    assert limits == {"Manager": 100000, "Senior Manager": 500000, "Director": 2500000, "CFO": 10000000}
    changes = [e for e in edges if e["source"] == "version:2.6" and e["kind"] == "changes"]
    assert sorted(e["target"] for e in changes) == ["param:2.1.1:amount_tolerance_pct", "param:4.1.1:max_invoices_per_vendor_per_day",
                                                    "param:5.1.1:approval_limits"]


def test_another_version_can_be_drawn_and_an_unknown_one_is_refused(lib):
    other = PolicyGraph.from_db(lib, "2.6")
    assert other.version == "2.6" and other.limits()[1]["Manager"] == 150000
    assert any(e["source"] == "version:2.5" and e["kind"] == "changes" for e in other.edges)
    with pytest.raises(ValueError):
        PolicyGraph.from_db(lib, "9.9")


@pytest.mark.parametrize("text, amounts", [
    ("Who approves ₹30 lakh?", [3_000_000]),
    ("a bill for Rs 7,50,000 and another of 1.2 crore", [750_000, 12_000_000]),
    ("95,000 rupees, INR 60,000 and 2500000", [95_000, 60_000, 2_500_000]),
    ("rule 5.1.1 of v2.5 in 2025: 3 invoices within 15% over 7 days", []),     # rules, versions, years, counts
    ("2.4 lakh rupees", [240_000]),
])
def test_amounts_are_read_as_money_and_nothing_else(text, amounts):
    assert parse_amounts(text) == amounts


def test_an_amount_is_routed_to_the_lowest_role_that_may_approve_it(graph):
    def lowest(question):
        return [f.data["lowest"] for f in graph.query(question).facts if f.kind == "routing" and "lowest" in f.data]

    assert lowest("Who has to approve an invoice of ₹30 lakh?") == ["CFO"]
    assert lowest("Is ₹1.2 crore within anyone's limit?") == [None]              # above every limit
    exact = graph.query("Exactly ₹25,00,000 was approved by a Director. Is that within the limit?")
    assert any(f.data == {"amount": 2_500_000, "role": "Director", "allowed": True} for f in exact.facts)  # equal is within
    band = graph.query("Is ₹4,99,000 suspicious and who approves it?")
    assert any(f.kind == "band" and f.data["clause"] == "4.1.2" and f.data["role"] == "Senior Manager" for f in band.facts)
    assert band.passages[0].section.startswith("5.1 ") and band.passages[0].clause_id is None     # the table of limits
    assert any(f.kind == "round" for f in graph.query("Who approves ₹60,000?").facts)            # a multiple of 10,000


def test_what_changed_between_versions(graph):
    found = graph.query("What changed between version 2.5 and 2.6?")
    assert {(f.data["clause"], f.data["role"], f.data["from"], f.data["to"]) for f in found.facts if f.kind == "change"} == {
        ("2.1.1", None, 1.0, 5.0), ("4.1.1", None, 3, 5), ("5.1.1", "Manager", 100000, 150000)}
    cited = {(p.clause_id or p.section.split()[0], p.version) for p in found.passages}
    assert cited >= {("2.1.1", "2.5"), ("2.1.1", "2.6"), ("4.1.1", "2.5"), ("4.1.1", "2.6"), ("5.1", "2.6")}
    assert len(found.passages) == 6 and ("5.1", "2.5") not in cited     # the older table falls past the six (docs/POLICY_GRAPH.md)
    same = graph.query("Did version 2.6 change the weekend rule?")
    assert [f.data for f in same.facts if f.kind == "change"] == [{"clause": "4.2.1", "unchanged": True, "from_version": "2.5"}]
    assert {p.version for p in same.passages if p.clause_id == "4.2.1"} == {"2.5", "2.6"}


def test_sets_of_rules_and_the_remit_of_an_agent(graph):
    critical = graph.query("List the critical rules").facts
    assert any(f.data.get("members") == ["2.2.1", "2.2.2", "4.4.1", "5.1.1"] for f in critical)
    judged = graph.query("Which rules are judged by the agents rather than by code?").facts
    assert any(f.data.get("members") == ["2.1.4", "2.1.5", "2.2.2", "4.1.2"] for f in judged)
    remit = graph.query("Which rules does the Vendor Intelligence agent judge?").facts
    assert remit[0].data == {"agent": "agent:vendor_intelligence", "members": ["4.1.2"]}


def test_ask_ai_is_given_the_facts_and_their_passages_first(lib, graph):
    question = "Who has to approve an invoice of ₹30 lakh?"
    index = PolicyIndex.from_db(lib)
    out = copilot.answer(question, lib, index, None, graph=graph)
    assert out["facts"][0].data == {"amount": 3_000_000, "lowest": "CFO"} and out["passages"][0].section.startswith("5.1 ")
    client = ScriptedClient(lambda messages, temperature, sample: json.dumps({"answer": "A CFO [F1] [1].", "passages_used": [1]}))
    answered = copilot.answer(question, lib, index, client, graph=graph)
    system, user = client.calls[-1]["messages"][0]["content"], client.calls[-1]["messages"][1]["content"]
    assert "The FACTS are read by code" in system and "FACTS\n[F1] Under v2.5" in user and "the lowest role that may approve it is CFO" in user
    assert answered["answer"] == "A CFO [F1] [1]." and answered["sources"][0].section.startswith("5.1 ")
    without = copilot.answer(question, lib, index, None)                 # without the graph, as before
    assert without["facts"] == [] and without["passages"] == index.search(question, k=4)


def test_the_graph_evaluation_scores_every_method_on_every_question(lib):
    queries = graph_eval.load_queries()
    assert {q["split"] for q in queries} == {"dev", "test"} and len({q["id"] for q in queries}) == len(queries)
    graph = PolicyGraph.from_db(lib)
    passages = {(p.clause_id or p.section.split()[0], p.version) for p in graph.passages}
    for q in queries:                                     # every piece of evidence exists in the documents
        assert all((key, version) in passages for key, version in q["evidence"]), q["id"]
    result = graph_eval.evaluate(lib, queries)
    assert result["methods"] == ["lexical", "lexical, all versions", "graph", "graph + lexical"]   # no embedding model
    assert len(result["rows"]) == len(queries) * 4
    assert all(r["derived"] is None for r in result["rows"] if not r["method"].startswith("graph"))
    graph_rows = [r for r in result["rows"] if r["method"] == "graph + lexical"]
    assert sum(r["evidence"] for r in graph_rows) > sum(r["evidence"] for r in result["rows"] if r["method"] == "lexical")
    assert "| graph + lexical | test |" in graph_eval.render(result, queries)
