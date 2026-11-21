"""The audit agent: answers an auditor's question by planning calls to tools over the audit, running them and citing
what they returned.

Ask AI (auditiq/copilot.py) retrieves passages and facts and has the model write one answer, and a data question
needs the model to write SQL. The agent works the other way round: a question is turned into a plan of tool calls,
each tool is code that reads the store (the audit results, the policy, the leads, the risk screen and its SHAP
values, the counterfactuals, the trail investigator, the e-mail triage, the collusion tests), and the answer is
assembled from the tools' observations, each cited as [T1], [T2], ... Two planners share the tools:

    rules   the question's words, ids, amounts and rule numbers choose the tools (``plan``). No model is needed,
            so it answers in well under a second on a laptop, and the same question gets the same answer
    model   with a model configured, a ReAct loop (Yao et al., 2023, "ReAct: Synergizing reasoning and acting in
            language models", ICLR): the model sees the tools' descriptions, asks for one tool at a time in JSON,
            reads the observation and decides the next step, at most ``MAX_STEPS`` times, then answers citing the
            observations. A tool name or argument outside the list is refused and the model is told so

Whatever planned the steps, every number in the final answer is looked for in the observations; a number no tool
returned is listed as unverified next to the answer (``unverified_numbers``), so a model's invention shows. The
tools only read: the agent cannot change a result, a decision or the ledger. Text from the ledger or a vendor
e-mail that reads as an instruction to a model is withheld from the model's view of an observation
(auditiq/triage.py, ``TO_A_MODEL``).
"""
from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import db, investigator, leads, rings, triage
from .llm import ChatClient, extract_json
from .policy import clause_texts
from .policy_graph import parse_amounts, rupees

INVOICE = re.compile(r"\bINV\d{3,}\b", re.I)
VENDOR = re.compile(r"\bVEND\d{3,}\b", re.I)
RULE = re.compile(r"(?<![\d.])(\d\.\d\.\d)(?![\d.]*\d)")
NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
MAX_STEPS = 5
OBSERVATION_CHARS = 1800
NAME_SUFFIX = re.compile(r"\b(pvt\.?|private|ltd\.?|limited|llp|inc\.?|co\.?|and co|& co|corp\.?|corporation)\b", re.I)

AGENT_SYSTEM = """\
You are an audit agent. You answer an auditor's question about a procurement audit by calling tools that read the audit's database, one tool at a time, and then answering from what the tools returned.

TOOLS
{tools}

Each turn, reply with one JSON object and nothing else, either
{{"thought": "<why this tool>", "tool": "<tool name>", "args": {{<arguments>}}}}
or, when the observations answer the question,
{{"answer": "<a few sentences that cite the observations as [T1], [T2] ...>", "cites": ["T1", ...]}}

Use only numbers, names and ids that an observation gives. If the tools cannot answer, say so."""


@dataclass
class Observation:
    summary: str
    data: Any = None
    refs: list[str] = field(default_factory=list)


@dataclass
class Tool:
    name: str
    description: str
    params: dict[str, str]
    run: Callable[[Context, dict], Observation]


class Context:
    """What the tools read: one store connection, and the heavier analyses computed once. ``shared`` is a dict kept
    while the store does not change (the API keeps one per state of the store), so that the second question about
    the leads or the screen does not compute them again."""

    def __init__(self, conn: db.Database, screen=None, shared: dict | None = None):
        self.conn = conn
        self._screen = screen
        self._cache: dict[str, Any] = shared if shared is not None else {}

    def once(self, key: str, compute: Callable[[], Any]) -> Any:
        if key not in self._cache:
            self._cache[key] = compute()
        return self._cache[key]

    @property
    def screen(self):
        if self._screen is None:
            from .screen import Screen
            self._screen = Screen.load()
        return self._screen

    def vendor_names(self) -> dict[str, str]:
        return self.once("vendors", lambda: dict(self.conn.execute(
            "SELECT vendor_id, vendor_name FROM vendor_master").fetchall()))


def _money(x) -> str:
    return rupees(float(x or 0))


