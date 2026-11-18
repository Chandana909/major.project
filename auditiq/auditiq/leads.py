"""Leads for the reviewer from the two judgement rules that the policy words most precisely.

The controls decide the rule-defined clauses; the judgement clauses are left to the agents (C2 to C5), and a
controls-only audit (C1) approves every invoice that breaks only those. Two of them are worded closely enough that
the invoices which fit their wording can be listed for a reviewer by code, from the ledger alone, with the
policy's own guide values:

    near duplicates (2.2.2)   an invoice that bills the same PO and GRN for the same amount as an earlier invoice of
                              the same vendor, under a re-keyed form of the earlier number: changed case, separators
                              or leading zeros, an added suffix, one transposed or substituted character. Consecutive
                              numbers for separate POs and deliveries are not duplicates, and none is listed: the PO
                              and the GRN must be the same
    structuring (4.1.2)       invoices of one vendor approved by one role, on different days within the guide
                              window, each within the guide band below that role's limit, together above it. The
                              rule also asks for the same goods, which may be described differently ("Endpoint
                              security licences, annual", "Antivirus endpoint subscriptions (1 year)"): that is the
                              reviewer's judgement, so the descriptions are listed with the group, not compared

A lead is not a finding. It does not change a result, a score or a route: it is a list a reviewer works through,
with the reasons each invoice is on it. Whether the wording fits is still the reviewer's judgement, which is why the
policy calls these rules judgement and the paper leaves them to the agents.

On a benchmark ledger the leads are compared with its answer key, including the hard negatives built to resemble
these anomalies (consecutive numbers with equal amounts, identical recurring amounts, an amount just inside a limit,
invoices at the daily count). The generator plants J1 and J2 in the pattern the policy describes, so agreement with
the answer key shows that the code follows the policy's wording, not how often real duplicates look like this.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date

from . import analytics, db

SUFFIX = re.compile(r"(?<=[0-9])[A-Z]{1,4}$")       # an added suffix after the last digit: A, R, DUP, COPY
DIGITS = re.compile(r"[0-9]+")
SEPARATORS = re.compile(r"[^A-Z0-9]+")
SHOW = 300                                          # leads listed in full; the counts cover all


def normalise_number(value, zeros: bool = True) -> str:
    """An invoice number without case, separators and an added suffix, and (``zeros``) without the leading zeros of
    each group of digits, taken group by group before the separators go ("25-26/00445" is "25", "26", "445")."""
    groups = SEPARATORS.split(str(value or "").upper())
    if zeros:
        groups = [DIGITS.sub(lambda m: m.group(0).lstrip("0") or "0", g) for g in groups]
    return SUFFIX.sub("", "".join(groups))


def one_edit(a: str, b: str) -> bool:
    """Whether b is a with one character substituted, inserted, removed, or two neighbours transposed."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
        return len(diff) == 1 or (len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]]
                                  and a[diff[1]] == b[diff[0]])
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    i = next((k for k, (x, y) in enumerate(zip(short, long_)) if x != y), len(short))
    return short[i:] == long_[i + 1:]


def rekeyed(earlier: str, later: str) -> str | None:
    """How the later number re-keys the earlier one, or None if it does not (the same number is 2.2.1's)."""
    if str(earlier).strip() == str(later).strip():
        return None
    if normalise_number(earlier) == normalise_number(later):
        return "re-keyed: case, separators, leading zeros or a suffix"
    # One character substituted or transposed, compared with and without the leading zeros: a letter O keyed for a
    # zero inside "000185" is one substitution only while the zeros are kept.
    if any(one_edit(normalise_number(earlier, zeros), normalise_number(later, zeros)) for zeros in (True, False)):
        return "re-keyed: one character substituted, added, removed or transposed"
    return None


