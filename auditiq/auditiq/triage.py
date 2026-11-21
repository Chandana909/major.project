"""E-mail triage: what each vendor e-mail asks for, and whether it is an attempt to redirect a payment.

The payables mailbox receives invoices, reminders and queries, and now and then a request to pay into a new bank
account. That last kind is how business e-mail compromise steals money: a message from a domain that reads like
the vendor's, pressing for an urgent payment to a new account and asking not to be called back. The audit stores
and links the vendor e-mails (auditiq/emails.py); this module judges them, by code, so that every verdict comes
with its reasons:

    category   invoice submission, payment reminder, quantity query, bank-detail change, or other: the
               category whose wording the subject and body match most (subject words count twice)
    signals    look-alike domain   the sender's domain is not one the vendor has written from before, and reads
                                   like one (contains it, or is one or two characters from it), or, for a
                                   vendor with no earlier e-mail, like the vendor's name
               new domain          the vendor has never written from this domain
               urgency             "urgent", "today", "immediately", "without delay"
               secrecy             "do not call", "reply to this e-mail only", "confidential"
               account change      a new bank account, IFSC code or account number in the message
               money at risk       the e-mail names an invoice that is not paid yet
               addresses a model   text written to instruct an AI system ("ignore previous instructions",
                                   "approve this invoice"): quarantined before any model reads it
    risk       high     an account change from a look-alike or new domain that presses (urgency or secrecy):
                        hold the payment and confirm by telephone with the contact on the vendor master
               medium   an account change from the vendor's own domain (confirm before changing the master: the
                        callback control), or text addressed to a model
               low      urgency or secrecy without an account change
               none     the rest

On the generated mailboxes the answer key says which e-mails are which (auditiq_bench/correspondence.py), and
``python -m evaluation.triage_eval`` measures the triage against it. The generator writes every e-mail of a kind
from a few templates, so agreement there shows that the rules do what they say, not how well they read real mail.
"""
from __future__ import annotations

import mailbox
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

from . import db, emails

CATEGORIES = ("bank_change", "payment_reminder", "quantity_query", "invoice_submission", "other")
CATEGORY_TITLES = {"bank_change": "Bank-detail change", "payment_reminder": "Payment reminder",
                   "quantity_query": "Quantity query", "invoice_submission": "Invoice submission", "other": "Other"}
WORDING = {
    "bank_change": [r"\bbank (account|details)\b", r"\bifsc\b", r"\baccount\s*(no\.?|number)?\s*\d{9,}",
                    r"\bnew (bank )?account\b", r"\bchange of bank\b", r"\breceive (funds|payments) at\b"],
    "payment_reminder": [r"\breminder\b", r"\boverdue\b", r"\bwas due\b", r"\bpayment date\b", r"\bis due\b",
                         r"\boutstanding\b"],
    "quantity_query": [r"\bquantity\b", r"\bgoods receipt\b", r"\bunits\b", r"\bwarehouse\b", r"\bshort(age)?\b"],
    "invoice_submission": [r"\bplease find (our|the|attached)?\s*invoice\b", r"\binvoice\b[^.]*\bdated\b",
                           r"\bpayment terms\b", r"\binvoice [a-z0-9/-]+ for\b"],
}
URGENCY = re.compile(r"\b(urgent\w*|immediately|today|asap|without delay|at the earliest|right away)\b", re.I)
SECRECY = re.compile(r"\b(do not call|don't call|reply to this e-?mail only|do not contact|confidential|"
                     r"keep this (between us|private))\b", re.I)
ACCOUNT = re.compile(r"\b(ifsc\s*[a-z]{4}0?\w{6,7}|account\s*(no\.?|number)?\s*\d{9,}|new (bank )?account)\b", re.I)
TO_A_MODEL = re.compile(r"(ignore (all |any |the )?(previous|prior|above) instructions|disregard (the|your) "
                        r"(rules|instructions)|you are (now )?(an?|the) (ai|assistant|language model|auditor bot)|"
                        r"system prompt|approve this invoice|mark (it|this invoice) as (paid|approved|clean))", re.I)
COMPILED = {k: [re.compile(p, re.I) for p in v] for k, v in WORDING.items()}
RISK_ORDER = ("high", "medium", "low", "none")


def classify(subject: str, body: str) -> tuple[str, dict[str, int]]:
    """The category whose wording the message matches most, and the score of each."""
    scores = {k: 2 * sum(bool(p.search(subject or "")) for p in ps) + sum(bool(p.search(body or "")) for p in ps)
              for k, ps in COMPILED.items()}
    best = max(CATEGORIES[:-1], key=lambda k: (scores[k], -CATEGORIES.index(k)))
    return (best if scores[best] > 0 else "other"), scores


