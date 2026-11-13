"""Vendor collusion rings: vendors and approvers tied together by shared identities and unusual approvals.

The links an auditor follows when looking for collusion between vendors, or between a vendor and the people
who approve its invoices. Each link is one of:

    shared PAN               two vendor records with the same PAN: one legal entity registered twice
    shared GSTIN             two vendor records with the same GST registration
    another vendor's GSTIN   an invoice of one vendor that carries the registration of another
    repeated findings        the approver approved more of the vendor's invoices with high or critical findings
                             than approvers of the same role do: a one-sided binomial test against the role's rate
    above own limit          the same, where among those findings are approvals above the approver's own limit
    approver hotspot         the approver's approvals as a whole carry more high or critical findings than the
                             role's rate allows; links the approver to every vendor of those invoices
    concentrated approvals   one approver approved at least 40 % of the vendor's invoices (at least 10 of them)

An approval link must survive the Benjamini-Hochberg procedure at a false discovery rate of 1 % over all the
tests of its kind: every approver-vendor pair with at least two invoices, and every approver. Comparing an
approver with others of the same role matters: a policy that gives one role a lower limit makes that role's
approvals break the rules more often, which says nothing about collusion.

A ring is a connected group of links with at least two vendors: vendors bound by an identity, or by approvers
they share. A group around a single vendor is listed apart, as a pair. Rings are ranked by the money on the
invoices with findings on their links. A ring is a lead for an investigation, not a finding.

When nothing passes, the watch list still ranks the approver-vendor pairs by how unusual they are, with their
p-values and false-discovery-rate q-values, and groups them the same way: where to look first, marked as
below significance.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

from . import db
from .analytics import active_version, approval_limits

FDR = 0.01                   # false discovery rate of the approval tests (Benjamini-Hochberg)
REPEATED = 2                 # findings a pair needs before it is tested
CONCENTRATION_SHARE = 0.40
CONCENTRATION_MIN = 10
WATCH = 40                   # pairs on the watch list
MAX_NODES = 1500             # members drawn at most, so that the page stays light on a large ledger
LINKS = ("shared PAN", "shared GSTIN", "another vendor's GSTIN", "repeated findings", "above own limit",
         "approver hotspot", "concentrated approvals")


def binomial_tail(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p): how likely k or more findings among n invoices are by chance."""
    if k <= 0:
        return 1.0
    if k > n or p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    return max(0.0, 1.0 - sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k)))


