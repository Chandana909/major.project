"""Deterministic controls (feature E1 of the paper).

Each control is a pure function of one extracted transaction and the clause
registry of the active policy. It returns zero or more flags. A control reads
every threshold from the registry; none is written in this file. A control
whose clause is absent from the policy does not run.

Transaction (see extraction.py):
    {invoice, po | None, grn | None, vendor, approvals: [...], vendor_history: [...]}
Flag:
    {clause, control, severity, source: "D", confidence: 1.0,
     evidence: [{field, value}], message}

This module is written from the policy text. It imports nothing from the
benchmark generator.
"""
from __future__ import annotations

import re
from datetime import date

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def paise(x) -> int:
    """Amounts are compared in paise to keep the arithmetic exact."""
    return int(round(float(x) * 100))


def number(x) -> str:
    """12.0 -> '12', 12.5 -> '12.5'."""
    return str(int(x)) if float(x).is_integer() else str(x)


def ev(field: str, value) -> dict:
    return {"field": field, "value": value}


def is_true(x) -> bool:
    return x is True or str(x).strip().lower() in ("true", "t", "1", "yes")


def make_flag(clauses: dict, clause: str, control: str, evidence: list[dict], message: str) -> dict:
    return {
        "clause": clause,
        "control": control,
        "severity": clauses[clause]["severity"],
        "source": "D",
        "confidence": 1.0,
        "evidence": evidence,
        "message": message,
    }


def is_earlier(other: dict, invoice: dict) -> bool:
    return other["date"] < invoice["date"] or (
        other["date"] == invoice["date"] and other["invoice_id"] < invoice["invoice_id"])


def approving_entry(txn: dict) -> dict | None:
    """The latest entry with action "Approved" (SOP 5.1)."""
    latest = None
    for entry in txn.get("approvals") or []:
        if entry.get("action_taken") == "Approved" and (
                latest is None or str(entry["timestamp"]) >= str(latest["timestamp"])):
            latest = entry
    return latest


def gstin_checks(gstin, clauses: dict) -> tuple[str, bool, bool]:
    g = "" if gstin is None else str(gstin)
    fmt, state = clauses.get("3.1.1"), clauses.get("3.1.2")
    format_ok = fmt is None or (len(g) == fmt["params"]["gstin_length"]
                                and re.fullmatch(r"[A-Za-z0-9]+", g) is not None)
    state_ok = True
    if state is not None:
        code = int(g[:2]) if re.match(r"[0-9]{2}", g) else None
        state_ok = code is not None and state["params"]["state_code_min"] <= code <= state["params"]["state_code_max"]
    return g, format_ok, state_ok


# ---- 2.1.1  Invoice amount differs from PO amount beyond the tolerance ----
def amount_match(txn: dict, clauses: dict) -> list[dict]:
    clause = clauses.get("2.1.1")
    if clause is None or not txn.get("po"):
        return []
    inv, po = paise(txn["invoice"]["amount"]), paise(txn["po"]["amount"])
    if po <= 0:
        return []
    tolerance = clause["params"]["amount_tolerance_pct"]
    if abs(inv - po) * 100 <= tolerance * po:
        return []
    pct = (inv - po) / po * 100
    return [make_flag(clauses, "2.1.1", "amount_match",
                      [ev("invoice.amount", txn["invoice"]["amount"]), ev("po.amount", txn["po"]["amount"])],
                      f"Invoice amount {txn['invoice']['amount']:.2f} differs from PO amount "
                      f"{txn['po']['amount']:.2f} by {pct:.2f}% (tolerance {number(tolerance)}%).")]


# ---- 2.1.2  Billed quantity exceeds received quantity ----
def quantity_match(txn: dict, clauses: dict) -> list[dict]:
    if "2.1.2" not in clauses or not txn.get("grn"):
        return []
    billed, received = txn["invoice"]["quantity"], txn["grn"]["received_quantity"]
    if not float(billed) > float(received):
        return []
    return [make_flag(clauses, "2.1.2", "quantity_match",
                      [ev("invoice.quantity", billed), ev("grn.received_quantity", received)],
                      f"Billed quantity {billed} exceeds received quantity {received}.")]


