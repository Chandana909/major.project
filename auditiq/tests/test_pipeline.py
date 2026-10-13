"""Tests of the LLM stages and of the LangGraph pipeline.

The model is replaced by a scripted stand-in, so these tests check the
pipeline's logic (what is asked, how replies are parsed, how flags are scored).
They say nothing about how well a real model audits.
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
from datetime import date, timedelta
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from test_controls import clean_txn

from auditiq import agents, prompts
from auditiq.audit_pack import render_markdown
from auditiq.cli import main as cli_main
from auditiq.extraction import extract
from auditiq.graph import PRESETS, build_graph, in_sample, preset, to_result
from auditiq.llm import ScriptedClient
from auditiq.policy import load_policy
from evaluation import run_config

POLICY = load_policy("2.5")
ROOT = Path(__file__).resolve().parents[1]
REMARK = "5 pieces rejected at QC and returned to the vendor."


def section(user: str, before: str) -> str:
    """The part of a user message above the line that consists of the heading ``before``."""
    lines = user.splitlines()
    return "\n".join(lines[: lines.index(before)])


def stage_of(messages: list[dict]) -> str:
    task = section(messages[1]["content"], before=prompts.RECORDS_HEADING)
    for name, spec in agents.AGENTS.items():
        if spec.title in task:
            return name
    return "challenger" if "You are the challenger" in task else "single_auditor"


def scripted(replies: dict) -> ScriptedClient:
    """``replies[stage]`` is a reply, or a function (temperature, sample, messages) -> reply.

    A stage without an entry finds nothing. Replies may be Python objects.
    """
    def responder(messages, temperature, sample):
        stage = stage_of(messages)
        reply = replies.get(stage, {"verdicts": []} if stage == "challenger" else {"flags": []})
        if callable(reply):
            reply = reply(temperature, sample, messages)
        return reply if isinstance(reply, str) else json.dumps(reply)
    return ScriptedClient(responder)


def run(config_name: str, txn: dict, replies: dict, **changes) -> tuple[dict, ScriptedClient]:
    client = scripted(replies)
    config = preset(config_name, **changes)
    state = build_graph(config, POLICY, client).invoke({"txn": txn})
    return to_result(state, config, POLICY, client.model), client


def short_delivery_txn() -> dict:
    t = clean_txn()
    t["grn"]["notes"] = REMARK
    return t


J4_FLAG = {"clause": "2.1.4", "explanation": "The remark records 5 rejected pieces but 50 are billed.",
           "evidence": [{"field": "grn.notes", "value": REMARK}, {"field": "invoice.quantity", "value": 50}]}


# ------------------------------------------------------------ configurations
def test_graph_of_each_configuration_contains_exactly_its_stages():
    def nodes(name):
        client = scripted({}) if PRESETS[name].agents != "none" else None
        return {n for n in build_graph(PRESETS[name], POLICY, client).get_graph().nodes if not n.startswith("__")}
    common = {"confidence", "risk_score", "write_audit_pack"}
    specialists = set(agents.AGENTS)
    assert nodes("C1") == common | {"controls"}
    assert nodes("C2") == common | {"single_auditor"}
    assert nodes("C3") == common | {"controls"} | specialists
    assert nodes("C4") == nodes("C5") == common | {"controls", "challenger"} | specialists


def test_remits_are_the_judgement_clauses_of_each_agents_sections():
    remits = {name: agents.remit(spec, POLICY) for name, spec in agents.AGENTS.items()}
    assert remits == {"math_approvals": ["2.1.4", "2.1.5"], "tax_identity": ["2.2.2"],
                      "vendor_intelligence": ["4.1.2"]}
    covered = sorted(k for clauses in remits.values() for k in clauses)
    assert covered == sorted(POLICY.clause_ids("judgement"))          # every judgement clause, once


def test_a_configuration_with_agents_needs_a_client_and_review_needs_a_checkpointer():
    with pytest.raises(ValueError, match="needs an LLM client"):
        build_graph(PRESETS["C3"], POLICY, None)
    with pytest.raises(ValueError, match="checkpointer"):
        build_graph(preset("C1", review=True), POLICY, None)
    with pytest.raises(ValueError, match="at least one re-run"):
        build_graph(preset("C5", reruns=0), POLICY, scripted({}))


def test_c1_needs_no_model():
    t = clean_txn()
    t["invoice"]["amount"] = t["po"]["amount"] = 50000
    state = build_graph(PRESETS["C1"], POLICY).invoke({"txn": t})
    assert [f["clause"] for f in state["flags"]] == ["4.3.1"] and state.get("calls", []) == []
    assert state["score"]["route"] == "approve"


# ------------------------------------------------------------------- stages
def test_c3_adds_the_agent_flag_and_scores_by_count():
    result, client = run("C3", short_delivery_txn(), {"math_approvals": {"flags": [J4_FLAG]}})
    [flag] = result["flags"]
    assert (flag["clause"], flag["severity"], flag["source"], flag["agent"]) == ("2.1.4", "high", "L", "math_approvals")
    assert (flag["g"], flag["p"], flag["a"], flag["confidence"]) == (1, 1, None, None)
    assert (result["r0"], result["rc"], result["route"]) == (50, 50, "escalate")
    assert result["cost"]["llm_calls"] == 3 and all(c["temperature"] == 0 for c in client.calls)


def test_c4_the_challenger_removes_a_flag_and_is_not_called_without_agent_flags():
    remove = {"verdicts": [{"id": 1, "verdict": "remove", "reason": "The remark confirms full acceptance."}]}
    result, _ = run("C4", short_delivery_txn(), {"math_approvals": {"flags": [J4_FLAG]}, "challenger": remove})
    assert result["flags"] == [] and result["route"] == "approve" and result["cost"]["llm_calls"] == 4
    assert result["removed_flags"][0]["removal_reason"] == "The remark confirms full acceptance."

    result, client = run("C4", clean_txn(), {})
    assert result["cost"]["llm_calls"] == 3 and "challenger" not in {stage_of(c["messages"]) for c in client.calls}


def test_the_challenger_cannot_remove_a_control_flag_and_keeps_what_it_does_not_rule_on():
    t = short_delivery_txn()
    t["invoice"]["amount"] = t["po"]["amount"] = 50000            # control flag 4.3.1
    verdicts = {"verdicts": [{"id": 0, "verdict": "remove"}, {"id": 7, "verdict": "remove"},
                             {"id": "x", "verdict": "remove"}, "remove everything"]}
    result, _ = run("C4", t, {"math_approvals": {"flags": [J4_FLAG]}, "challenger": verdicts})
    assert sorted(f["clause"] for f in result["flags"]) == ["2.1.4", "4.3.1"] and result["removed_flags"] == []


def test_c5_agreement_is_the_share_of_reruns_that_cite_the_clause_again():
    def math_agent(temperature, sample, _):
        return {"flags": [J4_FLAG]} if temperature == 0 or sample in (1, 2) else {"flags": []}
    result, client = run("C5", short_delivery_txn(), {"math_approvals": math_agent})
    [flag] = result["flags"]
    assert (flag["g"], flag["p"]) == (1, 1) and math.isclose(flag["a"], 2 / 3)
    assert math.isclose(flag["confidence"], 8 / 9)
    assert (result["r0"], result["rc"], result["route"]) == (50, 50, "escalate")     # 17.8, raised by the floor
    reruns = [c for c in client.calls if c["temperature"] > 0]
    assert sorted(c["sample"] for c in reruns) == [1, 2, 3] and {c["temperature"] for c in reruns} == {0.7}
    assert {stage_of(c["messages"]) for c in reruns} == {"math_approvals"}            # only the originating agent
    assert result["cost"]["llm_calls"] == 3 + 1 + 3


def test_the_worked_illustration_of_the_paper_through_the_graph():
    """A control flag and a weakly supported critical agent flag: escalated by count, sampled by confidence."""
    t = clean_txn()
    t["invoice"]["amount"] = t["po"]["amount"] = 50000            # round amount: 4.3.1, a control flag
    near_duplicate = {"clause": "2.2.2", "explanation": "Same amount under a re-keyed number.",
                      "evidence": [{"field": "history.INV49999.invoice_number", "value": "ABC/25-26/123"}]}
    replies = {"tax_identity": lambda temperature, sample, _:
               {"flags": [near_duplicate]} if temperature == 0 or sample == 1 else {"flags": []}}
    c4, _ = run("C4", t, replies)
    c5, _ = run("C5", t, replies)
    assert (c4["r0"], c4["route"]) == (70, "escalate")
    agent_flag = next(f for f in c5["flags"] if f["source"] == "L")
    assert (agent_flag["g"], agent_flag["p"]) == (0, 1) and math.isclose(agent_flag["a"], 1 / 3)
    assert math.isclose(agent_flag["confidence"], 4 / 9)
    assert c5["r0"] == 70 and math.isclose(c5["rc"], 5 + 30 * 4 / 9) and c5["route"] == "sample"


def test_flags_outside_the_remit_are_discarded_and_an_unknown_clause_is_kept():
    reply = {"flags": [{"clause": "2.1.1", "evidence": []},                 # decided by a control
                       {"clause": "4.1.2", "evidence": []},                 # another agent's remit
                       {"clause": "Rule 9.9.9", "evidence": []},            # not in the policy
                       {"clause": "9.9.9", "evidence": []},                 # the same clause again
                       {"evidence": []}, "2.1.4"]}                          # not flags
    result, _ = run("C3", clean_txn(), {"math_approvals": reply})
    [flag] = result["flags"]
    assert (flag["clause"], flag["severity"], flag["g"], flag["p"]) == ("9.9.9", "medium", 0, 0)
    assert result["issues"] == {"failed_stages": 0, "repaired_replies": 0, "out_of_remit_flags": 2,
                                "malformed_flags": 2}


def test_a_malformed_reply_is_sent_back_once_then_the_stage_fails_without_stopping_the_others():
    attempts = []

    def math_agent(temperature, sample, messages):
        attempts.append(len(messages))
        return "I found one problem with this invoice." if len(messages) == 2 else {"flags": [J4_FLAG]}
    result, _ = run("C3", short_delivery_txn(), {"math_approvals": math_agent})
    assert attempts == [2, 4]                                         # the repair request extends the conversation
    assert [f["clause"] for f in result["flags"]] == ["2.1.4"]
    assert result["issues"]["repaired_replies"] == 1 and result["cost"]["llm_calls"] == 4

    result, _ = run("C3", short_delivery_txn(), {"math_approvals": '{"findings": "none"}',
                                                 "tax_identity": {"flags": []}})
    assert result["flags"] == [] and result["issues"]["failed_stages"] == 1 and result["cost"]["llm_calls"] == 4


def test_the_challenger_sees_the_records_of_the_agents_whose_findings_it_tests():
    near_duplicate = {"clause": "2.2.2", "evidence": [{"field": "history.INV40090.amount", "value": 84250.5}]}
    _, client = run("C4", short_delivery_txn(), {"math_approvals": {"flags": [J4_FLAG]}})
    challenger = next(c for c in client.calls if stage_of(c["messages"]) == "challenger")["messages"][1]["content"]
    assert "GOODS RECEIPT NOTE" in challenger and "PROPOSED FINDINGS" in challenger
    assert "OTHER INVOICES OF THE SAME VENDOR" not in challenger          # no agent that read them raised a finding

    _, client = run("C4", short_delivery_txn(), {"math_approvals": {"flags": [J4_FLAG]},
                                                 "tax_identity": {"flags": [near_duplicate]}})
    challenger = next(c for c in client.calls if stage_of(c["messages"]) == "challenger")["messages"][1]["content"]
    assert "invoice_id | invoice_number | date | amount | po_id | grn_id\n" in challenger   # the tax agent's columns
    assert "GOODS RECEIPT NOTE" in challenger and "VENDOR MASTER RECORD" in challenger


def test_a_challenger_that_gives_no_usable_reply_removes_nothing():
    result, _ = run("C4", short_delivery_txn(), {"math_approvals": {"flags": [J4_FLAG]},
                                                 "challenger": "All findings look fine to me."})
    assert [f["clause"] for f in result["flags"]] == ["2.1.4"] and result["removed_flags"] == []
    assert result["issues"]["failed_stages"] == 1 and result["cost"]["llm_calls"] == 3 + 2


def test_c2_is_one_prompt_over_the_whole_policy_without_controls():
    t = short_delivery_txn()
    t["invoice"]["amount"] = 50000                                    # 2.1.1 and 4.3.1 for a control
    amount = {"clause": "2.1.1", "evidence": [{"field": "invoice.amount", "value": 50000},
                                              {"field": "po.amount", "value": 84250.5}]}
    result, client = run("C2", t, {"single_auditor": {"flags": [amount, J4_FLAG]}})
    assert sorted(f["clause"] for f in result["flags"]) == ["2.1.1", "2.1.4"]      # only what the model reported
    assert all(f["source"] == "L" for f in result["flags"]) and result["cost"]["llm_calls"] == 1
    user = client.calls[0]["messages"][1]["content"]
    assert prompts.CONTROL_HEADING not in user.splitlines() and "OTHER INVOICES OF THE SAME VENDOR" in user


# ------------------------------------------------------------------ prompts
def test_prompt_templates_contain_no_number():
    """Thresholds and rule numbers come from the policy at run time, never from a template."""
    for template in (prompts.SYSTEM, prompts.SPECIALIST_TASK, prompts.SINGLE_TASK, prompts.CHALLENGER_TASK,
                     prompts.REPAIR):
        assert not any(ch.isdigit() for ch in template)


def test_each_agent_sees_the_policy_the_control_findings_and_only_its_records():
    t = short_delivery_txn()
    t["invoice"]["amount"] = t["po"]["amount"] = 50000
    _, client = run("C3", t, {})
    seen = {stage_of(c["messages"]): c["messages"] for c in client.calls}
    for name, messages in seen.items():
        system, user = messages[0]["content"], messages[1]["content"]
        assert POLICY.text.strip() in system and "Rule 4.3.1: Invoice amount 50000.00" in user
        task = section(user, before=prompts.CONTROL_HEADING)
        assert all(f"Rule {k}" in task for k in agents.remit(agents.AGENTS[name], POLICY))
    # One system message for every stage, so that the policy is a shared prompt prefix.
    assert len({messages[0]["content"] for messages in seen.values()}) == 1
    assert "GOODS RECEIPT NOTE" in seen["math_approvals"][1]["content"]
    assert "OTHER INVOICES OF THE SAME VENDOR" not in seen["math_approvals"][1]["content"]
    assert "GOODS RECEIPT NOTE" not in seen["tax_identity"][1]["content"]
    assert "INV40090 | ABC/25-26/00122 | 2025-06-10 | 84250.50" in seen["tax_identity"][1]["content"]


def large_vendor_txn(n: int = 120) -> dict:
    """A vendor with ``n`` other invoices, one per day, the oldest more than three months before the audit."""
    t = clean_txn()
    first = date(2025, 6, 11) - timedelta(days=n)
    t["vendor_history"] = [
        {"invoice_id": f"INV5{i:04d}", "invoice_number": f"ZZ/{9000 + i}", "date": str(first + timedelta(days=i)),
         "amount": 1000.0 + i, "po_id": f"PO5{i:04d}", "grn_id": f"GRN5{i:04d}"} for i in range(n)]
    return t


def test_a_small_vendor_history_is_shown_whole():
    t = clean_txn()
    assert agents.select_history(t, ("duplicates",)) == t["vendor_history"]
    assert "OTHER INVOICES OF THE SAME VENDOR (2; oldest first" in agents.render_records(t, agents.SINGLE)


def test_a_large_vendor_history_is_cut_to_the_invoices_a_fixed_rule_ranks_first():
    t = large_vendor_txn()
    old = t["vendor_history"][:3]
    old[0]["po_id"] = t["invoice"]["po_id"]                       # bills the same purchase order
    old[1]["amount"] = t["invoice"]["amount"]                     # the same amount
    old[2]["invoice_number"] = "ABC/25-26/123"                    # the same number without its leading zeros

    by_duplicate = agents.select_history(t, ("duplicates",))
    assert len(by_duplicate) == agents.HISTORY_CAP
    assert [h["invoice_id"] for h in by_duplicate[:3]] == [h["invoice_id"] for h in old]
    assert by_duplicate == sorted(by_duplicate, key=lambda h: h["date"])               # still oldest first

    by_time = agents.select_history(t, ("time",))
    assert by_time == t["vendor_history"][-agents.HISTORY_CAP:]                        # the nearest in time
    both = agents.select_history(t, ("duplicates", "time"))
    assert {h["invoice_id"] for h in both} == {h["invoice_id"] for h in by_duplicate + by_time}
    assert agents.HISTORY_CAP < len(both) <= 2 * agents.HISTORY_CAP

    # The selection depends on the records only, so a re-run asks the same question.
    assert agents.select_history(t, ("duplicates", "time")) == both
    tax = agents.render_records(t, agents.AGENTS["tax_identity"])
    assert "OTHER INVOICES OF THE SAME VENDOR (the 40 most relevant of 120; oldest first" in tax
    assert old[0]["invoice_id"] in tax and t["vendor_history"][5]["invoice_id"] not in tax
    assert old[0]["invoice_id"] not in agents.render_records(t, agents.AGENTS["vendor_intelligence"])


def test_the_prompt_stays_bounded_for_the_largest_vendor(small_dataset):
    """No prompt of any stage grows with the size of the vendor beyond the cap."""
    transactions = extract(small_dataset)
    largest = max(transactions, key=lambda t: len(t["vendor_history"]))
    typical = min(transactions, key=lambda t: abs(len(t["vendor_history"]) - agents.HISTORY_CAP))
    for spec in (*agents.AGENTS.values(), agents.SINGLE):
        rows = agents.render_records(largest, spec).count("\n")
        assert rows <= agents.render_records(typical, spec).count("\n") + agents.HISTORY_CAP + 12, spec.name


def test_the_policy_swap_changes_the_prompt_without_changing_the_code():
    v26 = load_policy("2.6")
    old = agents.specialist_messages(agents.AGENTS["vendor_intelligence"], POLICY, clean_txn(), [])[0]["content"]
    new = agents.specialist_messages(agents.AGENTS["vendor_intelligence"], v26, clean_txn(), [])[0]["content"]
    assert "POLICY (version 2.5)" in old and "POLICY (version 2.6)" in new
    assert "| Manager | 100,000 |" in old and "| Manager | 150,000 |" in new


# -------------------------------------------------------------- human review
def review_graph(replies: dict, **changes):
    return build_graph(preset("C5", review=True, **changes), POLICY, scripted(replies), checkpointer=InMemorySaver())


def test_an_escalated_invoice_pauses_for_the_reviewer_and_resumes_with_the_decision():
    graph = review_graph({"math_approvals": {"flags": [J4_FLAG]}})
    thread = {"configurable": {"thread_id": "INV40100"}}
    paused = graph.invoke({"txn": short_delivery_txn()}, thread)
    request = paused["__interrupt__"][0].value
    assert request["invoice_id"] == "INV40100" and request["route"] == "escalate" and "audit_pack" not in paused
    done = graph.invoke(Command(resume={"decision": "reject", "reviewer": "A. Auditor",
                                        "justification": "Short delivery confirmed with the stores."}), thread)
    pack = done["audit_pack"]
    assert pack["review"] == {"queue": "escalate", "decision": "reject", "reviewer": "A. Auditor",
                              "justification": "Short delivery confirmed with the stores."}
    text = render_markdown(pack)
    assert "Route: **escalate**" in text and "Rule 2.1.4, receipt remarks" in text
    assert "reproduced by re-runs: 1.00" in text and "Decision: reject" in text


def test_an_approved_invoice_does_not_pause():
    graph = review_graph({})
    done = graph.invoke({"txn": clean_txn()}, {"configurable": {"thread_id": "t"}})
    assert "__interrupt__" not in done and done["audit_pack"]["review"] == {"decision": "auto_approved"}
    assert "No exception was found." in render_markdown(done["audit_pack"])


def test_the_sampled_queue_is_reviewed_at_the_configured_rate():
    weak = {"clause": "2.2.2", "evidence": []}                        # critical, never reproduced: c = 1/3
    replies = {"tax_identity": lambda temperature, sample, _: {"flags": [weak] if temperature == 0 else []}}
    never = review_graph(replies, sample_rate=0.0).invoke({"txn": clean_txn()}, {"configurable": {"thread_id": "a"}})
    assert never["score"]["route"] == "sample" and never["audit_pack"]["review"] == {"decision": "not_sampled"}
    always = review_graph(replies, sample_rate=1.0).invoke({"txn": clean_txn()}, {"configurable": {"thread_id": "b"}})
    assert always["__interrupt__"][0].value["route"] == "sample"
    share = sum(in_sample(f"INV{n}", 0.25) for n in range(40000, 44000)) / 4000
    assert 0.22 < share < 0.28 and in_sample("INV40001", 0.25) == in_sample("INV40001", 0.25)


# ----------------------------------------------------- property of the design
def test_confidence_weighting_never_changes_which_invoices_are_approved():
    """C4 and C5 on the same replies: identical approved sets, and Rc <= R0 (Section IV-C)."""
    def pick(seed: str, options: list):
        return options[int(hashlib.sha256(seed.encode()).hexdigest(), 16) % len(options)]

    def agent(name: str, clause: str):
        def reply(temperature, sample, messages):
            invoice = json.loads(messages[1]["content"].split("INVOICE UNDER AUDIT\n")[1].split("\n")[0])
            key = f"{name}-{invoice['invoice_id']}"
            if pick(key, [True, False, False]) is False:
                return {"flags": []}
            if temperature > 0 and pick(f"{key}-{sample}", [True, False]) is False:
                return {"flags": []}
            evidence = pick(key + "e", [[{"field": "invoice.amount", "value": invoice["amount"]}],
                                        [{"field": "invoice.amount", "value": -1}], []])
            return {"flags": [{"clause": pick(key + "c", [clause, clause, "9.9.9"]), "evidence": evidence}]}
        return reply

    replies = {"math_approvals": agent("m", "2.1.5"), "tax_identity": agent("t", "2.2.2"),
               "vendor_intelligence": agent("v", "4.1.2"),
               "challenger": lambda temperature, sample, messages: {"verdicts": [
                   {"id": 1, "verdict": pick(messages[1]["content"][-200:], ["keep", "keep", "remove"])}]}}
    routes = {"approve": 0, "sample": 0, "escalate": 0}
    for n in range(240):
        t = clean_txn()
        t["invoice"]["invoice_id"] = f"INV{50000 + n}"
        if n % 5 == 0:
            t["invoice"]["amount"] = t["po"]["amount"] = 50000         # low control flag
        if n % 7 == 0:
            t["invoice"]["date"] = "2025-06-14"                        # medium control flag
        c4, _ = run("C4", t, replies)
        c5, _ = run("C5", t, replies)
        assert {f["clause"] for f in c4["flags"]} == {f["clause"] for f in c5["flags"]}
        assert c5["r0"] == c4["r0"] and c5["rc"] <= c5["r0"] + 1e-9
        assert (c5["route"] == "approve") == (c4["route"] == "approve")
        assert c4["route"] != "sample"
        routes[c5["route"]] += 1
    assert min(routes.values()) >= 10, routes          # the property was exercised on all three routes


# ------------------------------------------------------------ project layout
def imported_packages(folder: str) -> set[str]:
    found = set()
    for path in (ROOT / folder).rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return found


def test_the_pipeline_and_the_benchmark_generator_share_no_code():
    assert not {"auditiq_bench", "evaluation"} & imported_packages("auditiq")
    assert not {"auditiq", "evaluation"} & imported_packages("auditiq_bench")


# ----------------------------------------------------------------- runners
def test_run_config_writes_one_prediction_per_invoice_and_resumes(tmp_path):
    transactions = []
    for n in range(6):
        t = short_delivery_txn() if n % 2 else clean_txn()
        t["invoice"]["invoice_id"] = f"INV{60000 + n}"
        transactions.append(t)
    replies = {"math_approvals": lambda temperature, sample, messages:
               {"flags": [J4_FLAG] if REMARK in messages[1]["content"] else []}}
    out = tmp_path / "C4.jsonl"
    first = scripted(replies)
    results = run_config.run(transactions[:4], PRESETS["C4"], POLICY, first, out, workers=3, progress=False)
    assert [r["invoice_id"] for r in results] == [f"INV{60000 + n}" for n in range(4)]
    second = scripted(replies)
    results = run_config.run(transactions, PRESETS["C4"], POLICY, second, out, workers=3, progress=False)
    assert len(results) == 6 and len(out.read_text(encoding="utf-8").splitlines()) == 6
    assert len(second.calls) == 3 + 4                  # only the two new invoices were audited
    summary = run_config.summarize(results)
    assert (summary["invoices"], summary["invoices_flagged"], summary["agent_flags"]) == (6, 3, 3)
    assert summary["routes"] == {"approve": 3, "escalate": 3} and summary["llm_calls"] == 6 * 3 + 3


def test_cli_audits_an_invoice_with_the_controls_only_configuration(capsys, small_dataset):
    assert cli_main(["audit", "--dataset", str(small_dataset), "--invoice", "INV40001",
                     "--config", "C1"]) == 0
    out = capsys.readouterr().out
    assert "# Audit pack: INV40001" in out and "Policy version applied: 2.5" in out
    assert cli_main(["audit", "--dataset", str(small_dataset), "--invoice", "INV00000",
                     "--config", "C1"]) == 2
    assert cli_main(["graph", "--config", "C5", "--review"]) == 0
    assert "human_review" in capsys.readouterr().out