# ------------------------------------------------------------------ tools
def t_audit_result(ctx: Context, args: dict) -> Observation:
    invoice_id = str(args.get("invoice_id", "")).upper()
    row = db.latest_result(ctx.conn, invoice_id)
    if row is None:
        exists = ctx.conn.scalar("SELECT COUNT(*) FROM invoices WHERE invoice_id = ?", (invoice_id,))
        return Observation(f"{invoice_id} is {'in the ledger but has not been audited' if exists else 'not in the ledger'}.",
                           {"invoice_id": invoice_id, "audited": False}, [invoice_id])
    flags = [dict(zip(r.keys(), tuple(r))) for r in ctx.conn.execute(
        "SELECT clause, severity, source, message FROM audit_flags WHERE result_id = ? AND status = 'kept' "
        "ORDER BY flag_id", (row["result_id"],)).fetchall()]
    review = ctx.conn.execute("SELECT decision, reviewer, justification FROM review_decisions WHERE result_id = ? "
                              "ORDER BY decision_id DESC LIMIT 1", (row["result_id"],)).fetchone()
    found = "; ".join(f"rule {f['clause']} ({f['severity']}, {'control' if f['source'] == 'D' else 'agent'}): "
                      f"{str(f['message'] or '').rstrip('.')}" for f in flags) or "no finding"
    summary = (f"{invoice_id} was audited under {row['configuration']} with policy v{row['policy_version']}: route "
               f"{row['route']}, risk {row['risk_level']}, score {float(row['rc'] or 0):.1f}, state "
               f"{row['workflow_status']}. Findings: {found}.")
    if review is not None:
        summary += f" Reviewer {review['reviewer']} decided to {review['decision']}" + \
                   (f" ({review['justification']})." if review["justification"] else ".")
    return Observation(summary, {"invoice_id": invoice_id, "route": row["route"], "risk_level": row["risk_level"],
                                 "score": float(row["rc"] or 0), "state": row["workflow_status"],
                                 "rules": [f["clause"] for f in flags]}, [invoice_id] + [f["clause"] for f in flags])


def t_invoice_records(ctx: Context, args: dict) -> Observation:
    invoice_id = str(args.get("invoice_id", "")).upper()
    txn = db.extract_one(ctx.conn, invoice_id)
    if txn is None:
        return Observation(f"{invoice_id} is not in the ledger.", None, [invoice_id])
    inv, vendor = txn["invoice"], txn["vendor"] or {}
    approved = [a for a in txn["approvals"] if a.get("action_taken") == "Approved"]
    approver = approved[-1] if approved else None
    summary = (f"{invoice_id}: invoice {inv['invoice_number']} of {_money(inv['amount'])} dated {str(inv['date'])[:10]} "
               f"from {vendor.get('vendor_name')} ({inv['vendor_id']}), PO {inv.get('po_id') or 'none'}, GRN "
               f"{inv.get('grn_id') or 'none'}, '{inv.get('description')}'. ")
    summary += (f"Approved by {approver['approver_name']} ({approver['approver_role']}) on "
                f"{str(approver['timestamp'])[:10]}." if approver else "No approval is recorded.")
    return Observation(summary, {"invoice": inv, "approver": approver, "vendor": vendor.get("vendor_name")},
                       [invoice_id, inv["vendor_id"]])


def t_explain_invoice(ctx: Context, args: dict) -> Observation:
    from . import counterfactual
    from .screen import FEATURE_NAMES, JUDGEMENT_HEADS, explain_row, features, policy_parameters

    invoice_id = str(args.get("invoice_id", "")).upper()
    txn = db.extract_one(ctx.conn, invoice_id)
    if txn is None:
        return Observation(f"{invoice_id} is not in the ledger.", None, [invoice_id])
    version = db.versions_in_force(ctx.conn, [invoice_id]).get(invoice_id)
    policy = db.read_policy(ctx.conn, version) if version else db.read_policy(ctx.conn)
    parts = []
    data: dict[str, Any] = {"invoice_id": invoice_id}
    try:
        values = features(txn, policy_parameters(policy))
        explained = explain_row(ctx.screen, [values[n] for n in FEATURE_NAMES], top=4)
        overall = explained["any"]
        best = max(JUDGEMENT_HEADS, key=lambda h: explained[h]["probability"])
        drivers = ", ".join(f"{c['feature']} = {c['value']:g} ({c['shap']:+.2f})" for c in overall["contributions"][:3])
        suggestion = (f"Of the judgement rules it points to {best} ({explained[best]['title'].lower()}) with "
                      f"probability {explained[best]['probability']:.3f}." if explained[best]["probability"] >= 0.5 else
                      f"No judgement rule stands out (the highest, {best}, has probability "
                      f"{explained[best]['probability']:.3f}).")
        parts.append(f"The risk screen gives {invoice_id} an anomaly probability of {overall['probability']:.3f} "
                     f"(average invoice {overall['base_probability']:.3f}); the largest SHAP contributions in "
                     f"log-odds are {drivers}. {suggestion}")
        data["screen"] = {"probability": overall["probability"], "suggested_rule": best,
                          "suggested_probability": explained[best]["probability"],
                          "contributions": overall["contributions"]}
    except Exception as error:                     # no trained screen: the counterfactuals still answer
        parts.append(f"The risk screen is not available ({error}).")
    found = counterfactual.explain(txn, policy)
    for f in found:
        option = (f["record"] or f["policy"] or [{}])[0]
        parts.append(f"Rule {f['clause']}: {f['margin']['text']}; it would clear with: {option.get('change', 'no change')}.")
    if not found:
        parts.append("No control finding to explain under the policy in force.")
    data["counterfactuals"] = found
    return Observation(" ".join(parts), data, [invoice_id] + [f["clause"] for f in found])


