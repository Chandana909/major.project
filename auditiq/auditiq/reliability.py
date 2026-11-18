"""Can the ledger be relied on? The checks an auditor makes of information produced by the entity (ISA 500).

Before an audit's results mean anything, the records it read must be complete and accurate: every document it
names must exist, the arithmetic of each invoice must hold, every invoice must carry its approval, the company's own
numbered series must have no holes, and every invoice must have been audited under the policy in force on its date.
The audit's rules decide some of these as findings (an invoice that names a missing purchase order breaks rule 2.1.3);
the checks here look at the ledger as data, and say which exceptions the rules already decide.

    totals         record counts and amount totals of every ledger table (control totals)
    fingerprint    a SHA-256 over every row of every ledger table, in key order: cited in the working papers, it
                   shows later that the ledger audited is the ledger on file
    checks         references, approvals, arithmetic, date logic, goods received but not invoiced (unrecorded
                   liabilities), gaps in the company's numbered series, vendor master data, and audit coverage

Nothing is changed. A check lists at most ``EXAMPLES`` of its exceptions; the count covers all.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict

from . import db

EXAMPLES = 8
NUMBERED = {"invoices": "invoice_id", "purchase_orders": "po_id", "goods_receipts": "grn_id", "approval_logs": "log_id"}
KEYS = {"vendor_master": "vendor_id", **NUMBERED}
SERIES = re.compile(r"^([A-Za-z_-]*)(\d+)$")
GSTIN = re.compile(r"^[0-9]{2}[A-Z0-9]{13}$")


def fingerprint(conn: db.Database) -> dict:
    """SHA-256 of every ledger table, row by row in key order, and one over all of them."""
    tables = {}
    for table, key in KEYS.items():
        h = hashlib.sha256()
        for row in conn.execute(f"SELECT * FROM {table} ORDER BY {key}"):
            h.update(json.dumps([None if v is None else (float(v) if isinstance(v, float) else v) for v in tuple(row)],
                                ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))
            h.update(b"\n")
        tables[table] = h.hexdigest()
    return {"tables": tables, "ledger": hashlib.sha256(json.dumps(tables, sort_keys=True).encode()).hexdigest()}


def totals(conn: db.Database) -> list[dict]:
    out = []
    for table, amount in (("invoices", "amount"), ("purchase_orders", "amount"), ("goods_receipts", "amount"),
                          ("vendor_master", None), ("approval_logs", None)):
        n, total = conn.execute(f"SELECT COUNT(*), {f'COALESCE(SUM({amount}), 0)' if amount else '0'} FROM {table}").fetchone()
        out.append({"table": table, "records": int(n), "amount": round(float(total or 0), 2) if amount else None})
    return out


def _check(check_id: str, title: str, assertion: str, found: list, decided_by: str | None = None,
           note: str = "") -> dict:
    return {"id": check_id, "title": title, "assertion": assertion, "exceptions": len(found),
            "examples": found[:EXAMPLES], "decided_by": decided_by, "note": note}


def _ids(conn: db.Database, sql: str, params: tuple = ()) -> list[str]:
    return [str(r[0]) for r in conn.execute(sql, params)]


def series_gaps(ids: list[str]) -> dict:
    """The holes in a numbered series (a prefix and a number): how many numbers are missing between the lowest and
    the highest, and the first of them. A series of other identifiers is reported as not numbered."""
    by_prefix: dict[str, list[int]] = defaultdict(list)
    widths: dict[str, int] = defaultdict(int)
    for i in ids:
        m = SERIES.match(i)
        if not m:
            return {"numbered": False, "missing": 0, "first_missing": []}
        by_prefix[m.group(1)].append(int(m.group(2)))
        widths[m.group(1)] = max(widths[m.group(1)], len(m.group(2)))     # "INV0001": numbers written with 4 digits
    missing, first = 0, []
    for prefix, numbers in by_prefix.items():
        present = set(numbers)
        low, high = min(numbers), max(numbers)
        missing += (high - low + 1) - len(present)
        width = widths[prefix]
        for n in range(low, high + 1):
            if len(first) >= EXAMPLES:
                break
            if n not in present:
                first.append(f"{prefix}{n:0{width}d}")
    return {"numbered": True, "missing": missing, "first_missing": first,
            "range": {p: [min(v), max(v)] for p, v in by_prefix.items()}}


def ledger_reliability(conn: db.Database) -> dict:
    """Every check, the control totals and the fingerprint of the ledger."""
    checks = [
        _check("vendor", "Invoices whose vendor is not in the vendor master", "occurrence",
               _ids(conn, "SELECT i.invoice_id FROM invoices i LEFT JOIN vendor_master v ON v.vendor_id = i.vendor_id "
                          "WHERE v.vendor_id IS NULL ORDER BY i.invoice_id")),
        _check("po-on-file", "Invoices naming a purchase order that is not on file", "occurrence",
               _ids(conn, "SELECT i.invoice_id FROM invoices i LEFT JOIN purchase_orders p ON p.po_id = i.po_id "
                          "WHERE i.po_id IS NOT NULL AND i.po_id <> '' AND p.po_id IS NULL ORDER BY i.invoice_id"),
               decided_by="2.1.3"),
        _check("grn-on-file", "Invoices naming a goods receipt that is not on file", "occurrence",
               _ids(conn, "SELECT i.invoice_id FROM invoices i LEFT JOIN goods_receipts g ON g.grn_id = i.grn_id "
                          "WHERE i.grn_id IS NOT NULL AND i.grn_id <> '' AND g.grn_id IS NULL ORDER BY i.invoice_id"),
               decided_by="2.1.3"),
        _check("po-vendor", "Invoices billed by another vendor than their purchase order's", "occurrence",
               _ids(conn, "SELECT i.invoice_id FROM invoices i JOIN purchase_orders p ON p.po_id = i.po_id "
                          "WHERE p.vendor_id <> i.vendor_id ORDER BY i.invoice_id")),
        _check("grn-po", "Goods receipts whose purchase order is not on file, or is another vendor's", "occurrence",
               _ids(conn, "SELECT g.grn_id FROM goods_receipts g LEFT JOIN purchase_orders p ON p.po_id = g.po_id "
                          "WHERE p.po_id IS NULL OR p.vendor_id <> g.vendor_id ORDER BY g.grn_id")),
        _check("approved", "Invoices without an approval entry", "authorization",
               _ids(conn, "SELECT i.invoice_id FROM invoices i WHERE NOT EXISTS (SELECT 1 FROM approval_logs a "
                          "WHERE a.transaction_id = i.invoice_id AND a.action_taken = 'Approved') ORDER BY i.invoice_id")),
        _check("approval-orphans", "Approval entries for invoices that are not in the ledger", "occurrence",
               _ids(conn, "SELECT a.log_id FROM approval_logs a LEFT JOIN invoices i ON i.invoice_id = a.transaction_id "
                          "WHERE i.invoice_id IS NULL ORDER BY a.log_id")),
        _check("approver-recorded", "Invoices whose recorded approver is not the one in the approval log", "authorization",
               _approver_mismatches(conn)),
        _check("total", "Invoices whose amount and tax do not add up to the total", "accuracy",
               _ids(conn, "SELECT invoice_id FROM invoices WHERE total_amount IS NOT NULL AND tax_amount IS NOT NULL "
                          "AND ABS(amount + tax_amount - total_amount) > 0.01 ORDER BY invoice_id")),
        _check("extension", "Invoices whose quantity times unit price is not the amount", "accuracy",
               _ids(conn, "SELECT invoice_id FROM invoices WHERE quantity IS NOT NULL AND unit_price IS NOT NULL "
                          "AND ABS(quantity * unit_price - amount) > 1 + 0.0001 * ABS(amount) ORDER BY invoice_id")),
        _check("dates", "Invoices dated before their order, receipts before their order, due dates before the invoice",
               "cut-off", _ids(conn,
                               "SELECT i.invoice_id FROM invoices i LEFT JOIN purchase_orders p ON p.po_id = i.po_id "
                               "LEFT JOIN goods_receipts g ON g.grn_id = i.grn_id WHERE i.date < p.po_date "
                               "OR g.receipt_date < p.po_date OR i.due_date < i.date ORDER BY i.invoice_id")),
        _check("received-not-invoiced", "Goods received that no invoice bills (possible unrecorded liabilities)",
               "completeness", _received_not_invoiced(conn),
               note="A receipt not yet invoiced may be a liability missing from the books; it is followed up with the "
                    "vendor, not decided by a rule."),
        _vendor_master(conn),
        *_series(conn),
        *_coverage(conn),
    ]
    integrity = [c for c in checks if c["assertion"] != "audit coverage"]
    open_ = [c for c in integrity if c["exceptions"] and not c["decided_by"]]
    decided = [c for c in integrity if c["exceptions"] and c["decided_by"]]
    coverage = [c for c in checks if c["assertion"] == "audit coverage" and c["exceptions"]]
    return {"ledger": conn.scalar("SELECT value FROM meta WHERE key = 'dataset'"), "totals": totals(conn),
            "fingerprint": fingerprint(conn), "checks": checks,
            "summary": {"checks": len(checks), "without_exceptions": sum(not c["exceptions"] for c in checks),
                        "open": [c["id"] for c in open_], "decided_by_rules": [c["id"] for c in decided],
                        "coverage": [c["id"] for c in coverage],
                        "reliable": not open_,
                        "conclusion": ("the ledger's records are complete and consistent for the audit's purpose"
                                       + (": the exceptions found are findings the audit's rules decide" if decided else "")
                                       if not open_ else
                                       "the ledger has exceptions no rule decides: resolve them before relying on the audit")}}


def _received_not_invoiced(conn: db.Database) -> list[str]:
    # A set difference, not NOT EXISTS: invoices.grn_id has no index, and the subquery would scan every invoice for
    # every receipt (64 s on the 25,000-invoice ledger).
    billed = {r[0] for r in conn.execute("SELECT DISTINCT grn_id FROM invoices WHERE grn_id IS NOT NULL")}
    return sorted(g for g in _ids(conn, "SELECT grn_id FROM goods_receipts") if g not in billed)


def _approver_mismatches(conn: db.Database) -> list[str]:
    last: dict[str, str] = {}
    for transaction, name in conn.execute("SELECT transaction_id, approver_name FROM approval_logs "
                                          "WHERE action_taken = 'Approved' ORDER BY timestamp, log_id"):
        last[transaction] = name
    return [i for i, recorded in conn.execute("SELECT invoice_id, approved_by FROM invoices ORDER BY invoice_id")
            if recorded and i in last and str(recorded).strip() != str(last[i]).strip()]


def _vendor_master(conn: db.Database) -> dict:
    bad = []
    for vendor_id, gstin, pan in conn.execute(
            "SELECT vendor_id, official_gstin, pan_number FROM vendor_master ORDER BY vendor_id"):
        g = str(gstin or "")
        if not GSTIN.match(g) or (pan and g[2:12] != str(pan)):
            bad.append(vendor_id)
    return _check("vendor-master", "Vendors whose GSTIN is malformed or does not contain their PAN", "occurrence", bad)


def _series(conn: db.Database) -> list[dict]:
    out = []
    names = {"invoices": "invoice", "purchase_orders": "purchase order", "goods_receipts": "goods receipt",
             "approval_logs": "approval log"}
    for table, key in NUMBERED.items():
        gaps = series_gaps(_ids(conn, f"SELECT {key} FROM {table}"))
        if not gaps["numbered"]:
            continue
        out.append({**_check(f"series-{table}", f"Numbers missing from the {names[table]} series", "completeness",
                             gaps["first_missing"]), "exceptions": gaps["missing"],
                    "note": "range " + ", ".join(f"{p}{lo} to {p}{hi}" for p, (lo, hi) in gaps["range"].items())})
    return out


def _coverage(conn: db.Database) -> list[dict]:
    never = _ids(conn, "SELECT i.invoice_id FROM invoices i LEFT JOIN latest_results m ON m.invoice_id = i.invoice_id "
                       "WHERE m.invoice_id IS NULL ORDER BY i.invoice_id")
    timeline = db.policy_timeline(conn)
    other: list[str] = []
    if timeline:
        expr, params = db.in_force_sql(timeline, "i.date")
        other = _ids(conn, f"SELECT l.invoice_id FROM v_latest_results l JOIN invoices i ON i.invoice_id = l.invoice_id "
                           f"WHERE l.policy_version <> {expr} ORDER BY l.invoice_id", tuple(params))
    return [_check("audited", "Invoices never audited", "audit coverage", never),
            _check("in-force", "Invoices last audited under a policy version not in force on their date",
                   "audit coverage", other)]
