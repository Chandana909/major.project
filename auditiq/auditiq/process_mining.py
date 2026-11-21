"""Process mining of procure-to-pay: the event log of every invoice, its process map, variants, conformance and
cycle times.

Every invoice is a case, and the ledger already holds the time of each step of its process:

    PO raised          purchase_orders.po_date
    Goods received     goods_receipts.receipt_date
    Invoice dated      invoices.date
    Escalated          each approval-log entry with action "Escalated" (an approver passing it up)
    Approved           the approval-log entry with action "Approved" (the last one, as the controls read it)
    Due                invoices.due_date

From that event log (van der Aalst, "Process Mining: Data Science in Action", 2016) this module derives:

    process map    the directly-follows graph: how often one step is directly followed by another, and the median
                   time between them
    variants       the distinct orders of steps, with how many invoices follow each
    conformance    each invoice against the reference model PO -> GRN -> invoice -> (escalations) -> approval -> due:
                   a step missing, or two steps in the wrong order (an invoice dated before its goods arrived, an
                   approval before the invoice, an approval after the due date), with how many of those invoices the
                   latest audit already flagged
    cycle times    median and 90th percentile days of each stage, and of approval by the approving role

Nothing here is a finding: it describes how the process ran and where it left its path. Read-only, by code, no model.
On the generated ledgers almost every invoice follows the reference model; the deviations there are the invoices
without a PO or a goods receipt, which rule 2.1.3 already flags.
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import date, datetime

from . import db

STEPS = ("PO raised", "Goods received", "Invoice dated", "Escalated", "Approved", "Due")
REFERENCE = ("PO raised", "Goods received", "Invoice dated", "Approved", "Due")     # escalations may come before approval
STAGES = (("PO raised", "Goods received"), ("Goods received", "Invoice dated"), ("Invoice dated", "Approved"),
          ("Approved", "Due"), ("PO raised", "Approved"))
SHOW = 20                   # variants and examples listed


def _when(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    try:
        return datetime.fromisoformat(str(value)[:19])
    except ValueError:
        return None


def event_log(conn: db.Database) -> dict[str, list[tuple[str, datetime]]]:
    """Every invoice's events, in order of time (a step's place in STEPS breaks ties: an approval stamped the day an
    invoice is dated comes after it)."""
    po = {r[0]: _when(r[1]) for r in conn.execute("SELECT po_id, po_date FROM purchase_orders")}
    grn = {r[0]: _when(r[1]) for r in conn.execute("SELECT grn_id, receipt_date FROM goods_receipts")}
    logs: dict[str, list[tuple[str, datetime]]] = defaultdict(list)
    approved: dict[str, datetime] = {}
    for transaction, action, at in conn.execute(
            "SELECT transaction_id, action_taken, timestamp FROM approval_logs ORDER BY timestamp, log_id"):
        when = _when(at)
        if when is None:
            continue
        if action == "Approved":
            approved[transaction] = when                     # the last approval wins, as in the controls
        elif action == "Escalated":
            logs[transaction].append(("Escalated", when))
    cases = {}
    for invoice_id, po_id, grn_id, day, due in conn.execute(
            "SELECT invoice_id, po_id, grn_id, date, due_date FROM invoices"):
        events = [("PO raised", po.get(po_id)), ("Goods received", grn.get(grn_id)), ("Invoice dated", _when(day)),
                  *logs.get(invoice_id, []), ("Approved", approved.get(invoice_id)), ("Due", _when(due))]
        events = [(step, at) for step, at in events if at is not None]
        events.sort(key=lambda e: (e[1], STEPS.index(e[0])))
        cases[invoice_id] = events
    return cases


def _days(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 86400


def _stats(values: list[float]) -> dict:
    if not values:
        return {"cases": 0, "median": None, "p90": None}
    ordered = sorted(values)
    return {"cases": len(values), "median": round(statistics.median(ordered), 2),
            "p90": round(ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))], 2)}


def deviations(events: list[tuple[str, datetime]]) -> list[str]:
    """How a case leaves the reference model."""
    at = {}
    for step, when in events:
        at.setdefault(step, when)                         # the first time of each step
    out = [f"no {step.lower()}" for step in ("PO raised", "Goods received", "Approved") if step not in at]
    order = [("Goods received", "Invoice dated", "invoice dated before the goods were received"),
             ("PO raised", "Invoice dated", "invoice dated before the PO was raised"),
             ("PO raised", "Goods received", "goods received before the PO was raised"),
             ("Invoice dated", "Approved", "approved before the invoice was dated"),
             ("Approved", "Due", "approved after the due date")]
    for first, then, text in order:
        if first in at and then in at and at[then] < at[first].replace(hour=0, minute=0, second=0):
            out.append(text)
    return out


def mine(conn: db.Database) -> dict:
    """The process map, variants, conformance and cycle times of the store's ledger."""
    cases = event_log(conn)
    flagged = {r[0]: r[1] for r in conn.execute(
        "SELECT l.invoice_id, COUNT(f.flag_id) FROM v_latest_results l LEFT JOIN audit_flags f ON "
        "f.result_id = l.result_id AND f.status = 'kept' GROUP BY l.invoice_id")}
    roles = {}
    for transaction, role in conn.execute("SELECT transaction_id, approver_role FROM approval_logs WHERE action_taken = "
                                          "'Approved' ORDER BY timestamp, log_id"):
        roles[transaction] = role
    activity = Counter()
    edges: dict[tuple[str, str], list[float]] = defaultdict(list)
    variants: dict[tuple, list[str]] = defaultdict(list)
    stage_days: dict[str, list[float]] = defaultdict(list)
    approval_by_role: dict[str, list[float]] = defaultdict(list)
    escalations = Counter()
    kinds: dict[str, list[str]] = defaultdict(list)
    for invoice_id, events in cases.items():
        steps = [s for s, _ in events]
        activity.update(steps)
        for (a, ta), (b, tb) in zip(events, events[1:]):
            edges[(a, b)].append(_days(ta, tb))
        collapsed = tuple(s for k, s in enumerate(steps) if not (s == "Escalated" and k and steps[k - 1] == "Escalated"))
        variants[collapsed].append(invoice_id)
        at = {}
        for step, when in events:
            at.setdefault(step, when)
        for a, b in STAGES:
            if a in at and b in at:
                stage_days[f"{a} -> {b}"].append(_days(at[a], at[b]))
        if "Invoice dated" in at and "Approved" in at and roles.get(invoice_id):
            approval_by_role[roles[invoice_id]].append(_days(at["Invoice dated"], at["Approved"]))
        escalations[steps.count("Escalated")] += 1
        for kind in deviations(events):
            kinds[kind].append(invoice_id)
    conformant = sum(1 for events in cases.values() if not deviations(events))
    reference = set(REFERENCE)
    ranked = sorted(variants.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    total = len(cases)
    return {
        "cases": total, "events": sum(activity.values()), "steps": list(STEPS), "reference": list(REFERENCE),
        "conformant": conformant, "conformant_share": round(conformant / total, 4) if total else None,
        "activities": [{"step": s, "cases": activity.get(s, 0)} for s in STEPS],
        "edges": sorted(({"from": a, "to": b, "cases": len(v), "median_days": round(statistics.median(v), 2)}
                         for (a, b), v in edges.items()), key=lambda e: -e["cases"]),
        "variants": [{"steps": list(k), "cases": len(v), "share": round(len(v) / total, 4),
                      "follows_reference": set(k) - {"Escalated"} == reference
                      and [s for s in k if s != "Escalated"] == list(REFERENCE),
                      "examples": sorted(v)[:5]} for k, v in ranked[:SHOW]],
        "variant_count": len(variants),
        "deviations": sorted(({"kind": k, "cases": len(v),
                               "flagged_by_audit": sum(1 for i in v if flagged.get(i)),
                               "audited": sum(1 for i in v if i in flagged),
                               "examples": sorted(v)[:8]} for k, v in kinds.items()), key=lambda d: -d["cases"]),
        "cycle_times": [{"stage": stage, **_stats(v)} for stage, v in stage_days.items()],
        "approval_by_role": sorted(({"role": role, **_stats(v)} for role, v in approval_by_role.items()),
                                   key=lambda r: -(r["median"] or 0)),
        "escalations": [{"times": k, "cases": n} for k, n in sorted(escalations.items())],
    }
