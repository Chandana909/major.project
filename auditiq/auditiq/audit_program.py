"""The audit program: which test addresses which assertion and which fraud scheme, what each found, and what no test
covers.

An audit plan states, for every assertion about the transactions (ISA 315: occurrence, completeness, accuracy,
cut-off, classification; and authorization, the control objective of the approval rules) and for every way the
purchasing cycle is defrauded (the billing, purchasing and corruption schemes of the ACFE occupational fraud tree),
which procedure gives evidence. This module keeps that map next to the code: each test is a policy clause checked by
a control or an agent, a lead, an analytic, a statistic or an integrity check, with the assertions and schemes it
addresses. Which test addresses what is a judgement written down here, not a measurement; what each test found is
read from the store, and on a benchmark ledger every scheme is scored against the answer key: of the labelled
invoices of the classes that commit it, how many a finding of the latest results names, how many a lead lists, and
how many nothing reaches.

The gaps are the point as much as the coverage: an assertion or scheme with no test is a scope limitation an auditor
has to state (no bidding data, so no bid-rigging test; no employee master, so related parties are matched only by
shared vendor identities).
"""
from __future__ import annotations

from collections import Counter, defaultdict

from . import analytics, db

ASSERTIONS = {
    "occurrence": "The invoice is for goods or services actually ordered, received and owed",
    "completeness": "Every liability is recorded, and every invoice was audited",
    "accuracy": "Amounts, quantities and taxes are right",
    "cut-off": "Each invoice is recorded in the period it belongs to",
    "classification": "The right goods, tax registration and account",
    "authorization": "Approved by someone allowed to approve it",
}
SCHEMES = {
    "shell-company": "Billing: a fictitious or unregistered vendor",
    "overbilling": "Billing: a real vendor bills more than was ordered or delivered",
    "duplicate-billing": "Billing: the same goods billed twice",
    "not-received": "Billing: goods or services that were not received",
    "personal-purchases": "Billing: personal or other goods passed off as the ordered ones",
    "limit-evasion": "Purchasing: an order split or structured to avoid a higher approval",
    "override": "Management override of an approval limit",
    "kickbacks": "Corruption: an approver and a vendor working together",
    "conflict-of-interest": "Corruption: vendors related to each other or to staff",
    "bid-rigging": "Corruption: rigged quotations or tenders",
    "tax-misuse": "Regulatory: a wrong, borrowed or invalid GST registration",
}
# The tests: id, title, how it is decided, assertions, schemes. A clause id is a rule of the policy; its findings are
# counted from the latest results.
TESTS = [
    ("2.1.1", "Invoice amount differs from the PO", "control", ["accuracy", "occurrence"], ["overbilling"]),
    ("2.1.2", "Billed quantity exceeds the received quantity", "control", ["occurrence", "accuracy"],
     ["not-received", "overbilling"]),
    ("2.1.3", "PO or GRN reference missing", "control", ["occurrence", "authorization"], ["shell-company", "not-received"]),
    ("2.1.4", "GRN remark contradicts the billed quantity", "agent", ["occurrence", "accuracy"], ["not-received"]),
    ("2.1.5", "Description inconsistent with the PO", "agent", ["occurrence", "classification"],
     ["personal-purchases", "overbilling"]),
    ("2.2.1", "Invoice number used before by the vendor", "control", ["occurrence"], ["duplicate-billing"]),
    ("2.2.2", "Near duplicate under a re-keyed number", "agent and lead", ["occurrence"], ["duplicate-billing"]),
    ("3.1.1", "Malformed GSTIN", "control", ["classification", "occurrence"], ["tax-misuse", "shell-company"]),
    ("3.1.2", "GSTIN with an invalid state code", "control", ["classification"], ["tax-misuse"]),
    ("3.1.3", "Invoice GSTIN differs from the vendor master", "control", ["occurrence", "classification"],
     ["tax-misuse", "shell-company", "overbilling"]),
    ("4.1.1", "More invoices of a vendor on one day than allowed", "control", ["authorization"], ["limit-evasion"]),
    ("4.1.2", "Structuring across days just below a limit", "agent and lead", ["authorization"], ["limit-evasion"]),
    ("4.2.1", "Invoice dated on a weekend", "control", ["occurrence"], ["shell-company"]),
    ("4.3.1", "Round amount", "control", ["accuracy"], ["shell-company", "overbilling"]),
    ("4.4.1", "Blocked or suspended vendor", "control", ["occurrence", "authorization"],
     ["shell-company", "conflict-of-interest"]),
    ("5.1.1", "Amount above the approver's limit", "control", ["authorization"], ["override"]),
    ("rings", "Collusion rings: shared identities and approver-vendor links (FDR-tested)", "analytic",
     ["occurrence", "authorization"], ["kickbacks", "conflict-of-interest", "shell-company"]),
    ("benford", "Benford's law on the amounts", "analytic", ["accuracy", "occurrence"], ["shell-company", "overbilling"]),
    ("limits", "Amounts piled up just under the approval limits", "analytic", ["authorization"], ["limit-evasion"]),
    ("sample", "Monetary-unit sample of the approved invoices (ISA 530)", "statistic",
     ["occurrence", "accuracy", "classification"],
     ["shell-company", "overbilling", "duplicate-billing", "not-received", "personal-purchases"]),
    ("reliability", "Data reliability of the ledger (ISA 500)", "integrity",
     ["completeness", "accuracy", "occurrence", "cut-off", "authorization"], []),
    ("seal", "Sealed audit record and evidence fingerprints (ISA 230)", "integrity", [], []),
]
LIMITS = {
    "cut-off": "Only date logic is checked (an invoice dated before its order or receipt); no period-end cut-off test, "
               "since the ledger has no closing dates or payments.",
    "completeness": "Receipts not invoiced and gaps in the company's numbered series are checked; a liability that "
                    "left no record at all cannot be found from the ledger.",
    "bid-rigging": "No quotation or tender data: not tested.",
    "conflict-of-interest": "No employee master: related parties are matched only by shared vendor PAN or GSTIN and "
                            "by approval patterns.",
    "personal-purchases": "Only the agents' description check (2.1.5) and the sample address it; C1 runs no agent.",
}


