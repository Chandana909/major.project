"""Tests of the model-assisted reading of policies in their own wording.

The model is a scripted stand-in whose reply is built from the document, so
these tests check what the code does with a reply: what it verifies, what it
holds back, and what a person must confirm. They say nothing about how well a
real model reads a policy; evaluation/policy_llm_eval.py measures that.
"""
from __future__ import annotations

import copy
import json
import re

import pytest

from auditiq import cli, db, policy_extract, policy_ingest, policy_llm, service
from auditiq.graph import PRESETS
from auditiq.llm import LLMSettings, ScriptedClient
from auditiq.policy import derive_policy, load_policy
from auditiq.policy_pdf import write_pdf
from evaluation import policy_llm_eval as study

BASE = load_policy("2.5").registry
STRICT = study.POLICIES["strict"]
SENTENCE_START = re.compile(r"\.\s(?=[A-Z(])")


def document(tmp_path, style: str, version: str = "5.9", overrides: dict = STRICT):
    intended = derive_policy(BASE, version, "2026-04-01", overrides)
    pdf = write_pdf(study.render(style, intended), tmp_path / f"{style}_v{version}.pdf",
                    f"{study.STYLES[style]}, version {version}", f"{study.STYLES[style]} | version {version}")
    return intended, pdf


def passage(text: str, anchor: str) -> str:
    """The sentence of the document that contains ``anchor``, word for word."""
    at = text.casefold().index(anchor)
    starts = [m.end() for m in SENTENCE_START.finditer(text, 0, at)]
    end = SENTENCE_START.search(text, at)
    return text[starts[-1] if starts else 0: end.start() + 1 if end else len(text)].strip()


def right_reply(pdf, style: str, intended: dict) -> dict:
    """What a model that reads the document correctly would return."""
    pages, _ = policy_llm.document_pages(pdf)
    return {"version": intended["version"],
            "rules": [{"clause": clause, "quotes": [passage(pages[0], study.ANCHORS[style][clause][0])],
                       "values": copy.deepcopy(spec["params"])} for clause, spec in intended["clauses"].items()]}


def client_for(reply) -> ScriptedClient:
    return ScriptedClient(lambda messages, temperature, sample: reply if isinstance(reply, str) else json.dumps(reply))


def test_numbers_are_recognised_in_the_forms_a_policy_writes_them():
    assert policy_llm.indian(100000) == "1,00,000" and policy_llm.indian(12500000) == "1,25,00,000"
    assert policy_llm.indian(999) == "999" and policy_llm.indian(50000) == "50,000"
    quote = policy_llm.normalize("limit of Rs. 1,00,000; at most three invoices; 0.5 per cent; codes 01 to 37; 150 days")
    assert all(policy_llm.stated(v, quote) for v in (100000, 3, 0.5, 1, 37))
    assert not policy_llm.stated(15, quote)                      # 150 is not 15
    assert not policy_llm.stated(5, quote)                       # 0.5 is not 5
    assert not policy_llm.stated(1, policy_llm.normalize("invoices of one vendor on the same day"))   # "one" is a word
    assert policy_llm.stated(500000, policy_llm.normalize("up to 5 lakh rupees"))
    assert policy_llm.stated(["Saturday", "Sunday"], policy_llm.normalize("closed on Saturdays and Sundays"))
    assert policy_llm.stated({"Manager": 50000}, policy_llm.normalize("a Manager up to INR 50,000"))
    assert not policy_llm.stated({"Director": 50000}, policy_llm.normalize("a Manager up to INR 50,000"))


@pytest.mark.parametrize("style", list(study.STYLES))
def test_a_correct_reading_is_verified_in_full_and_gives_the_intended_policy(tmp_path, style):
    intended, pdf = document(tmp_path, style)
    assert len(policy_extract.build(pdf, BASE).problems) >= 16           # the template reader cannot read this wording
    proposal = policy_llm.propose(pdf, BASE, client_for(right_reply(pdf, style, intended)))
    assert proposal.problems == [] and proposal.version == "5.9" and proposal.pages == 1
    assert all(rule["located"] for rule in proposal.rules.values()) and len(proposal.rules) == 16
    assert [i["status"] for i in proposal.items] == [policy_llm.VERIFIED] * 11
    values, still_open = policy_llm.decide(proposal, accept_verified=True)
    assert still_open == [] and values == {k: v["params"] for k, v in intended["clauses"].items() if v["params"]}
    counts = study.score(proposal, intended, style)["counts"]
    assert counts["right_verified"] == counts["values"] == 14 and counts["right_passage"] == 16
    assert counts["policy_correct_after_confirmation"]
    # The model is shown the rules and the document, and no threshold of the reference version.
    user = policy_llm.messages(policy_llm.document_pages(pdf)[0], BASE)[1]["content"]
    rules = user.split("\nRULES\n")[1].split("\nPOLICY DOCUMENT\n")[0]
    assert "[page 1]" in user and rules.count("\n- ") + 1 == 16
    assert not re.search(r"\d", re.sub(r"- \d\.\d\.\d:", "", rules)) and "Suspended" not in rules


