"""Evidence extraction: join the records linked to each invoice into one transaction.

    python -m auditiq.extraction data/seed_101 transactions.jsonl

First stage of the pipeline. Every later stage (controls, agents, challenger,
scorer) sees only what is produced here. The labels are never read.

One line per invoice:
    { invoice, po | null, grn | null, vendor, approvals: [...], vendor_history: [...] }
vendor_history holds the other invoices of the same vendor, oldest first (a
``history.History``: a list with an index of the vendor's invoices).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from .history import History, vendor_histories

INVOICE_FIELDS = ["invoice_id", "vendor_id", "invoice_number", "date", "amount", "quantity",
                  "unit_price", "gstin", "po_id", "grn_id", "description"]
PO_FIELDS = ["po_id", "vendor_id", "po_date", "amount", "quantity", "unit_price", "description"]
GRN_FIELDS = ["grn_id", "po_id", "receipt_date", "received_quantity", "ordered_quantity", "amount", "notes"]
VENDOR_FIELDS = ["vendor_id", "vendor_name", "vendor_category", "official_gstin", "blacklisted", "gstin_status"]
LOG_FIELDS = ["log_id", "approver_name", "approver_role", "timestamp", "action_taken", "amount_limit"]
HISTORY_FIELDS = ["invoice_id", "invoice_number", "date", "amount", "quantity", "po_id", "grn_id", "description"]
NUMERIC = {"amount", "unit_price", "amount_limit"}
INTEGER = {"quantity", "received_quantity", "ordered_quantity"}
BOOLEAN = {"blacklisted"}
NULLABLE = {"po_id", "grn_id"}


def read(dataset: Path, name: str) -> pd.DataFrame:
    # Everything is read as text so that identifiers and GSTINs are not altered.
    return pd.read_csv(dataset / f"{name}.csv", dtype=str, keep_default_na=False, encoding="utf-8")


def record(row: dict, fields: list[str]) -> dict:
    out = {}
    for f in fields:
        value = row[f]
        if f in NUMERIC:
            value = float(value)
        elif f in INTEGER:
            value = int(value)
        elif f in BOOLEAN:
            value = value.strip().lower() in ("true", "t", "1")
        elif f in NULLABLE and value == "":
            value = None
        out[f] = value
    return out


def extract(dataset: Path) -> list[dict]:
    invoices = read(dataset, "invoices").to_dict("records")
    po = {r["po_id"]: r for r in read(dataset, "purchase_orders").to_dict("records")}
    grn = {r["grn_id"]: r for r in read(dataset, "goods_receipts").to_dict("records")}
    vendor = {r["vendor_id"]: r for r in read(dataset, "vendor_master").to_dict("records")}
    logs: dict[str, list[dict]] = {}
    for r in read(dataset, "approval_logs").to_dict("records"):
        logs.setdefault(r["transaction_id"], []).append(record(r, LOG_FIELDS))
    for entries in logs.values():
        entries.sort(key=lambda e: (e["timestamp"], e["log_id"]))

    def approver(invoice_id: str) -> dict:
        approved = [e for e in logs.get(invoice_id, []) if e["action_taken"] == "Approved"]
        last = approved[-1] if approved else {}
        return {"approver_role": last.get("approver_role"), "approver_name": last.get("approver_name")}

    # One history record per invoice, shared by every transaction of the vendor,
    # so that a ledger of any size stays small in memory. Stages only read it.
    by_vendor: dict[str, list[dict]] = {}
    for r in sorted(invoices, key=lambda r: (r["date"], r["invoice_id"])):
        by_vendor.setdefault(r["vendor_id"], []).append(
            {**record(r, HISTORY_FIELDS), **approver(r["invoice_id"])})
    indexes = vendor_histories(by_vendor)

    transactions = []
    for r in sorted(invoices, key=lambda r: r["invoice_id"]):
        transactions.append({
            "invoice": record(r, INVOICE_FIELDS),
            "po": record(po[r["po_id"]], PO_FIELDS) if r["po_id"] in po else None,
            "grn": record(grn[r["grn_id"]], GRN_FIELDS) if r["grn_id"] in grn else None,
            "vendor": record(vendor[r["vendor_id"]], VENDOR_FIELDS),
            "approvals": logs.get(r["invoice_id"], []),
            "vendor_history": History([h for h in by_vendor[r["vendor_id"]] if h["invoice_id"] != r["invoice_id"]],
                                      indexes[r["vendor_id"]]),
        })
    return transactions


def write_jsonl(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    rows = extract(Path(sys.argv[1]))
    write_jsonl(rows, Path(sys.argv[2]))
    print(f"wrote {len(rows)} transactions to {sys.argv[2]}")
