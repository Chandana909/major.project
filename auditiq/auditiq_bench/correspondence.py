"""Synthetic vendor correspondence for a ledger: one mbox file of MIME e-mails and a CSV of what each one is.

    python -m auditiq_bench.correspondence --dataset data/bench_seed_202 --out .auditiq/bench_seed_202.mbox

The e-mails are what a payables mailbox receives from the ledger's vendors:
invoices sent for payment, payment reminders, quantity queries, and requests to
change bank details. A few of the bank-detail requests come from a look-alike of
the vendor's domain and press for payment to a new account: the business-e-mail-
compromise pattern that e-mail triage has to catch. The labels file says which.

Every address is under the reserved domain `.example` (RFC 2606). Generation is
seeded: the same ledger and seed give the same file.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import mailbox
import random
import re
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

import pandas as pd

BUYER = "payables@buyer.example"
IST = timezone(timedelta(hours=5, minutes=30))
SUBMITTED, REMINDED, BANK_CHANGES, LOOKALIKES = 0.35, 0.06, 0.08, 0.03     # shares of invoices / vendors


def domain(vendor_name: str) -> str:
    return (re.sub(r"[^a-z0-9]+", "", vendor_name.lower())[:24] or "vendor") + ".example"


def lookalike(real: str, rng: random.Random) -> str:
    """A domain that reads like the vendor's at a glance."""
    name = real.removesuffix(".example")
    options = [f"{name}-accounts", f"{name}s", f"pay-{name}"] + ([name.replace("i", "l", 1)] if "i" in name else [])
    return rng.choice(options) + ".example"


def _read(dataset: Path, name: str) -> list[dict]:
    return pd.read_csv(dataset / f"{name}.csv", dtype=str, keep_default_na=False, encoding="utf-8").to_dict("records")


def _when(day: str, rng: random.Random, after_days: tuple[int, int] = (0, 1)) -> datetime:
    start = datetime.strptime(day[:10], "%Y-%m-%d").replace(tzinfo=IST)
    return start + timedelta(days=rng.randint(*after_days), hours=rng.randint(9, 18), minutes=rng.randint(0, 59))


def _account(rng: random.Random) -> str:
    bank = rng.choice(["HDFC", "ICIC", "SBIN", "UTIB", "KKBK"])
    return f"IFSC {bank}000{rng.randint(1000, 9999)}, account {rng.randint(10**11, 10**12 - 1)}"


