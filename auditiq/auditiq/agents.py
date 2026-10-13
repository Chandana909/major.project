"""The LLM stages: three specialist agents, the single-prompt auditor and the challenger.

A specialist is one structured LLM call with a narrow remit. Its remit is the
judgement clauses of its policy sections; everything a field comparison can
decide has been decided by the controls before the specialist runs. Flags that
cite a clause outside the remit are discarded by code.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher

from . import prompts
from .llm import ChatClient, extract_json
from .policy import Policy
from .scoring import clause_id, normalize_flag

FULL_HISTORY = ("invoice_id", "invoice_number", "date", "amount", "quantity", "po_id", "grn_id",
                "approver_role", "approver_name", "description")


@dataclass(frozen=True)
class AgentSpec:
    name: str
    title: str
    sections: tuple[str, ...]         # policy sections of the remit, as clause-id prefixes
    records: tuple[str, ...]          # records shown besides the invoice under audit
    history_fields: tuple[str, ...] = ()
    history_rules: tuple[str, ...] = ()   # how the vendor's other invoices are chosen: "duplicates", "time"


AGENTS: dict[str, AgentSpec] = {
    a.name: a
    for a in [
        AgentSpec("math_approvals", "Math and Approvals agent", ("2.1.", "5."),
                  records=("po", "grn", "approvals")),
        AgentSpec("tax_identity", "Tax and Identity agent", ("2.2.", "3."),
                  records=("vendor", "history"), history_rules=("duplicates",),
                  history_fields=("invoice_id", "invoice_number", "date", "amount", "po_id", "grn_id")),
        AgentSpec("vendor_intelligence", "Vendor Intelligence agent", ("4.",),
                  records=("vendor", "approvals", "history"), history_rules=("time",),
                  history_fields=("invoice_id", "date", "amount", "description", "approver_role", "approver_name")),
    ]
}
SINGLE = AgentSpec("single_auditor", "auditor", (), records=("po", "grn", "vendor", "approvals", "history"),
                   history_fields=FULL_HISTORY, history_rules=("duplicates", "time"))

# An agent sees at most this many other invoices of the vendor per rule. Below
# the cap it sees all of them; above it, the ones a fixed rule ranks first, so
# that the prompt stays bounded however large the vendor is.
HISTORY_CAP = 40


def _number_key(number) -> str:
    return "".join(ch for ch in str(number or "").upper() if ch.isalnum())


def select_history(txn: dict, rules: tuple[str, ...], cap: int = HISTORY_CAP) -> list[dict]:
    """The vendor's other invoices an agent is shown, oldest first.

    "duplicates" ranks an invoice that bills the same PO or GRN first, then one
    of the same amount, then by similarity of the invoice number, then by
    closeness in time. "time" ranks by closeness in time. With both rules the
    result is the union of the two selections.
    """
    history = txn.get("vendor_history") or []
    if len(history) <= cap:
        return list(history)
    invoice = txn["invoice"]
    day = date.fromisoformat(str(invoice["date"])[:10])
    own = _number_key(invoice.get("invoice_number"))

    def gap(h: dict) -> int:
        return abs((date.fromisoformat(str(h["date"])[:10]) - day).days)

    def duplicate_rank(h: dict) -> tuple:
        same_document = any(invoice.get(key) is not None and h.get(key) == invoice.get(key)
                            for key in ("po_id", "grn_id"))
        similarity = SequenceMatcher(None, own, _number_key(h.get("invoice_number"))).ratio()
        return (not same_document, h.get("amount") != invoice.get("amount"), -similarity, gap(h), h["invoice_id"])

    chosen: dict[str, dict] = {}
    for rule in rules:
        rank = duplicate_rank if rule == "duplicates" else (lambda h: (gap(h), h["invoice_id"]))
        for h in sorted(history, key=rank)[:cap]:
            chosen[h["invoice_id"]] = h
    return sorted(chosen.values(), key=lambda h: (h["date"], h["invoice_id"]))


def remit(spec: AgentSpec, policy: Policy) -> list[str]:
    """Judgement clauses of the agent's sections under the active policy."""
    return [k for k, c in policy.clauses.items() if c["kind"] == "judgement" and k.startswith(spec.sections)]


# ------------------------------------------------------------------ prompts
def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _cell(value) -> str:
    if value is None:
        return ""
    return f"{value:.2f}" if isinstance(value, float) else str(value)