def t_invoice_story(ctx: Context, args: dict) -> Observation:
    invoice_id = str(args.get("invoice_id", "")).upper()
    told = investigator.story(ctx.conn, invoice_id)
    if told is None:
        return Observation(f"{invoice_id} is not in the ledger.", None, [invoice_id])
    steps = "; ".join(f"{s['at'][:16]} {s['what']}" for s in told["steps"][-8:])
    return Observation(f"Story of {invoice_id} ({told['audits']} audit(s)): {steps}. Now: {told['state']}.", told,
                       [invoice_id])


def _vendor_id(ctx: Context, text: str) -> str | None:
    found = VENDOR.search(text or "")
    if found:
        return found.group(0).upper()
    lowered = f" {str(text or '').lower()} "
    best = None
    for vendor_id, name in ctx.vendor_names().items():
        full = str(name or "").lower()
        short = " ".join(NAME_SUFFIX.sub(" ", full).split())
        for candidate in (full, short):
            if len(candidate) >= 5 and f" {candidate}" in lowered and (best is None or len(candidate) > best[1]):
                best = (vendor_id, len(candidate))
    return best[0] if best else None


def t_vendor_profile(ctx: Context, args: dict) -> Observation:
    vendor_id = _vendor_id(ctx, str(args.get("vendor", "")))
    if vendor_id is None or vendor_id not in ctx.vendor_names():
        return Observation(f"No vendor matches '{args.get('vendor')}'.", None)
    name = ctx.vendor_names()[vendor_id]
    n, amount = ctx.conn.execute("SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM invoices WHERE vendor_id = ?",
                                 (vendor_id,)).fetchone()
    rules = dict(ctx.conn.execute(
        "SELECT f.clause, COUNT(*) FROM audit_flags f JOIN v_latest_results l ON l.result_id = f.result_id "
        "WHERE l.vendor_id = ? AND f.status = 'kept' GROUP BY f.clause ORDER BY COUNT(*) DESC", (vendor_id,)).fetchall())
    waiting = int(ctx.conn.scalar("SELECT COUNT(*) FROM v_review_queue WHERE vendor_id = ?", (vendor_id,)) or 0)
    vendor = ctx.conn.execute("SELECT vendor_category, city, gstin_status, blacklisted FROM vendor_master WHERE "
                              "vendor_id = ?", (vendor_id,)).fetchone()
    found = ", ".join(f"{c} x{k}" for c, k in rules.items()) or "none"
    summary = (f"{name} ({vendor_id}, {vendor['vendor_category']}, {vendor['city']}): {int(n):,} invoices for "
               f"{_money(amount)}; findings in the latest results: {found}; {waiting} waiting for review; GST status "
               f"{vendor['gstin_status']}{', blacklisted' if vendor['blacklisted'] else ''}.")
    return Observation(summary, {"vendor_id": vendor_id, "name": name, "invoices": int(n), "amount": float(amount),
                                 "findings": rules, "waiting": waiting}, [vendor_id])


def t_top_vendors(ctx: Context, args: dict) -> Observation:
    by = str(args.get("by", "findings"))
    n = max(1, min(int(args.get("n", 5) or 5), 20))
    if by == "waiting":
        sql = ("SELECT vendor_id, vendor_name, COUNT(*) AS value FROM v_review_queue GROUP BY vendor_id, vendor_name "
               "ORDER BY value DESC, vendor_id LIMIT ?")
    elif by == "amount":
        sql = ("SELECT i.vendor_id, v.vendor_name, SUM(i.amount) AS value FROM invoices i JOIN vendor_master v ON "
               "v.vendor_id = i.vendor_id GROUP BY i.vendor_id, v.vendor_name ORDER BY value DESC, i.vendor_id LIMIT ?")
    else:
        by = "findings"
        sql = ("SELECT l.vendor_id, v.vendor_name, COUNT(*) AS value FROM audit_flags f JOIN v_latest_results l ON "
               "l.result_id = f.result_id JOIN vendor_master v ON v.vendor_id = l.vendor_id WHERE f.status = 'kept' "
               "GROUP BY l.vendor_id, v.vendor_name ORDER BY value DESC, l.vendor_id LIMIT ?")
    rows = [dict(zip(r.keys(), tuple(r))) for r in ctx.conn.execute(sql, (n,)).fetchall()]
    shown = "; ".join(f"{r['vendor_name']} ({r['vendor_id']}): "
                      f"{_money(r['value']) if by == 'amount' else int(r['value'])}" for r in rows)
    label = {"findings": "most findings in the latest results", "waiting": "most invoices waiting for review",
             "amount": "largest invoiced amount"}[by]
    return Observation(f"Vendors with the {label}: {shown or 'none'}.", rows, [r["vendor_id"] for r in rows])