def _ledger(conn: db.Database) -> tuple[list[dict], dict[str, tuple]]:
    invoices = [dict(zip(r.keys(), r)) for r in conn.execute(
        "SELECT i.invoice_id, i.vendor_id, v.vendor_name, i.invoice_number, CAST(i.date AS TEXT) AS date, i.amount, "
        "i.po_id, i.grn_id, i.description FROM invoices i LEFT JOIN vendor_master v ON v.vendor_id = i.vendor_id "
        "ORDER BY i.date, i.invoice_id").fetchall()]
    approver: dict[str, tuple] = {}
    for transaction, role, name in conn.execute(
            "SELECT transaction_id, approver_role, approver_name FROM approval_logs WHERE action_taken = 'Approved' "
            "ORDER BY timestamp, log_id"):
        approver[transaction] = (role, name)                  # the last approval wins, as in the controls
    return invoices, approver


def near_duplicates(invoices: list[dict]) -> list[dict]:
    """Pairs of the same vendor, PO, GRN and amount where the later number re-keys the earlier one."""
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for inv in invoices:                                      # oldest first
        if inv["po_id"] and inv["grn_id"]:
            buckets[(inv["vendor_id"], inv["po_id"], inv["grn_id"], round(float(inv["amount"] or 0) * 100))].append(inv)
    pairs = []
    for group in buckets.values():
        for k, later in enumerate(group):
            for earlier in group[:k]:
                if str(earlier["invoice_number"]).strip() == str(later["invoice_number"]).strip():
                    continue                                  # the same number: an exact duplicate, a finding of 2.2.1
                # The same receipt billed again for the same amount is listed even under an unrelated number: the
                # reviewer decides whether the number is a re-keyed form, as the rule asks.
                how = rekeyed(earlier["invoice_number"], later["invoice_number"]) or \
                    "the same PO, GRN and amount; the number is not a re-keyed form of the earlier one"
                if how:
                    pairs.append({"invoice_id": later["invoice_id"], "original_id": earlier["invoice_id"],
                                  "vendor_id": later["vendor_id"], "vendor_name": later["vendor_name"],
                                  "number": later["invoice_number"], "original_number": earlier["invoice_number"],
                                  "date": later["date"], "original_date": earlier["date"],
                                  "amount": float(later["amount"] or 0), "po_id": later["po_id"],
                                  "grn_id": later["grn_id"], "reason": how})
                    break                                     # one original is enough to list the later invoice
    return pairs


def structuring(invoices: list[dict], approver: dict[str, tuple], limits: dict[str, float], window_days: int,
                band_pct: float) -> list[dict]:
    """Groups of one vendor and approving role, on different days within the window, each within the band below the
    role's limit, together above it. Whether they are for the same goods is the reviewer's judgement: the rule's
    wording allows the same goods to be described differently, so the descriptions are shown, not compared."""
    near: dict[tuple, list[dict]] = defaultdict(list)
    for inv in invoices:
        role = (approver.get(inv["invoice_id"]) or (None, None))[0]
        limit = limits.get(role or "")
        amount = float(inv["amount"] or 0)
        if limit and limit * (1 - band_pct / 100) <= amount <= limit and inv["date"]:
            near[(inv["vendor_id"], role)].append({**inv, "role": role, "limit": limit,
                                                   "day": date.fromisoformat(inv["date"][:10])})
    groups, seen = [], set()
    for (_vendor, role), items in near.items():
        items.sort(key=lambda x: (x["day"], x["invoice_id"]))
        for i, first in enumerate(items):
            window = [x for x in items[i:] if (x["day"] - first["day"]).days <= window_days]
            total = sum(float(x["amount"] or 0) for x in window)
            if len(window) < 2 or len({x["day"] for x in window}) < 2 or total <= first["limit"]:
                continue
            members = tuple(x["invoice_id"] for x in window)
            if set(members) <= seen:                          # inside a group already listed
                continue
            seen.update(members)
            descriptions = [str(x["description"] or "") for x in window]
            groups.append({"vendor_id": first["vendor_id"], "vendor_name": first["vendor_name"], "role": role,
                           "limit": first["limit"], "invoices": list(members), "first": str(window[0]["day"]),
                           "last": str(window[-1]["day"]), "total": round(total, 2),
                           "amounts": [float(x["amount"] or 0) for x in window], "descriptions": descriptions,
                           "same_description": len({" ".join(d.lower().split()) for d in descriptions}) == 1})
    groups.sort(key=lambda g: -g["total"])
    return groups


