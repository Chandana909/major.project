"""The audit pipeline as a LangGraph state graph.

    extraction -> controls -> three specialist agents (in parallel) -> challenger
               -> confidence -> risk score and route -> human review -> audit pack

The six configurations of the paper are six graphs built from the same node
functions; a configuration leaves nodes out, it does not change them.

    C1  controls only
    C2  single LLM prompt, no controls, no challenger
    C3  controls + specialists, count-based score
    C4  C3 + challenger
    C5  C4 + confidence-weighted score and sampled review

(C0, the classical detectors, is not a pipeline; see evaluation/run_c0.py.)
"""
from __future__ import annotations

import hashlib
import operator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from . import agents, scoring
from .audit_pack import build_pack
from .controls import run_controls
from .llm import ChatClient
from .policy import Policy


@dataclass(frozen=True)
class PipelineConfig:
    name: str
    controls: bool = True
    agents: str = "specialists"       # "none", "single" or "specialists"
    challenger: bool = True
    confidence: bool = True           # features E2 and E3
    reruns: int = 3                   # m, the number of agreement re-runs
    temperature: float = 0.0
    rerun_temperature: float = 0.7
    review: bool = False              # pause escalated transactions for a human reviewer
    sample_rate: float = 1.0          # rho, the reviewed share of the sampled-review queue


PRESETS: dict[str, PipelineConfig] = {
    "C1": PipelineConfig("C1", agents="none", challenger=False, confidence=False),
    "C2": PipelineConfig("C2", controls=False, agents="single", challenger=False, confidence=False),
    "C3": PipelineConfig("C3", challenger=False, confidence=False),
    "C4": PipelineConfig("C4", confidence=False),
    "C5": PipelineConfig("C5"),
}


def preset(name: str, **changes) -> PipelineConfig:
    return replace(PRESETS[name], **changes)


class AuditState(TypedDict, total=False):
    txn: dict
    control_flags: list[dict]
    proposed: Annotated[list[dict], operator.add]     # agent flags, before the challenger
    kept: list[dict]
    removed: list[dict]
    flags: list[dict]                                 # final flags, with confidence terms
    score: dict
    review: dict
    audit_pack: dict
    calls: Annotated[list[dict], operator.add]        # one cost record per LLM call
    notes: Annotated[list[dict], operator.add]        # discarded flags and failed calls


def in_sample(invoice_id: str, rate: float) -> bool:
    """Deterministic selection of a share ``rate`` of the sampled-review queue."""
    draw = int(hashlib.sha256(invoice_id.encode("utf-8")).hexdigest()[:8], 16) / 2 ** 32
    return draw < rate