def program(conn: db.Database, leads: dict | None = None, rings: dict | None = None) -> dict:
    """The map, what each test found in the store, the gaps, and on a benchmark ledger each scheme against the key."""
    version = analytics.governing_version(conn)
    clauses = {c: (title, kind) for c, title, kind in conn.execute(
        "SELECT clause_id, title, kind FROM policy_clauses WHERE version = ?", (version,))}
    findings = Counter({c: int(n) for c, n in conn.execute(
        "SELECT f.clause, COUNT(DISTINCT l.invoice_id) FROM audit_flags f JOIN v_latest_results l "
        "ON l.result_id = f.result_id WHERE f.status = 'kept' GROUP BY f.clause")})
    configurations = Counter({c: int(n) for c, n in conn.execute(
        "SELECT configuration, COUNT(*) FROM v_latest_results GROUP BY configuration")})
    agents_ran = sum(n for c, n in configurations.items() if c != "C1")
    lead_counts = {"2.2.2": (leads or {}).get("near_duplicates", {}).get("invoices"),
                   "4.1.2": (leads or {}).get("structuring", {}).get("invoices")}
    rows = []
    for test_id, title, how, assertions, schemes in TESTS:
        row = {"id": test_id, "title": title, "how": how, "assertions": assertions, "schemes": schemes,
               "in_policy": None, "found": None, "listed": None, "ran": True}
        if test_id[0].isdigit():
            row["in_policy"] = test_id in clauses
            row["found"] = findings.get(test_id, 0)
            row["ran"] = test_id in clauses and (how == "control" or agents_ran > 0 or test_id in lead_counts)
            row["listed"] = lead_counts.get(test_id)
        elif test_id == "rings" and rings is not None:
            row["found"] = len(rings.get("rings", []))
        rows.append(row)
    covered_assertions = {a for r in rows if r["ran"] for a in r["assertions"]}
    covered_schemes = {s for r in rows if r["ran"] for s in r["schemes"]}
    by_assertion = {a: [r["id"] for r in rows if a in r["assertions"] and r["ran"]] for a in ASSERTIONS}
    by_scheme = {s: [r["id"] for r in rows if s in r["schemes"] and r["ran"]] for s in SCHEMES}
    return {"policy_version": version, "assertions": ASSERTIONS, "schemes": SCHEMES, "tests": rows,
            "by_assertion": by_assertion, "by_scheme": by_scheme,
            "untested": {"assertions": [a for a in ASSERTIONS if a not in covered_assertions],
                         "schemes": [s for s in SCHEMES if s not in covered_schemes]},
            "limits": LIMITS, "agents_ran": agents_ran,
            "answer_key": _schemes_against_key(conn, version, leads)}


def _schemes_against_key(conn: db.Database, version: str | None, leads: dict | None) -> dict | None:
    """Per scheme: the labelled invoices of the classes that commit it (a class commits the schemes of its clauses),
    and how many a kept finding names, how many only a lead lists, and how many nothing reaches."""
    if not conn.scalar("SELECT COUNT(*) FROM benchmark_labels"):
        return None
    key_policy = conn.scalar("SELECT value FROM meta WHERE key = 'labels_policy'") or analytics.BENCHMARK_POLICY
    if key_policy != version:
        return {"policy_version": key_policy, "compared": False}
    schemes_of = {test_id: schemes for test_id, _, _, _, schemes in TESTS if test_id[0].isdigit()}
    flagged: dict[str, set] = defaultdict(set)
    for invoice_id, clause in conn.execute(
            "SELECT l.invoice_id, f.clause FROM audit_flags f JOIN v_latest_results l ON l.result_id = f.result_id "
            "WHERE f.status = 'kept'"):
        flagged[invoice_id].add(clause)
    listed = {"2.2.2": {p["invoice_id"] for p in (leads or {}).get("near_duplicates", {}).get("pairs", [])},
              "4.1.2": {i for g in (leads or {}).get("structuring", {}).get("groups", []) for i in g["invoices"]}}
    out: dict = {s: Counter() for s in SCHEMES}
    for invoice_id, clause_ids in conn.execute(
            "SELECT invoice_id, clause_ids FROM benchmark_labels WHERE label = 'anomalous'"):
        clauses = analytics._clauses(clause_ids)
        for s in {s for c in clauses for s in schemes_of.get(c, [])}:
            # Only a finding or lead on a rule that addresses this scheme counts for it: an invoice planted with two
            # schemes and caught for one of them is not caught for the other.
            relevant = {c for c in clauses if s in schemes_of.get(c, [])}
            found = bool(flagged.get(invoice_id, set()) & relevant)
            lead = any(invoice_id in listed.get(c, set()) for c in relevant)
            c = out[s]
            c["labelled"] += 1
            c["found"] += found
            c["lead_only"] += lead and not found
            c["missed"] += not found and not lead
    return {"policy_version": key_policy, "compared": True,
            "schemes": {s: {"labelled": c["labelled"], "found": c["found"], "lead_only": c["lead_only"],
                            "missed": c["missed"],
                            "reached": round((c["found"] + c["lead_only"]) / c["labelled"], 4) if c["labelled"] else None}
                        for s, c in out.items() if c["labelled"]}}