def judgement_leads(conn: db.Database) -> dict:
    """Both lists, with what the latest results did with their invoices and, on a benchmark ledger, the answer key."""
    version = analytics.governing_version(conn)
    clauses = {r[0]: r for r in conn.execute(
        "SELECT clause_id, title, kind FROM policy_clauses WHERE version = ?", (version,))}
    params = {(c, p): v for c, p, v in conn.execute(
        "SELECT clause_id, param_name, param_value FROM policy_parameters WHERE version = ?", (version,))}
    _, limits = analytics.approval_limits(conn, version)
    window = int(float(params.get(("4.1.2", "guide_window_days"), 7)))
    band = float(params.get(("4.1.2", "guide_band_pct"), 15))
    invoices, approver = _ledger(conn)
    pairs = near_duplicates(invoices) if "2.2.2" in clauses else []
    groups = structuring(invoices, approver, limits, window, band) if "4.1.2" in clauses else []

    latest = {r[0]: (r[1], int(r[2] or 0), r[3]) for r in conn.execute(
        "SELECT invoice_id, route, flag_count, configuration FROM v_latest_results")}
    amount_of = {inv["invoice_id"]: float(inv["amount"] or 0) for inv in invoices}

    def outcome(ids: list[str]) -> dict:
        routes = Counter((latest.get(i) or ("unaudited",))[0] for i in ids)
        return {"invoices": len(ids), "amount": round(sum(amount_of.get(i, 0.0) for i in ids), 2),
                "approved": routes.get("approve", 0), "to_a_person": routes.get("escalate", 0) + routes.get("sample", 0),
                "unaudited": routes.get("unaudited", 0)}

    dup_ids = sorted({p["invoice_id"] for p in pairs})
    split_ids = sorted({i for g in groups for i in g["invoices"]})         # overlapping windows share invoices
    out = {"policy_version": version, "guide": {"window_days": window, "band_pct": band, "limits": limits},
           "near_duplicates": {"clause": "2.2.2", "pairs": pairs[:SHOW], "count": len(pairs), **outcome(dup_ids)},
           "structuring": {"clause": "4.1.2", "groups": groups[:SHOW], "count": len(groups), **outcome(split_ids)},
           "answer_key": _answer_key(conn, version, {"2.2.2": dup_ids, "4.1.2": split_ids})}
    for key, ids in (("near_duplicates", dup_ids), ("structuring", split_ids)):
        decided = {i: latest[i] for i in ids if i in latest}
        out[key]["configurations"] = dict(Counter(c for _, _, c in decided.values()))
    return out


def _answer_key(conn: db.Database, version: str | None, listed: dict[str, list[str]]) -> dict | None:
    """Per rule: the labelled invoices of its class, how many are listed, and what else is listed (other anomalies,
    hard negatives by type, clean invoices). Only for labels written for the version the leads were made under."""
    if not conn.scalar("SELECT COUNT(*) FROM benchmark_labels"):
        return None
    key_policy = conn.scalar("SELECT value FROM meta WHERE key = 'labels_policy'") or analytics.BENCHMARK_POLICY
    if key_policy != version:
        return {"policy_version": key_policy, "compared": False}
    labels = {r[0]: (r[1], r[2] or "", r[3] or "") for r in conn.execute(
        "SELECT invoice_id, label, clause_ids, hard_negative_type FROM benchmark_labels")}
    out: dict = {"policy_version": key_policy, "compared": True}
    for clause, ids in listed.items():
        labelled = {i for i, (label, clauses, _) in labels.items() if label == "anomalous"
                    and clause in analytics._clauses(clauses)}
        ids_set = set(ids)
        other = Counter()
        for i in ids_set - labelled:
            label, _, hn = labels.get(i, ("unlabelled", "", ""))
            other[hn if label == "hard_negative" else label] += 1
        found = len(labelled & ids_set)
        out[clause] = {"labelled": len(labelled), "listed": len(ids_set), "listed_labelled": found,
                       "recall": round(found / len(labelled), 4) if labelled else None,
                       "precision": round(found / len(ids_set), 4) if ids_set else None,
                       "listed_otherwise": dict(sorted(other.items()))}
    return out