def benjamini_hochberg(pvalues: list[float]) -> list[float]:
    """The q-value of each test: the smallest false discovery rate at which the procedure would reject it."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    q = [1.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, pvalues[i] * m / rank)
        q[i] = running
    return q


class _Components:
    """Union-find over node ids."""

    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        self.parent[self.find(a)] = self.find(b)


def vendor_node(vendor_id: str) -> str:
    return f"v:{vendor_id}"


def approver_node(name: str) -> str:
    return f"a:{name}"


def _new_edge() -> dict:
    return {"kinds": Counter(), "invoices": {}, "rules": Counter()}


def _attach(edge: dict, pair: dict) -> None:
    edge["invoices"].update(pair["invoices"])
    edge["rules"].update(pair["rules"])


def find_rings(conn: db.Database, limit: int = 40) -> dict:
    """The rings of the ledger (the strongest `limit` drawn with their members and links), the pairs, the watch
    list, and the tests behind them."""
    limit_clause, limits = approval_limits(conn, active_version(conn))
    vendors = {}
    for vendor_id, name, category, pan, gstin, blacklisted in conn.execute(
            "SELECT vendor_id, vendor_name, vendor_category, pan_number, official_gstin, blacklisted FROM vendor_master"):
        vendors[vendor_id] = {"name": name, "category": category, "pan": (pan or "").strip().upper(),
                              "gstin": (gstin or "").strip().upper(), "blacklisted": bool(blacklisted)}
    roles = dict(conn.execute("SELECT approver_name, MAX(approver_role) FROM approval_logs GROUP BY approver_name"))
    edges: dict[tuple[str, str], dict] = {}

    def link(a: str, b: str, kind: str) -> dict:
        edge = edges.setdefault((a, b) if a < b else (b, a), _new_edge())
        edge["kinds"][kind] += 1
        return edge

    # Identities: one PAN or one registration on two vendor records, and invoices that carry another's GSTIN.
    for field, kind in (("pan", "shared PAN"), ("gstin", "shared GSTIN")):
        holders = defaultdict(list)
        for vendor_id, v in vendors.items():
            if v[field]:
                holders[v[field]].append(vendor_id)
        for ids in holders.values():
            for other in ids[1:]:
                link(vendor_node(ids[0]), vendor_node(other), kind)
    owner = {v["gstin"]: vendor_id for vendor_id, v in vendors.items() if v["gstin"]}
    mismatched = 0
    for invoice_id, vendor_id, gstin, amount in conn.execute(
            "SELECT i.invoice_id, i.vendor_id, i.gstin, i.amount FROM invoices i JOIN vendor_master v "
            "ON v.vendor_id = i.vendor_id WHERE i.gstin IS NOT NULL AND i.gstin <> '' AND i.gstin <> v.official_gstin"):
        mismatched += 1
        other = owner.get((gstin or "").strip().upper())
        if other and other != vendor_id:
            link(vendor_node(vendor_id), vendor_node(other), "another vendor's GSTIN")["invoices"][invoice_id] = float(amount or 0)

    # Invoices per approver and vendor, and the invoices and spend of each vendor, in one scan of the ledger;
    # then the invoices with high or critical findings.
    per_vendor: dict[str, Counter] = defaultdict(Counter)
    totals: dict[str, list] = defaultdict(lambda: [0, 0.0])
    for vendor_id, approver, n, amount in conn.execute(
            "SELECT vendor_id, approved_by, COUNT(*), SUM(amount) FROM invoices GROUP BY vendor_id, approved_by"):
        totals[vendor_id][0] += int(n)
        totals[vendor_id][1] += float(amount or 0)
        if approver:
            per_vendor[vendor_id][approver] = int(n)
    flagged: dict[tuple[str, str], dict] = defaultdict(lambda: {"invoices": {}, "rules": Counter(), "over": 0})
    for invoice_id, vendor_id, approver, amount, clause in conn.execute(
            "SELECT i.invoice_id, i.vendor_id, i.approved_by, i.amount, f.clause FROM audit_flags f "
            "JOIN v_latest_results l ON l.result_id = f.result_id JOIN invoices i ON i.invoice_id = l.invoice_id "
            "WHERE f.status = 'kept' AND f.severity IN ('high', 'critical') "
            "AND i.approved_by IS NOT NULL AND i.approved_by <> ''"):
        pair = flagged[(approver, vendor_id)]
        pair["invoices"][invoice_id] = float(amount or 0)
        pair["rules"][clause] += 1
        pair["over"] += clause == limit_clause

    # The rate of each role: the share of its approvals with high or critical findings.
    approver_n: Counter[str] = Counter()
    approver_k: Counter[str] = Counter()
    for counts in per_vendor.values():
        for approver, n in counts.items():
            approver_n[approver] += n
    for (approver, _), pair in flagged.items():
        approver_k[approver] += len(pair["invoices"])
    role_n: Counter = Counter()
    role_k: Counter = Counter()
    for approver, n in approver_n.items():
        role_n[roles.get(approver)] += n
        role_k[roles.get(approver)] += approver_k[approver]
    rate = {role: role_k[role] / n for role, n in role_n.items() if n}

    # Pairs: every approver-vendor pair with at least two invoices is a test.
    tested = [(approver, vendor_id, n) for vendor_id, counts in per_vendor.items()
              for approver, n in counts.items() if n >= REPEATED]
    found = [len(flagged[(a, v)]["invoices"]) if (a, v) in flagged else 0 for a, v, _ in tested]
    p_pairs = [binomial_tail(k, n, rate.get(roles.get(a), 0.0)) if k >= REPEATED else 1.0
               for (a, _, n), k in zip(tested, found)]
    q_pairs = benjamini_hochberg(p_pairs)
    for (approver, vendor_id, _), k, q in zip(tested, found, q_pairs):
        if k >= REPEATED and q <= FDR:
            pair = flagged[(approver, vendor_id)]
            edge = link(approver_node(approver), vendor_node(vendor_id), "repeated findings")
            if pair["over"]:
                edge["kinds"]["above own limit"] += 1
            _attach(edge, pair)

    # Approvers: one test each, against the rate of their role.
    approvers = sorted(approver_n)
    p_approvers = [binomial_tail(approver_k[a], approver_n[a], rate.get(roles.get(a), 0.0)) for a in approvers]
    q_approvers = benjamini_hochberg(p_approvers)
    hotspots = {a for a, q in zip(approvers, q_approvers) if q <= FDR}
    for (approver, vendor_id), pair in flagged.items():
        if approver in hotspots:
            _attach(link(approver_node(approver), vendor_node(vendor_id), "approver hotspot"), pair)

    # Concentration: one approver for a large share of a vendor's invoices.
    concentration = {}
    for vendor_id, counts in per_vendor.items():
        total = sum(counts.values())
        approver, n = counts.most_common(1)[0]
        concentration[vendor_id] = n / total
        if total >= CONCENTRATION_MIN and n / total >= CONCENTRATION_SHARE:
            _attach(link(approver_node(approver), vendor_node(vendor_id), "concentrated approvals"),
                    flagged.get((approver, vendor_id), {"invoices": {}, "rules": Counter()}))

    # The watch list: the most unusual pairs, significant or not, and their links for the drawing.
    ranked = sorted((i for i, k in enumerate(found) if k >= REPEATED), key=lambda i: (p_pairs[i], -found[i]))[:WATCH]
    watch, watch_edges = [], {}
    for i in ranked:
        approver, vendor_id, n = tested[i]
        pair = flagged[(approver, vendor_id)]
        role = roles.get(approver)
        watch.append({"approver": approver, "role": role, "vendor_id": vendor_id,
                      "vendor_name": vendors.get(vendor_id, {}).get("name"), "flagged": found[i], "invoices": n,
                      "expected": n * rate.get(role, 0.0), "p": p_pairs[i], "q": q_pairs[i],
                      "significant": q_pairs[i] <= FDR, "amount": sum(pair["invoices"].values()),
                      "rules": dict(pair["rules"])})
        edge = watch_edges.setdefault((approver_node(approver), vendor_node(vendor_id)), _new_edge())
        edge["kinds"]["unusual approvals"] += 1
        _attach(edge, pair)

    stats = _vendor_stats(conn, totals)
    names = {vendor_id: v["name"] for vendor_id, v in vendors.items()}
    rings, pairs, nodes, links = _groups(edges, limit, vendors, roles, limits, stats, concentration)
    leads, _, lead_nodes, lead_links = _groups(watch_edges, WATCH, vendors, roles, limits, stats, concentration,
                                               singles_are_groups=True)
    return {
        "rings": [{**r, "vendor_names": [names.get(v, v) for v in r["vendors"]],
                   "approver_roles": [roles.get(a) for a in r["approvers"]]} for r in rings["shown"]],
        "total_rings": rings["total"],
        "pairs": [{"vendor_id": p["vendors"][0], "vendor_name": names.get(p["vendors"][0]),
                   "approvers": p["approvers"], "roles": [roles.get(a) for a in p["approvers"]],
                   "link_kinds": p["link_kinds"], "rules": p["rules"], "flagged_invoices": p["flagged_invoices"],
                   "flagged_amount": p["flagged_amount"], "max_risk": p["max_risk"]} for p in pairs[:limit]],
        "total_pairs": len(pairs),
        "nodes": nodes,
        "edges": links,
        "watch": watch,
        "leads": {"groups": [{**g, "vendor_names": [names.get(v, v) for v in g["vendors"]],
                              "approver_roles": [roles.get(a) for a in g["approvers"]]} for g in leads["shown"]],
                  "nodes": lead_nodes, "edges": lead_links},
        "identity": {
            "vendors": len(vendors),
            "shared_pan": sum(1 for e in edges.values() if e["kinds"]["shared PAN"]),
            "shared_gstin": sum(1 for e in edges.values() if e["kinds"]["shared GSTIN"]),
            "another_vendors_gstin": sum(len(e["invoices"]) for e in edges.values() if e["kinds"]["another vendor's GSTIN"]),
            "gstin_mismatches": mismatched,
            "approvers": len(roles),
        },
        "tests": {
            "fdr": FDR, "repeated": REPEATED,
            "pairs_tested": len(tested), "pairs_with_findings": sum(1 for k in found if k >= REPEATED),
            "pairs_significant": sum(1 for k, q in zip(found, q_pairs) if k >= REPEATED and q <= FDR),
            "approvers_tested": len(approvers), "hotspots": len(hotspots),
            "min_q_pair": min((q for k, q in zip(found, q_pairs) if k >= REPEATED), default=None),
            "min_q_approver": min(q_approvers, default=None),
            "role_rates": [{"role": role, "invoices": role_n[role], "flagged": role_k[role], "rate": r}
                           for role, r in sorted(rate.items(), key=lambda kv: str(kv[0]))],
        },
        "method": {"concentration_share": CONCENTRATION_SHARE, "concentration_min": CONCENTRATION_MIN,
                   "repeated": REPEATED, "fdr": FDR, "limit_clause": limit_clause, "links": list(LINKS)},
    }


def _groups(edges: dict, limit: int, vendors: dict, roles: dict, limits: dict, stats: dict, concentration: dict,
            singles_are_groups: bool = False) -> tuple[dict, list, list, list]:
    """Connected groups of the links: those with two vendors or more (all of them with `singles_are_groups`),
    the groups around one vendor, and the members and links of the groups drawn."""
    components = _Components()
    for a, b in edges:
        components.union(a, b)
    members: dict[str, set] = defaultdict(set)
    grouped: dict[str, list] = defaultdict(list)
    for (a, b), e in edges.items():
        root = components.find(a)
        members[root].update((a, b))
        grouped[root].append(((a, b), e))
    groups, singles = [], []
    for root, nodes in members.items():
        group_edges = grouped[root]
        invoices: dict[str, float] = {}
        for _, e in group_edges:
            invoices.update(e["invoices"])
        vendor_ids = sorted(n[2:] for n in nodes if n.startswith("v:"))
        entry = {"vendors": vendor_ids, "approvers": sorted(n[2:] for n in nodes if n.startswith("a:")),
                 "links": len(group_edges), "link_kinds": dict(sum((e["kinds"] for _, e in group_edges), Counter())),
                 "rules": dict(sum((e["rules"] for _, e in group_edges), Counter())),
                 "flagged_invoices": len(invoices), "flagged_amount": sum(invoices.values()),
                 "amount": sum(stats.get(v, {}).get("amount", 0.0) for v in vendor_ids),
                 "blacklisted": sum(vendors.get(v, {}).get("blacklisted", False) for v in vendor_ids),
                 "waiting": sum(stats.get(v, {}).get("waiting", 0) for v in vendor_ids),
                 "max_risk": max((stats.get(v, {}).get("max_risk", 0.0) for v in vendor_ids), default=0.0),
                 "edges": group_edges}
        (groups if singles_are_groups or len(vendor_ids) >= 2 else singles).append(entry)
    groups.sort(key=_rank)
    singles.sort(key=_rank)
    shown, drawn = [], 0
    for group in groups[:limit]:                     # the strongest groups, as many as the drawing can hold
        size = len(group["vendors"]) + len(group["approvers"])
        if shown and drawn + size > MAX_NODES:
            break
        shown.append(group)
        drawn += size
    nodes_out, edges_out = [], []
    for index, group in enumerate(shown, start=1):
        group["id"] = index
        for vendor_id in group["vendors"]:
            v, s = vendors.get(vendor_id, {}), stats.get(vendor_id, {})
            nodes_out.append({"id": vendor_node(vendor_id), "kind": "vendor", "ring": index, "label": v.get("name"),
                              "vendor_id": vendor_id, "category": v.get("category"),
                              "blacklisted": v.get("blacklisted", False), "invoices": s.get("invoices", 0),
                              "amount": s.get("amount", 0.0), "flagged": s.get("flagged", 0),
                              "max_risk": s.get("max_risk", 0.0), "top_approver_share": concentration.get(vendor_id)})
        for name in group["approvers"]:
            nodes_out.append({"id": approver_node(name), "kind": "approver", "ring": index, "label": name,
                              "role": roles.get(name), "limit": limits.get(roles.get(name) or "")})
        for (a, b), e in group.pop("edges"):
            edges_out.append({"source": a, "target": b, "ring": index, "kinds": sorted(e["kinds"]),
                              "invoices": len(e["invoices"]), "amount": sum(e["invoices"].values()),
                              "rules": dict(e["rules"])})
    for group in groups[len(shown):] + singles:
        group.pop("edges", None)
    return {"shown": shown, "total": len(groups)}, singles, nodes_out, edges_out


def _rank(group: dict) -> tuple:
    """Most money with findings on the links first, then the larger group."""
    return -group["flagged_amount"], -len(group["vendors"]) - len(group["approvers"]), group["vendors"]


def _vendor_stats(conn: db.Database, totals: dict[str, list]) -> dict[str, dict]:
    """Invoices and spend of each vendor (counted by the caller), with its findings, waiting invoices and risk."""
    stats = {vendor_id: {"invoices": n, "amount": amount, "flagged": 0, "waiting": 0, "max_risk": 0.0}
             for vendor_id, (n, amount) in totals.items()}
    for vendor_id, flagged, waiting, max_risk in conn.execute(
            "SELECT vendor_id, SUM(CASE WHEN flag_count > 0 THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN workflow_status = 'PENDING_REVIEW' THEN 1 ELSE 0 END), MAX(rc) FROM v_latest_results "
            "GROUP BY vendor_id"):
        if vendor_id in stats:
            stats[vendor_id].update(flagged=int(flagged or 0), waiting=int(waiting or 0), max_risk=float(max_risk or 0))
    return stats