def generate(dataset: Path, seed: int = 7) -> tuple[list[EmailMessage], list[dict]]:
    """The e-mails for a ledger, oldest first, and one label per e-mail."""
    rng = random.Random(seed)
    vendors = {v["vendor_id"]: v for v in _read(dataset, "vendor_master")}
    receipts = {g["grn_id"]: g for g in _read(dataset, "goods_receipts")}
    invoices = sorted(_read(dataset, "invoices"), key=lambda r: (r["date"], r["invoice_id"]))
    drafts: list[tuple[datetime, str, str, str, dict]] = []      # (sent, sender, subject, body, label)

    def add(sent, sender, subject, body, category, invoice, suspicious=False):
        drafts.append((sent, sender, subject, body, {"category": category, "suspicious": suspicious,
                                                     "invoice_id": invoice["invoice_id"],
                                                     "vendor_id": invoice["vendor_id"]}))

    for inv in invoices:
        vendor = vendors[inv["vendor_id"]]
        sender = f"accounts@{domain(vendor['vendor_name'])}"
        number, amount = inv["invoice_number"], float(inv["total_amount"] or inv["amount"])
        if rng.random() < SUBMITTED:
            add(_when(inv["date"], rng), sender, f"Invoice {number} for {inv['po_id'] or 'your order'}",
                f"Dear team,\n\nPlease find our invoice {number} dated {inv['date']} for INR {amount:,.2f} "
                f"({inv['description']}).\nPayment terms: {inv['payment_terms']}.\n\nRegards,\n{vendor['vendor_name']}",
                "invoice_submission", inv)
        if inv["payment_status"] == "Unpaid" and rng.random() < REMINDED:
            add(_when(inv["due_date"] or inv["date"], rng, (3, 12)), sender, f"Reminder: invoice {number} is due",
                f"Hello,\n\nOur invoice {number} for INR {amount:,.2f} was due on {inv['due_date']}. "
                f"Could you share the payment date?\n\nThank you,\n{vendor['vendor_name']}", "payment_reminder", inv)
        grn = receipts.get(inv["grn_id"])
        if grn and grn["received_quantity"] and inv["quantity"] and int(float(grn["received_quantity"])) < int(float(inv["quantity"])):
            add(_when(inv["date"], rng, (2, 6)), sender, f"Query on quantity accepted against {number}",
                f"Hello,\n\nYour goods receipt {grn['grn_id']} records {grn['received_quantity']} units against the "
                f"{inv['quantity']} we invoiced on {number}. Please check with your warehouse.\n\n"
                f"Regards,\n{vendor['vendor_name']}", "quantity_query", inv)

    # Requests to change bank details, one per chosen vendor, about its latest unpaid invoice.
    latest_unpaid = {}
    for inv in invoices:
        if inv["payment_status"] == "Unpaid":
            latest_unpaid[inv["vendor_id"]] = inv
    for vendor_id, inv in sorted(latest_unpaid.items()):
        vendor, draw = vendors[vendor_id], rng.random()
        real = domain(vendor["vendor_name"])
        if draw < LOOKALIKES:
            add(_when(inv["date"], rng, (1, 4)), f"finance@{lookalike(real, rng)}",
                f"URGENT: new bank account for invoice {inv['invoice_number']}",
                f"Dear Sir/Madam,\n\nOur bank account is under audit and cannot receive funds. Please release "
                f"invoice {inv['invoice_number']} today to our new account: {_account(rng)}.\nDo not call our office; "
                f"reply to this e-mail only.\n\n{vendor['vendor_name']}", "bank_change", inv, suspicious=True)
        elif draw < LOOKALIKES + BANK_CHANGES:
            add(_when(inv["date"], rng, (1, 10)), f"accounts@{real}", "Change of bank details",
                f"Dear team,\n\nFrom next month we receive payments at {_account(rng)}. The signed letter on our "
                f"letterhead follows by post; please confirm with our registered contact before updating your "
                f"records. This applies to invoices after {inv['invoice_number']}.\n\nRegards,\n{vendor['vendor_name']}",
                "bank_change", inv)

    drafts.sort(key=lambda d: (d[0], d[1], d[2]))
    messages, labels = [], []
    for i, (sent, sender, subject, body, label) in enumerate(drafts):
        message = EmailMessage()
        message_id = f"<{hashlib.sha256(f'{seed}:{i}:{subject}'.encode()).hexdigest()[:20]}@{sender.split('@')[1]}>"
        message["Message-ID"], message["From"], message["To"] = message_id, sender, BUYER
        message["Date"], message["Subject"] = format_datetime(sent), subject
        message.set_content(body)
        messages.append(message)
        labels.append({"message_id": message_id, **label})
    return messages, labels


def write(messages: list[EmailMessage], labels: list[dict], out: Path) -> Path:
    """The mbox file and, beside it, `<name>.labels.csv`."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    box = mailbox.mbox(out)
    try:
        for message in messages:
            box.add(message)
        box.flush()
    finally:
        box.close()
    label_file = out.with_suffix(".labels.csv")
    with label_file.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["message_id", "category", "suspicious", "invoice_id", "vendor_id"])
        writer.writeheader()
        writer.writerows(labels)
    return label_file


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, required=True, help="a ledger folder, such as data/bench_seed_202")
    ap.add_argument("--out", type=Path, required=True, help="the mbox file to write")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    messages, labels = generate(args.dataset, args.seed)
    label_file = write(messages, labels, args.out)
    counts: dict[str, int] = {}
    for label in labels:
        key = label["category"] + (" (look-alike domain)" if label["suspicious"] else "")
        counts[key] = counts.get(key, 0) + 1
    print(f"{len(messages):,} e-mails in {args.out}; labels in {label_file}")
    for key, n in sorted(counts.items()):
        print(f"  {key:36s} {n:6,}")


if __name__ == "__main__":
    main()