def test_what_the_document_does_not_state_is_held_back(tmp_path):
    intended, pdf = document(tmp_path, "memo")
    reply = right_reply(pdf, "memo", intended)
    by_clause = {r["clause"]: r for r in reply["rules"]}
    by_clause["2.1.1"]["values"]["amount_tolerance_pct"] = 2.0                       # the document says 0.5
    by_clause["4.1.1"]["quotes"] = ["No supplier may present more than 9 bills on a day."]   # not in the document
    by_clause["4.2.1"]["values"]["non_business_days"] = ["Funday"]
    by_clause["5.1.1"]["values"]["approval_limits"].pop("CFO")
    del by_clause["4.3.1"]["values"]["round_amount_multiple"]
    reply["rules"].append({"clause": "9.9.9", "quotes": ["anything"], "values": {}})  # not a rule of the system
    proposal = policy_llm.propose(pdf, BASE, client_for(reply))

    status = {(i["clause"], i["parameter"]): (i["status"], i["reason"]) for i in proposal.items}
    assert status[("2.1.1", "amount_tolerance_pct")] == (policy_llm.ATTENTION, "the value is not written in the quoted text")
    assert status[("4.1.1", "max_invoices_per_vendor_per_day")] == (
        policy_llm.ATTENTION, "no quote of the rule was found in the document")
    assert status[("4.2.1", "non_business_days")] == (policy_llm.ATTENTION, "'Funday' is not a day of the week")
    assert status[("5.1.1", "approval_limits")] == (policy_llm.ATTENTION, "no limit for CFO")
    assert status[("4.3.1", "round_amount_multiple")] == (policy_llm.MISSING, "the model gave no value")
    assert status[("3.1.1", "gstin_length")] == (policy_llm.VERIFIED, "")
    assert proposal.problems == ["Rule 4.1.1 (same-day splitting): no passage of the document was located for it"]
    assert "9.9.9" not in proposal.rules

    counts = study.score(proposal, intended, "memo")["counts"]
    assert (counts["wrong_caught"], counts["wrong_passed"], counts["missing"]) == (2, 0, 2)   # 2.0, Funday; CFO, round
    assert counts["located"] == 15 and counts["policy_correct_after_confirmation"]       # nothing wrong got through
    _, still_open = policy_llm.decide(proposal, accept_verified=True)
    assert len(still_open) == 5 and all("supply the value" in line for line in still_open)


def test_a_reply_that_cannot_be_read_proposes_nothing(tmp_path):
    intended, pdf = document(tmp_path, "handbook")
    proposal = policy_llm.propose(pdf, BASE, client_for("I am sorry, I cannot read this document."))
    assert proposal.problems[0] == "the model's reply could not be read" and len(proposal.problems) == 17
    assert {i["status"] for i in proposal.items} == {policy_llm.MISSING}


