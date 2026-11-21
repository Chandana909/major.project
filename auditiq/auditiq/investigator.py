"""The trail investigator: an agent that audits the audit. It reads the stored audit record and reports what happened,
where, and what needs attention.

The audit trail says what the pipeline and the reviewers did; this module checks how it was done. Every check is a
predicate over the store, run by code, so the same store always gives the same report:

    integrity       every seal and chained hash recomputed (auditiq/seal.py): nothing stored was changed after
                    the fact (ISA 230)
    evidence        the records each latest result was based on are still the ones in the ledger
    completeness    each latest result's trail has its stages, in order: extraction, controls, the model's calls
                    for a configuration with agents, scoring
    coverage        invoices never audited, and invoices last audited under a policy version that does not govern
                    their date
    model failures  results of which a model stage failed: the decision rests on fewer agents than designed
    backlog         invoices waiting for a reviewer, and for how long (a service level, 5 days by default)
    documentation   decisions whose written reason is missing or a single word: a decision must be documented so
                    that an experienced auditor can understand it (ISA 230, paragraph 8)
    pace            decisions in bursts too fast for the evidence to have been read (rubber-stamping)
    segregation     a reviewer who decides on an invoice they approved for payment, or whose purchase order they
                    raised: the same person on both sides of a control (COSO principle 10)
    overrides       invoices with a critical finding cleared by a reviewer, and reviewers who clear one vendor's
                    critical invoices repeatedly
    superseded      a reviewer's rejection followed by a newer result that lets the invoice through: re-auditing
                    until the answer changes ("opinion shopping") unless the policy or the records changed
    flips           invoices whose outcome changed between consecutive audits, with the cause (another policy
                    version, another configuration, changed records) or with none, which is the case to look at

The report adds the timeline of the engagement (runs, decisions, documents) and, for any invoice, its story: every
record, audit, finding, decision and e-mail in order (``story``). ``render_markdown`` writes the report as text a
person can read; every number in it comes from the checks.

What it cannot see: anything done outside the store (a decision taken on paper, a result deleted with its run before
any digest was kept), and whether a justification, though long, is true.
"""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime

from . import db, emails, seal

SLA_DAYS = 5.0
MIN_REASON = 20                     # characters a justification needs to count as one
BOILERPLATE = {"ok", "okay", "approved", "approve", "fine", "done", "checked", "yes", "no", "na", "n/a", "nil", "-",
               ".", "reviewed", "as per policy", "correct", "valid", "good", "rejected", "reject"}
BURST_GAP_S = 30.0                  # decisions closer than this, one after another, are a burst
BURST_MIN = 5                       # decisions in a row that make a burst
REPEAT_CLEARANCES = 3               # one reviewer clearing this many critical invoices of one vendor
SHOW = 50                           # items listed per check; the counts cover all
STAGES = ("extraction", "controls", "scoring")
SEVERITY_ORDER = ("fail", "attention", "pass")


def _time(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(value)[:19])
    except ValueError:
        return None


def _rows(cursor) -> list[dict]:
    return [dict(zip(r.keys(), tuple(r))) for r in cursor.fetchall()]


def _check(key: str, title: str, standard: str, status: str, summary: str, items: list[dict], why: str,
           action: str, count: int | None = None) -> dict:
    return {"key": key, "title": title, "standard": standard, "status": status, "summary": summary,
            "count": len(items) if count is None else count, "items": items[:SHOW], "why": why, "action": action}


# ------------------------------------------------------------------ the checks
def check_integrity(conn: db.Database) -> dict:
    report = seal.verify(conn)
    r, e, u = report["results"], report["entries"], report["runs"]
    items = ([{"where": f"result {i}", "result_id": i, "what": "the result no longer matches its seal"}
              for i in r["altered_ids"]]
             + [{"where": f"result {i}", "result_id": i, "what": "the state is not the decision its trail records"}
                for i in r["review_inconsistent_ids"]]
             + [{"where": f"trail entry {i}", "entry_id": i, "what": "the chained hash breaks here"} for i in e["broken_ids"]]
             + [{"where": f"run {i}", "run_id": i, "what": "the run's results changed after it was sealed"}
                for i in u["altered_ids"]])
    count = r["altered"] + r["review_inconsistent"] + e["broken"] + u["altered"]
    summary = (f"{r['sealed']:,} of {r['checked']:,} results, {e['checked']:,} trail entries and {u['sealed']:,} runs "
               "match their seals" if report["intact"] else
               f"{count:,} item(s) no longer match their seals: {r['altered']} results, {r['review_inconsistent']} "
               f"review states, {e['broken']} trail entries, {u['altered']} runs")
    return _check("integrity", "The sealed record", "ISA 230", "pass" if report["intact"] else "fail", summary, items,
                  "Audit documentation must not change after the fact; a mismatch means a row was edited outside the "
                  "application.", "Restore the rows from a backup or an export, find who had write access to the "
                  "store, and compare the run digest with the copy kept outside it.", count)


