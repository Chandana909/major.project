"""Working papers: the engagement in one workbook, tied to the sealed store by a digest.

    python -m auditiq workpapers --out engagement.xlsx      write the workbook, print its digest
    python -m auditiq workpapers --check engagement.xlsx    does the workbook still match the store?

One sheet per part of the audit file (ISA 230): the summary (scope, population, outcome, conclusions), every kept
finding of the latest results, the review queue, the leads under the judgement rules, the monetary-unit sample with
its evaluation, the data-reliability checks, the audit program (which test addresses which assertion and scheme, and
what no test covers), and the integrity of the record (seals, evidence, the digest of the sealed runs).

The report digest is a SHA-256 over every value in the workbook except the time it was written. Written again from
an unchanged store, the workbook has the same digest; after an audit, a decision or a change to the ledger it does
not, which ``check`` reports. The sample's random start is taken from the digest of the sealed runs, so nobody chose
it and anyone with the store draws the same sample.
"""
from __future__ import annotations

import io
from pathlib import Path

from . import audit_program, db, leads, reliability, rings, sampling, seal

SHEETS = ("Summary", "Findings", "Review queue", "Leads", "Sample", "Reliability", "Program", "Integrity")


def sample_seed(conn: db.Database) -> int:
    """A seed nobody chose: from the digest of the sealed runs (1 for a store without one)."""
    digest = seal.run_digest(conn)
    return int(digest[:8], 16) % 1_000_000_000 + 1 if digest else 1


def engagement(conn: db.Database, seed: int | None = None) -> dict:
    """Everything the workbook holds, and its digest."""
    seed = sample_seed(conn) if seed is None else seed
    found_leads = leads.judgement_leads(conn)
    found_rings = rings.find_rings(conn, limit=40)
    try:
        sample = sampling.monetary_unit_sample(conn, seed=seed)
    except ValueError as error:                       # nothing approved yet: no population to sample
        sample = {"error": str(error), "seed": seed}
    reliable = reliability.ledger_reliability(conn)
    program = audit_program.program(conn, leads=found_leads, rings=found_rings)
    record = seal.verify(conn)
    drift = seal.evidence_drift(conn)
    title = {c: t for c, t in conn.execute(
        "SELECT clause_id, title FROM policy_clauses WHERE version = (SELECT version FROM company_policies "
        "WHERE is_active = 1)")}
    findings = [list(r) for r in conn.execute(
        "SELECT l.invoice_id, i.vendor_id, CAST(i.date AS TEXT), i.amount, f.clause, f.severity, f.source, "
        "COALESCE(f.agent, ''), f.message, l.route, l.workflow_status, l.policy_version, l.configuration "
        "FROM audit_flags f JOIN v_latest_results l ON l.result_id = f.result_id JOIN invoices i "
        "ON i.invoice_id = l.invoice_id WHERE f.status = 'kept' ORDER BY l.invoice_id, f.flag_id")]
    for row in findings:
        row.insert(5, title.get(row[4], ""))
    queue = [list(r) for r in conn.execute(
        "SELECT invoice_id, vendor_id, vendor_name, CAST(invoice_date AS TEXT), amount, route, risk_level, rc, "
        "flag_count, configuration FROM v_review_queue ORDER BY rc DESC, invoice_id")]
    states = {s: int(n) for s, n in conn.execute(
        "SELECT workflow_status, COUNT(*) FROM v_latest_results GROUP BY workflow_status ORDER BY workflow_status")}
    runs = [list(r) for r in conn.execute(
        "SELECT u.run_id, u.configuration, u.policy_version, CAST(u.started_at AS TEXT), CAST(u.finished_at AS TEXT), "
        "COUNT(r.result_id), u.seal FROM audit_runs u LEFT JOIN audit_results r ON r.run_id = u.run_id "
        "GROUP BY u.run_id, u.configuration, u.policy_version, u.started_at, u.finished_at, u.seal ORDER BY u.run_id")]
    data = {
        "scope": {"ledger": conn.scalar("SELECT value FROM meta WHERE key = 'dataset'"),
                  "policy_timeline": db.timeline_summary(conn),
                  "invoices": int(conn.scalar("SELECT COUNT(*) FROM invoices") or 0),
                  "amount": round(float(conn.scalar("SELECT COALESCE(SUM(amount), 0) FROM invoices") or 0), 2),
                  "ledger_fingerprint": reliable["fingerprint"]["ledger"]},
        "outcome": {"states": states, "findings": len(findings), "queue": len(queue)},
        "findings": findings, "queue": queue,
        "leads": {"near_duplicates": found_leads["near_duplicates"]["pairs"],
                  "structuring": found_leads["structuring"]["groups"], "answer_key": found_leads["answer_key"]},
        "sample": sample, "reliability": {k: reliable[k] for k in ("totals", "checks", "summary", "fingerprint")},
        "program": {k: program[k] for k in ("tests", "untested", "limits", "answer_key")},
        "integrity": {"record": record, "evidence": drift, "runs": runs, "digest": seal.run_digest(conn)},
    }
    return {"generated_at": db.now(), "seed": seed, "data": data, "digest": seal.digest(data)}