# ---- 2.1.3  Missing PO or GRN reference ----
def missing_reference(txn: dict, clauses: dict) -> list[dict]:
    if "2.1.3" not in clauses:
        return []
    missing, evidence = [], []
    inv = txn["invoice"]
    for field, record, label, noun in (("po_id", txn.get("po"), "PO", "purchase order"),
                                       ("grn_id", txn.get("grn"), "GRN", "goods receipt")):
        reference = inv.get(field)
        if not reference:
            missing.append(f"no {label} reference")
            evidence.append(ev(f"invoice.{field}", reference))
        elif not record:
            missing.append(f"{label} reference {reference} matches no {noun}")
            evidence.append(ev(f"invoice.{field}", reference))
    if not missing:
        return []
    return [make_flag(clauses, "2.1.3", "missing_reference", evidence, f"Invoice has {' and '.join(missing)}.")]


# ---- 2.2.1  Invoice number already used by an earlier invoice of the vendor ----
def exact_duplicate(txn: dict, clauses: dict) -> list[dict]:
    if "2.2.1" not in clauses:
        return []
    inv = txn["invoice"]
    num = str(inv.get("invoice_number") or "").strip()
    if num == "":
        return []
    earlier = [h for h in txn.get("vendor_history") or []
               if str(h.get("invoice_number") or "").strip() == num and is_earlier(h, inv)]
    if not earlier:
        return []
    original = min(earlier, key=lambda h: (h["date"], h["invoice_id"]))
    return [make_flag(clauses, "2.2.1", "exact_duplicate",
                      [ev("invoice.invoice_number", inv["invoice_number"]),
                       ev(f"history.{original['invoice_id']}.invoice_number", original["invoice_number"])],
                      f"Invoice number {num} was already used by {original['invoice_id']} of the same vendor, "
                      f"dated {original['date']}.")]


# ---- 3.1.1  GSTIN format ----
def gstin_format(txn: dict, clauses: dict) -> list[dict]:
    clause = clauses.get("3.1.1")
    if clause is None:
        return []
    g, format_ok, _ = gstin_checks(txn["invoice"].get("gstin"), clauses)
    if format_ok:
        return []
    return [make_flag(clauses, "3.1.1", "gstin_format", [ev("invoice.gstin", txn["invoice"].get("gstin"))],
                      f"GSTIN '{g}' is not exactly {clause['params']['gstin_length']} alphanumeric characters "
                      f"(length {len(g)}).")]


# ---- 3.1.2  GSTIN state code ----
def gstin_state_code(txn: dict, clauses: dict) -> list[dict]:
    clause = clauses.get("3.1.2")
    if clause is None:
        return []
    g, _, state_ok = gstin_checks(txn["invoice"].get("gstin"), clauses)
    if state_ok:
        return []
    return [make_flag(clauses, "3.1.2", "gstin_state_code", [ev("invoice.gstin", txn["invoice"].get("gstin"))],
                      f"GSTIN '{g}' does not start with a state code from {clause['params']['state_code_min']} "
                      f"to {clause['params']['state_code_max']}.")]


# ---- 3.1.3  Well-formed GSTIN differs from the vendor master ----
def gstin_vendor_match(txn: dict, clauses: dict) -> list[dict]:
    if "3.1.3" not in clauses or not txn.get("vendor"):
        return []
    g, format_ok, state_ok = gstin_checks(txn["invoice"].get("gstin"), clauses)
    official = txn["vendor"].get("official_gstin")
    if not format_ok or not state_ok or not official or g == str(official):
        return []
    return [make_flag(clauses, "3.1.3", "gstin_vendor_match",
                      [ev("invoice.gstin", txn["invoice"]["gstin"]), ev("vendor.official_gstin", official)],
                      f"Invoice GSTIN {g} differs from the vendor master GSTIN {official}.")]