def check_evidence(conn: db.Database) -> dict:
    drift = seal.evidence_drift(conn)
    items = [{"where": i["invoice_id"], "invoice_id": i["invoice_id"],
              "what": f"its {', '.join(i['changed'])} record(s) changed after the audit"} for i in drift["changed_invoices"]]
    return _check("evidence", "Evidence still in the ledger", "ISA 500", "pass" if not drift["changed"] else "attention",
                  f"{drift['unchanged']:,} of {drift['fingerprinted']:,} fingerprinted results still describe their "
                  f"records" + (f"; {drift['changed']:,} were based on records changed since" if drift["changed"] else ""),
                  items, "A result describes the records it read; when they change, the result no longer describes "
                  "the invoice.", "Audit the listed invoices again and ask why their records changed after the "
                  "audit.", drift["changed"])


def check_completeness(conn: db.Database) -> dict:
    stages: dict[int, list[str]] = defaultdict(list)
    for result_id, stage in conn.execute(
            "SELECT t.result_id, t.stage FROM audit_trail t JOIN latest_results m ON m.result_id = t.result_id "
            "ORDER BY t.result_id, t.seq, t.entry_id"):
        stages[int(result_id)].append(stage)
    latest = _rows(conn.execute("SELECT result_id, invoice_id, configuration, llm_calls FROM v_latest_results"))
    items = []
    for row in latest:
        seen = stages.get(int(row["result_id"]), [])
        problems = []
        missing = [s for s in STAGES if s not in seen]
        if missing:
            problems.append("no " + ", ".join(missing) + " stage")
        elif not seen.index("extraction") < seen.index("controls") < seen.index("scoring"):
            problems.append("stages out of order")
        model_steps = [s for s in seen if s not in STAGES and s != "review"]
        if row["configuration"] != "C1" and int(row["llm_calls"] or 0) != len(model_steps):
            problems.append(f"{row['llm_calls']} model calls counted, {len(model_steps)} in the trail")
        if problems:
            items.append({"where": row["invoice_id"], "invoice_id": row["invoice_id"], "result_id": row["result_id"],
                          "what": "; ".join(problems)})
    return _check("completeness", "Every audit fully recorded", "ISA 230", "fail" if items else "pass",
                  f"{len(latest) - len(items):,} of {len(latest):,} latest results have every stage in their trail",
                  items, "The trail is the record of how a result was reached; a missing stage cannot be re-performed.",
                  "Audit the listed invoices again; a gap that recurs points to a fault in the pipeline.")


def check_coverage(conn: db.Database) -> dict:
    governing = db.versions_in_force(conn)
    latest = dict(conn.execute("SELECT invoice_id, policy_version FROM v_latest_results").fetchall())
    never = sorted(i for i in governing if i not in latest)
    other = sorted(i for i, v in governing.items() if i in latest and latest[i] != v)
    ungoverned = int(conn.scalar("SELECT COUNT(*) FROM invoices") or 0) - len(governing)
    items = ([{"where": i, "invoice_id": i, "what": "never audited"} for i in never[:SHOW]]
             + [{"where": i, "invoice_id": i, "what": f"audited under v{latest[i]}; v{governing[i]} governs its date"}
                for i in other[:SHOW]])
    total = len(never) + len(other)
    status = "pass" if not total else ("fail" if other else "attention")
    return _check("coverage", "Every invoice audited under the policy in force", "ISA 330", status,
                  f"{len(governing) - total:,} of {len(governing):,} invoices have a result under the version in force "
                  f"on their date; {len(never):,} never audited, {len(other):,} under another version"
                  + (f"; {ungoverned:,} dated before any version took effect" if ungoverned else ""),
                  items, "An invoice outside the audit, or judged by rules that did not apply on its date, is not "
                  "covered by the audit's conclusion.", "Apply the policy timeline (python -m auditiq policy apply) "
                  "and audit what was never audited.", total)