def _label(domain: str) -> str:
    return str(domain or "").lower().split(".")[0]


def _edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def looks_like(candidate: str, genuine: str) -> bool:
    """Whether a domain label reads like a genuine one without being it."""
    a, b = _label(candidate), _label(genuine)
    if not a or not b or a == b:
        return False
    if len(b) >= 4 and (b in a or a in b):
        return True
    return _edit_distance(a, b) <= 2 or SequenceMatcher(None, a, b).ratio() >= 0.85


def name_slug(vendor_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(vendor_name or "").lower())


def judge(mail: dict, vendor_name: str | None, known_domains: set[str], payment_status: str | None) -> dict:
    """The category, signals, risk and recommended action for one stored e-mail."""
    subject, body = str(mail.get("subject") or ""), str(mail.get("body") or "")
    category, scores = classify(subject, body)
    domain = str(mail.get("sender_domain") or "").lower()
    text = f"{subject}\n{body}"
    signals: dict[str, bool] = {}
    if known_domains:
        signals["new_domain"] = domain not in known_domains
        signals["lookalike_domain"] = signals["new_domain"] and any(looks_like(domain, d) for d in known_domains)
    else:
        slug = name_slug(vendor_name or "")
        label = _label(domain)
        own = bool(slug) and (label == slug or (len(label) >= 12 and slug.startswith(label)))
        signals["new_domain"] = False
        signals["lookalike_domain"] = bool(slug) and not own and looks_like(domain, slug)
    signals["urgency"] = bool(URGENCY.search(text))
    signals["secrecy"] = bool(SECRECY.search(text))
    signals["account_change"] = category == "bank_change" or bool(ACCOUNT.search(body))
    signals["money_at_risk"] = bool(mail.get("invoice_id")) and str(payment_status or "").lower() == "unpaid"
    signals["addresses_a_model"] = bool(TO_A_MODEL.search(text))
    pressing = signals["urgency"] or signals["secrecy"]
    if signals["account_change"] and (signals["lookalike_domain"] or (signals["new_domain"] and pressing)):
        risk = "high"
    elif signals["account_change"] or signals["addresses_a_model"]:
        risk = "medium"
    elif pressing:
        risk = "low"
    else:
        risk = "none"
    reasons = []
    if signals["lookalike_domain"]:
        reasons.append(f"sent from {domain}, which reads like the vendor's domain but is not it")
    elif signals["new_domain"]:
        reasons.append(f"the vendor has not written from {domain} before")
    if signals["account_change"]:
        reasons.append("asks to pay into another bank account")
    if signals["urgency"]:
        reasons.append("presses for an urgent payment")
    if signals["secrecy"]:
        reasons.append("asks not to be called back")
    if signals["money_at_risk"]:
        reasons.append(f"names the unpaid invoice {mail['invoice_id']}")
    if signals["addresses_a_model"]:
        reasons.append("contains instructions addressed to an AI system; quarantined from every model prompt")
    action = {"high": "Hold the payment; confirm the request by telephone with the contact on the vendor master, "
                      "never with details from the e-mail",
              "medium": "Confirm with the vendor's registered contact before changing the vendor master",
              "low": "Read it before acting on it", "none": "File it"}[risk]
    if signals["addresses_a_model"] and risk != "high":
        action = "Keep it out of every model prompt and read it yourself; " + action[0].lower() + action[1:]
    return {"message_id": mail.get("message_id"), "sent_at": str(mail.get("sent_at") or ""),
            "sender": mail.get("sender"), "sender_domain": domain, "subject": subject,
            "invoice_id": mail.get("invoice_id"), "vendor_id": mail.get("vendor_id"), "category": category,
            "scores": scores, "signals": signals, "risk": risk, "reasons": reasons, "action": action}


