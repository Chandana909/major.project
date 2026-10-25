"""Revisions: what each control finding requires, computed from its evidence and the policy (no model).

AuditBench (Wang et al., 2025) evaluates models on finding errors, explaining them, citing the standard they
violate and making the required revisions, and reports them weak at the explanation and the citation and
struggling with the revisions. For the twelve rules the controls decide, the revision is arithmetic on the
records and the policy, so it is computed, not generated: the amount an invoice may bill, the quantity it may
bill, the GSTIN it must carry, the role that must approve it. A finding of an agent (a judgement rule) gets no computed revision: it goes to the
reviewer.

A revision is
    {"clause", "kind", "action", "changes": [{"field", "from", "to"}], "amount_at_issue"}
kind      amend      the invoice must be corrected: `changes` say how, and a corrected invoice passes the rule
          reapprove  the invoice must be approved again, by the role in `changes`
          consolidate  the invoices of the day are one purchase; `changes` name the role its total needs
          reject     the invoice must not be paid (a duplicate)
          hold       payment waits until the vendor's standing is restored
          obtain     a missing document must be obtained before payment
          verify     the invoice is allowed by no rule as it stands, but needs supporting evidence
`amount_at_issue` is the money the finding concerns, where there is one (rupees, two decimals).
evaluation/revisions.py checks, on every finding of the benchmark ledgers, that an amended or re-approved
invoice passes the rule it failed and raises no new finding.
"""
from __future__ import annotations

from .controls import approving_entry, gstin_checks, number, paise


def _rupees(paise_value: int) -> float:
    return round(paise_value / 100, 2)


def _role_for(amount, limits: dict) -> tuple[str, float] | None:
    """The role with the lowest approval limit that covers the amount."""
    covering = [(limit, role) for role, limit in limits.items() if paise(limit) >= paise(amount)]
    if not covering:
        return None
    limit, role = min(covering)
    return role, limit