def check_model_failures(conn: db.Database) -> dict:
    rows = _rows(conn.execute("SELECT invoice_id, result_id, configuration, failed_stages FROM v_latest_results "
                              "WHERE failed_stages > 0 ORDER BY failed_stages DESC, invoice_id"))
    items = [{"where": r["invoice_id"], "invoice_id": r["invoice_id"], "result_id": r["result_id"],
              "what": f"{r['failed_stages']} model stage(s) failed under {r['configuration']}"} for r in rows]
    return _check("model_failures", "Model stages that failed", "ISA 500 (reliability of automated tools)",
                  "attention" if items else "pass",
                  f"{len(items):,} latest results lost a model stage" if items else "no latest result lost a model stage",
                  items, "A stage that fails contributes no finding, so the decision rests on fewer checks than the "
                  "configuration promises.", "Audit the listed invoices again once the model answers.")


def check_backlog(conn: db.Database, now: datetime, sla_days: float = SLA_DAYS) -> dict:
    rows = _rows(conn.execute("SELECT invoice_id, result_id, risk_level, amount, created_at FROM v_review_queue"))
    ages = []
    for r in rows:
        created = _time(r["created_at"])
        r["age_days"] = round((now - created).total_seconds() / 86400, 2) if created else None
        ages.append(r["age_days"] or 0.0)
    late = sorted((r for r in rows if (r["age_days"] or 0) > sla_days), key=lambda r: -(r["age_days"] or 0))
    items = [{"where": r["invoice_id"], "invoice_id": r["invoice_id"], "result_id": r["result_id"],
              "what": f"waiting {r['age_days']:.1f} days ({r['risk_level']}, ₹{float(r['amount'] or 0):,.2f})"}
             for r in late]
    oldest = max(ages) if ages else 0.0
    return _check("backlog", f"Reviews waiting longer than {sla_days:g} days", "service level",
                  "attention" if late else "pass",
                  f"{len(rows):,} invoices waiting; {len(late):,} beyond {sla_days:g} days; the oldest "
                  f"{oldest:.1f} days" if rows else "nothing is waiting for review",
                  items, "An escalated invoice that waits is either paid unreviewed or holds up a vendor.",
                  "Assign the oldest items first.", len(late))


def _decisions(conn: db.Database) -> list[dict]:
    rows = _rows(conn.execute(
        "SELECT d.decision_id, d.result_id, d.decision, d.reviewer, d.justification, d.decided_at, r.invoice_id, "
        "r.vendor_id, r.route, r.risk_level, r.created_at FROM review_decisions d "
        "JOIN audit_results r ON r.result_id = d.result_id ORDER BY d.decided_at, d.decision_id"))
    critical = {int(r[0]) for r in conn.execute(
        "SELECT DISTINCT result_id FROM audit_flags WHERE status = 'kept' AND severity = 'critical'")}
    for r in rows:
        r["at"] = _time(r["decided_at"])
        r["critical"] = int(r["result_id"]) in critical or r["risk_level"] == "CRITICAL"
    return rows


def check_documentation(decisions: list[dict]) -> dict:
    items = []
    for d in decisions:
        reason = " ".join(str(d["justification"] or "").split())
        if len(reason) < MIN_REASON or reason.lower().strip(" .!") in BOILERPLATE:
            weight = "high" if d["decision"] in ("approve", "override") and d["critical"] else "medium"
            items.append({"where": d["invoice_id"], "invoice_id": d["invoice_id"], "result_id": d["result_id"],
                          "reviewer": d["reviewer"], "severity": weight,
                          "what": f"{d['reviewer']} {d['decision']}d it with " +
                                  (f"the reason '{reason}'" if reason else "no reason")})
    items.sort(key=lambda i: (i["severity"] != "high", i["invoice_id"]))
    high = sum(i["severity"] == "high" for i in items)
    return _check("documentation", "Decisions with a written reason", "ISA 230, paragraph 8",
                  "fail" if high else ("attention" if items else "pass"),
                  f"{len(decisions) - len(items):,} of {len(decisions):,} decisions give a reason; {len(items):,} do not"
                  + (f", {high:,} of them clearing a critical invoice" if high else ""),
                  items, "A decision without its reason cannot be understood or defended by another auditor.",
                  "Ask the reviewers to complete the reasons; refuse a clearance of a critical invoice without one.")