def t_findings_summary(ctx: Context, args: dict) -> Observation:
    audited = int(ctx.conn.scalar("SELECT COUNT(*) FROM latest_results") or 0)
    invoices = int(ctx.conn.scalar("SELECT COUNT(*) FROM invoices") or 0)
    routes = dict(ctx.conn.execute("SELECT route, COUNT(*) FROM v_latest_results GROUP BY route").fetchall())
    waiting = int(ctx.conn.scalar("SELECT COUNT(*) FROM v_review_queue") or 0)
    rules = [(c, int(k)) for c, k in ctx.conn.execute(
        "SELECT f.clause, COUNT(*) FROM audit_flags f JOIN latest_results m ON m.result_id = f.result_id WHERE "
        "f.status = 'kept' GROUP BY f.clause ORDER BY COUNT(*) DESC, f.clause")]
    flagged = int(ctx.conn.scalar("SELECT COUNT(*) FROM v_latest_results WHERE flag_count > 0") or 0)
    summary = (f"{audited:,} of {invoices:,} invoices audited; {flagged:,} with at least one finding; routes: "
               + ", ".join(f"{k} {int(v):,}" for k, v in sorted(routes.items())) + f"; {waiting:,} waiting for review. "
               "Findings by rule: " + (", ".join(f"{c} {k:,}" for c, k in rules) or "none") + ".")
    return Observation(summary, {"audited": audited, "invoices": invoices, "flagged": flagged, "routes": routes,
                                 "waiting": waiting, "rules": dict(rules)})


def t_review_queue(ctx: Context, args: dict) -> Observation:
    n = max(1, min(int(args.get("n", 10) or 10), 50))
    level = str(args.get("level") or "").upper() or None
    where, params = ("WHERE risk_level = ?", [level]) if level in ("CRITICAL", "HIGH", "MEDIUM", "LOW") else ("", [])
    total = int(ctx.conn.scalar(f"SELECT COUNT(*) FROM v_review_queue {where}", params) or 0)
    rows = [dict(zip(r.keys(), tuple(r))) for r in ctx.conn.execute(
        f"SELECT invoice_id, vendor_name, amount, risk_level, rc FROM v_review_queue {where} ORDER BY rc DESC, "
        f"invoice_id LIMIT {n}", params).fetchall()]
    shown = "; ".join(f"{r['invoice_id']} {r['vendor_name']} {_money(r['amount'])} {r['risk_level']}" for r in rows)
    return Observation(f"{total:,} invoices{' at ' + level if level and where else ''} waiting for review; the "
                       f"highest first: {shown or 'none'}.", {"total": total, "items": rows},
                       [r["invoice_id"] for r in rows])


def _active_limits(ctx: Context) -> tuple[str, dict[str, float]]:
    policy = db.read_policy(ctx.conn)
    limits = (policy.clauses.get("5.1.1") or {}).get("params", {}).get("approval_limits", {})
    return policy.version, {k: float(v) for k, v in limits.items()}


def t_approval_rule(ctx: Context, args: dict) -> Observation:
    amount = float(args.get("amount") or 0)
    version, limits = _active_limits(ctx)
    covering = sorted((v, r) for r, v in limits.items() if v >= amount)
    table = ", ".join(f"{r} up to {_money(v)}" for v, r in sorted((v, r) for r, v in limits.items()))
    if not covering:
        return Observation(f"No role may approve {_money(amount)} under policy v{version} ({table}).",
                           {"amount": amount, "role": None, "limits": limits}, ["5.1.1"])
    limit, role = covering[0]
    return Observation(f"Under policy v{version}, rule 5.1.1, an invoice of {_money(amount)} needs a {role} "
                       f"(limit {_money(limit)}), the lowest role whose limit covers it ({table}).",
                       {"amount": amount, "role": role, "limit": limit, "limits": limits}, ["5.1.1"])


