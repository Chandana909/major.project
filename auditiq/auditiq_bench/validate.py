"""Checks on a finished dataset, computed from the exported tables.

The generator labels by construction. This module recomputes, from the tables
alone, which rule-defined clauses each invoice violates and requires the result
to equal the labels, in both directions. It also checks the structure of the
judgement classes and that no unlabelled invoice falls inside their definitions.
It belongs to the generator and shares no code with ``controls/``.
"""
from __future__ import annotations

import re
from datetime import date

import pandas as pd

from . import catalog as cat
from .generator import NEAR_BAND, NEAR_DAYS
from .taxonomy import CLASSES, HARD_NEGATIVE_TYPES

RULE_CLAUSES = {c for k in CLASSES.values() if k.kind == "rule" for c in k.clauses}
MONTH_SUFFIX = re.compile(r", [A-Z][a-z]{2} \d{4}$")


def rule_clauses(tables: dict[str, pd.DataFrame], policy: dict) -> dict[str, set[str]]:
    """Clauses of the rule-defined classes that each invoice violates."""
    p = {k: v["params"] for k, v in policy["clauses"].items()}
    tol = p["2.1.1"]["amount_tolerance_pct"] / 100.0
    max_day = p["4.1.1"]["max_invoices_per_vendor_per_day"]
    multiple = p["4.3.1"]["round_amount_multiple"]
    limits = p["5.1.1"]["approval_limits"]
    blocked_status = set(p["4.4.1"]["blocked_gstin_statuses"])
    off_days = set(p["4.2.1"]["non_business_days"])

    inv = tables["invoices"].fillna("")
    po = tables["purchase_orders"].set_index("po_id")
    grn = tables["goods_receipts"].set_index("grn_id")
    vendor = tables["vendor_master"].set_index("vendor_id")
    logs = tables["approval_logs"]
    approved = (logs[logs["action_taken"] == "Approved"]
                .sort_values("timestamp").groupby("transaction_id").last())
    per_day = inv.groupby(["vendor_id", "date"]).size()

    found: dict[str, set[str]] = {}
    seen_numbers: dict[tuple[str, str], int] = {}
    for row in inv.sort_values(["date", "invoice_id"]).itertuples():
        hit: set[str] = set()
        amount = float(row.amount)
        has_po = row.po_id != "" and row.po_id in po.index
        has_grn = row.grn_id != "" and row.grn_id in grn.index
        if not has_po or not has_grn:
            hit.add("2.1.3")
        if has_po:
            po_amount = float(po.at[row.po_id, "amount"])
            if abs(amount - po_amount) > tol * po_amount + 1e-6:
                hit.add("2.1.1")
        if has_grn and int(row.quantity) > int(grn.at[row.grn_id, "received_quantity"]):
            hit.add("2.1.2")
        key = (row.vendor_id, row.invoice_number)
        if key in seen_numbers:
            hit.add("2.2.1")
        seen_numbers[key] = seen_numbers.get(key, 0) + 1

        g = row.gstin
        format_ok = len(g) == p["3.1.1"]["gstin_length"] and g.isascii() and g.isalnum()
        state_ok = (len(g) >= 2 and g[:2].isdigit()
                    and p["3.1.2"]["state_code_min"] <= int(g[:2]) <= p["3.1.2"]["state_code_max"])
        if not format_ok:
            hit.add("3.1.1")
        if not state_ok:
            hit.add("3.1.2")
        if format_ok and state_ok and g != vendor.at[row.vendor_id, "official_gstin"]:
            hit.add("3.1.3")

        if per_day[(row.vendor_id, row.date)] > max_day:
            hit.add("4.1.1")
        if date.fromisoformat(row.date).strftime("%A") in off_days:
            hit.add("4.2.1")
        if round(amount * 100) % (multiple * 100) == 0:
            hit.add("4.3.1")
        if bool(vendor.at[row.vendor_id, "blacklisted"]) or vendor.at[row.vendor_id, "gstin_status"] in blocked_status:
            hit.add("4.4.1")
        if row.invoice_id in approved.index:
            if amount > limits[approved.at[row.invoice_id, "approver_role"]]:
                hit.add("5.1.1")
        found[row.invoice_id] = hit
    return found