def check_pace(decisions: list[dict], gap_s: float = BURST_GAP_S, minimum: int = BURST_MIN) -> dict:
    by_reviewer: dict[str, list[dict]] = defaultdict(list)
    for d in decisions:
        if d["at"] is not None:
            by_reviewer[d["reviewer"]].append(d)
    bursts = []
    for reviewer, items in by_reviewer.items():
        items.sort(key=lambda d: (d["at"], d["decision_id"]))
        run = [items[0]] if items else []
        for previous, current in zip(items, items[1:]):
            if (current["at"] - previous["at"]).total_seconds() <= gap_s:
                run.append(current)
                continue
            if len(run) >= minimum:
                bursts.append((reviewer, run))
            run = [current]
        if len(run) >= minimum:
            bursts.append((reviewer, run))
    out = []
    for reviewer, run in bursts:
        gaps = [(b["at"] - a["at"]).total_seconds() for a, b in zip(run, run[1:])]
        cleared = sum(d["decision"] in ("approve", "override") for d in run)
        out.append({"where": f"{reviewer}, {run[0]['at']:%Y-%m-%d %H:%M:%S} to {run[-1]['at']:%H:%M:%S}",
                    "reviewer": reviewer, "decisions": len(run), "cleared": cleared,
                    "median_gap_s": statistics.median(gaps) if gaps else None,
                    "invoices": [d["invoice_id"] for d in run][:20],
                    "what": f"{len(run)} decisions, a median of {statistics.median(gaps):.0f} s apart; {cleared} cleared"})
    total = sum(o["decisions"] for o in out)
    return _check("pace", "Time taken per decision", "ISA 220 (direction, supervision and review)",
                  "fail" if any(o["cleared"] for o in out) else ("attention" if out else "pass"),
                  f"{len(out)} burst(s) of at least {minimum} decisions under {gap_s:g} s apart, {total:,} decisions in all"
                  if out else f"no reviewer made {minimum} decisions in a row under {gap_s:g} s apart",
                  out, "A decision taken in seconds cannot rest on reading the evidence: the review exists on paper only.",
                  "Re-review the invoices of each burst with another reviewer.", total)


def check_segregation(conn: db.Database, decisions: list[dict]) -> dict:
    if not decisions:
        return _check("segregation", "Reviewer independent of the transaction", "COSO principle 10; SOX 404", "pass",
                      "no decisions yet", [], "", "")
    ids = sorted({d["invoice_id"] for d in decisions})
    approvers: dict[str, set] = defaultdict(set)
    requesters: dict[str, str] = {}
    for start in range(0, len(ids), db.FEW):
        part = ids[start:start + db.FEW]
        marks = ", ".join("?" for _ in part)
        for invoice_id, name in conn.execute(f"SELECT transaction_id, approver_name FROM approval_logs "
                                             f"WHERE transaction_id IN ({marks})", part):
            approvers[invoice_id].add(str(name or "").strip().lower())
        for invoice_id, requester in conn.execute(f"SELECT i.invoice_id, p.requester FROM invoices i JOIN "
                                                  f"purchase_orders p ON p.po_id = i.po_id WHERE i.invoice_id IN ({marks})",
                                                  part):
            requesters[invoice_id] = str(requester or "").strip().lower()
    items = []
    for d in decisions:
        who = str(d["reviewer"] or "").strip().lower()
        roles = (["approved it for payment"] if who in approvers.get(d["invoice_id"], set()) else []) + \
                (["raised its purchase order"] if who and requesters.get(d["invoice_id"]) == who else [])
        if who and roles:
            items.append({"where": d["invoice_id"], "invoice_id": d["invoice_id"], "result_id": d["result_id"],
                          "reviewer": d["reviewer"], "what": f"{d['reviewer']} {' and '.join(roles)}, then "
                                                             f"{d['decision']}d its audit result"})
    return _check("segregation", "Reviewer independent of the transaction", "COSO principle 10; SOX 404",
                  "fail" if items else "pass",
                  f"{len(items):,} decisions by a reviewer who was part of the transaction" if items else
                  f"none of {len(decisions):,} decisions was taken by the invoice's approver or requester",
                  items, "A person who approved a payment, or ordered the goods, reviewing the audit of it marks their "
                  "own work.", "Re-assign these invoices to an independent reviewer and block the pairing in the "
                  "review tool.")