def render_records(txn: dict, spec: AgentSpec) -> str:
    """The records an agent sees, as text. Labels never reach this function."""
    parts = ["INVOICE UNDER AUDIT", _json(txn["invoice"])]
    if "po" in spec.records:
        parts += ["", "PURCHASE ORDER", _json(txn["po"]) if txn.get("po") else "none on record"]
    if "grn" in spec.records:
        parts += ["", "GOODS RECEIPT NOTE", _json(txn["grn"]) if txn.get("grn") else "none on record"]
    if "vendor" in spec.records:
        parts += ["", "VENDOR MASTER RECORD", _json(txn["vendor"])]
    if "approvals" in spec.records:
        parts += ["", "APPROVAL LOG (oldest first)"]
        parts += [_json(a) for a in txn.get("approvals") or []] or ["none on record"]
    if "history" in spec.records:
        total = len(txn.get("vendor_history") or [])
        history = select_history(txn, spec.history_rules)
        shown = f"{total}" if len(history) == total else f"the {len(history)} most relevant of {total}"
        parts += ["", f"OTHER INVOICES OF THE SAME VENDOR ({shown}; oldest first; one per line)",
                  " | ".join(spec.history_fields)]
        parts += [" | ".join(_cell(h.get(f)) for f in spec.history_fields) for h in history]
    return "\n".join(parts)


def _control_findings(control_flags: list[dict]) -> str:
    return "\n".join(f"- Rule {f['clause']}: {f['message']}" for f in control_flags) or "none"


def _remit_text(clauses: list[str], policy: Policy) -> str:
    named = [f"Rule {k} ({policy.clauses[k]['title'].lower()})" for k in clauses]
    listed = named[0] if len(named) == 1 else ", ".join(named[:-1]) + " and " + named[-1]
    return ("this rule of the policy: " if len(named) == 1 else "these rules of the policy: ") + listed


def _messages(policy: Policy, user: str) -> list[dict]:
    return [{"role": "system", "content": prompts.system_message(policy.version, policy.text)},
            {"role": "user", "content": user}]


def specialist_messages(spec: AgentSpec, policy: Policy, txn: dict, control_flags: list[dict]) -> list[dict]:
    # str.replace, not str.format: the template contains literal JSON braces.
    task = (prompts.SPECIALIST_TASK.replace("{title}", spec.title)
            .replace("{remit}", _remit_text(remit(spec, policy), policy)))
    return _messages(policy, prompts.user_message(task, render_records(txn, spec),
                                                  control_findings=_control_findings(control_flags)))


def single_messages(policy: Policy, txn: dict) -> list[dict]:
    return _messages(policy, prompts.user_message(prompts.SINGLE_TASK, render_records(txn, SINGLE)))


def challenger_view(proposed: list[dict]) -> AgentSpec:
    """The records the challenger sees: those shown to the agents whose findings it tests.

    A finding is tested against the evidence its author had. This also keeps
    the prompt short: the vendor's other invoices appear only when an agent
    that read them raised a finding, and only with the columns that agent saw.
    """
    authors = [AGENTS.get(f.get("agent"), SINGLE) for f in proposed]
    return AgentSpec("challenger", "challenger", (),
                     records=tuple(r for r in SINGLE.records if any(r in a.records for a in authors)),
                     history_fields=tuple(f for f in FULL_HISTORY if any(f in a.history_fields for a in authors)),
                     history_rules=tuple(r for r in SINGLE.history_rules if any(r in a.history_rules for a in authors)))


def challenger_messages(policy: Policy, txn: dict, control_flags: list[dict], proposed: list[dict]) -> list[dict]:
    findings = "\n".join(
        _json({"id": i, "clause": f["clause"], "evidence": f["evidence"], "explanation": f["message"]})
        for i, f in enumerate(proposed, start=1))
    return _messages(policy, prompts.user_message(prompts.CHALLENGER_TASK,
                                                  render_records(txn, challenger_view(proposed)),
                                                  control_findings=_control_findings(control_flags),
                                                  proposed=findings))


# ------------------------------------------------------------------- calls
def call_json(client: ChatClient, messages: list[dict], required_key: str, *, stage: str, agent: str,
              temperature: float, sample: int = 0) -> tuple[dict | None, list[dict]]:
    """One LLM call that must return a JSON object with ``required_key`` holding a list.

    A reply of the wrong form is sent back once for repair. Returns the object
    (or None after two failures) and one cost record per call made.
    """
    calls = []
    for attempt in range(2):
        reply = client.complete(messages, temperature=temperature, sample=sample)
        try:
            data = extract_json(reply.text)
            ok = isinstance(data.get(required_key), list)
        except ValueError:
            data, ok = None, False
        calls.append({"stage": stage, "agent": agent, "sample": sample, "attempt": attempt, "ok": ok,
                      "prompt_tokens": reply.prompt_tokens, "completion_tokens": reply.completion_tokens,
                      "latency_ms": reply.latency_ms, "cached": reply.cached})
        if ok:
            return data, calls
        messages = messages + [{"role": "assistant", "content": reply.text},
                               {"role": "user", "content": prompts.REPAIR}]
    return None, calls