def t_policy_rule(ctx: Context, args: dict) -> Observation:
    policy = db.read_policy(ctx.conn)
    clause = str(args.get("clause", "")).strip()
    entry = policy.clauses.get(clause)
    if entry is None:
        return Observation(f"Policy v{policy.version} has no rule {clause}.", None)
    wording = clause_texts(policy.text).get(clause, "")
    params = ", ".join(f"{k} = {v}" for k, v in entry.get("params", {}).items())
    return Observation(f"Rule {clause} of policy v{policy.version}, {entry['title']} ({entry['severity']}, "
                       f"{'decided by a control' if entry['kind'] == 'control' else 'a judgement rule for the agents'})"
                       + (f"; parameters {params}" if params else "") + (f". Wording: {wording}" if wording else "."),
                       {"clause": clause, **entry, "wording": wording}, [clause])


def t_judgement_leads(ctx: Context, args: dict) -> Observation:
    found = ctx.once("leads", lambda: leads.judgement_leads(ctx.conn))
    nd, st = found["near_duplicates"], found["structuring"]
    pairs, groups = nd["pairs"], st["groups"]
    shown = ", ".join(f"{p['invoice_id']} (repeats {p['original_id']})" for p in pairs[:5])
    groups_shown = ", ".join(f"{'+'.join(g['invoices'])} ({g['vendor_name']}, {_money(g['total'])} against a "
                             f"{g['role']} limit of {_money(g['limit'])})" for g in groups[:3])
    return Observation(f"{nd['count']} near-duplicate lead(s) under rule 2.2.2" + (f", such as {shown}" if shown else "")
                       + f"; of their invoices the latest results approved {nd['approved']}. {st['count']} "
                       f"structuring group(s) under rule 4.1.2" + (f", such as {groups_shown}" if groups_shown else "")
                       + f"; of their invoices the latest results approved {st['approved']}. A lead is not a finding.",
                       {"near_duplicates": pairs[:20], "structuring": groups[:10]},
                       [p["invoice_id"] for p in pairs[:5]])


def t_screen_leads(ctx: Context, args: dict) -> Observation:
    from .screen import JUDGEMENT_HEADS
    rows = ctx.once("screen", lambda: screen_store(ctx.conn, ctx.screen))
    n = max(1, min(int(args.get("n", 8) or 8), 30))
    passed = [r for r in rows if r["route"] in ("approve", None)]
    passed.sort(key=lambda r: -r["judgement"])
    top = passed[:n]
    shown = "; ".join(f"{r['invoice_id']} {r['suggested']} p={r['judgement']:.3f}" for r in top)
    return Observation(f"Of the {len(passed):,} invoices the latest results passed, the risk screen rates highest for a "
                       f"judgement rule ({', '.join(JUDGEMENT_HEADS)}): {shown or 'none'}. A screen score is not a "
                       "finding; these are for a reviewer or the agents.", top, [r["invoice_id"] for r in top])


def t_trail_investigation(ctx: Context, args: dict) -> Observation:
    report = ctx.once("investigation", lambda: investigator.investigate(ctx.conn))
    failing = [c for c in report["checks"] if c["status"] != "pass"]
    shown = "; ".join(f"{c['title']} ({c['status']}): {c['summary']}" for c in failing[:6])
    return Observation(f"{report['verdict']} " + (shown + "." if shown else "Every check passed."),
                       {"verdict": report["verdict"], "checks": [{k: c[k] for k in ("key", "title", "status", "count",
                                                                                   "summary")} for c in report["checks"]]})


def t_mail_alerts(ctx: Context, args: dict) -> Observation:
    found = ctx.once("mail", lambda: triage.triage_store(ctx.conn))
    if not found["emails"]:
        return Observation("No vendor e-mail is stored.", found)
    high = [a for a in found["alerts"] if a["risk"] == "high"]
    shown = "; ".join(f"{a['sender']} about {a['invoice_id'] or 'no invoice'}: {', '.join(a['reasons'])}" for a in high[:5])
    return Observation(f"{found['emails']:,} vendor e-mails; {found['by_risk']['high']} high-risk (payment redirection), "
                       f"{found['by_risk']['medium']} to confirm; {len(found['holds'])} invoice(s) to hold for "
                       f"{_money(found['hold_amount'])}" + (f". High-risk: {shown}." if shown else "."),
                       {"by_risk": found["by_risk"], "holds": found["holds"], "high": high[:10]},
                       [h["invoice_id"] for h in found["holds"]])