def check_overrides(decisions: list[dict]) -> dict:
    cleared = [d for d in decisions if d["critical"] and d["decision"] in ("approve", "override")]
    per_pair = Counter((d["reviewer"], d["vendor_id"]) for d in cleared)
    repeated = {pair for pair, n in per_pair.items() if n >= REPEAT_CLEARANCES}
    items = [{"where": d["invoice_id"], "invoice_id": d["invoice_id"], "result_id": d["result_id"],
              "reviewer": d["reviewer"], "vendor_id": d["vendor_id"],
              "repeated": (d["reviewer"], d["vendor_id"]) in repeated,
              "what": f"{d['reviewer']} {d['decision']}d a critical invoice of {d['vendor_id']}"
                      + (f" (the {per_pair[(d['reviewer'], d['vendor_id'])]}th of this vendor's by this reviewer)"
                         if (d["reviewer"], d["vendor_id"]) in repeated else "")} for d in cleared]
    items.sort(key=lambda i: (not i["repeated"], i["reviewer"], i["invoice_id"]))
    return _check("overrides", "Critical findings cleared by a reviewer", "ISA 240 (management override)",
                  "fail" if repeated else ("attention" if cleared else "pass"),
                  f"{len(cleared):,} invoices with a critical finding cleared; {len(repeated)} reviewer-vendor "
                  f"pair(s) with {REPEAT_CLEARANCES} or more" if cleared else "no critical finding was cleared",
                  items, "Clearing a critical finding is allowed with a reason; the same reviewer clearing one "
                  "vendor's critical invoices again and again is the pattern of an override.",
                  "Have a second reviewer confirm each clearance of a critical finding.", len(cleared))


def _history(conn: db.Database, invoice_ids: list[str] | None = None) -> dict[str, list[dict]]:
    """Every result of each invoice audited more than once, oldest first."""
    where = ""
    params: list = []
    if invoice_ids is not None:
        where = f"AND r.invoice_id IN ({', '.join('?' for _ in invoice_ids)})"
        params = list(invoice_ids)
    rows = _rows(conn.execute(
        "SELECT r.result_id, r.invoice_id, r.route, r.workflow_status, r.risk_level, r.created_at, r.evidence, "
        "u.configuration, u.policy_version FROM audit_results r JOIN audit_runs u ON u.run_id = r.run_id "
        "WHERE r.invoice_id IN (SELECT invoice_id FROM audit_results GROUP BY invoice_id HAVING COUNT(*) > 1) "
        f"{where} ORDER BY r.invoice_id, r.result_id", params))
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        out[r["invoice_id"]].append(r)
    return out


def _cause(a: dict, b: dict) -> str | None:
    causes = []
    if a["policy_version"] != b["policy_version"]:
        causes.append(f"policy v{a['policy_version']} to v{b['policy_version']}")
    if a["configuration"] != b["configuration"]:
        causes.append(f"configuration {a['configuration']} to {b['configuration']}")
    if a["evidence"] is not None and b["evidence"] is not None and a["evidence"] != b["evidence"]:
        causes.append("the records changed")
    return ", ".join(causes) or None


def check_flips(history: dict[str, list[dict]]) -> dict:
    items = []
    for invoice_id, results in history.items():
        for a, b in zip(results, results[1:]):
            if a["route"] != b["route"]:
                cause = _cause(a, b)
                items.append({"where": invoice_id, "invoice_id": invoice_id, "result_id": b["result_id"],
                              "from": a["route"], "to": b["route"], "cause": cause, "unexplained": cause is None,
                              "what": f"{a['route']} to {b['route']}: " + (cause or "nothing that the audit depends on "
                                                                            "changed")})
    unexplained = [i for i in items if i["unexplained"]]
    items.sort(key=lambda i: (not i["unexplained"], i["invoice_id"]))
    return _check("flips", "Outcomes that changed between audits", "ISA 230 (consistency of the record)",
                  "fail" if unexplained else ("attention" if items else "pass"),
                  f"{len(items):,} changes of route between consecutive audits; {len(unexplained):,} with no change of "
                  "policy, configuration or records" if items else "no invoice changed route between audits",
                  items, "The same records under the same policy and configuration should give the same outcome; a "
                  "change without a cause is a model's inconsistency or an edit.", "Look at the unexplained ones "
                  "first; for a model configuration compare the agents' replies in the trail.", len(items))