def validate(tables: dict[str, pd.DataFrame], policy: dict, expected_counts: dict | None = None) -> list[str]:
    """Return a list of problems; an empty list means the dataset is consistent."""
    problems: list[str] = []
    labels = tables["labels"].fillna("").set_index("invoice_id")
    inv = tables["invoices"].fillna("").set_index("invoice_id")
    grn = tables["goods_receipts"].fillna("").set_index("grn_id")
    po = tables["purchase_orders"].set_index("po_id")
    limits = policy["clauses"]["5.1.1"]["params"]["approval_limits"]
    j2 = policy["clauses"]["4.1.2"]["params"]

    for name in ("invoices", "purchase_orders", "goods_receipts", "approval_logs", "vendor_master"):
        key = tables[name].columns[0]
        if tables[name][key].duplicated().any():
            problems.append(f"{name}: duplicate {key}")

    # 1. Rule-defined clauses equal the labels, invoice by invoice.
    found = rule_clauses(tables, policy)
    for invoice_id, hit in found.items():
        labelled = set(filter(None, labels.at[invoice_id, "clause_ids"].split("|"))) & RULE_CLAUSES
        if hit != labelled:
            problems.append(f"{invoice_id}: tables show {sorted(hit)}, label says {sorted(labelled)} "
                            f"({labels.at[invoice_id, 'class_id'] or labels.at[invoice_id, 'label']})")

    # 2. Label fields are coherent.
    for row in labels.itertuples():
        clauses = set(filter(None, row.clause_ids.split("|")))
        if row.label == "anomalous":
            if row.class_id not in CLASSES or not clauses or not clauses <= set(CLASSES[row.class_id].clauses):
                problems.append(f"{row.Index}: class {row.class_id!r} with clauses {sorted(clauses)}")
        elif clauses or row.class_id:
            problems.append(f"{row.Index}: {row.label} invoice carries a class or clause")
        if (row.label == "hard_negative") != (row.hard_negative_type in HARD_NEGATIVE_TYPES):
            problems.append(f"{row.Index}: hard-negative type {row.hard_negative_type!r} on a {row.label} invoice")

    # 3. Duplicates (R3, J1): the labelled invoice follows an original with the
    #    same vendor, PO, GRN and amount; nothing else shares a PO.
    for po_id, group in inv[inv["po_id"] != ""].groupby("po_id"):
        if len(group) == 1:
            continue
        group = group.sort_values(["date"])
        original, copies = group.iloc[0], group.iloc[1:]
        if labels.at[original.name, "label"] != "clean":
            problems.append(f"{original.name}: original of a duplicate is not clean")
        for copy_id, copy in copies.iterrows():
            cls = labels.at[copy_id, "class_id"]
            same = (copy.vendor_id == original.vendor_id and copy.grn_id == original.grn_id
                    and float(copy.amount) == float(original.amount) and copy.date > original.date
                    and labels.at[copy_id, "related_invoice_id"] == original.name)
            same_number = copy.invoice_number == original.invoice_number
            if not same or cls not in ("R3", "J1") or (cls == "R3") != same_number:
                problems.append(f"{copy_id}: shares {po_id} with {original.name} but is labelled {cls!r}")
    for cls in ("R3", "J1"):
        for invoice_id in labels.index[labels["class_id"] == cls]:
            related = labels.at[invoice_id, "related_invoice_id"]
            if related not in inv.index or inv.at[related, "po_id"] != inv.at[invoice_id, "po_id"]:
                problems.append(f"{invoice_id}: {cls} without an original on the same PO")

    # 4. Structuring (J2): group structure, and no unlabelled near-limit pair.
    logs = tables["approval_logs"]
    approved = (logs[logs["action_taken"] == "Approved"]
                .sort_values("timestamp").groupby("transaction_id").last())
    for gid, members in labels[labels["class_id"] == "J2"].groupby("group_id"):
        rows = inv.loc[members.index]
        dates = sorted(date.fromisoformat(d) for d in rows["date"])
        roles = set(approved.loc[members.index, "approver_role"])
        names = set(approved.loc[members.index, "approver_name"])
        ok = len(roles) == 1 and len(names) == 1 and rows["vendor_id"].nunique() == 1
        if ok:
            limit = limits[next(iter(roles))]
            amounts = rows["amount"].astype(float)
            ok = (len(set(dates)) == len(dates) >= 2
                  and (dates[-1] - dates[0]).days < j2["guide_window_days"]
                  and ((amounts > (1 - j2["guide_band_pct"] / 100) * limit) & (amounts < limit)).all()
                  and amounts.sum() > limit
                  and rows["po_id"].map(lambda x: po.at[x, "description"]).nunique() == 1)
        if not ok:
            problems.append(f"{gid}: not a structuring group as defined in clause 4.1.2")
    for limit in sorted(set(limits.values())):
        near = inv[(inv["amount"].astype(float) >= (1 - NEAR_BAND) * limit) & (inv["amount"].astype(float) <= limit)]
        for vendor_id, group in near.groupby("vendor_id"):
            rows = sorted((date.fromisoformat(r.date), r.Index) for r in group.itertuples())
            for (d1, a), (d2, b) in zip(rows, rows[1:]):
                if (d2 - d1).days <= NEAR_DAYS:
                    g1, g2 = labels.at[a, "group_id"], labels.at[b, "group_id"]
                    if not (g1 and g1 == g2 and labels.at[a, "class_id"] == "J2"):
                        problems.append(f"{a}, {b}: two invoices of {vendor_id} near limit {limit:,} "
                                        f"within {NEAR_DAYS} days outside a J2 group")

    # 5. Receipt remarks (J4) and descriptions (J3).
    benign = set(cat.BENIGN_REMARKS_GOODS) | set(cat.BENIGN_REMARKS_SERVICES) | set(cat.SHORT_RECEIPT_REMARKS)
    j4_grns = set(inv.loc[labels.index[labels["class_id"] == "J4"], "grn_id"])
    for grn_id, notes in grn["notes"].items():
        if (notes not in benign) != (grn_id in j4_grns):
            problems.append(f"{grn_id}: remark {notes!r} does not match its J4 status")
    items = {it.po_text: it for it in cat.ITEMS}
    for row in inv[inv["po_id"].isin(po.index)].itertuples():
        po_text = po.at[row.po_id, "description"]
        suffix = (MONTH_SUFFIX.search(po_text) or [""])[0]
        item = items[po_text.removesuffix(suffix)]
        same_goods = row.description in {
            t.format(po=item.po_text, alt=item.alt_text, qty=row.quantity, unit=item.unit) + suffix
            for t in cat.INVOICE_TEXT_TEMPLATES
        }
        if same_goods == (labels.at[row.Index, "class_id"] == "J3"):
            problems.append(f"{row.Index}: description {row.description!r} vs PO {po_text!r} "
                            f"does not match its J3 status")

    # 6. Composition.
    if expected_counts:
        counts = {
            "invoices": len(inv),
            "vendors": len(tables["vendor_master"]),
            **{f"class:{c}": int((labels["class_id"] == c).sum()) for c in expected_counts.get("classes", [])},
            **{f"hn:{h}": int((labels["hard_negative_type"] == h).sum()) for h in expected_counts.get("hard_negatives", [])},
            "clean": int((labels["label"] == "clean").sum()),
        }
        for key, want in expected_counts["values"].items():
            if counts.get(key) != want:
                problems.append(f"count {key}: {counts.get(key)} instead of {want}")
    return problems