def t_collusion_rings(ctx: Context, args: dict) -> Observation:
    n = max(1, min(int(args.get("n", 5) or 5), 20))
    found = ctx.once(f"rings:{n}", lambda: rings.find_rings(ctx.conn, limit=n))
    groups = found.get("rings", [])
    shown = "; ".join(f"ring {i + 1}: " + ", ".join(m.get("id", m.get("vendor_id", "?")) if isinstance(m, dict) else str(m)
                                                    for m in (g.get("vendors") or g.get("members") or [])[:6])
                      for i, g in enumerate(groups[:n]))
    return Observation(f"{len(groups)} collusion ring(s) found" + (f": {shown}." if shown else "."),
                       {"rings": groups[:n]}, [])


TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("audit_result", "the latest audit result of an invoice: route, risk, findings with rules, review decision",
         {"invoice_id": "an invoice id such as INV40042"}, t_audit_result),
    Tool("invoice_records", "an invoice's records: number, amount, date, vendor, PO, GRN, description, approver",
         {"invoice_id": "an invoice id"}, t_invoice_records),
    Tool("explain_invoice", "why: the risk screen's probability and SHAP contributions, the judgement rule it "
                            "suggests, and for each control finding the margin and the change that would clear it",
         {"invoice_id": "an invoice id"}, t_explain_invoice),
    Tool("invoice_story", "what happened to an invoice, in order: records, approvals, e-mails, audits, decisions",
         {"invoice_id": "an invoice id"}, t_invoice_story),
    Tool("vendor_profile", "a vendor's invoices, amount, findings by rule and invoices waiting",
         {"vendor": "a vendor id (VEND1001) or name"}, t_vendor_profile),
    Tool("top_vendors", "the vendors ranked by findings, invoices waiting or amount",
         {"by": "findings, waiting or amount", "n": "how many (1 to 20)"}, t_top_vendors),
    Tool("findings_summary", "the audit as a whole: invoices audited, routes, waiting, findings by rule", {},
         t_findings_summary),
    Tool("review_queue", "the invoices waiting for review, highest risk first",
         {"level": "CRITICAL, HIGH, MEDIUM, LOW or empty", "n": "how many (1 to 50)"}, t_review_queue),
    Tool("approval_rule", "which role must approve an amount under the active policy", {"amount": "rupees"},
         t_approval_rule),
    Tool("policy_rule", "a rule of the active policy: title, severity, kind, parameters, wording",
         {"clause": "a rule number such as 5.1.1"}, t_policy_rule),
    Tool("judgement_leads", "invoices that fit the wording of rules 2.2.2 (near duplicates) and 4.1.2 (structuring)",
         {}, t_judgement_leads),
    Tool("screen_leads", "invoices the audit passed that the risk screen rates highest for a judgement rule",
         {"n": "how many (1 to 30)"}, t_screen_leads),
    Tool("trail_investigation", "whether the audit record and the review were done properly: seals, coverage, "
                                "reasons, pace, segregation of duties, overrides, outcomes that changed", {},
         t_trail_investigation),
    Tool("mail_alerts", "vendor e-mails that try to redirect a payment, and the invoices to hold", {}, t_mail_alerts),
    Tool("collusion_rings", "vendors and approvers linked by shared identities or tested approval patterns",
         {"n": "how many rings (1 to 20)"}, t_collusion_rings),
]}


def screen_store(conn: db.Database, screen, limit: int | None = None) -> list[dict]:
    """The screen's probabilities for the invoices of the store (at most ``limit``), with their latest route."""
    from .screen import matrix, policy_parameters

    ids = db.invoice_ids(conn, limit=limit)
    if not ids:
        return []
    governing = db.versions_in_force(conn, ids)
    params = {v: policy_parameters(db.read_policy(conn, v)) for v in set(governing.values())}
    fallback = policy_parameters(db.read_policy(conn))
    transactions = db.extract_many(conn, ids)
    X = matrix(transactions, lambda t: params.get(governing.get(t["invoice"]["invoice_id"]), fallback))
    scores = screen.scores(X)
    suggested, best = screen.suggested_rule(scores)
    routes = dict(conn.execute("SELECT invoice_id, route FROM v_latest_results").fetchall())
    return [{"invoice_id": i, "route": routes.get(i), "any": float(scores["any"][k]), "judgement": float(best[k]),
             "suggested": str(suggested[k]), "row": X[k]} for k, i in enumerate(ids)]


