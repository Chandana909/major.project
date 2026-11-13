"""Vendor e-mails: read a MIME message, link it to the invoice it names, store it.

A message (RFC 5322 bytes, as it arrives on the Kafka topic `auditiq.email`) is
parsed with Python's email package. The invoice numbers it mentions are looked
up in the ledger; the e-mail is linked to that invoice and its vendor, so a
reviewer sees the vendor's correspondence beside the invoice. An e-mail can
arrive before the invoice it is about (they come through different topics): the
numbers it mentions are kept, and it is linked when the invoice arrives
(`link_waiting`, called by the invoice worker).
"""
from __future__ import annotations

import email
import re
from email import policy as email_policy
from email.utils import parseaddr, parsedate_to_datetime

from . import db

LINK_LOCK = 4_702_315_002       # PostgreSQL advisory lock: linking e-mails and invoices one transaction at a time

# Invoice numbers as vendors print them (INV-ROU-0146, BED00312, GOY/25-26/00432, cho-000367): letters and digits,
# both present, perhaps in parts joined by - or /. Dates and amounts have no letters, words no digits. A token is
# looked up as it is written.
NUMBER = re.compile(r"\b(?=[A-Z0-9/-]*\d)(?=[A-Z0-9/-]*[A-Z])[A-Z0-9]+(?:[-/][A-Z0-9]+)*\b", re.IGNORECASE)


def parse(raw: bytes) -> dict:
    """The fields of a message that are stored: sender, recipient, subject, date and plain-text body."""
    message = email.message_from_bytes(raw, policy=email_policy.default)
    sender = parseaddr(str(message.get("From", "")))[1].lower()
    part = message.get_body(preferencelist=("plain", "html"))
    body = part.get_content() if part is not None else ""
    try:
        sent_at = parsedate_to_datetime(str(message["Date"])).strftime("%Y-%m-%d %H:%M:%S") if message["Date"] else None
    except (TypeError, ValueError):
        sent_at = None
    return {"message_id": str(message.get("Message-ID", "")).strip(), "sender": sender,
            "sender_domain": sender.rpartition("@")[2], "recipient": parseaddr(str(message.get("To", "")))[1].lower(),
            "subject": str(message.get("Subject", "")), "sent_at": sent_at, "body": body.strip()}


def link(conn: db.Database, mail: dict) -> tuple[str | None, str | None]:
    """The invoice (and its vendor) that an e-mail names: a number in the subject first, then in the body. When
    several invoices carry the number (a duplicate), the latest one dated on or before the e-mail."""
    sent = (mail.get("sent_at") or "9999")[:10]
    for text in (mail["subject"], mail["body"]):
        numbers = sorted(set(NUMBER.findall(text)))
        if not numbers:
            continue
        rows = conn.execute(f"SELECT invoice_id, vendor_id, date FROM invoices WHERE invoice_number IN "
                            f"({', '.join('?' for _ in numbers)}) ORDER BY date, invoice_id", numbers).fetchall()
        if rows:
            before = [r for r in rows if str(r["date"])[:10] <= sent]
            row = before[-1] if before else rows[0]
            return row["invoice_id"], row["vendor_id"]
    return None, None


def lock_linking(conn: db.Database) -> None:
    """Hold, until the transaction ends, the lock under which e-mails and invoices are linked.

    An e-mail and the invoice it names can be written at the same time by two workers. Neither transaction sees
    the other's row before it commits, so without the lock each would look for the other, find nothing, and the
    e-mail would stay unlinked. With it, the later of the two sees the earlier one's row. (SQLite runs one write
    transaction at a time and needs no lock.)"""
    if conn.backend == "postgres":
        conn.execute("SELECT pg_advisory_xact_lock(?)", (LINK_LOCK,))


def store(conn: db.Database, raw: bytes) -> dict:
    """Parse, link and store one message (not committed). A message stored before is replaced. The result has the
    stored fields and `mentions`, the invoice-like numbers the message contains."""
    mail = parse(raw)
    if not mail["message_id"]:
        raise ValueError("the message has no Message-ID")
    mail["invoice_id"], mail["vendor_id"] = link(conn, mail)
    columns = [*mail, "received_at"]
    conn.execute(
        f"INSERT INTO emails ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)}) "
        "ON CONFLICT (message_id) DO UPDATE SET " + ", ".join(f"{c} = excluded.{c}" for c in columns[1:]),
        [*mail.values(), db.now()])
    mentions = sorted(set(NUMBER.findall(mail["subject"])) | set(NUMBER.findall(mail["body"])))
    conn.execute("DELETE FROM email_mentions WHERE message_id = ?", (mail["message_id"],))
    conn.executemany("INSERT INTO email_mentions (message_id, mention) VALUES (?, ?)",
                     [(mail["message_id"], m) for m in mentions])
    return {**mail, "mentions": mentions}


def link_waiting(conn: db.Database, numbers: list[str]) -> int:
    """Link the stored e-mails that mention one of these invoice numbers and have no invoice yet (not committed).
    Returns how many were linked."""
    numbers = sorted({n for n in numbers if n})
    if not numbers:
        return 0
    waiting = conn.execute(
        "SELECT DISTINCT e.message_id, e.subject, e.body, e.sent_at FROM email_mentions m "
        "JOIN emails e ON e.message_id = m.message_id "
        f"WHERE e.invoice_id IS NULL AND m.mention IN ({', '.join('?' for _ in numbers)})", numbers).fetchall()
    linked = 0
    for row in waiting:
        invoice_id, vendor_id = link(conn, dict(zip(row.keys(), tuple(row))))
        if invoice_id:
            conn.execute("UPDATE emails SET invoice_id = ?, vendor_id = ? WHERE message_id = ?",
                         (invoice_id, vendor_id, row["message_id"]))
            linked += 1
    return linked


def for_invoice(conn: db.Database, invoice_id: str) -> list[dict]:
    """The stored e-mails linked to an invoice, oldest first."""
    rows = conn.execute("SELECT message_id, sender, subject, sent_at, body FROM emails WHERE invoice_id = ? "
                        "ORDER BY sent_at, message_id", (invoice_id,)).fetchall()
    return [dict(zip(r.keys(), tuple(r))) for r in rows]