def parse_flags(data: dict, agent: str, allowed: set[str] | None, clauses: dict) -> tuple[list[dict], dict]:
    """Turn a reply into flags.

    ``allowed`` is the remit; a flag citing another clause of the policy is
    discarded (None: every clause is allowed). A flag citing a clause that does
    not exist in the policy is kept, so that the clause-validity term can see it.
    """
    flags, seen = [], set()
    dropped = {"malformed": 0, "out_of_remit": 0, "repeated": 0}
    for item in data["flags"]:
        if not isinstance(item, dict) or not str(item.get("clause") or "").strip():
            dropped["malformed"] += 1
            continue
        cid = clause_id(item["clause"])
        if allowed is not None and cid in clauses and cid not in allowed:
            dropped["out_of_remit"] += 1
            continue
        key = cid or str(item["clause"])
        if key in seen:
            dropped["repeated"] += 1
            continue
        seen.add(key)
        evidence = item.get("evidence")
        flags.append(normalize_flag({
            "clause": item["clause"],
            "source": "L",
            "agent": agent,
            "evidence": evidence if isinstance(evidence, list) else [],
            "message": str(item.get("explanation") or "").strip(),
        }, clauses))
    return flags, dropped


def run_specialist(client: ChatClient, spec: AgentSpec, policy: Policy, txn: dict, control_flags: list[dict], *,
                   temperature: float = 0.0, sample: int = 0, stage: str = "agent") -> dict:
    """Run one specialist. Returns {flags, calls, dropped, failed}."""
    data, calls = call_json(client, specialist_messages(spec, policy, txn, control_flags), "flags",
                            stage=stage, agent=spec.name, temperature=temperature, sample=sample)
    if data is None:
        return {"flags": [], "calls": calls, "dropped": {}, "failed": True}
    flags, dropped = parse_flags(data, spec.name, set(remit(spec, policy)), policy.clauses)
    return {"flags": flags, "calls": calls, "dropped": dropped, "failed": False}


def run_single(client: ChatClient, policy: Policy, txn: dict, *, temperature: float = 0.0, sample: int = 0,
               stage: str = "agent") -> dict:
    """The single-prompt auditor of configuration C2: the whole policy, no controls."""
    data, calls = call_json(client, single_messages(policy, txn), "flags",
                            stage=stage, agent=SINGLE.name, temperature=temperature, sample=sample)
    if data is None:
        return {"flags": [], "calls": calls, "dropped": {}, "failed": True}
    flags, dropped = parse_flags(data, SINGLE.name, None, policy.clauses)
    return {"flags": flags, "calls": calls, "dropped": dropped, "failed": False}


def run_challenger(client: ChatClient, policy: Policy, txn: dict, control_flags: list[dict],
                   proposed: list[dict], *, temperature: float = 0.0) -> dict:
    """Ask the challenger for a verdict on each agent flag.

    Returns {kept, removed, calls, failed}. A flag without a valid verdict is
    kept, and so is every flag when the challenger gives no usable reply.
    """
    if not proposed:
        return {"kept": [], "removed": [], "calls": [], "failed": False}
    data, calls = call_json(client, challenger_messages(policy, txn, control_flags, proposed), "verdicts",
                            stage="challenger", agent="challenger", temperature=temperature)
    if data is None:
        return {"kept": list(proposed), "removed": [], "calls": calls, "failed": True}
    reasons = {}
    for v in data["verdicts"]:
        if isinstance(v, dict) and str(v.get("verdict") or "").strip().lower() == "remove":
            try:
                reasons[int(v.get("id"))] = str(v.get("reason") or "").strip()
            except (TypeError, ValueError):
                continue
    kept, removed = [], []
    for i, flag in enumerate(proposed, start=1):
        if i in reasons:
            removed.append({**flag, "removed_by": "challenger", "removal_reason": reasons[i]})
        else:
            kept.append(flag)
    return {"kept": kept, "removed": removed, "calls": calls, "failed": False}