def _sheet(wb, name: str, header: list[str], rows: list[list]) -> None:
    from openpyxl.styles import Font

    ws = wb.create_sheet(name)
    ws.append(header)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        ws.append([v if v is None or isinstance(v, (int, float, str)) else str(v) for v in row])
    ws.freeze_panes = "A2"
    for k, title in enumerate(header, start=1):
        width = max([len(str(title))] + [len(str(r[k - 1])) for r in rows[:200] if k - 1 < len(r) and r[k - 1] is not None])
        ws.column_dimensions[ws.cell(row=1, column=k).column_letter].width = min(60, max(10, width + 2))


def to_xlsx(report: dict) -> bytes:
    """The workbook as bytes."""
    from openpyxl import Workbook

    d = report["data"]
    wb = Workbook()
    wb.remove(wb.active)
    sample = d["sample"]
    key = sample.get("answer_key") if isinstance(sample, dict) else None
    rel, rec, ev = d["reliability"]["summary"], d["integrity"]["record"], d["integrity"]["evidence"]
    summary = [
        ["Report digest", report["digest"]],
        ["Written at", report["generated_at"]],
        ["Ledger", d["scope"]["ledger"]],
        ["Invoices", d["scope"]["invoices"]],
        ["Amount", d["scope"]["amount"]],
        ["Ledger fingerprint", d["scope"]["ledger_fingerprint"]],
        *[[f"Policy v{t['version']}", f"from {t['from'] or 'the start'} until {t['until'] or 'now'}: {t['invoices']} "
           f"invoices, {t['under_other_version']} audited under another version, {t['unaudited']} not audited"]
          for t in d["scope"]["policy_timeline"]],
        *[[f"Results {state}", n] for state, n in d["outcome"]["states"].items()],
        ["Kept findings", d["outcome"]["findings"]],
        ["Waiting for review", d["outcome"]["queue"]],
        ["Data reliability", rel["conclusion"]],
        ["Audit record", "intact" if rec["intact"] else "ALTERED"],
        ["Evidence", f"{ev['unchanged']} results still match the ledger, {ev['changed']} based on records changed since"],
        ["Digest of the sealed runs", d["integrity"]["digest"]],
        ["Sample seed", report["seed"]],
    ]
    if isinstance(sample, dict) and "plan" in sample:
        p = sample["plan"]
        summary += [["Sample", f"{sample['drawn']} invoices drawn from {p['items']} approved without a person "
                               f"({p['book_value']}), {p['confidence']:.0%} confidence, tolerable {p['tolerable_pct']}%"]]
        if key:
            summary += [["Sample against the answer key", f"{key['misstatements']} anomalous; upper limit "
                                                           f"{key['upper_limit']} against tolerable {p['tolerable']}: "
                                                           f"{key['conclusion']}"]]
    summary += [["Untested schemes", ", ".join(d["program"]["untested"]["schemes"]) or "none"]]
    _sheet(wb, "Summary", ["Item", "Value"], summary)
    _sheet(wb, "Findings", ["Invoice", "Vendor", "Date", "Amount", "Rule", "Title", "Severity", "Source", "By",
                            "Finding", "Route", "State", "Policy", "Configuration"], d["findings"])
    _sheet(wb, "Review queue", ["Invoice", "Vendor", "Name", "Date", "Amount", "Route", "Risk level", "Score",
                                "Findings", "Configuration"], d["queue"])
    lead_rows = [["2.2.2", p["invoice_id"], p["original_id"], p["vendor_name"], p["number"], p["original_number"],
                  p["amount"], p["reason"]] for p in d["leads"]["near_duplicates"]]
    lead_rows += [["4.1.2", " ".join(g["invoices"]), "", g["vendor_name"], g["role"], g["limit"], g["total"],
                   " | ".join(g["descriptions"])] for g in d["leads"]["structuring"]]
    _sheet(wb, "Leads", ["Rule", "Invoice(s)", "Earlier invoice", "Vendor", "Number / role", "Earlier number / limit",
                         "Amount / total", "Why / descriptions"], lead_rows)
    marked = set(key["sampled_anomalous"]) if key else set()
    _sheet(wb, "Sample", ["Invoice", "Vendor", "Date", "Amount", "Units", "Certain", "Findings", "Answer key"],
           [[s["invoice_id"], s["vendor_name"], s["date"], s["amount"], s["units"], s["certain"], s["findings"],
             ("anomalous" if s["invoice_id"] in marked else "clean") if key else ""]
            for s in (sample.get("sample", []) if isinstance(sample, dict) else [])])
    _sheet(wb, "Reliability", ["Check", "Assertion", "Exceptions", "Decided by rule", "Examples", "Note"],
           [[c["title"], c["assertion"], c["exceptions"], c["decided_by"] or "", ", ".join(map(str, c["examples"])),
             c["note"]] for c in d["reliability"]["checks"]]
           + [[f"Total of {t['table']}", "", t["records"], "", t["amount"] if t["amount"] is not None else "", ""]
              for t in d["reliability"]["totals"]])
    scheme_key = (d["program"]["answer_key"] or {}).get("schemes", {})
    _sheet(wb, "Program", ["Test", "Title", "How", "Assertions", "Schemes", "In the policy", "Ran", "Found", "Listed"],
           [[t["id"], t["title"], t["how"], ", ".join(t["assertions"]), ", ".join(t["schemes"]), t["in_policy"],
             t["ran"], t["found"], t["listed"]] for t in d["program"]["tests"]]
           + [[f"scheme {s}", "", "answer key", "", "", "", "", v["found"], v["lead_only"]] for s, v in scheme_key.items()]
           + [[f"limit: {k}", v] for k, v in d["program"]["limits"].items()])
    _sheet(wb, "Integrity", ["Run", "Configuration", "Policy", "Started", "Finished", "Results", "Seal"],
           d["integrity"]["runs"])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def write(conn: db.Database, path: Path, seed: int | None = None) -> dict:
    report = engagement(conn, seed)
    Path(path).write_bytes(to_xlsx(report))
    return report


def check(conn: db.Database, path: Path) -> dict:
    """Whether a workbook still matches the store: its digest against the digest of the store's report now."""
    from openpyxl import load_workbook

    ws = load_workbook(path, read_only=True)["Summary"]
    values = {r[0]: r[1] for r in ws.iter_rows(min_row=2, values_only=True) if r and r[0]}
    stored, seed = values.get("Report digest"), values.get("Sample seed")
    now = engagement(conn, int(seed) if seed is not None else None)["digest"]
    return {"stored": stored, "current": now, "matches": stored == now}
