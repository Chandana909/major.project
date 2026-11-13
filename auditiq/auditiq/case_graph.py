"""The audited ledger as a knowledge graph, and retrieval over it for Ask AI.

The policy graph (policy_graph.py) holds what the rules say. This graph holds what the audit found: which vendor
billed which invoice, which rule the invoice breaks and why, who approved it, which vendors share an identity, and
which rings the approvers and vendors form. It is built by code from the store (the audit results, the findings with
their messages, the approval log, the vendor master and the ring detector); no model reads or writes it, so it can
be wrong only where the audit is.

    nodes   vendor            name, category, blacklisted, invoices, invoices with findings, money with findings
            invoice           an invoice with at least one finding: amount, date, score, level, route
            rule              a clause of the policy in force, with the invoices that break it
            approver          name, role, limit, approvals, approvals with findings, approvals above the limit
            ring              a connected group of vendors and approvers (rings.py)
    edges   vendor   -billed->        invoice
            invoice  -violates->      rule            (with the message of the finding)
            invoice  -approved by->   approver
            vendor   -shares PAN->    vendor          (also shares GSTIN)
            vendor / approver -member of-> ring

``CaseGraph.query(question)`` recognises what a question names (invoice numbers, vendor ids and names, approvers,
rule numbers, kinds of fraud in everyday words) and follows the edges from there. It returns facts, each a statement
computed from the graph with the numbers it rests on, and the nodes to light up. The facts go to the model in Ask AI
beside the policy facts and the policy passages, which is what lets a question about the ledger ("which vendors
are in a collusion ring and who approves their invoices?") be answered from the ledger and not from the policy
text alone. Invoices without a finding are not nodes: they are in the totals of their vendor and approver.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from . import db
from . import rings as ring_module
from .policy_graph import CLAUSE_ID, Fact, rupees

INVOICE_ID = re.compile(r"\bINV\d{3,}\b", re.IGNORECASE)
VENDOR_ID = re.compile(r"\bVEND\d{3,}\b", re.IGNORECASE)
RING_NUMBER = re.compile(r"\bring\s*#?\s*(\d+)\b", re.IGNORECASE)

# What a question says in everyday words, and the rules it points to.
RULE_WORDS: list[tuple[re.Pattern, list[str]]] = [
    (re.compile(r"\b(mismatch\w*|differ\w*|discrepanc\w*|three.way|numbers?)\b", re.I), ["2.1.1", "2.1.2", "3.1.3"]),
    (re.compile(r"\b(overbill\w*|over-bill\w*|price|amount match|billed more than)\b", re.I), ["2.1.1"]),
    (re.compile(r"\b(quantit\w*|short receipt|received|grn|goods receipt)\b", re.I), ["2.1.2"]),
    (re.compile(r"\b(missing (po|grn|reference)|no po|no grn|reference)\b", re.I), ["2.1.3"]),
    (re.compile(r"\b(duplicate\w*|double pay\w*|paid twice|billed twice)\b", re.I), ["2.2.1", "2.2.2"]),
    (re.compile(r"\b(gstin|gst|tax (id|number|identity))\b", re.I), ["3.1.1", "3.1.2", "3.1.3"]),
    (re.compile(r"\b(split\w*|same.day)\b", re.I), ["4.1.1"]),
    (re.compile(r"\bstructur\w*\b", re.I), ["4.1.2"]),
    (re.compile(r"\b(weekend\w*|saturday|sunday|non.business)\b", re.I), ["4.2.1"]),
    (re.compile(r"\bround(ed)?[ -]?(amount|sum|figure)s?\b", re.I), ["4.3.1"]),
    (re.compile(r"\b(blacklist\w*|blocked|suspended|fraudulent vendors?|banned)\b", re.I), ["4.4.1"]),
    (re.compile(r"\b(above (their|its|his|her|own|the) .{0,20}limit|approval limit|authority|delegation|over.limit|"
                r"beyond .{0,12}limit)\b", re.I), ["5.1.1"]),
]
RING_WORDS = re.compile(r"\b(collu\w*|rings?|cartel|conspir\w*|connected|related vendors?|network)\b", re.IGNORECASE)
IDENTITY_WORDS = re.compile(r"\b(pan|shell|registered twice|same (gstin|registration)|shared (gstin|registration)|"
                            r"share[sd]? (a |the )?(same )?(pan|gstin|identity|registration)|twice)\b", re.IGNORECASE)
BLOCKED_WORDS = re.compile(r"\b(blacklist\w*|blocked|suspended|fraudulent vendors?|banned)\b", re.I)
APPROVER_WORDS = re.compile(r"\b(approver\w*|who approv\w*|approved by|signed off)\b", re.I)
FRAUD_WORDS = re.compile(r"\b(fraud\w*|anomal\w*|finding\w*|flag\w*|risk\w*|suspicious|exception\w*|irregular\w*|"
                         r"summary|overview)\b", re.I)
MAX_FACTS = 14


def money(value: float) -> str:
    return rupees(value)


def plural(n: int, word: str) -> str:
    return f"{n:,} {word}" + ("" if n == 1 else "s")


@dataclass
class CaseAnswer:
    question: str
    facts: list[Fact] = field(default_factory=list)
    nodes: list[str] = field(default_factory=list)
    recognised: dict = field(default_factory=dict)

    def facts_text(self) -> str:
        """The facts as the lines of a prompt: [C1] ..., [C2] ..."""
        return "\n".join(f"[C{i}] {f.text}" for i, f in enumerate(self.facts, start=1))


class CaseGraph:
    """The findings of the latest audit as a graph. Build it with ``from_db``; the constructor takes plain data."""

    def __init__(self, version: str, rules: dict[str, dict], vendors: dict[str, dict], totals: dict[str, dict],
                 invoices: dict[str, dict], approvers: dict[str, dict], ring_list: list[dict],
                 links: list[dict] | None = None) -> None:
        self.version = version
        self.rules, self.vendors, self.totals, self.invoices = rules, vendors, totals, invoices
        self.approvers, self.rings = approvers, ring_list
        self.by_name = {v["name"].lower(): vid for vid, v in vendors.items()}
        self.approver_by_lower = {name.lower(): name for name in approvers}
        # What the flagged invoices say, by rule, vendor and approver.
        self.rule_invoices: dict[str, list[str]] = defaultdict(list)
        self.vendor_invoices: dict[str, list[str]] = defaultdict(list)
        self.approver_invoices: dict[str, list[str]] = defaultdict(list)
        for invoice_id, inv in invoices.items():
            self.vendor_invoices[inv["vendor"]].append(invoice_id)
            if inv.get("approver"):
                self.approver_invoices[inv["approver"]].append(invoice_id)
            for flag in inv["flags"]:
                self.rule_invoices[flag["clause"]].append(invoice_id)
        self.over_limit = {name: sum(any(f["clause"] == "5.1.1" for f in invoices[i]["flags"]) for i in ids)
                           for name, ids in self.approver_invoices.items()}
        self.ring_of_vendor: dict[str, list[int]] = defaultdict(list)
        self.ring_of_approver: dict[str, list[int]] = defaultdict(list)
        for ring in ring_list:
            for vendor_id in ring["vendors"]:
                self.ring_of_vendor[vendor_id].append(ring["id"])
            for name in ring["approvers"]:
                self.ring_of_approver[name].append(ring["id"])
        # The tested links of the ring detector: an approver and a vendor joined by approvals that carry more findings
        # than the approver's role allows, at a false discovery rate of 1% (rings.py). The detector also joins an
        # approver to every vendor of its flagged invoices (the hotspot link), which widens a ring; the core of a ring
        # is the vendors with a tested link to its approvers, or all of its vendors when it has no approver (an identity).
        tested = {"repeated findings", "above own limit", "concentrated approvals"}
        self.tested: dict[str, list[str]] = defaultdict(list)
        for edge in sorted(links or [], key=lambda e: -e.get("invoices", 0)):
            if tested & set(edge.get("kinds", [])):
                a, b = edge["source"], edge["target"]
                vendor_node, approver_node = (a, b) if a.startswith("v:") else (b, a)
                if approver_node.startswith("a:") and vendor_node[2:] not in self.tested[approver_node[2:]]:
                    self.tested[approver_node[2:]].append(vendor_node[2:])
        self.core: dict[int, list[str]] = {}
        for ring in ring_list:
            core = [v for v in ring["vendors"] if not ring["approvers"] or any(v in self.tested.get(a, []) for a in ring["approvers"])]
            self.core[ring["id"]] = core or list(ring["vendors"])
        self.shared: dict[str, list[tuple[str, str]]] = defaultdict(list)       # vendor -> [(other vendor, "PAN"/"GSTIN")]
        for field_name, label in (("pan", "PAN"), ("gstin", "GSTIN")):
            holders: dict[str, list[str]] = defaultdict(list)
            for vendor_id, v in vendors.items():
                if v.get(field_name):
                    holders[v[field_name]].append(vendor_id)
            for group in holders.values():
                for a in group:
                    self.shared[a] += [(b, label) for b in group if b != a]

    # ------------------------------------------------------------------ build
    @classmethod
    def from_db(cls, conn: db.Database, ring_data: dict | None = None) -> "CaseGraph":
        version = conn.scalar("SELECT version FROM company_policies WHERE is_active = 1 LIMIT 1") or ""
        rules = {c: {"title": t, "severity": s} for c, t, s in conn.execute(
            "SELECT clause_id, title, severity FROM policy_clauses WHERE version = ?", (version,)).fetchall()}
        has_status = "gstin_status" in conn.columns("vendor_master")
        vendors = {}
        for row in conn.execute("SELECT vendor_id, vendor_name, vendor_category, pan_number, official_gstin, blacklisted"
                                + (", gstin_status" if has_status else "") + " FROM vendor_master").fetchall():
            vendors[row[0]] = {"name": row[1], "category": row[2], "pan": (row[3] or "").strip().upper(),
                               "gstin": (row[4] or "").strip().upper(), "blacklisted": bool(row[5]),
                               "status": row[6] if has_status else ""}
        totals = {r[0]: {"invoices": int(r[1]), "amount": float(r[2]), "flagged": int(r[3]), "flagged_amount": float(r[4])}
                  for r in conn.execute(
                      "SELECT l.vendor_id, COUNT(*), COALESCE(SUM(i.amount), 0), "
                      "SUM(CASE WHEN l.flag_count > 0 THEN 1 ELSE 0 END), "
                      "COALESCE(SUM(CASE WHEN l.flag_count > 0 THEN i.amount ELSE 0 END), 0) "
                      "FROM v_latest_results l JOIN invoices i ON i.invoice_id = l.invoice_id GROUP BY l.vendor_id").fetchall()}
        invoices = {}
        for row in conn.execute(
                "SELECT l.invoice_id, l.vendor_id, l.route, l.risk_level, l.rc, i.amount, CAST(i.date AS TEXT) "
                "FROM v_latest_results l JOIN invoices i ON i.invoice_id = l.invoice_id WHERE l.flag_count > 0").fetchall():
            invoices[row[0]] = {"vendor": row[1], "route": row[2], "level": row[3], "score": float(row[4] or 0),
                                "amount": float(row[5] or 0), "date": row[6], "approver": None, "role": None,
                                "limit": None, "flags": []}
        for invoice_id, clause, severity, message in conn.execute(
                "SELECT l.invoice_id, f.clause, f.severity, f.message FROM v_latest_results l "
                "JOIN audit_flags f ON f.result_id = l.result_id "
                "WHERE l.flag_count > 0 AND COALESCE(f.removal_reason, '') = '' ORDER BY l.invoice_id, f.flag_id").fetchall():
            if invoice_id in invoices:
                invoices[invoice_id]["flags"].append({"clause": clause, "severity": severity, "message": message or ""})
        latest: dict[str, tuple] = {}
        for tid, name, role, limit, stamp, log_id in conn.execute(
                "SELECT a.transaction_id, a.approver_name, a.approver_role, a.amount_limit, CAST(a.timestamp AS TEXT), "
                "a.log_id FROM approval_logs a JOIN v_latest_results l ON l.invoice_id = a.transaction_id "
                "WHERE l.flag_count > 0 AND a.action_taken = 'Approved'").fetchall():
            if tid not in latest or (stamp, log_id) > latest[tid][:2]:
                latest[tid] = (stamp, log_id, name, role, limit)
        for tid, (_, _, name, role, limit) in latest.items():
            if tid in invoices:
                invoices[tid].update(approver=name, role=role, limit=float(limit) if limit is not None else None)
        approvers = {r[0]: {"role": r[1], "limit": float(r[2]) if r[2] is not None else None, "approvals": int(r[3])}
                     for r in conn.execute("SELECT approver_name, MAX(approver_role), MAX(amount_limit), COUNT(*) "
                                           "FROM approval_logs WHERE action_taken = 'Approved' GROUP BY approver_name").fetchall()}
        found = ring_data if ring_data is not None else ring_module.find_rings(conn, limit=200)
        return cls(version, rules, vendors, totals, invoices, approvers, found["rings"], found.get("edges"))

    # ------------------------------------------------------------- the graph
    def counts(self) -> dict:
        return {"vendors": len(self.vendors), "invoices_with_findings": len(self.invoices),
                "rules": len(self.rules), "approvers": len(self.approvers), "rings": len(self.rings),
                "findings": sum(len(i["flags"]) for i in self.invoices.values())}

    def public(self, focus: str | None = None, limit: int = 250) -> dict:
        """Nodes and edges for a view: the rings of the ledger, or the neighbourhood of one node (a vendor, an invoice,
        an approver, a ring or a rule; by id, name or node id such as ``v:VEND1001``)."""
        nodes: dict[str, dict] = {}
        edges: dict[tuple, dict] = {}

        def vendor(vid: str) -> str:
            nid, v, t = f"v:{vid}", self.vendors.get(vid, {}), self.totals.get(vid, {})
            nodes.setdefault(nid, {"id": nid, "kind": "vendor", "label": v.get("name", vid), "category": v.get("category"),
                                   "blacklisted": v.get("blacklisted", False), "invoices": t.get("invoices", 0),
                                   "flagged": t.get("flagged", 0), "amount": t.get("flagged_amount", 0.0),
                                   "risk": max((self.invoices[i]["score"] for i in self.vendor_invoices.get(vid, [])), default=0.0)})
            return nid

        def approver(name: str) -> str:
            nid, a = f"a:{name}", self.approvers.get(name, {})
            nodes.setdefault(nid, {"id": nid, "kind": "approver", "label": name, "role": a.get("role"),
                                   "limit": a.get("limit"), "approvals": a.get("approvals", 0),
                                   "flagged": len(self.approver_invoices.get(name, [])),
                                   "over_limit": self.over_limit.get(name, 0),
                                   "risk": max((self.invoices[i]["score"] for i in self.approver_invoices.get(name, [])), default=0.0)})
            return nid

        def rule(clause: str) -> str:
            nid, r = f"r:{clause}", self.rules.get(clause, {})
            nodes.setdefault(nid, {"id": nid, "kind": "rule", "label": f"{clause} {r.get('title', '')}".strip(),
                                   "severity": r.get("severity"), "invoices": len(self.rule_invoices.get(clause, []))})
            return nid

        def invoice(iid: str) -> str:
            nid, inv = f"i:{iid}", self.invoices[iid]
            nodes.setdefault(nid, {"id": nid, "kind": "invoice", "label": iid, "amount": inv["amount"], "date": inv["date"],
                                   "risk": inv["score"], "level": inv["level"], "route": inv["route"]})
            return nid

        def ring(rid: int) -> str:
            r = next(x for x in self.rings if x["id"] == rid)
            nid = f"g:{rid}"
            nodes.setdefault(nid, {"id": nid, "kind": "ring", "label": f"Ring {rid}", "vendors": len(r["vendors"]),
                                   "approvers": len(r["approvers"]), "amount": r["flagged_amount"],
                                   "link_kinds": r["link_kinds"]})
            return nid

        def link(a: str, b: str, kind: str, **attrs) -> None:
            edges.setdefault((a, b, kind), {"source": a, "target": b, "kind": kind, **attrs})

        def with_invoice(iid: str, budget: int = 25) -> None:
            inv = self.invoices[iid]
            i = invoice(iid)
            link(vendor(inv["vendor"]), i, "billed")
            for flag in inv["flags"]:
                link(i, rule(flag["clause"]), "violates", severity=flag["severity"])
            if inv["approver"]:
                link(i, approver(inv["approver"]), "approved by")

        def around_ring(r: dict) -> None:
            rid = ring(r["id"])
            for vid in r["vendors"]:
                link(vendor(vid), rid, "member of")
                for other, label in self.shared.get(vid, []):
                    if other in r["vendors"] and vid < other:
                        link(vendor(vid), vendor(other), f"shares {label}")
                counts = Counter(f["clause"] for i in self.vendor_invoices.get(vid, []) for f in self.invoices[i]["flags"])
                for clause, n in counts.most_common(3):
                    link(vendor(vid), rule(clause), "breaks", count=n)
            for name in r["approvers"]:
                link(approver(name), rid, "member of")

        key = (focus or "").strip()
        target = self.resolve(key) if key else None
        if target is None:
            for r in sorted(self.rings, key=lambda x: -x["flagged_amount"])[:12]:
                around_ring(r)
        else:
            kind, ident = target
            if kind == "vendor":
                v = vendor(ident)
                ranked = sorted(self.vendor_invoices.get(ident, []), key=lambda i: -self.invoices[i]["score"])
                for iid in ranked[:25]:
                    with_invoice(iid)
                for other, label in self.shared.get(ident, []):
                    link(v, vendor(other), f"shares {label}")
                for rid in self.ring_of_vendor.get(ident, []):
                    link(v, ring(rid), "member of")
            elif kind == "approver":
                a = approver(ident)
                ranked = sorted(self.approver_invoices.get(ident, []), key=lambda i: -self.invoices[i]["score"])
                for iid in ranked[:25]:
                    with_invoice(iid)
                for rid in self.ring_of_approver.get(ident, []):
                    link(a, ring(rid), "member of")
            elif kind == "invoice":
                with_invoice(ident)
                inv = self.invoices[ident]
                for rid in self.ring_of_vendor.get(inv["vendor"], []):
                    link(vendor(inv["vendor"]), ring(rid), "member of")
            elif kind == "ring":
                around_ring(next(x for x in self.rings if x["id"] == int(ident)))
            else:
                r = rule(ident)
                by_vendor = Counter(self.invoices[i]["vendor"] for i in self.rule_invoices.get(ident, []))
                by_approver = Counter(self.invoices[i]["approver"] for i in self.rule_invoices.get(ident, [])
                                      if self.invoices[i]["approver"])
                for vid, n in by_vendor.most_common(10):
                    link(vendor(vid), r, "breaks", count=n)
                for name, n in by_approver.most_common(8):
                    link(approver(name), r, "approved breaches of", count=n)
        keep = list(nodes)[:limit]
        kept = set(keep)
        return {"focus": key or None, "focus_kind": target[0] if target else None, "nodes": [nodes[n] for n in keep],
                "edges": [e for e in edges.values() if e["source"] in kept and e["target"] in kept],
                "counts": self.counts(), "policy_version": self.version,
                "truncated": len(nodes) > limit}

    def resolve(self, key: str) -> tuple[str, str] | None:
        """(kind, id) of what ``key`` names: a node id, an invoice, a vendor id or name, an approver, a ring, a rule."""
        prefix, _, rest = key.partition(":")
        if rest and prefix in ("v", "i", "a", "g", "r"):
            key = rest
            if prefix == "g":
                return ("ring", key) if any(str(r["id"]) == key for r in self.rings) else None
            if prefix == "r":
                return ("rule", key) if key in self.rules else None
        if key.upper() in self.invoices:
            return "invoice", key.upper()
        if key.upper() in self.vendors:
            return "vendor", key.upper()
        if key.lower() in self.by_name:
            return "vendor", self.by_name[key.lower()]
        if key in self.approvers:
            return "approver", key
        if key.lower() in self.approver_by_lower:
            return "approver", self.approver_by_lower[key.lower()]
        if key in self.rules:
            return "rule", key
        if key.isdigit() and any(str(r["id"]) == key for r in self.rings):
            return "ring", key
        return None

    # ---------------------------------------------------------------- facts
    def vendor_name(self, vendor_id: str) -> str:
        return self.vendors.get(vendor_id, {}).get("name", vendor_id)

    def _rule_counts(self, invoice_ids: list[str]) -> str:
        counts = Counter(f["clause"] for i in invoice_ids for f in self.invoices[i]["flags"])
        return ", ".join(f"{c} {self.rules.get(c, {}).get('title', '').lower()} ×{n}".replace("  ", " ")
                         for c, n in counts.most_common(6))

    def fact_invoice(self, invoice_id: str) -> Fact:
        inv = self.invoices.get(invoice_id)
        if inv is None:
            return Fact(f"No findings are held for {invoice_id}: it was audited without a finding, or it is not in the "
                        "ledger.", "invoice", self.version, data={"invoices": [invoice_id], "findings": 0})
        rings_of = sorted(set(self.ring_of_vendor.get(inv["vendor"], []) + self.ring_of_approver.get(inv["approver"], [])))
        approver = (f"; approved by {inv['approver']} ({inv['role']}, limit {money(inv['limit'])})" if inv["approver"]
                    and inv["limit"] is not None else "")
        findings = "; ".join(f"{f['clause']} {self.rules.get(f['clause'], {}).get('title', '')} ({f['severity']}): {f['message']}".strip()
                             for f in inv["flags"])
        text = (f"{invoice_id} of {self.vendor_name(inv['vendor'])} ({inv['vendor']}), {money(inv['amount'])}, dated "
                f"{inv['date']}, scored {inv['score']:.0f} ({inv['level']}) and went to {inv['route']}{approver}. "
                f"Findings: {findings}." + (f" Its vendor or approver belongs to ring {', '.join(map(str, rings_of))}." if rings_of else ""))
        return Fact(text, "invoice", self.version, data={
            "invoices": [invoice_id], "vendors": [inv["vendor"]], "approvers": [inv["approver"]] if inv["approver"] else [],
            "rules": [f["clause"] for f in inv["flags"]], "rings": rings_of, "score": inv["score"]})

    def fact_vendor(self, vendor_id: str) -> Fact:
        v, t = self.vendors[vendor_id], self.totals.get(vendor_id, {"invoices": 0, "amount": 0.0, "flagged": 0, "flagged_amount": 0.0})
        ids = self.vendor_invoices.get(vendor_id, [])
        by_approver = Counter(self.invoices[i]["approver"] for i in ids if self.invoices[i]["approver"])
        parts = [f"Vendor {v['name']} ({vendor_id}, {v['category']}) has {plural(t['invoices'], 'invoice')} worth "
                 f"{money(t['amount'])}; {t['flagged']:,} carry findings, worth {money(t['flagged_amount'])}."]
        if ids:
            parts.append("Rules broken: " + self._rule_counts(ids) + ".")
        if v["blacklisted"] or (v["status"] and v["status"] != "Active"):
            parts.append(f"The vendor is blacklisted or its GST registration is {v['status'] or 'blocked'}.")
        if self.shared.get(vendor_id):
            parts.append("It shares an identity with " + ", ".join(
                f"{self.vendor_name(o)} ({o}, same {label})" for o, label in self.shared[vendor_id]) + ".")
        if by_approver:
            parts.append("Its invoices with findings were approved by " + ", ".join(
                f"{a} ({n})" for a, n in by_approver.most_common(3)) + ".")
        rings_of = self.ring_of_vendor.get(vendor_id, [])
        if rings_of:
            parts.append("It is a member of ring " + ", ".join(map(str, rings_of)) + ".")
        return Fact(" ".join(parts), "vendor", self.version, data={
            "vendors": [vendor_id] + [o for o, _ in self.shared.get(vendor_id, [])],
            "approvers": [a for a, _ in by_approver.most_common(3)], "rings": rings_of,
            "flagged": t["flagged"], "flagged_amount": t["flagged_amount"]})

    def fact_approver(self, name: str) -> Fact:
        a = self.approvers[name]
        ids = self.approver_invoices.get(name, [])
        amount = sum(self.invoices[i]["amount"] for i in ids)
        by_vendor = Counter(self.invoices[i]["vendor"] for i in ids)
        tested = self.tested.get(name, [])
        parts = [f"Approver {name} ({a['role']}, limit {money(a['limit']) if a['limit'] is not None else 'not stated'}) approved "
                 f"{a['approvals']:,} invoices; {len(ids):,} carry findings, worth {money(amount)}, of which "
                 f"{self.over_limit.get(name, 0):,} are above the approver's own limit (rule 5.1.1)."]
        if tested:
            parts.append("Vendors with a tested ring link to this approver (approvals that carry more findings than the "
                         "role's rate allows, false discovery rate 1%): " + ", ".join(
                             f"{self.vendor_name(v)} ({v}, {by_vendor.get(v, 0)} invoices with findings)" for v in tested) + ".")
        elif by_vendor:
            parts.append("Most of them are invoices of " + ", ".join(
                f"{self.vendor_name(v)} ({n})" for v, n in by_vendor.most_common(4)) + ".")
        rings_of = self.ring_of_approver.get(name, [])
        if rings_of:
            parts.append("The approver is a member of ring " + ", ".join(map(str, rings_of)) + ".")
        return Fact(" ".join(parts), "approver", self.version, data={
            "approvers": [name], "vendors": tested or [v for v, _ in by_vendor.most_common(4)], "rings": rings_of,
            "flagged": len(ids), "over_limit": self.over_limit.get(name, 0)})

    def fact_ring(self, ring: dict) -> Fact:
        roles = ring["approver_roles"] or [None] * len(ring["approvers"])
        core = self.core.get(ring["id"], list(ring["vendors"]))
        others = len(ring["vendors"]) - len(core)
        by_approver = {a: [v for v in self.tested.get(a, []) if v in ring["vendors"]] for a in ring["approvers"]}
        if ring["approvers"]:
            members = " ".join(f"Approver {a} ({r}) has tested ring links with the vendors "
                               + ", ".join(f"{self.vendor_name(v)} ({v})" for v in by_approver[a]) + "."
                               for a, r in zip(ring["approvers"], roles))
        else:
            members = "vendors " + ", ".join(f"{self.vendor_name(v)} ({v})" for v in core)
        text = (f"Ring {ring['id']}" + (" (approver ring)" if ring["approvers"] else " (shared identity, no approver)") + ": " + members
                + (f" {others} more vendors are in the ring through the approver's hotspot link only." if others else "")
                + ". Links: " + ", ".join(f"{k} ×{n}" for k, n in ring["link_kinds"].items())
                + f". {plural(ring['flagged_invoices'], 'invoice')} with findings worth {money(ring['flagged_amount'])}"
                + (", rules " + ", ".join(f"{c} ×{n}" for c, n in sorted(ring["rules"].items(), key=lambda kv: -kv[1])[:4]) if ring["rules"] else "")
                + ". A ring is a lead for investigation, not a finding.")
        return Fact(text, "ring", self.version, data={
            "rings": [ring["id"]], "vendors": list(core), "approvers": list(ring["approvers"]), "by_approver": by_approver,
            "flagged": ring["flagged_invoices"], "flagged_amount": ring["flagged_amount"]})

    def fact_rule(self, clause: str) -> Fact:
        ids = self.rule_invoices.get(clause, [])
        r = self.rules.get(clause, {"title": "", "severity": ""})
        amount = sum(self.invoices[i]["amount"] for i in ids)
        by_vendor = Counter(self.invoices[i]["vendor"] for i in ids)
        by_approver = Counter(self.invoices[i]["approver"] for i in ids if self.invoices[i]["approver"])
        text = (f"Rule {clause} ({r['title'].lower()}, {r['severity']}) is broken by {plural(len(ids), 'invoice')}, worth "
                f"{money(amount)}, among {len(by_vendor):,} vendors.")
        if by_vendor:
            text += " Most often: " + ", ".join(f"{self.vendor_name(v)} ({n})" for v, n in by_vendor.most_common(4)) + "."
        if by_approver and clause == "5.1.1":
            text += " Approved above their own limit most often by " + ", ".join(f"{a} ({n})" for a, n in by_approver.most_common(5)) + "."
        return Fact(text, "rule", self.version, clause=clause, data={
            "rules": [clause], "vendors": [v for v, _ in by_vendor.most_common(4)],
            "approvers": [a for a, _ in by_approver.most_common(5)], "flagged": len(ids)})

    def fact_blocked(self) -> Fact:
        blocked = [vid for vid, v in self.vendors.items() if v["blacklisted"] or (v["status"] and v["status"] != "Active")]
        billed = sum(self.totals.get(v, {}).get("invoices", 0) for v in blocked)
        money_billed = sum(self.totals.get(v, {}).get("amount", 0.0) for v in blocked)
        top = sorted(blocked, key=lambda v: -self.totals.get(v, {}).get("amount", 0.0))[:5]
        text = (f"{len(blocked):,} vendors are blacklisted or have a suspended GST registration; they billed {billed:,} "
                f"invoices worth {money(money_billed)}, and {len(self.rule_invoices.get('4.4.1', [])):,} of those invoices "
                "carry a finding under rule 4.4.1. Largest: " + ", ".join(
                    f"{self.vendor_name(v)} ({v}, {money(self.totals.get(v, {}).get('amount', 0.0))})" for v in top) + ".")
        return Fact(text, "vendors", self.version, clause="4.4.1", data={"vendors": top, "blocked": len(blocked), "invoices": billed})

    def fact_rings(self) -> Fact:
        kinds = Counter(k for r in self.rings for k in r["link_kinds"])
        text = (f"The audit found {len(self.rings):,} rings, groups of vendors and approvers tied by shared identities or by "
                "approvals that carry more findings than chance allows. Links: " + ", ".join(f"{k} ×{n}" for k, n in kinds.most_common()) + ".")
        return Fact(text, "rings", self.version, data={"rings": [r["id"] for r in self.rings]})

    def fact_identity(self) -> Fact:
        pairs: dict[str, set[tuple[str, str]]] = {"PAN": set(), "GSTIN": set()}
        for vendor_id, others in self.shared.items():
            for other, label in others:
                pairs[label].add((min(vendor_id, other), max(vendor_id, other)))
        parts, members = [], []
        for label, found in pairs.items():
            shown = sorted(found)[:8]
            parts.append(f"{len(found):,} pairs of vendor records share a {label}: " + "; ".join(
                f"{self.vendor_name(a)} ({a}) and {self.vendor_name(b)} ({b}), "
                f"{self.totals.get(a, {}).get('flagged', 0) + self.totals.get(b, {}).get('flagged', 0)} invoices with findings"
                for a, b in shown) + ("" if len(found) <= 8 else f"; {len(found) - 8} more") + ".")
            members += [v for pair in shown for v in pair]
        return Fact(" ".join(parts) + " One legal entity registered twice is a way to split spend and to hide a vendor's history.",
                    "identity", self.version, data={"vendors": list(dict.fromkeys(members)),
                                                     "pairs": {k: len(v) for k, v in pairs.items()}})

    def fact_over_limit(self) -> Fact:
        top = sorted(self.over_limit.items(), key=lambda kv: -kv[1])[:6]
        text = ("Approvers with the most approvals above their own limit (rule 5.1.1): " + ", ".join(
            f"{n} ({self.approvers[n]['role']}, {c})" for n, c in top if c) + ".")
        return Fact(text, "approvers", self.version, clause="5.1.1", data={"approvers": [n for n, c in top if c]})

    def fact_overview(self) -> Fact:
        flagged = sum(t["flagged"] for t in self.totals.values())
        total = sum(t["invoices"] for t in self.totals.values())
        amount = sum(t["flagged_amount"] for t in self.totals.values())
        by_rule = sorted(self.rule_invoices.items(), key=lambda kv: -len(kv[1]))[:5]
        text = (f"The audit raised findings on {flagged:,} of {total:,} invoices ({(flagged / total if total else 0):.1%}), "
                f"worth {money(amount)}. Most frequent rules: " + ", ".join(
                    f"{c} {self.rules.get(c, {}).get('title', '').lower()} ({len(ids):,})" for c, ids in by_rule)
                + f". {len(self.rings):,} rings were found.")
        return Fact(text, "overview", self.version, data={"flagged": flagged, "invoices": total})

    # ---------------------------------------------------------------- query
    def recognise(self, question: str) -> dict:
        q = question.lower()
        invoices = list(dict.fromkeys(m.upper() for m in INVOICE_ID.findall(question)))
        vendors = [m.upper() for m in VENDOR_ID.findall(question) if m.upper() in self.vendors]
        for name in sorted(self.by_name, key=len, reverse=True):
            if len(name) >= 4 and name in q and self.by_name[name] not in vendors:
                vendors.append(self.by_name[name])
        approvers = [orig for low, orig in sorted(self.approver_by_lower.items(), key=lambda kv: -len(kv[0]))
                     if low in q]
        rules = [c for c in dict.fromkeys(CLAUSE_ID.findall(question)) if c in self.rules]
        topics = {}
        for pattern, clauses in RULE_WORDS:
            if pattern.search(question):
                for c in clauses:
                    if c in self.rules and c not in rules:
                        topics[c] = True
        return {"invoices": invoices, "vendors": vendors, "approvers": approvers, "rules": rules,
                "rule_words": list(topics), "rings": [int(n) for n in RING_NUMBER.findall(question)
                                                       if any(r["id"] == int(n) for r in self.rings)],
                "ring_words": bool(RING_WORDS.search(question)), "identity_words": bool(IDENTITY_WORDS.search(question)),
                "blocked_words": bool(BLOCKED_WORDS.search(question)),
                "approver_words": bool(APPROVER_WORDS.search(question)), "fraud_words": bool(FRAUD_WORDS.search(question))}

    def query(self, question: str) -> CaseAnswer:
        rec = self.recognise(question)
        out = CaseAnswer(question, recognised={k: v for k, v in rec.items() if v})
        seen: set[tuple] = set()

        def add(fact: Fact, *nodes: str) -> None:
            key = (fact.kind, fact.text)
            if key in seen or len(out.facts) >= MAX_FACTS:
                return
            seen.add(key)
            out.facts.append(fact)
            out.nodes.extend(n for n in nodes if n not in out.nodes)

        for iid in rec["invoices"][:3]:
            fact = self.fact_invoice(iid)
            add(fact, f"i:{iid}", *(f"v:{v}" for v in fact.data.get("vendors", [])))
        for vid in rec["vendors"][:3]:
            add(self.fact_vendor(vid), f"v:{vid}")
        for name in rec["approvers"][:3]:
            add(self.fact_approver(name), f"a:{name}")
        for rid in rec["rings"][:2]:
            add(self.fact_ring(next(r for r in self.rings if r["id"] == rid)), f"g:{rid}")
        for clause in rec["rules"][:3]:
            add(self.fact_rule(clause), f"r:{clause}")
        named = bool(rec["invoices"] or rec["vendors"] or rec["approvers"] or rec["rings"] or rec["rules"])
        if rec["identity_words"] and not rec["invoices"]:
            fact = self.fact_identity()
            add(fact, *(f"v:{v}" for v in fact.data["vendors"]))
        if rec["ring_words"] and not rec["invoices"]:
            add(self.fact_rings(), *(f"g:{r['id']}" for r in self.rings))
            for r in sorted(self.rings, key=lambda x: -x["flagged_amount"])[:6]:
                add(self.fact_ring(r), f"g:{r['id']}", *(f"v:{v}" for v in r["vendors"]), *(f"a:{n}" for n in r["approvers"]))
        if rec["blocked_words"] and not rec["invoices"]:
            add(self.fact_blocked(), "r:4.4.1")
        if rec["approver_words"] and not rec["approvers"] and (rec["rule_words"] or "5.1.1" in rec["rules"] or not named):
            add(self.fact_over_limit(), "r:5.1.1")
        if not rec["rules"]:
            for clause in rec["rule_words"][:3]:
                add(self.fact_rule(clause), f"r:{clause}")
        if not out.facts and rec["fraud_words"]:
            add(self.fact_overview())
        return out