def check_superseded(conn: db.Database, history: dict[str, list[dict]]) -> dict:
    decided = {int(r[0]): r[1] for r in conn.execute("SELECT result_id, decision FROM review_decisions")}
    items = []
    for invoice_id, results in history.items():
        for a in results[:-1]:
            if decided.get(int(a["result_id"])) not in ("reject",):
                continue
            later = results[-1]
            if later["workflow_status"] in (db.AUTO_APPROVED, db.NOT_SAMPLED, db.REVIEWED["approve"],
                                            db.REVIEWED["override"]):
                cause = _cause(a, later)
                items.append({"where": invoice_id, "invoice_id": invoice_id, "result_id": later["result_id"],
                              "rejected_result": a["result_id"], "now": later["workflow_status"], "cause": cause,
                              "what": f"rejected by a reviewer, then let through as {later['workflow_status']} by a "
                                      f"later audit" + (f" ({cause})" if cause else " with nothing changed")})
    return _check("superseded", "Rejections undone by a later audit", "ISA 220; ISA 240",
                  "fail" if any(i["cause"] is None for i in items) else ("attention" if items else "pass"),
                  f"{len(items):,} invoices rejected by a reviewer now pass on a newer result" if items else
                  "no rejected invoice passes on a newer result",
                  items, "A rejection is a decision; auditing again until the answer changes overturns it without "
                  "a second reviewer.", "Require a reviewer's decision before a newer result can release an invoice "
                  "that was rejected.")


# ------------------------------------------------------------------ timeline and stories
def timeline(conn: db.Database, limit: int = 400) -> dict:
    """What happened, in order: runs, decisions (by day and reviewer), documents ingested, policies taking effect."""
    events = []
    for r in _rows(conn.execute(
            "SELECT u.run_id, u.configuration, u.policy_version, u.model, u.note, u.started_at, u.finished_at, "
            "COUNT(r.result_id) AS results, SUM(CASE WHEN r.flag_count > 0 THEN 1 ELSE 0 END) AS flagged "
            "FROM audit_runs u LEFT JOIN audit_results r ON r.run_id = u.run_id GROUP BY u.run_id, u.configuration, "
            "u.policy_version, u.model, u.note, u.started_at, u.finished_at")):
        events.append({"at": str(r["started_at"] or ""), "kind": "run", "where": f"run {r['run_id']}",
                       "what": f"{r['configuration']} under policy v{r['policy_version']}: {int(r['results'] or 0):,} "
                               f"results, {int(r['flagged'] or 0):,} with findings"
                               + (f" ({r['note']})" if r["note"] else "")
                               + ("" if r["finished_at"] else "; never finished")})
    for day, reviewer, decision, n in conn.execute(
            "SELECT SUBSTR(CAST(decided_at AS TEXT), 1, 10), reviewer, decision, COUNT(*) FROM review_decisions "
            "GROUP BY SUBSTR(CAST(decided_at AS TEXT), 1, 10), reviewer, decision"):
        events.append({"at": f"{day} 23:59:59", "kind": "review", "where": reviewer,
                       "what": f"{reviewer}: {int(n):,} {decision} decision(s) on {day}"})
    for name, version, at in conn.execute("SELECT file_name, version, ingested_at FROM policy_documents"):
        events.append({"at": str(at or ""), "kind": "document", "where": name,
                       "what": f"policy document {name} ingested" + (f" (v{version})" if version else "")})
    for version, effective in conn.execute("SELECT version, effective_date FROM company_policies"):
        events.append({"at": f"{str(effective)[:10]} 00:00:00", "kind": "policy", "where": f"v{version}",
                       "what": f"policy v{version} takes effect"})
    events.sort(key=lambda e: e["at"])
    by_kind = Counter(e["kind"] for e in events)
    return {"events": events[-limit:], "total": len(events), "by_kind": dict(by_kind)}


