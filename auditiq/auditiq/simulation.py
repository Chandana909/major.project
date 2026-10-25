"""What a policy document would do to the ledger, before it is adopted: a dry run of the controls.

The survey of LLM multi-agent systems in finance (Liu et al., 2026) names policy evaluation, simulating the
effect of a policy before it applies, among the uses of such systems. For the rules the controls decide the
simulation is exact: every invoice of the stored ledger is audited by the twelve controls under the active
policy and under the new document, in memory, and the two are compared. Nothing is stored.

    simulate(conn, registry) -> {invoices, decisions_moved, newly_flagged, cleared, routes, route_changes,
                                 findings_by_rule, amount_newly_held, examples}

A decision moves when the set of rules an invoice violates changes (the displacement of RESULTS.md, Section
3.2). Routes are those of configuration C1. The judgement rules, which need a model, are not simulated.
"""
from __future__ import annotations

from collections import Counter

from . import db, scoring
from .controls import run_controls

OPTIONS = scoring.ScoringOptions(use_confidence=False)        # configuration C1: controls, no confidence


def _route(txn: dict, clauses: dict) -> tuple[set[str], str]:
    flags = [scoring.normalize_flag(f, clauses) for f in run_controls(txn, clauses)]
    return {f["clause"] for f in flags}, scoring.score(flags, OPTIONS)["route"]


def simulate(conn: db.Database, registry: dict, examples: int = 20) -> dict:
    active = db.read_policy(conn)
    before_clauses, after_clauses = active.registry["clauses"], registry["clauses"]
    transactions = db.extract_many(conn, db.invoice_ids(conn))
    routes_before, routes_after, changes = Counter(), Counter(), Counter()
    rules_before, rules_after = Counter(), Counter()
    moved, newly, cleared, held, shown = 0, 0, 0, 0.0, []
    for txn in transactions:
        b_rules, b_route = _route(txn, before_clauses)
        a_rules, a_route = _route(txn, after_clauses)
        routes_before[b_route] += 1
        routes_after[a_route] += 1
        rules_before.update(b_rules)
        rules_after.update(a_rules)
        if b_route != a_route:
            changes[f"{b_route} -> {a_route}"] += 1
        if a_route == "escalate" and b_route != "escalate":
            held += float(txn["invoice"]["amount"] or 0)
        if b_rules != a_rules:
            moved += 1
            newly += not b_rules and bool(a_rules)
            cleared += bool(b_rules) and not a_rules
            if len(shown) < examples:
                shown.append({"invoice_id": txn["invoice"]["invoice_id"], "amount": txn["invoice"]["amount"],
                              "before": sorted(b_rules), "after": sorted(a_rules), "route_before": b_route,
                              "route_after": a_route})
    rules = sorted(set(rules_before) | set(rules_after))
    return {"active_version": active.version, "new_version": registry.get("version"),
            "invoices": len(transactions), "decisions_moved": moved, "newly_flagged": newly, "cleared": cleared,
            "routes": {"before": dict(routes_before), "after": dict(routes_after)},
            "route_changes": dict(changes.most_common()),
            "findings_by_rule": [{"rule": r, "before": rules_before[r], "after": rules_after[r]} for r in rules],
            "amount_newly_held": round(held, 2), "examples": shown}