def build_graph(config: PipelineConfig, policy: Policy, client: ChatClient | None = None, *,
                checkpointer=None, options: scoring.ScoringOptions | None = None):
    """Compile the graph of one configuration.

    ``client`` may be None only when the configuration has no LLM stage.
    ``checkpointer`` is required when ``config.review`` is set.
    """
    if config.agents not in ("none", "single", "specialists"):
        raise ValueError(f"unknown agents setting {config.agents!r}")
    if config.agents != "none" and client is None:
        raise ValueError(f"configuration {config.name} needs an LLM client")
    if config.agents == "none" and not config.controls:
        raise ValueError("a configuration needs controls or agents")
    if config.review and checkpointer is None:
        raise ValueError("human review needs a checkpointer to pause and resume")
    if config.confidence and config.agents != "none" and config.reruns < 1:
        raise ValueError("the agreement term needs at least one re-run")

    clauses = policy.clauses
    options = replace(options or scoring.ScoringOptions(), use_confidence=config.confidence)
    specialists = [s for s in agents.AGENTS.values() if agents.remit(s, policy)] \
        if config.agents == "specialists" else []
    model = getattr(client, "model", None)

    # ------------------------------------------------------------- nodes
    def controls_node(state: AuditState) -> dict:
        found = run_controls(state["txn"], clauses)
        return {"control_flags": [scoring.normalize_flag(f, clauses) for f in found]}

    def agent_update(name: str, out: dict) -> dict:
        note = {"stage": "agent", "agent": name, "failed": out["failed"], **out["dropped"]}
        return {"proposed": out["flags"], "calls": out["calls"], "notes": [note]}

    def specialist_node(spec: agents.AgentSpec):
        def node(state: AuditState) -> dict:
            out = agents.run_specialist(client, spec, policy, state["txn"], state.get("control_flags", []),
                                        temperature=config.temperature)
            return agent_update(spec.name, out)
        return node

    def single_node(state: AuditState) -> dict:
        out = agents.run_single(client, policy, state["txn"], temperature=config.temperature)
        return agent_update(agents.SINGLE.name, out)

    def challenger_node(state: AuditState) -> dict:
        out = agents.run_challenger(client, policy, state["txn"], state.get("control_flags", []),
                                    state.get("proposed", []), temperature=config.temperature)
        return {"kept": out["kept"], "removed": out["removed"], "calls": out["calls"],
                "notes": [{"stage": "challenger", "failed": out["failed"]}] if out["calls"] else []}

    def rerun(agent_name: str, txn: dict, control_flags: list[dict], sample: int) -> dict:
        if agent_name == agents.SINGLE.name:
            return agents.run_single(client, policy, txn, temperature=config.rerun_temperature,
                                     sample=sample, stage="rerun")
        return agents.run_specialist(client, agents.AGENTS[agent_name], policy, txn, control_flags,
                                     temperature=config.rerun_temperature, sample=sample, stage="rerun")

    def confidence_node(state: AuditState) -> dict:
        txn, control_flags = state["txn"], state.get("control_flags", [])
        agent_flags = state["kept"] if "kept" in state else state.get("proposed", [])
        calls, cited = [], {}
        if config.confidence and agent_flags:
            # Agreement: re-run each originating agent m times and count how often
            # it cites the same clause again.
            names = sorted({f["agent"] for f in agent_flags})
            jobs = [(name, k) for name in names for k in range(1, config.reruns + 1)]
            with ThreadPoolExecutor(max_workers=min(len(jobs), 6)) as pool:
                outs = list(pool.map(lambda job: rerun(job[0], txn, control_flags, job[1]), jobs))
            for (name, _), out in zip(jobs, outs):
                calls += out["calls"]
                cited.setdefault(name, []).append({f["clause"] for f in out["flags"]})
        final = [{**f, "confidence": 1.0} for f in control_flags]
        for f in agent_flags:
            terms = {"g": scoring.grounding(f, txn), "p": scoring.clause_validity(f, clauses),
                     "a": None, "confidence": None}
            if config.confidence:
                runs = cited[f["agent"]]
                agreement = sum(f["clause"] in run for run in runs) / len(runs)
                c = scoring.confidence(f, txn, clauses, agreement, options)
                terms.update(a=c["a"], confidence=c["c"])
            final.append({**f, **terms})
        return {"flags": final, "calls": calls}

    def score_node(state: AuditState) -> dict:
        return {"score": scoring.score(state["flags"], options)}

    def review_node(state: AuditState) -> dict:
        route, invoice_id = state["score"]["route"], state["txn"]["invoice"]["invoice_id"]
        if route == "approve":
            return {"review": {"decision": "auto_approved"}}
        if route == "sample" and not in_sample(invoice_id, config.sample_rate):
            return {"review": {"decision": "not_sampled"}}
        decision = interrupt({"invoice_id": invoice_id, "route": route, "score": state["score"],
                              "flags": state["flags"], "removed": state.get("removed", [])})
        return {"review": {"queue": route, **decision}}

    def pack_node(state: AuditState) -> dict:
        return {"audit_pack": build_pack(
            state["txn"], state["flags"], state.get("removed", []), state["score"], state.get("review"),
            clauses, policy_version=policy.version, configuration=config.name, model=model)}

    # ------------------------------------------------------------- edges
    graph = StateGraph(AuditState)
    source = START
    if config.controls:
        graph.add_node("controls", controls_node)
        graph.add_edge(START, "controls")
        source = "controls"

    agent_nodes = []
    for spec in specialists:
        graph.add_node(spec.name, specialist_node(spec))
        agent_nodes.append(spec.name)
    if config.agents == "single":
        graph.add_node(agents.SINGLE.name, single_node)
        agent_nodes.append(agents.SINGLE.name)
    for name in agent_nodes:
        graph.add_edge(source, name)

    graph.add_node("confidence", confidence_node)
    if agent_nodes and config.challenger:
        graph.add_node("challenger", challenger_node)
        graph.add_edge(agent_nodes, "challenger")
        graph.add_edge("challenger", "confidence")
    elif agent_nodes:
        graph.add_edge(agent_nodes, "confidence")
    else:
        graph.add_edge(source, "confidence")

    graph.add_node("risk_score", score_node)
    graph.add_node("write_audit_pack", pack_node)
    graph.add_edge("confidence", "risk_score")
    if config.review:
        graph.add_node("human_review", review_node)
        graph.add_edge("risk_score", "human_review")
        graph.add_edge("human_review", "write_audit_pack")
    else:
        graph.add_edge("risk_score", "write_audit_pack")
    graph.add_edge("write_audit_pack", END)
    return graph.compile(checkpointer=checkpointer)


def to_result(state: dict, config: PipelineConfig, policy: Policy, model: str | None = None) -> dict:
    """One prediction record, in the format evaluation/metrics.py reads."""
    calls, notes = state.get("calls", []), state.get("notes", [])
    return {
        "invoice_id": state["txn"]["invoice"]["invoice_id"],
        "config": config.name,
        "policy_version": policy.version,
        "model": model,
        "anomalous": bool(state["flags"]),
        "flags": state["flags"],
        "removed_flags": state.get("removed", []),
        "r0": state["score"]["r0"],
        "rc": state["score"]["rc"],
        "route": state["score"]["route"],
        "cost": {
            "llm_calls": len(calls),
            "prompt_tokens": sum(c["prompt_tokens"] for c in calls),
            "completion_tokens": sum(c["completion_tokens"] for c in calls),
            # Sum of the model's response times, as first measured; with
            # parallel agents the elapsed time is lower.
            "latency_ms": round(sum(c["latency_ms"] for c in calls), 1),
            "cache_hits": sum(bool(c["cached"]) for c in calls),
        },
        "issues": {
            "failed_stages": sum(bool(n.get("failed")) for n in notes),
            "repaired_replies": sum(c["attempt"] > 0 and c["ok"] for c in calls),
            "out_of_remit_flags": sum(n.get("out_of_remit", 0) for n in notes),
            "malformed_flags": sum(n.get("malformed", 0) for n in notes),
        },
    }


def audit(txn: dict, config: PipelineConfig, policy: Policy, client: ChatClient | None = None) -> dict:
    """Audit one transaction without human review; returns the final graph state."""
    return build_graph(config, policy, client).invoke({"txn": txn})