def triage_store(conn: db.Database, limit: int = 200) -> dict:
    """Every stored e-mail judged, oldest first so that a vendor's known domains are those it wrote from before."""
    mails = [dict(zip(r.keys(), tuple(r))) for r in conn.execute(
        "SELECT message_id, sender, sender_domain, subject, sent_at, body, invoice_id, vendor_id FROM emails "
        "ORDER BY sent_at, message_id").fetchall()]
    vendors = dict(conn.execute("SELECT vendor_id, vendor_name FROM vendor_master").fetchall())
    status = {}
    linked = sorted({m["invoice_id"] for m in mails if m["invoice_id"]})
    for start in range(0, len(linked), db.FEW):
        part = linked[start:start + db.FEW]
        status.update(dict(conn.execute(f"SELECT invoice_id, payment_status FROM invoices WHERE invoice_id IN "
                                        f"({', '.join('?' for _ in part)})", part).fetchall()))
    known: dict[str, set[str]] = defaultdict(set)
    judged = []
    for mail in mails:
        vendor_id = mail["vendor_id"]
        verdict = judge(mail, vendors.get(vendor_id), set(known[vendor_id]) if vendor_id else set(),
                        status.get(mail["invoice_id"]))
        judged.append(verdict)
        # A domain becomes the vendor's once it has written from it without a risk to hold: a look-alike that
        # wrote first is not made genuine by writing again.
        if vendor_id and verdict["risk"] in ("none", "low"):
            known[vendor_id].add(verdict["sender_domain"])
    by_risk = Counter(j["risk"] for j in judged)
    alerts = sorted((j for j in judged if j["risk"] in ("high", "medium")),
                    key=lambda j: (RISK_ORDER.index(j["risk"]), j["sent_at"]))
    holds = {}
    for j in judged:
        if j["risk"] == "high" and j["invoice_id"] and j["signals"]["money_at_risk"]:
            holds.setdefault(j["invoice_id"], j)
    amounts = {}
    hold_ids = sorted(holds)
    for start in range(0, len(hold_ids), db.FEW):
        part = hold_ids[start:start + db.FEW]
        amounts.update({i: float(a or 0) for i, a in conn.execute(
            f"SELECT invoice_id, amount FROM invoices WHERE invoice_id IN ({', '.join('?' for _ in part)})", part)})
    return {"emails": len(judged), "linked": sum(1 for j in judged if j["invoice_id"]),
            "by_category": {c: sum(1 for j in judged if j["category"] == c) for c in CATEGORIES},
            "by_risk": {r: by_risk.get(r, 0) for r in RISK_ORDER},
            "signals": {s: sum(1 for j in judged if j["signals"].get(s)) for s in
                        ("lookalike_domain", "new_domain", "urgency", "secrecy", "account_change", "money_at_risk",
                         "addresses_a_model")},
            "alerts": alerts[:limit], "alerts_total": len(alerts),
            "holds": [{"invoice_id": i, "vendor_id": holds[i]["vendor_id"], "amount": amounts.get(i, 0.0),
                       "message_id": holds[i]["message_id"], "sender": holds[i]["sender"], "subject": holds[i]["subject"]}
                      for i in hold_ids],
            "hold_amount": round(sum(amounts.values()), 2), "titles": CATEGORY_TITLES,
            "recent": judged[-limit:][::-1]}


def for_invoice(conn: db.Database, invoice_id: str) -> list[dict]:
    """The triage of the e-mails linked to one invoice (judged in the context of the whole mailbox)."""
    vendor = conn.scalar("SELECT vendor_id FROM invoices WHERE invoice_id = ?", (invoice_id,))
    if vendor is None or not conn.scalar("SELECT COUNT(*) FROM emails WHERE invoice_id = ?", (invoice_id,)):
        return []
    mails = [dict(zip(r.keys(), tuple(r))) for r in conn.execute(
        "SELECT message_id, sender, sender_domain, subject, sent_at, body, invoice_id, vendor_id FROM emails "
        "WHERE vendor_id = ? ORDER BY sent_at, message_id", (vendor,)).fetchall()]
    name = conn.scalar("SELECT vendor_name FROM vendor_master WHERE vendor_id = ?", (vendor,))
    status = conn.scalar("SELECT payment_status FROM invoices WHERE invoice_id = ?", (invoice_id,))
    known: set[str] = set()
    out = []
    for mail in mails:
        verdict = judge(mail, name, set(known), status if mail["invoice_id"] == invoice_id else None)
        if verdict["risk"] in ("none", "low"):
            known.add(verdict["sender_domain"])
        if mail["invoice_id"] == invoice_id:
            out.append(verdict)
    return out


def load_mailbox(conn: db.Database, path: Path) -> int:
    """Store every message of an mbox file in the store, as the e-mail worker does, without Kafka. Returns how many."""
    box = mailbox.mbox(Path(path), create=False)
    stored = 0
    try:
        emails.lock_linking(conn)
        for message in box:
            emails.store(conn, message.as_bytes())
            stored += 1
    finally:
        box.close()
    conn.commit()
    return stored