def story(conn: db.Database, invoice_id: str) -> dict | None:
    """The life of one invoice, in order: its records, every audit of it with findings and trail, every decision,
    the vendor e-mails that name it, and where it stands."""
    txn = db.extract_one(conn, invoice_id)
    if txn is None:
        return None
    inv, vendor = txn["invoice"], txn["vendor"] or {}
    steps = [{"at": str(inv["date"])[:10], "kind": "ledger",
              "what": f"Invoice {inv['invoice_number']} of ₹{float(inv['amount'] or 0):,.2f} from {vendor.get('vendor_name', inv['vendor_id'])}"
                      f" ({inv['vendor_id']}), PO {inv.get('po_id') or 'none'}, GRN {inv.get('grn_id') or 'none'}"}]
    if txn.get("po"):
        steps.append({"at": str(txn["po"].get("po_date") or "")[:10], "kind": "ledger",
                      "what": f"Purchase order {txn['po']['po_id']} for ₹{float(txn['po'].get('amount') or 0):,.2f}"})
    if txn.get("grn"):
        steps.append({"at": str(txn["grn"].get("receipt_date") or "")[:10], "kind": "ledger",
                      "what": f"Goods receipt {txn['grn']['grn_id']}: {txn['grn'].get('received_quantity')} received"
                              + (f"; remark: {txn['grn']['notes']}" if txn["grn"].get("notes") else "")})
    for a in txn["approvals"]:
        steps.append({"at": str(a.get("timestamp") or "")[:19], "kind": "approval",
                      "what": f"{a.get('action_taken')} by {a.get('approver_name')} ({a.get('approver_role')})"})
    for mail in emails.for_invoice(conn, invoice_id):
        steps.append({"at": str(mail.get("sent_at") or ""), "kind": "email",
                      "what": f"E-mail from {mail['sender']}: {mail['subject']}"})
    results = _rows(conn.execute(
        "SELECT r.result_id, r.run_id, r.route, r.risk_level, r.rc, r.workflow_status, r.created_at, r.seal, "
        "u.configuration, u.policy_version FROM audit_results r JOIN audit_runs u ON u.run_id = r.run_id "
        "WHERE r.invoice_id = ? ORDER BY r.result_id", (invoice_id,)))
    for r in results:
        found = [f"{c} ({s})" for c, s in conn.execute(
            "SELECT clause, severity FROM audit_flags WHERE result_id = ? AND status = 'kept' ORDER BY flag_id",
            (r["result_id"],))]
        trail = [s for (s,) in conn.execute("SELECT stage FROM audit_trail WHERE result_id = ? ORDER BY seq",
                                            (r["result_id"],))]
        steps.append({"at": str(r["created_at"] or ""), "kind": "audit", "result_id": r["result_id"],
                      "what": f"Audited in run {r['run_id']} ({r['configuration']}, policy v{r['policy_version']}): "
                              f"{r['route']}, {r['risk_level']}, score {float(r['rc'] or 0):.1f}; "
                              + (f"findings {', '.join(found)}" if found else "no finding")
                              + f"; trail of {len(trail)} steps ({' > '.join(dict.fromkeys(trail))})"})
    for d in _rows(conn.execute("SELECT d.result_id, d.decision, d.reviewer, d.justification, d.decided_at FROM "
                                "review_decisions d JOIN audit_results r ON r.result_id = d.result_id WHERE "
                                "r.invoice_id = ? ORDER BY d.decided_at", (invoice_id,))):
        steps.append({"at": str(d["decided_at"] or ""), "kind": "review", "result_id": d["result_id"],
                      "what": f"{d['reviewer']} {d['decision']}d result {d['result_id']}"
                              + (f": \"{d['justification']}\"" if d["justification"] else " without a reason")})
    steps.sort(key=lambda s: (s["at"], ("ledger", "approval", "email", "audit", "review").index(s["kind"])))
    latest = db.latest_result(conn, invoice_id)
    integrity = None
    if latest is not None:
        integrity = "unsealed" if latest["seal"] is None else (
            "intact" if seal.verify(conn, result_ids=[int(latest["result_id"])])["intact"] else "altered")
    now_state = (f"{latest['workflow_status']} after {len(results)} audit(s); the latest result is {integrity}"
                 if latest is not None else "never audited")
    return {"invoice_id": invoice_id, "vendor_id": inv["vendor_id"], "steps": steps, "audits": len(results),
            "state": now_state}


