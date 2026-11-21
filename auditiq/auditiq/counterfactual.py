"""Counterfactual explanations of control findings: how far past its rule an invoice is, and what would clear it.

A control's finding is exact, but a bare "the amount exceeds the limit" does not tell a reviewer whether the
invoice missed by a rupee or by a lakh, nor what a change of the policy would do. For every finding of a control
this module states

    margin     how far the invoice is beyond the rule's threshold, in the rule's own unit and as a share of
               the threshold: an invoice 0.3 % over a tolerance is a different case from one 300 % over it
    record     the smallest change to the invoice's records that would clear the finding (bill the quantity
               received, the approval of the role whose limit covers the amount, the vendor master's GSTIN, the
               next business day); each one is applied to a copy of the transaction and every control is run
               again, so an option is listed only if it does clear the finding, together with any finding it
               would raise instead (moving a weekend invoice to Monday can break the same-day rule)
    policy     the change of the rule's parameter that would clear it (the tolerance, the role's limit, the daily
               count, the non-business days, the round multiple, the blocked statuses), verified the same way,
               with how many other invoices whose latest result carries a finding of that rule the same change
               would clear: the cost of the change across the ledger

This is the counterfactual of Wachter, Mittelstadt and Russell (2017), "Counterfactual explanations without opening
the black box" (Harvard Journal of Law & Technology 31(2)), applied to a model that is code: the answer is found by
running the controls themselves, not by approximating them, so it is exact. A counterfactual explains a finding; it
is not advice to change a record. Some changes would hide the very thing the rule is there to find (a fresh number
on a duplicate invoice), and the option says so.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Callable
from datetime import date, timedelta

from . import controls
from .policy import Policy

RULES_WITHOUT_PARAMETER = {"2.1.2", "2.1.3", "2.2.1", "3.1.1", "3.1.3"}
CAUTION = {
    "2.2.1": "A fresh number would only hide the repeat: an invoice under a re-keyed number is what rule 2.2.2 looks for.",
    "3.1.3": "The vendor master is the authority; an invoice carrying another registration is billed by someone else.",
    "4.4.1": "Lifting a block is a decision about the vendor, taken in the vendor master, not on an invoice.",
}


def _rupees(x: float) -> str:
    return f"₹{x:,.2f}"


def _copy(txn: dict) -> dict:
    """A copy whose own records can be edited; the vendor history is shared (it is only read)."""
    out = {k: copy.deepcopy(v) for k, v in txn.items() if k != "vendor_history"}
    out["vendor_history"] = txn.get("vendor_history") or []
    return out


def _clauses_with(clauses: dict, clause: str, param: str, value) -> dict:
    changed = copy.deepcopy(clauses)
    changed[clause]["params"][param] = value
    return changed


def found(txn: dict, clauses: dict) -> set[str]:
    return {f["clause"] for f in controls.run_controls(txn, clauses)}


def _verify(txn: dict, clauses: dict, clause: str, before: set[str]) -> dict:
    after = found(txn, clauses)
    return {"clears": clause not in after, "raises": sorted(after - before)}


def _day(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _same_type(original, day: date):
    return day if isinstance(original, date) else day.isoformat()


def _next_business(day: date, non_business: list[str], avoid: Callable[[date], bool] = lambda _d: False) -> date:
    candidate = day + timedelta(days=1)
    for _ in range(60):
        if controls.DAY_NAMES[candidate.weekday()] not in non_business and not avoid(candidate):
            return candidate
        candidate += timedelta(days=1)
    return candidate


# ------------------------------------------------------------------ one finding
def _amount_match(txn, clauses, flag, before, other):
    tol = float(clauses["2.1.1"]["params"]["amount_tolerance_pct"])
    inv, po = float(txn["invoice"]["amount"]), float(txn["po"]["amount"])
    pct = abs(inv - po) / po * 100
    lo, hi = math.ceil(po * (1 - tol / 100) * 100) / 100, math.floor(po * (1 + tol / 100) * 100) / 100
    target = hi if inv > po else lo
    margin = {"value": round(pct - tol, 4), "unit": "percentage points beyond the tolerance",
              "text": f"{pct:.2f}% from the PO amount against a tolerance of {controls.number(tol)}%: "
                      f"{pct - tol:.2f} points beyond it ({_rupees(abs(inv - target))} beyond the nearest amount allowed)"}
    record = []
    t = _copy(txn)
    t["invoice"]["amount"] = target
    record.append({"change": f"An invoice amount within {controls.number(tol)}% of the PO amount "
                             f"({_rupees(lo)} to {_rupees(hi)}); the nearest is {_rupees(target)}",
                   "edit": {"invoice.amount": target}, **_verify(t, clauses, "2.1.1", before)})
    new_tol = math.ceil(pct * 100) / 100
    changed = _clauses_with(clauses, "2.1.1", "amount_tolerance_pct", new_tol)
    policy = [{"change": f"Rule 2.1.1's tolerance raised from {controls.number(tol)}% to {controls.number(new_tol)}%",
               "parameter": "2.1.1.amount_tolerance_pct", "from": tol, "to": new_tol,
               **_verify(txn, changed, "2.1.1", before), "also_clears": other("2.1.1", changed)}]
    return margin, record, policy


def _quantity_match(txn, clauses, flag, before, other):
    billed, received = float(txn["invoice"]["quantity"]), float(txn["grn"]["received_quantity"])
    margin = {"value": billed - received, "unit": "units billed beyond the units received",
              "text": f"{controls.number(billed)} billed against {controls.number(received)} received: "
                      f"{controls.number(billed - received)} units ({(billed - received) / billed * 100:.1f}% of the bill) "
                      "not received"}
    t = _copy(txn)
    t["invoice"]["quantity"] = int(received) if float(received).is_integer() else received
    record = [{"change": f"Bill the {controls.number(received)} units the goods receipt records",
               "edit": {"invoice.quantity": t["invoice"]["quantity"]}, **_verify(t, clauses, "2.1.2", before)}]
    t = _copy(txn)
    t["grn"]["received_quantity"] = txn["invoice"]["quantity"]
    record.append({"change": f"A goods receipt for all {controls.number(billed)} units billed",
                   "edit": {"grn.received_quantity": txn["invoice"]["quantity"]}, **_verify(t, clauses, "2.1.2", before)})
    return margin, record, []


def _missing_reference(txn, clauses, flag, before, other):
    inv = txn["invoice"]
    t = _copy(txn)
    if not t.get("po"):
        t["invoice"]["po_id"] = inv.get("po_id") or "PO-ON-FILE"
        t["po"] = {"po_id": t["invoice"]["po_id"], "vendor_id": inv.get("vendor_id"), "po_date": inv.get("date"),
                   "amount": inv.get("amount"), "quantity": inv.get("quantity"), "unit_price": inv.get("unit_price"),
                   "description": inv.get("description")}
    if not t.get("grn"):
        t["invoice"]["grn_id"] = inv.get("grn_id") or "GRN-ON-FILE"
        t["grn"] = {"grn_id": t["invoice"]["grn_id"], "po_id": t["invoice"]["po_id"], "receipt_date": inv.get("date"),
                    "received_quantity": inv.get("quantity"), "ordered_quantity": inv.get("quantity"),
                    "amount": inv.get("amount"), "notes": ""}
    margin = {"value": None, "unit": None, "text": flag["message"]}
    record = [{"change": "The purchase order and goods receipt the invoice was raised against, on file and referenced "
                         "(checked with records that agree with the invoice)",
               "edit": {"invoice.po_id": t["invoice"]["po_id"], "invoice.grn_id": t["invoice"]["grn_id"]},
               **_verify(t, clauses, "2.1.3", before)}]
    return margin, record, []


def _exact_duplicate(txn, clauses, flag, before, other):
    original = next((e["field"].split(".")[1] for e in flag["evidence"] if e["field"].startswith("history.")), None)
    t = _copy(txn)
    t["invoice"]["invoice_number"] = f"{txn['invoice']['invoice_number']}-NEW"
    margin = {"value": None, "unit": None, "text": f"The number was used before by {original}" if original else
              flag["message"]}
    record = [{"change": "A number the vendor has not used before", "edit": {"invoice.invoice_number": "<unused>"},
               **_verify(t, clauses, "2.2.1", before), "caution": CAUTION["2.2.1"]}]
    return margin, record, []


def _gstin(clause):
    def handler(txn, clauses, flag, before, other):
        official = str((txn.get("vendor") or {}).get("official_gstin") or "")
        margin = {"value": None, "unit": None, "text": flag["message"]}
        record, policy = [], []
        if official:
            t = _copy(txn)
            t["invoice"]["gstin"] = official
            record.append({"change": f"The vendor master's GSTIN, {official}", "edit": {"invoice.gstin": official},
                           **_verify(t, clauses, clause, before), **({"caution": CAUTION[clause]} if clause in CAUTION else {})})
        if clause == "3.1.2":
            g = str(txn["invoice"].get("gstin") or "")
            p = clauses["3.1.2"]["params"]
            if g[:2].isdigit():
                code = int(g[:2])
                param, value = ("state_code_max", code) if code > p["state_code_max"] else ("state_code_min", code)
                changed = _clauses_with(clauses, "3.1.2", param, value)
                policy.append({"change": f"Rule 3.1.2's state codes widened to {changed['3.1.2']['params']['state_code_min']:02d}"
                                         f" to {changed['3.1.2']['params']['state_code_max']:02d}",
                               "parameter": f"3.1.2.{param}", "from": p[param], "to": value,
                               **_verify(txn, changed, "3.1.2", before), "also_clears": other("3.1.2", changed)})
        return margin, record, policy
    return handler


def _same_day(txn, clauses, flag, before, other):
    limit = int(clauses["4.1.1"]["params"]["max_invoices_per_vendor_per_day"])
    count = len([e for e in flag["evidence"] if e["field"].startswith("history.")]) + 1
    day = _day(txn["invoice"]["date"])
    margin = {"value": count - limit, "unit": "invoices beyond the daily count",
              "text": f"{count} invoices of the vendor on {day.isoformat()} against at most {limit}: "
                      f"{count - limit} too many"}
    history = list(txn.get("vendor_history") or [])
    busy = lambda d: sum(1 for h in history if _day(h["date"]) == d) + 1 > limit    # noqa: E731
    non_business = list((clauses.get("4.2.1") or {}).get("params", {}).get("non_business_days", ["Saturday", "Sunday"]))
    moved = _next_business(day, non_business, busy)
    t = _copy(txn)
    t["invoice"]["date"] = _same_type(txn["invoice"]["date"], moved)
    record = [{"change": f"This invoice dated {moved.isoformat()}, the next business day with room under the daily "
                         "count", "edit": {"invoice.date": moved.isoformat()}, **_verify(t, clauses, "4.1.1", before)}]
    changed = _clauses_with(clauses, "4.1.1", "max_invoices_per_vendor_per_day", count)
    policy = [{"change": f"Rule 4.1.1's daily count raised from {limit} to {count}",
               "parameter": "4.1.1.max_invoices_per_vendor_per_day", "from": limit, "to": count,
               **_verify(txn, changed, "4.1.1", before), "also_clears": other("4.1.1", changed)}]
    return margin, record, policy


def _non_business(txn, clauses, flag, before, other):
    days = list(clauses["4.2.1"]["params"]["non_business_days"])
    day = _day(txn["invoice"]["date"])
    name = controls.DAY_NAMES[day.weekday()]
    margin = {"value": None, "unit": None, "text": f"Dated {day.isoformat()}, a {name}"}
    moved = _next_business(day, days)
    t = _copy(txn)
    t["invoice"]["date"] = _same_type(txn["invoice"]["date"], moved)
    record = [{"change": f"Dated {moved.isoformat()}, the next business day", "edit": {"invoice.date": moved.isoformat()},
               **_verify(t, clauses, "4.2.1", before)}]
    changed = _clauses_with(clauses, "4.2.1", "non_business_days", [d for d in days if d != name])
    policy = [{"change": f"{name} no longer a non-business day under rule 4.2.1", "parameter": "4.2.1.non_business_days",
               "from": days, "to": changed["4.2.1"]["params"]["non_business_days"],
               **_verify(txn, changed, "4.2.1", before), "also_clears": other("4.2.1", changed)}]
    return margin, record, policy


def _round(txn, clauses, flag, before, other):
    multiple = int(clauses["4.3.1"]["params"]["round_amount_multiple"])
    amount = float(txn["invoice"]["amount"])
    margin = {"value": None, "unit": None,
              "text": f"{_rupees(amount)} is {controls.number(amount / multiple)} times {multiple:,}"}
    t = _copy(txn)
    t["invoice"]["amount"] = round(amount - 1, 2)
    record = [{"change": f"Any amount that is not a multiple of {multiple:,} (such as {_rupees(amount - 1)})",
               "edit": {"invoice.amount": round(amount - 1, 2)}, **_verify(t, clauses, "4.3.1", before)}]
    policy = []
    for factor in (2, 5, 10, 100):
        bigger = multiple * factor
        if controls.paise(amount) % (bigger * 100) != 0:
            changed = _clauses_with(clauses, "4.3.1", "round_amount_multiple", bigger)
            policy.append({"change": f"Rule 4.3.1's round multiple raised from {multiple:,} to {bigger:,}",
                           "parameter": "4.3.1.round_amount_multiple", "from": multiple, "to": bigger,
                           **_verify(txn, changed, "4.3.1", before), "also_clears": other("4.3.1", changed)})
            break
    return margin, record, policy


def _blocked(txn, clauses, flag, before, other):
    vendor = txn.get("vendor") or {}
    statuses = list(clauses["4.4.1"]["params"]["blocked_gstin_statuses"])
    margin = {"value": None, "unit": None, "text": flag["message"]}
    t = _copy(txn)
    t["vendor"]["blacklisted"] = False
    if t["vendor"].get("gstin_status") in statuses:
        t["vendor"]["gstin_status"] = "Active"
    record = [{"change": "The vendor cleared in the vendor master (not blacklisted, GST registration active)",
               "edit": {"vendor.blacklisted": False, "vendor.gstin_status": t["vendor"].get("gstin_status")},
               **_verify(t, clauses, "4.4.1", before), "caution": CAUTION["4.4.1"]}]
    policy = []
    if not controls.is_true(vendor.get("blacklisted")) and vendor.get("gstin_status") in statuses:
        changed = _clauses_with(clauses, "4.4.1", "blocked_gstin_statuses",
                                [s for s in statuses if s != vendor["gstin_status"]])
        policy.append({"change": f"GST status {vendor['gstin_status']} no longer blocked under rule 4.4.1",
                       "parameter": "4.4.1.blocked_gstin_statuses", "from": statuses,
                       "to": changed["4.4.1"]["params"]["blocked_gstin_statuses"],
                       **_verify(txn, changed, "4.4.1", before), "also_clears": other("4.4.1", changed)})
    return margin, record, policy


def _approval(txn, clauses, flag, before, other):
    limits = clauses["5.1.1"]["params"]["approval_limits"]
    entry = controls.approving_entry(txn)
    role, amount = entry["approver_role"], float(txn["invoice"]["amount"])
    limit = float(limits[role])
    margin = {"value": round(amount - limit, 2), "unit": "rupees above the approver's limit",
              "text": f"{_rupees(amount)} against the {role} limit of {_rupees(limit)}: {_rupees(amount - limit)} "
                      f"({(amount - limit) / limit * 100:.1f}%) above it"}
    record = []
    covering = sorted(((float(v), r) for r, v in limits.items() if float(v) >= amount))
    if covering:
        needed = covering[0][1]
        t = _copy(txn)
        for e in t["approvals"]:
            if e is not None and e.get("action_taken") == "Approved" and e.get("log_id") == entry.get("log_id"):
                e["approver_role"] = needed
        record.append({"change": f"Approved by a {needed} (limit {_rupees(covering[0][0])}), the lowest role whose "
                                 "limit covers the amount", "edit": {"approval.approver_role": needed},
                       **_verify(t, clauses, "5.1.1", before)})
    t = _copy(txn)
    t["invoice"]["amount"] = limit
    record.append({"change": f"An amount within the {role} limit (at most {_rupees(limit)})",
                   "edit": {"invoice.amount": limit}, **_verify(t, clauses, "5.1.1", before)})
    new_limit = math.ceil(amount)
    changed = _clauses_with(clauses, "5.1.1", "approval_limits", {**limits, role: new_limit})
    policy = [{"change": f"The {role} limit of rule 5.1.1 raised from {_rupees(limit)} to {_rupees(new_limit)}",
               "parameter": f"5.1.1.approval_limits.{role}", "from": limit, "to": new_limit,
               **_verify(txn, changed, "5.1.1", before), "also_clears": other("5.1.1", changed)}]
    return margin, record, policy


HANDLERS = {"2.1.1": _amount_match, "2.1.2": _quantity_match, "2.1.3": _missing_reference, "2.2.1": _exact_duplicate,
            "3.1.1": _gstin("3.1.1"), "3.1.2": _gstin("3.1.2"), "3.1.3": _gstin("3.1.3"), "4.1.1": _same_day,
            "4.2.1": _non_business, "4.3.1": _round, "4.4.1": _blocked, "5.1.1": _approval}


def explain(txn: dict, policy: Policy, flagged: Callable[[str], list[dict]] | None = None) -> list[dict]:
    """Every finding of the controls on ``txn`` under ``policy``, with its margin and its verified counterfactuals.

    ``flagged(clause)`` gives the transactions of the invoices whose latest result carries a kept finding of that
    rule; with it, each policy change says how many of them (other than this invoice) it would also clear.
    """
    clauses = policy.clauses
    flags = controls.run_controls(txn, clauses)
    before = {f["clause"] for f in flags}
    own = txn["invoice"]["invoice_id"]

    def other(clause: str, changed: dict) -> int | None:
        if flagged is None:
            return None
        control = next(c for c in controls.CONTROLS if any(f["clause"] == clause for f in c(txn, clauses)))
        return sum(1 for t in flagged(clause) if t["invoice"]["invoice_id"] != own
                   and not any(f["clause"] == clause for f in control(t, changed)))

    out = []
    for flag in flags:
        handler = HANDLERS.get(flag["clause"])
        if handler is None:
            continue
        margin, record, policy_changes = handler(txn, clauses, flag, before, other)
        out.append({"clause": flag["clause"], "title": clauses[flag["clause"]]["title"], "severity": flag["severity"],
                    "message": flag["message"], "margin": margin, "record": [o for o in record if o["clears"]],
                    "policy": [o for o in policy_changes if o["clears"]],
                    "no_parameter": flag["clause"] in RULES_WITHOUT_PARAMETER})
    return out