# ------------------------------------------------------------------ the rules planner
def plan(question: str, ctx: Context) -> list[tuple[str, dict]]:
    """The tools a question asks for, read from its words, ids, amounts and rule numbers."""
    q = question.lower()
    steps: list[tuple[str, dict]] = []
    invoices = list(dict.fromkeys(m.upper() for m in INVOICE.findall(question)))
    rules_named = RULE.findall(question)
    amounts = parse_amounts(question)

    def has(*words: str) -> bool:
        return any(re.search(rf"\b{w}", q) for w in words)

    for invoice_id in invoices[:3]:
        if has("story", "history", "happen", "timeline", "lifecycle", "journey", "trail of"):
            steps.append(("invoice_story", {"invoice_id": invoice_id}))
        elif has("what would", "clear", "pass", "counterfactual", "fix", "how close", "margin", "shap", "explain",
                 "model", "screen", "contribut"):
            steps += [("audit_result", {"invoice_id": invoice_id}), ("explain_invoice", {"invoice_id": invoice_id})]
        elif has("who approv", "approver", "approved by", "amount", "dated", "records", "details", "po ", "grn"):
            steps += [("invoice_records", {"invoice_id": invoice_id}), ("audit_result", {"invoice_id": invoice_id})]
        elif has("why", "flag", "finding", "risk", "reason", "escalat", "rule"):
            steps += [("audit_result", {"invoice_id": invoice_id}), ("explain_invoice", {"invoice_id": invoice_id})]
        else:
            steps += [("audit_result", {"invoice_id": invoice_id}), ("invoice_records", {"invoice_id": invoice_id})]
    if invoices:
        return steps
    if amounts and has("approv", "sign", "role", "who can", "authori", "limit"):
        return [("approval_rule", {"amount": amounts[0]})]
    for clause in rules_named[:2]:
        steps.append(("policy_rule", {"clause": clause}))
    vendor = _vendor_id(ctx, question)
    if vendor and not has("top", "most", "which vendors", "riskiest"):
        steps.append(("vendor_profile", {"vendor": vendor}))
    if has("collu", "ring", "cartel", "kickback", "shell"):
        steps.append(("collusion_rings", {"n": 5}))
    if has("phish", "bank detail", "bank account", "e-?mails?", "mail", "bec", "redirect", "spoof", "look-?alike"):
        steps.append(("mail_alerts", {}))
    if has("tamper", "integrit", "trail", "investigat", "rubber", "segregat", "override", "reviewer", "opinion shop",
           "audit the audit", "documentation", "sla", "backlog"):
        steps.append(("trail_investigation", {}))
    if has("near.?duplicate", "structur", "leads?", "split"):
        steps.append(("judgement_leads", {}))
    if has("machine learning", "screen", "second opinion", "missed", "shap", "model think", "ml ", "slipped",
           "might have missed"):
        steps.append(("screen_leads", {"n": 8}))
    if has("top", "most", "riskiest", "highest", "largest", "biggest", "worst") and has("vendor", "supplier"):
        by = "waiting" if has("waiting", "queue", "pending") else ("amount" if has("amount", "spend", "paid", "value",
                                                                                     "largest", "biggest") else "findings")
        steps.append(("top_vendors", {"by": by, "n": 5}))
    if has("queue", "waiting", "pending") and not any(s[0] == "top_vendors" for s in steps):
        level = next((lv for lv in ("critical", "high", "medium", "low") if has(lv)), "")
        steps.append(("review_queue", {"level": level.upper(), "n": 10}))
    if not steps and has("how many", "count", "summary", "overview", "finding", "flag", "anomal", "status", "result"):
        steps.append(("findings_summary", {}))
    return steps


# ------------------------------------------------------------------ answers
def _numbers(text: str) -> set[str]:
    """The numbers of a text, without thousands separators; rule numbers (5.1.1) are names, not numbers."""
    text = RULE.sub(" ", text or "")
    return {n.replace(",", "").rstrip(".").lstrip("0") or "0" for n in NUMBER.findall(text)}


def unverified_numbers(answer: str, observations: list[Observation]) -> list[str]:
    """Numbers in the answer that no observation contains (ids such as INV40042 are matched as words)."""
    seen = set()
    for o in observations:
        seen |= _numbers(o.summary) | _numbers(json.dumps(o.data, default=str, ensure_ascii=False))
    out = []
    for n in sorted(_numbers(answer)):
        if n in seen or re.fullmatch(r"[0-9]", n):
            continue
        out.append(n)
    return out


def _safe(text: str) -> str:
    """An observation as a model sees it: text that instructs a model is withheld."""
    return triage.TO_A_MODEL.sub("[withheld: text addressed to a model]", text)