def test_nothing_is_stored_without_a_named_person_and_a_value_for_every_parameter(lib, tmp_path):
    intended, pdf = document(tmp_path, "handbook")
    reply = right_reply(pdf, "handbook", intended)
    next(r for r in reply["rules"] if r["clause"] == "4.3.1")["values"]["round_amount_multiple"] = 9000   # not the document's
    proposal = policy_llm.propose(pdf, BASE, client_for(reply))
    reference = db.read_policy(lib).registry

    values, still_open = policy_llm.decide(proposal)                               # nothing confirmed yet
    assert values == {} and len(still_open) == 11
    values, still_open = policy_llm.decide(proposal, accept_verified=True)
    assert still_open == ["Rule 4.3.1 round_amount_multiple: the value is not written in the quoted text; supply the value"]
    refused = policy_llm.adopt(lib, pdf, proposal, reference, values, reviewer="A. Auditor")
    assert not refused["adopted"] and refused["problems"] == ["no confirmed value for 4.3.1.round_amount_multiple"]
    values, still_open = policy_llm.decide(proposal, accept_verified=True, overrides={("4.3.1", "round_amount_multiple"): 5000})
    assert still_open == []
    assert not policy_llm.adopt(lib, pdf, proposal, reference, values, reviewer=" ")["adopted"]
    assert lib.scalar("SELECT COUNT(*) FROM company_policies WHERE version = '5.9'") == 0

    report = policy_llm.adopt(lib, pdf, proposal, reference, values, reviewer="A. Auditor", activate=True)
    assert report["adopted"] and report["values_supplied_by_the_person"] == ["4.3.1.round_amount_multiple"]
    stored = db.read_policy(lib)
    assert stored.version == "5.9" and stored.clauses == intended["clauses"]
    assert stored.registry["adoption"]["confirmed_by"] == "A. Auditor"
    assert stored.registry["adoption"]["model"] == "scripted-test-double"
    assert "Procure-to-Pay Compliance Handbook" in stored.text and "sanctioning limit of a Manager" in stored.text
    assert not policy_llm.adopt(lib, pdf, proposal, reference, values, reviewer="A. Auditor")["adopted"]   # version exists

    # Findings under the adopted policy cite the organisation's own document.
    citations = policy_ingest.clause_citations(lib, "5.9")
    assert len(citations) == 16 and citations["5.1.1"]["document"] == pdf.name and citations["5.1.1"]["page"] == 1
    invoice_id = lib.scalar(
        "SELECT i.invoice_id FROM invoices i JOIN approval_logs a ON a.transaction_id = i.invoice_id "
        "JOIN benchmark_labels l ON l.invoice_id = i.invoice_id WHERE a.action_taken = 'Approved' "
        "AND a.approver_role = 'Manager' AND i.amount > 60000 AND i.amount < 90000 AND l.label = 'clean' "
        "ORDER BY i.invoice_id")
    service.audit_invoices(lib, PRESETS["C1"], db.read_policy(lib), None, [invoice_id])
    flags = json.loads(db.latest_result(lib, invoice_id)["audit_pack"])["flags"]
    assert [(f["clause"], f["citation"]["document"]) for f in flags] == [("5.1.1", pdf.name)]


def test_the_reviewer_can_give_the_passage_of_a_rule_the_model_did_not_quote(lib, tmp_path):
    intended, pdf = document(tmp_path, "handbook")
    reply = right_reply(pdf, "handbook", intended)
    limits = next(r for r in reply["rules"] if r["clause"] == "5.1.1")
    real = limits["quotes"][0]
    limits["quotes"] = ["Managers may sanction up to fifty thousand rupees."]          # paraphrased, not in the document
    proposal = policy_llm.propose(pdf, BASE, client_for(reply))
    assert not proposal.rules["5.1.1"]["located"] and proposal.item("5.1.1", "approval_limits")["status"] == policy_llm.ATTENTION
    assert proposal.problems == ["Rule 5.1.1 (approval limit): no passage of the document was located for it"]

    assert policy_llm.add_passages(proposal, {"5.1.1": "The limits are set by the board."}) == ["5.1.1"]   # not in it
    assert policy_llm.add_passages(proposal, {"5.1.1": real}) == []
    assert proposal.problems == [] and proposal.rules["5.1.1"]["by_person"]
    assert proposal.item("5.1.1", "approval_limits")["status"] == policy_llm.VERIFIED       # the model's values, now checked
    values, still_open = policy_llm.decide(proposal, accept_verified=True)
    assert still_open == []
    report = policy_llm.adopt(lib, pdf, proposal, db.read_policy(lib).registry, values, reviewer="A. Auditor")
    assert report["adopted"] and report["values_supplied_by_the_person"] == ["passage of 5.1.1"]
    assert policy_ingest.clause_citations(lib, "5.9")["5.1.1"]["text"] == real


def test_the_adopt_command_shows_the_proposal_and_waits_for_confirmation(sqlite_library, tmp_path, capsys, monkeypatch):
    intended, pdf = document(tmp_path, "memo", version="6.1")
    reply = right_reply(pdf, "memo", intended)
    monkeypatch.setattr(cli.LLMSettings, "from_env", classmethod(lambda cls, *a, **k: LLMSettings("http://none", "scripted")))
    monkeypatch.setattr(cli, "OpenAIChatClient", lambda settings, cache: client_for(reply))
    monkeypatch.setattr(cli, "ResponseCache", lambda: None)

    assert cli.main(["--db", sqlite_library, "policy", "adopt", str(pdf), "--llm"]) == 1
    out = capsys.readouterr().out
    assert "amount_tolerance_pct" in out and "verified" in out and "not adopted" in out and "waiting for confirmation" in out
    assert cli.main(["--db", sqlite_library, "policy", "adopt", str(pdf), "--llm", "--accept-verified"]) == 1   # no name
    capsys.readouterr()
    assert cli.main(["--db", sqlite_library, "policy", "adopt", str(pdf), "--llm", "--accept-verified",
                     "--reviewer", "A. Auditor", "--activate"]) == 0
    assert "adopted as policy version 6.1 (16 rules), confirmed by A. Auditor; now the active version" in capsys.readouterr().out
    conn = db.connect(sqlite_library)
    assert db.read_policy(conn).clauses == intended["clauses"]
    conn.close()