def correct(flag: dict, txn: dict, clauses: dict) -> dict | None:
    """The revision a control finding requires, or None for an agent's finding."""
    if flag.get("source") != "D":
        return None
    control = flag.get("control")
    inv = txn["invoice"]
    out = {"clause": flag["clause"], "kind": "verify", "action": "", "changes": [], "amount_at_issue": None}

    if control == "amount_match":
        po = txn["po"]["amount"]
        difference = paise(inv["amount"]) - paise(po)
        over = difference > 0
        out.update(kind="amend", amount_at_issue=_rupees(abs(difference)),
                   changes=[{"field": "invoice.amount", "from": inv["amount"], "to": po}],
                   action=(f"Bill the PO amount of {po:.2f}: the invoice is {_rupees(difference):.2f} above it; "
                           "obtain a credit note for the difference." if over else
                           f"Bill the PO amount of {po:.2f}, or record why the invoice is "
                           f"{_rupees(-difference):.2f} below it (a partial delivery is invoiced against its "
                           "own goods receipt)."))
        # Raised to the PO amount, an invoice can pass its approver's limit: the revision says who approves it.
        limits = clauses.get("5.1.1", {}).get("params", {}).get("approval_limits", {})
        entry = approving_entry(txn)
        limit = limits.get(entry["approver_role"]) if entry else None
        if limit is not None and paise(po) > paise(limit):
            needed = _role_for(po, limits)
            if needed:
                out["changes"].append({"field": "approval.approver_role", "from": entry["approver_role"],
                                       "to": needed[0]})
                out["action"] += (f" At {po:.2f} it is above the {entry['approver_role']}'s limit of "
                                  f"{number(limit)}: obtain approval from a {needed[0]}.")
    elif control == "quantity_match":
        billed, received = inv["quantity"], txn["grn"]["received_quantity"]
        excess = float(billed) - float(received)
        unit = inv.get("unit_price")
        money = _rupees(round(excess * paise(unit))) if unit not in (None, "") else None
        out.update(kind="amend", amount_at_issue=money,
                   changes=[{"field": "invoice.quantity", "from": billed, "to": received}],
                   action=f"Bill only the {number(received)} units received; {number(excess)} were not received"
                          + (f" ({money:.2f} at the invoice's unit price): obtain a credit note." if money is not None
                             else "."))
    elif control == "missing_reference":
        missing = [e["field"].split(".")[-1] for e in flag.get("evidence", [])]
        nouns = {"po_id": "the purchase order", "grn_id": "the goods receipt"}
        out.update(kind="obtain", action="Obtain " + " and ".join(nouns.get(m, m) for m in missing)
                   + " the invoice must refer to, and hold payment until it is on record.")
    elif control == "exact_duplicate":
        original = next((e for e in flag.get("evidence", []) if e["field"].startswith("history.")), None)
        first = original["field"].split(".")[1] if original else "an earlier invoice"
        out.update(kind="reject", amount_at_issue=float(inv["amount"]),
                   action=f"Reject: the invoice number was already billed by {first}. Paying it would pay "
                          f"{float(inv['amount']):.2f} twice.")
    elif control in ("gstin_format", "gstin_state_code", "gstin_vendor_match"):
        official = (txn.get("vendor") or {}).get("official_gstin")
        _, format_ok, state_ok = gstin_checks(official, clauses)
        if official and format_ok and state_ok:
            out.update(kind="amend", changes=[{"field": "invoice.gstin", "from": inv.get("gstin"), "to": official}],
                       action=f"Obtain a corrected invoice bearing the vendor's registered GSTIN {official}; input "
                              "tax credit cannot be claimed on the invoice as it stands.")
        else:
            out.update(kind="obtain", action="Obtain the vendor's valid GSTIN and update the vendor master before "
                                             "accepting the invoice.")
    elif control == "same_day_splitting":
        day = inv["date"]
        others = [h for h in txn.get("vendor_history") or [] if h["date"] == day]
        total = paise(inv["amount"]) + sum(paise(h["amount"]) for h in others)
        limits = clauses.get("5.1.1", {}).get("params", {}).get("approval_limits", {})
        needed = _role_for(_rupees(total), limits)
        role_text = (f"approved as one purchase by a {needed[0]} (limit {number(needed[1])})" if needed else
                     "approved as one purchase above every approval limit in the policy")
        out.update(kind="consolidate", amount_at_issue=_rupees(total),
                   changes=[{"field": "approval.approver_role", "from": None, "to": needed[0]}] if needed else [],
                   action=f"Treat the {len(others) + 1} invoices of {day} as one purchase of {_rupees(total):.2f}, "
                          f"{role_text}.")
    elif control == "non_business_day":
        out.update(action=f"Confirm the invoice date of {inv['date']} with the vendor and obtain the delivery "
                          "record: the policy does not allow invoices on that day.")
    elif control == "round_amount":
        out.update(amount_at_issue=float(inv["amount"]),
                   action=f"Obtain the itemised bill behind the round amount of {float(inv['amount']):.2f}.")
    elif control == "blocked_vendor":
        out.update(kind="hold", amount_at_issue=float(inv["amount"]),
                   action="Hold payment: the vendor is blocked. Pay only after the vendor's standing is restored "
                          "in the vendor master.")
    elif control == "approval_limit":
        limits = clauses["5.1.1"]["params"]["approval_limits"]
        needed = _role_for(inv["amount"], limits)
        entry = approving_entry(txn) or {}
        if needed:
            out.update(kind="reapprove",
                       changes=[{"field": "approval.approver_role", "from": entry.get("approver_role"),
                                 "to": needed[0]}],
                       action=f"Obtain approval from a {needed[0]} (limit {number(needed[1])}) before payment.")
        else:
            out.update(kind="reapprove", action="The amount exceeds every approval limit in the policy: refer it "
                                                "to the board or split the purchase under separate approvals.")
    else:
        return None
    return out


def apply(txn: dict, revision: dict) -> dict:
    """A copy of the transaction with the revision's changes made (for checking that it resolves the finding)."""
    fixed = {**txn, "invoice": dict(txn["invoice"]), "approvals": [dict(a) for a in txn.get("approvals") or []]}
    for change in revision["changes"]:
        record, _, field = change["field"].partition(".")
        if record == "invoice":
            fixed["invoice"][field] = change["to"]
        elif record == "approval" and change["to"]:
            entry = approving_entry(fixed)
            if entry is not None:
                entry[field] = change["to"]
    return fixed