def run_tool(ctx: Context, name: str, args: dict) -> tuple[Observation, float]:
    tool = TOOLS[name]
    started = time.perf_counter()
    try:
        observation = tool.run(ctx, args or {})
    except Exception as error:                       # a tool that fails is reported as its observation
        observation = Observation(f"The tool {name} failed: {type(error).__name__}: {error}", None)
    return observation, round((time.perf_counter() - started) * 1000, 1)


def ask(question: str, conn: db.Database, client: ChatClient | None = None, mode: str = "auto",
        screen=None, shared: dict | None = None) -> dict:
    """Answer a question with the tools. ``mode``: rules, model, or auto (the rules planner when it recognises
    the question, else the model when one is given). ``shared``: see ``Context``."""
    ctx = Context(conn, screen, shared)
    planned = plan(question, ctx) if mode in ("auto", "rules") else []
    out = {"question": question, "mode": None, "steps": [], "answer": "", "citations": [], "unverified_numbers": [],
           "calls": []}
    observations: list[Observation] = []
    if planned or mode == "rules" or client is None:
        out["mode"] = "rules"
        for name, args in planned:
            observation, ms = run_tool(ctx, name, args)
            observations.append(observation)
            out["steps"].append({"n": len(observations), "tool": name, "args": args, "summary": observation.summary,
                                 "refs": observation.refs, "ms": ms, "data": observation.data})
        if not observations:
            out["answer"] = ("I could not tell which tool answers this. Name an invoice (INV...), a vendor, a rule "
                             "(5.1.1) or an amount, or ask about findings, the review queue, collusion rings, e-mails, "
                             "leads, the risk screen or the audit trail." +
                             ("" if client is None else " With a model configured, ask in the model mode."))
            return out
        out["answer"] = " ".join(f"{o.summary} [T{k}]" for k, o in enumerate(observations, start=1))
        out["citations"] = [f"T{k}" for k in range(1, len(observations) + 1)]
        return out

    out["mode"] = "model"
    tools_text = "\n".join(f"- {t.name}({', '.join(f'{p}: {d}' for p, d in t.params.items())}): {t.description}"
                           for t in TOOLS.values())
    messages = [{"role": "system", "content": AGENT_SYSTEM.format(tools=tools_text)},
                {"role": "user", "content": question}]
    for _ in range(MAX_STEPS):
        data, call = _next(client, messages)
        out["calls"].append(call)
        if data is None:
            out["answer"] = "The model did not return a usable step."
            break
        if isinstance(data.get("answer"), str):
            out["answer"] = data["answer"].strip()
            out["citations"] = [c for c in data.get("cites", []) if isinstance(c, str)]
            break
        name, args = data.get("tool"), data.get("args") if isinstance(data.get("args"), dict) else {}
        if name not in TOOLS:
            messages += [{"role": "assistant", "content": json.dumps(data)},
                         {"role": "user", "content": f"There is no tool {name!r}. Use one of: {', '.join(TOOLS)}."}]
            continue
        observation, ms = run_tool(ctx, name, args)
        observations.append(observation)
        k = len(observations)
        out["steps"].append({"n": k, "tool": name, "args": args, "thought": str(data.get("thought") or ""),
                             "summary": observation.summary, "refs": observation.refs, "ms": ms,
                             "data": observation.data})
        shown = _safe(json.dumps(observation.data, default=str, ensure_ascii=False))[:OBSERVATION_CHARS]
        messages += [{"role": "assistant", "content": json.dumps(data)},
                     {"role": "user", "content": f"T{k}: {_safe(observation.summary)}\nDATA: {shown}"}]
    else:
        out["answer"] = out["answer"] or "The step limit was reached before an answer; the observations are below."
    out["unverified_numbers"] = unverified_numbers(out["answer"], observations)
    return out


def _next(client: ChatClient, messages: list[dict]) -> tuple[dict | None, dict]:
    """One step of the model: a tool request or the answer, and the cost record of the call."""
    reply = client.complete(messages, temperature=0.0)
    try:
        data = extract_json(reply.text)
    except ValueError:
        data = None
    ok = isinstance(data, dict) and (isinstance(data.get("answer"), str) or isinstance(data.get("tool"), str))
    call = {"stage": "agent", "agent": "audit_agent", "sample": 0, "attempt": 0, "ok": ok,
            "prompt_tokens": reply.prompt_tokens, "completion_tokens": reply.completion_tokens,
            "latency_ms": reply.latency_ms, "cached": reply.cached}
    return (data if ok else None), call