# ------------------------------------------------------------------ the report
def investigate(conn: db.Database, now: datetime | None = None, sla_days: float = SLA_DAYS) -> dict:
    """Every check, the timeline and the verdict, as one report."""
    now = now or datetime.now().replace(microsecond=0)
    decisions = _decisions(conn)
    history = _history(conn)
    checks = [check_integrity(conn), check_evidence(conn), check_completeness(conn), check_coverage(conn),
              check_model_failures(conn), check_backlog(conn, now, sla_days), check_documentation(decisions),
              check_pace(decisions), check_segregation(conn, decisions), check_overrides(decisions),
              check_superseded(conn, history), check_flips(history)]
    status = Counter(c["status"] for c in checks)
    verdict = ("The audit record needs action: " if status["fail"] else
               "The audit record holds, with points to follow up: " if status["attention"] else
               "The audit record holds: ") + \
        f"{status['fail']} check(s) failed, {status['attention']} need attention, {status['pass']} passed."
    scope = {"ledger": conn.scalar("SELECT value FROM meta WHERE key = 'dataset'"),
             "invoices": int(conn.scalar("SELECT COUNT(*) FROM invoices") or 0),
             "audited": int(conn.scalar("SELECT COUNT(*) FROM latest_results") or 0),
             "results": int(conn.scalar("SELECT COUNT(*) FROM audit_results") or 0),
             "runs": int(conn.scalar("SELECT COUNT(*) FROM audit_runs") or 0),
             "decisions": len(decisions), "reviewers": len({d["reviewer"] for d in decisions}),
             "trail_entries": int(conn.scalar("SELECT COUNT(*) FROM audit_trail") or 0),
             "first": str(conn.scalar("SELECT MIN(started_at) FROM audit_runs") or ""),
             "last": str(max(filter(None, [str(conn.scalar("SELECT MAX(created_at) FROM audit_results") or ""),
                                           str(conn.scalar("SELECT MAX(decided_at) FROM review_decisions") or "")]),
                             default="")),
             "digest": seal.run_digest(conn), "generated": now.isoformat(sep=" ")}
    report = {"verdict": verdict, "status": dict(status), "scope": scope,
              "checks": sorted(checks, key=lambda c: SEVERITY_ORDER.index(c["status"])),
              "timeline": timeline(conn), "reviewers": _reviewer_table(decisions)}
    report["markdown"] = render_markdown(report)
    return report


def _reviewer_table(decisions: list[dict]) -> list[dict]:
    table: dict[str, dict] = {}
    for d in decisions:
        t = table.setdefault(d["reviewer"], {"reviewer": d["reviewer"], "decisions": 0, "approve": 0, "reject": 0,
                                             "override": 0, "critical_cleared": 0, "without_reason": 0})
        t["decisions"] += 1
        t[d["decision"]] = t.get(d["decision"], 0) + 1
        t["critical_cleared"] += int(d["critical"] and d["decision"] in ("approve", "override"))
        t["without_reason"] += int(len(" ".join(str(d["justification"] or "").split())) < MIN_REASON)
    return sorted(table.values(), key=lambda t: -t["decisions"])


def render_markdown(report: dict) -> str:
    s = report["scope"]
    lines = ["# Investigation of the audit record", "",
             f"Generated {s['generated']} from the store of ledger `{s['ledger'] or 'unnamed'}`.", "",
             f"**{report['verdict']}**", "",
             "## Scope", "",
             f"- {s['invoices']:,} invoices in the ledger, {s['audited']:,} with a result; {s['results']:,} results "
             f"in {s['runs']:,} runs; {s['trail_entries']:,} trail entries",
             f"- {s['decisions']:,} review decisions by {s['reviewers']} reviewer(s)",
             f"- activity from {s['first'] or '-'} to {s['last'] or '-'}",
             f"- digest of the sealed runs: `{s['digest'] or 'none'}`", "",
             "## Findings", ""]
    for c in report["checks"]:
        mark = {"fail": "FAIL", "attention": "ATTENTION", "pass": "pass"}[c["status"]]
        lines += [f"### {c['title']}: {mark}", "", f"{c['summary']}. *({c['standard']})*", ""]
        if c["status"] != "pass":
            if c["why"]:
                lines += [f"Why it matters: {c['why']}", ""]
            for item in c["items"][:10]:
                lines.append(f"- **{item['where']}**: {item['what']}")
            if c["count"] > min(10, len(c["items"])):
                lines.append(f"- ... {c['count'] - min(10, len(c['items'])):,} more")
            lines += ["", f"What to do: {c['action']}", ""]
    if report["reviewers"]:
        lines += ["## Reviewers", "", "| Reviewer | Decisions | Approved | Rejected | Overridden | Critical cleared | "
                  "Without a reason |", "|---|---|---|---|---|---|---|"]
        for t in report["reviewers"]:
            lines.append(f"| {t['reviewer']} | {t['decisions']:,} | {t.get('approve', 0):,} | {t.get('reject', 0):,} | "
                         f"{t.get('override', 0):,} | {t['critical_cleared']:,} | {t['without_reason']:,} |")
        lines.append("")
    events = report["timeline"]["events"]
    if events:
        lines += ["## Timeline (latest events)", ""]
        for e in events[-15:]:
            lines.append(f"- {e['at'][:19]} · {e['kind']} · {e['what']}")
        lines.append("")
    lines += ["## Method", "",
              "Every check is a predicate over the store, run by code (auditiq/investigator.py): the same store gives "
              "the same report. The checks cannot see work done outside the store, or whether a reason, though "
              "written, is true.", ""]
    return "\n".join(lines)


def to_json(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=1, default=str)