# ---- 4.1.1  More invoices of the vendor on one day than allowed ----
def same_day_splitting(txn: dict, clauses: dict) -> list[dict]:
    clause = clauses.get("4.1.1")
    if clause is None:
        return []
    day = txn["invoice"]["date"]
    same_day = [h for h in txn.get("vendor_history") or [] if h["date"] == day]
    count, limit = len(same_day) + 1, clause["params"]["max_invoices_per_vendor_per_day"]
    if count <= limit:
        return []
    return [make_flag(clauses, "4.1.1", "same_day_splitting",
                      [ev("invoice.date", day)] + [ev(f"history.{h['invoice_id']}.date", h["date"]) for h in same_day],
                      f"The vendor has {count} invoices dated {day}; at most {limit} are allowed.")]


# ---- 4.2.1  Invoice dated on a non-business day ----
def non_business_day(txn: dict, clauses: dict) -> list[dict]:
    clause = clauses.get("4.2.1")
    day = txn["invoice"].get("date")
    if clause is None or not day:
        return []
    name = DAY_NAMES[date.fromisoformat(str(day)[:10]).weekday()]
    if name not in clause["params"]["non_business_days"]:
        return []
    return [make_flag(clauses, "4.2.1", "non_business_day", [ev("invoice.date", day)],
                      f"Invoice is dated {day}, a {name}.")]


# ---- 4.3.1  Round amount ----
def round_amount(txn: dict, clauses: dict) -> list[dict]:
    clause = clauses.get("4.3.1")
    if clause is None:
        return []
    amount, multiple = paise(txn["invoice"]["amount"]), clause["params"]["round_amount_multiple"]
    if amount <= 0 or amount % (multiple * 100) != 0:
        return []
    return [make_flag(clauses, "4.3.1", "round_amount", [ev("invoice.amount", txn["invoice"]["amount"])],
                      f"Invoice amount {txn['invoice']['amount']:.2f} is an exact multiple of {multiple}.")]


# ---- 4.4.1  Blacklisted or suspended vendor ----
def blocked_vendor(txn: dict, clauses: dict) -> list[dict]:
    clause = clauses.get("4.4.1")
    vendor = txn.get("vendor")
    if clause is None or not vendor:
        return []
    if is_true(vendor.get("blacklisted")):
        return [make_flag(clauses, "4.4.1", "blocked_vendor", [ev("vendor.blacklisted", vendor["blacklisted"])],
                          f"Vendor {vendor['vendor_id']} is blacklisted.")]
    if vendor.get("gstin_status") in clause["params"]["blocked_gstin_statuses"]:
        return [make_flag(clauses, "4.4.1", "blocked_vendor", [ev("vendor.gstin_status", vendor["gstin_status"])],
                          f"GST registration of vendor {vendor['vendor_id']} is {vendor['gstin_status']}.")]
    return []


# ---- 5.1.1  Amount above the approval limit of the approving role ----
def approval_limit(txn: dict, clauses: dict) -> list[dict]:
    clause = clauses.get("5.1.1")
    entry = approving_entry(txn)
    if clause is None or entry is None:
        return []
    limit = clause["params"]["approval_limits"].get(entry["approver_role"])
    if limit is None or paise(txn["invoice"]["amount"]) <= paise(limit):
        return []
    return [make_flag(clauses, "5.1.1", "approval_limit",
                      [ev("invoice.amount", txn["invoice"]["amount"]), ev("approval.approver_role", entry["approver_role"])],
                      f"Invoice amount {txn['invoice']['amount']:.2f} exceeds the {entry['approver_role']} approval "
                      f"limit of {number(limit)}; approved by {entry['approver_name']}.")]


CONTROLS = [
    amount_match,
    quantity_match,
    missing_reference,
    exact_duplicate,
    gstin_format,
    gstin_state_code,
    gstin_vendor_match,
    same_day_splitting,
    non_business_day,
    round_amount,
    blocked_vendor,
    approval_limit,
]


def run_controls(txn: dict, clauses: dict) -> list[dict]:
    """Run every control; ``clauses`` is the ``clauses`` map of the policy registry."""
    return [flag for control in CONTROLS for flag in control(txn, clauses)]
