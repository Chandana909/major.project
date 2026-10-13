"""Turn the builder's transactions into tables with final identifiers.

Identifiers are assigned in date order with a random tie-break, so an
identifier carries no information about the label.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

import pandas as pd

from . import catalog as cat
from .generator import Builder

GST_RATE = 0.18
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def financial_year(d: date) -> str:
    first = d.year if d.month >= 4 else d.year - 1
    return f"{first % 100:02d}-{(first + 1) % 100:02d}"


def rekey_variants(number: str) -> list[str]:
    """Re-keyed forms of an invoice number (class J1)."""
    out = []
    stripped = number.replace("/", "").replace("-", "")
    if stripped != number:
        out.append(stripped)
    if "/" in number:
        out.append(number.replace("/", "-"))
    elif "-" in number:
        out.append(number.replace("-", "/"))
    zeros = re.search(r"0+(\d+)$", number)
    if zeros:
        out.append(number[: zeros.start()] + zeros.group(1))
    out += [number + "-A", number + "A", number + "-R"]
    if number[-1].isdigit() and number[-2].isdigit() and number[-1] != number[-2]:
        out.append(number[:-2] + number[-1] + number[-2])
    if "0" in number:
        i = number.rfind("0")
        out.append(number[:i] + "O" + number[i + 1:])
    if any(ch.isalpha() for ch in number):
        out.append(number.lower())
    return out


def assign_invoice_numbers(b: Builder) -> None:
    by_vendor: dict[str, list[dict]] = {}
    for t in b.txns:
        by_vendor.setdefault(t["vendor"].vendor_id, []).append(t)
    for vendor_id in sorted(by_vendor):
        txns = by_vendor[vendor_id]
        originals = sorted((t for t in txns if t["label"]["related_key"] is None),
                           key=lambda t: (t["date"], t["key"]))
        seq = int(b.rng.integers(100, 900))
        previous = None
        for t in originals:
            consecutive = previous is not None and t.get("follows") == previous["key"]
            seq += 1 if consecutive or b.chance(0.6) else int(b.rng.integers(2, 6))
            v = t["vendor"]
            t["invoice"]["number"] = v.number_style.format(p=v.prefix, fy=financial_year(t["date"]), n=seq)
            previous = t
        used = {t["invoice"]["number"] for t in originals}
        assert len(used) == len(originals)
        copies = sorted((t for t in txns if t["label"]["related_key"] is not None), key=lambda t: t["key"])
        for t in copies:
            base_number = b.txns[t["label"]["related_key"]]["invoice"]["number"]
            if t["label"]["class_id"] == "R3":
                t["invoice"]["number"] = base_number
                continue
            variants = [v for v in rekey_variants(base_number) if v not in used]
            number = variants[int(b.rng.integers(len(variants)))]
            used.add(number)
            t["invoice"]["number"] = number
            t["label"]["note"] += f"; number '{number}' re-keys '{base_number}'"


def to_tables(b: Builder) -> dict[str, pd.DataFrame]:
    assign_invoice_numbers(b)
    tie = b.rng.random(len(b.txns))

    # Purchase orders and goods receipts (a duplicate invoice shares its
    # original's documents, so collect each object once).
    pos, grns, seen = [], [], set()
    for t in b.txns:
        for doc, bucket in ((t["po"], pos), (t["grn"], grns)):
            if doc is not None and id(doc) not in seen:
                seen.add(id(doc))
                doc["_tie"] = float(tie[t["key"]])
                bucket.append(doc)
        if t["grn"] is not None:
            t["grn"]["_po"] = t["po"]
    for i, po in enumerate(sorted(pos, key=lambda d: (d["po_date"], d["_tie"]))):
        po["_id"] = f"PO{20001 + i}"
    for i, grn in enumerate(sorted(grns, key=lambda d: (d["receipt_date"], d["_tie"]))):
        grn["_id"] = f"GRN{30001 + i}"
    dangling = set()

    invoices = sorted(b.txns, key=lambda t: (t["date"], float(tie[t["key"]])))
    for i, t in enumerate(invoices):
        t["invoice_id"] = f"INV{40001 + i}"

    inv_rows, label_rows, log_entries = [], [], []
    for t in invoices:
        inv, v = t["invoice"], t["vendor"]
        if t["po"] is not None:
            po_id = t["po"]["_id"]
        elif inv["dangling_po"]:
            po_id = f"PO{20001 + len(pos) + int(b.rng.integers(500, 5000))}"
            while po_id in dangling:
                po_id = f"PO{20001 + len(pos) + int(b.rng.integers(500, 5000))}"
            dangling.add(po_id)
        else:
            po_id = ""
        tax = round(inv["amount"] * GST_RATE, 2)
        approved = [a for a in t["approvals"] if a["action_taken"] == "Approved"][-1]
        inv_rows.append({
            "invoice_id": t["invoice_id"],
            "vendor_id": v.vendor_id,
            "invoice_number": inv["number"],
            "date": t["date"].isoformat(),
            "invoice_date": f"{t['date'].isoformat()} 00:00:00",
            "due_date": (t["date"] + timedelta(days=30)).isoformat(),
            "amount": inv["amount"],
            "invoice_amount": inv["amount"],
            "quantity": inv["quantity"],
            "unit_price": inv["unit_price"],
            "currency": "INR",
            "tax_amount": tax,
            "total_amount": round(inv["amount"] + tax, 2),
            "gstin": inv["gstin"],
            "po_id": po_id,
            "grn_id": t["grn"]["_id"] if t["grn"] is not None else "",
            "department": cat.CATEGORIES[v.category].department,
            "payment_terms": "Net 30",
            "payment_status": "Unpaid",
            "approval_status": "Approved",
            "approved_by": approved["approver_name"],
            "description": inv["description"],
        })
        for a in t["approvals"]:
            log_entries.append({**a, "transaction_id": t["invoice_id"]})
        lab = t["label"]
        severities = [b.policy["clauses"][c]["severity"] for c in lab["clauses"]]
        label_rows.append({
            "invoice_id": t["invoice_id"],
            "label": lab["label"],
            "class_id": lab["class_id"],
            "clause_ids": "|".join(lab["clauses"]),
            "severity": max(severities, key=SEVERITY_RANK.get) if severities else "",
            "group_id": lab["group_id"],
            "related_invoice_id": (b.txns[lab["related_key"]]["invoice_id"]
                                   if lab["related_key"] is not None else ""),
            "hard_negative_type": lab["hard_negative_type"],
            "note": lab["note"],
        })

    po_rows = [{
        "po_id": po["_id"],
        "vendor_id": po["vendor"].vendor_id,
        "po_date": po["po_date"].isoformat(),
        "amount": po["amount"],
        "po_amount": po["amount"],
        "quantity": po["quantity"],
        "unit_price": po["unit_price"],
        "tax_amount": round(po["amount"] * GST_RATE, 2),
        "total_amount": round(po["amount"] * (1 + GST_RATE), 2),
        "currency": "INR",
        "department": cat.CATEGORIES[po["vendor"].category].department,
        "requester": po["requester"],
        "status": "Closed",
        "description": po["description"],
    } for po in sorted(pos, key=lambda d: d["_id"])]

    grn_rows = [{
        "grn_id": g["_id"],
        "po_id": g["_po"]["_id"],
        "vendor_id": g["vendor"].vendor_id,
        "receipt_date": g["receipt_date"].isoformat(),
        "received_quantity": g["received_quantity"],
        "ordered_quantity": g["ordered_quantity"],
        "unit_price": g["unit_price"],
        "amount": round(g["received_quantity"] * g["unit_price"], 2),
        "received_amount": round(g["received_quantity"] * g["unit_price"], 2),
        "received_by": g["received_by"],
        "warehouse_location": "Main Stores",
        "quality_check": "Passed",
        "status": "Complete",
        "notes": g["notes"],
    } for g in sorted(grns, key=lambda d: d["_id"])]

    log_entries.sort(key=lambda a: (a["timestamp"], a["transaction_id"]))
    log_rows = [{
        "log_id": f"LOG{50001 + i}",
        "transaction_id": a["transaction_id"],
        "approver_name": a["approver_name"],
        "approver_role": a["approver_role"],
        "timestamp": a["timestamp"].strftime("%Y-%m-%d %H:%M:%S"),
        "action_taken": a["action_taken"],
        "amount_limit": a["amount_limit"],
    } for i, a in enumerate(log_entries)]

    vendor_rows = [{
        "vendor_id": v.vendor_id,
        "vendor_name": v.name,
        "official_gstin": v.gstin,
        "pan_number": v.pan,
        "vendor_category": v.category,
        "city": cat.STATES[v.state_code][1],
        "state": cat.STATES[v.state_code][0],
        "country": "India",
        "gstin_status": v.gstin_status,
        "kyc_status": "Verified",
        "is_active": True,
        "blacklisted": v.blacklisted,
        "blacklist_status": v.blacklisted,
    } for v in b.vendors]

    return {
        "vendor_master": pd.DataFrame(vendor_rows),
        "purchase_orders": pd.DataFrame(po_rows),
        "goods_receipts": pd.DataFrame(grn_rows),
        "invoices": pd.DataFrame(inv_rows),
        "approval_logs": pd.DataFrame(log_rows),
        "labels": pd.DataFrame(label_rows),
    }
