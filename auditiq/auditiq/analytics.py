"""Forensic analytics of the ledger, for the web application's Analytics and Overview pages.

Every figure is computed from the store when it is asked for: the ledger (invoices, vendors, approvals),
the latest audit result of each invoice and the active policy. Nothing is sampled or estimated; the Lorenz
curve alone is drawn through 51 of its points, and its Gini coefficient is computed on every vendor.

    ledger_analytics(conn)  monthly volume and findings, spend by category and month, Benford's first-digit
                            and first-two-digits tests, amounts against the approval limits, weekdays,
                            findings by vendor category and rule, approvers, spend concentration
    coverage(conn)          which checks produced the latest results, the findings that did not hold
                            payment, and, on a benchmark ledger, the results against its answer key

Benford conformity uses Nigrini's thresholds for the mean absolute deviation (Benford's Law, Wiley 2012):
first digit 0.006, 0.012, 0.015; first two digits 0.0012, 0.0018, 0.0022. A digit is marked when its
z-statistic, with the continuity correction, exceeds 1.96.
"""
from __future__ import annotations

import json
import math
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import date

from . import db
from .graph import PRESETS

# The policy every benchmark ledger of auditiq_bench is labelled for (the default of its generate()); used for
# stores loaded before the version was recorded in meta.labels_policy.
BENCHMARK_POLICY = "2.5"
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
BENFORD_FIRST = {d: math.log10(1 + 1 / d) for d in range(1, 10)}
BENFORD_TWO = {d: math.log10(1 + 1 / d) for d in range(10, 100)}
MAD_FIRST = ((0.006, "close conformity"), (0.012, "acceptable conformity"), (0.015, "marginally acceptable conformity"))
MAD_TWO = ((0.0012, "close conformity"), (0.0018, "acceptable conformity"), (0.0022, "marginally acceptable conformity"))
Z_CRITICAL = 1.96
BINS_PER_DECADE = 4
NEAR_LIMIT = 0.10            # "just below a limit": within 10 % under it
LORENZ_POINTS = 50
TOP_APPROVERS = 12


def _clauses(raw: str | None) -> list[str]:
    return [c.strip() for c in (raw or "").replace("|", ",").split(",") if c.strip()]


def active_version(conn: db.Database) -> str | None:
    return conn.scalar("SELECT version FROM company_policies WHERE is_active = 1")


def governing_version(conn: db.Database) -> str | None:
    """The policy version in force on the dates of most of the ledger's invoices: the limits that applied when they
    were approved, which the amount analyses measure against (not a version that took effect after them)."""
    timeline = db.policy_timeline(conn)
    if len(timeline) <= 1:
        return timeline[0][1] if timeline else None
    expr, params = db.in_force_sql(timeline, "date")
    row = conn.execute(f"SELECT {expr} AS v, COUNT(*) AS n FROM invoices GROUP BY 1 ORDER BY 2 DESC", params).fetchone()
    return row[0] if row else timeline[-1][1]


def approval_limits(conn: db.Database, version: str | None) -> tuple[str | None, dict[str, float]]:
    """The clause that holds the approval limits of the policy, and the limit of each role."""
    for clause, value in conn.execute(
            "SELECT clause_id, param_value FROM policy_parameters WHERE version = ? AND param_name = 'approval_limits'",
            (version,)):
        limits = json.loads(value) if isinstance(value, str) else value
        return clause, {role: float(limit) for role, limit in (limits or {}).items()}
    return None, {}


def judgement_clauses(conn: db.Database, version: str | None) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT clause_id FROM policy_clauses WHERE version = ? AND kind = 'judgement' ORDER BY clause_id", (version,))]


# ------------------------------------------------------------------- Benford
def benford(amounts: list[float]) -> dict:
    """Benford's first-digit and first-two-digits tests on the amounts of at least 10."""
    first: Counter[int] = Counter()
    two: Counter[int] = Counter()
    for amount in amounts:
        if amount >= 10:
            mantissa = f"{amount:.6e}"            # "4.396686e+06": the significant digits, whatever the size
            first[int(mantissa[0])] += 1
            two[int(mantissa[0] + mantissa[2])] += 1
    n = sum(first.values())
    return {"n": n, "first": _benford_test(first, BENFORD_FIRST, n, MAD_FIRST),
            "first_two": _benford_test(two, BENFORD_TWO, n, MAD_TWO)}


def _benford_test(counts: Counter, expected: dict[int, float], n: int, thresholds) -> dict:
    digits, mad, chi2 = [], 0.0, 0.0
    for d, p in expected.items():
        observed = counts[d] / n if n else 0.0
        z = (abs(observed - p) - 1 / (2 * n)) / math.sqrt(p * (1 - p) / n) if n else 0.0
        digits.append({"digit": d, "count": counts[d], "observed": observed, "expected": p,
                       "z": max(0.0, z), "significant": n > 0 and z > Z_CRITICAL})
        mad += abs(observed - p)
        chi2 += (counts[d] - n * p) ** 2 / (n * p) if n else 0.0
    mad /= len(expected)
    conformity = next((label for limit, label in thresholds if mad <= limit), "nonconformity") if n else "no data"
    return {"digits": digits, "mad": mad, "chi2": chi2, "dof": len(expected) - 1, "conformity": conformity,
            "thresholds": [limit for limit, _ in thresholds]}


# --------------------------------------------------------------- the analytics
def ledger_analytics(conn: db.Database) -> dict:
    """Every view of the Analytics page, from one pass over the ledger and its latest results."""
    version = governing_version(conn)
    limit_clause, limits = approval_limits(conn, version)
    vendors = {v: (name, category or "Uncategorised", bool(blocked)) for v, name, category, blocked in conn.execute(
        "SELECT vendor_id, vendor_name, vendor_category, blacklisted FROM vendor_master")}
    roles = dict(conn.execute("SELECT approver_name, MAX(approver_role) FROM approval_logs GROUP BY approver_name"))
    clauses_of: dict[str, list[str]] = defaultdict(list)
    for invoice_id, clause in conn.execute(
            "SELECT l.invoice_id, f.clause FROM audit_flags f JOIN v_latest_results l ON l.result_id = f.result_id "
            "WHERE f.status = 'kept'"):
        clauses_of[invoice_id].append(clause)

    months: dict[str, Counter] = defaultdict(Counter)
    skyline: dict[tuple[str, str], float] = defaultdict(float)
    weekdays = [Counter() for _ in WEEKDAYS]
    categories: dict[str, Counter] = defaultdict(Counter)
    approvers: dict[str, Counter] = defaultdict(Counter)
    approver_vendors: dict[str, set] = defaultdict(set)
    spend: Counter[str] = Counter()
    amounts: list[float] = []
    flagged_amounts: list[float] = []

    for invoice_id, vendor_id, day, amount, approver, flag_count, route in conn.execute(
            "SELECT i.invoice_id, i.vendor_id, CAST(i.date AS TEXT), i.amount, i.approved_by, l.flag_count, l.route "
            "FROM invoices i LEFT JOIN v_latest_results l ON l.invoice_id = i.invoice_id"):
        amount = float(amount or 0)
        flagged = bool(flag_count)
        category = vendors.get(vendor_id, ("", "Uncategorised", False))[1]
        amounts.append(amount)
        if flagged:
            flagged_amounts.append(amount)
        spend[vendor_id] += amount
        month = (day or "")[:7]
        m = months[month]
        m["invoices"] += 1
        m["amount"] += amount
        m["flagged"] += flagged
        m["escalated"] += route == "escalate"
        m["findings"] += int(flag_count or 0)
        skyline[(month, category)] += amount
        if day:
            w = weekdays[date.fromisoformat(day[:10]).weekday()]
            w["invoices"] += 1
            w["amount"] += amount
            w["flagged"] += flagged
        c = categories[category]
        c["invoices"] += 1
        c["amount"] += amount
        c["flagged"] += flagged
        for clause in clauses_of.get(invoice_id, ()):
            c[f"rule:{clause}"] += 1
        a = approvers[approver or "(none)"]
        a["invoices"] += 1
        a["amount"] += amount
        a["flagged"] += flagged
        a["flagged_amount"] += amount if flagged else 0.0
        a["over_limit"] += limit_clause in clauses_of.get(invoice_id, ())
        approver_vendors[approver or "(none)"].add(vendor_id)

    month_keys = sorted(k for k in months if k)
    category_keys = sorted(categories, key=lambda k: -categories[k]["amount"])
    rule_keys = sorted({k[5:] for c in categories.values() for k in c if k.startswith("rule:")},
                       key=lambda r: [int(x) for x in r.split(".")])
    return {
        "invoices": len(amounts),
        "policy_version": version,
        "monthly": [{"month": k, "invoices": months[k]["invoices"], "amount": months[k]["amount"],
                     "flagged": months[k]["flagged"], "escalated": months[k]["escalated"],
                     "findings": months[k]["findings"]} for k in month_keys],
        "skyline": {"months": month_keys, "categories": category_keys,
                    "amounts": [[skyline.get((m, c), 0.0) for m in month_keys] for c in category_keys]},
        "benford": benford(amounts),
        "amounts": _amount_bins(amounts, flagged_amounts, limits),
        "weekdays": [{"weekday": WEEKDAYS[i], "invoices": w["invoices"], "amount": w["amount"],
                      "flagged": w["flagged"]} for i, w in enumerate(weekdays)],
        "categories": {
            "rules": rule_keys,
            "rows": [{"category": k, "invoices": categories[k]["invoices"], "amount": categories[k]["amount"],
                      "flagged": categories[k]["flagged"],
                      "findings": [categories[k][f"rule:{r}"] for r in rule_keys]} for k in category_keys]},
        "approvers": _approvers(approvers, approver_vendors, roles, limits),
        "concentration": _concentration(spend, vendors),
    }


def _amount_bins(amounts: list[float], flagged: list[float], limits: dict[str, float]) -> dict:
    """Invoices per quarter-decade of amount, and how many fall just under and just over each approval limit."""
    positive = [a for a in amounts if a > 0]
    if not positive:
        return {"bins": [], "limits": []}
    low = math.floor(math.log10(min(positive)) * BINS_PER_DECADE)
    high = math.floor(math.log10(max(positive)) * BINS_PER_DECADE) + 1
    counts, hits = Counter(), Counter()
    for a in positive:
        counts[math.floor(math.log10(a) * BINS_PER_DECADE)] += 1
    for a in flagged:
        if a > 0:
            hits[math.floor(math.log10(a) * BINS_PER_DECADE)] += 1
    bins = [{"low": 10 ** (k / BINS_PER_DECADE), "high": 10 ** ((k + 1) / BINS_PER_DECADE),
             "invoices": counts[k], "flagged": hits[k]} for k in range(low, high)]
    ordered = sorted(amounts)
    near = []
    for role, limit in sorted(limits.items(), key=lambda kv: kv[1]):
        at, under, over = (bisect_left(ordered, x) for x in (limit, limit * (1 - NEAR_LIMIT), limit * (1 + NEAR_LIMIT)))
        near.append({"role": role, "limit": limit, "below": at - under, "above": over - at})
    return {"bins": bins, "limits": near, "near": NEAR_LIMIT}


def _approvers(approvers: dict[str, Counter], vendors: dict[str, set], roles: dict[str, str],
               limits: dict[str, float]) -> dict:
    rows = [{"approver": name, "role": roles.get(name), "limit": limits.get(roles.get(name) or ""),
             "invoices": a["invoices"], "amount": a["amount"], "flagged": a["flagged"],
             "flagged_amount": a["flagged_amount"], "over_limit": a["over_limit"], "vendors": len(vendors[name])}
            for name, a in approvers.items()]
    rows.sort(key=lambda r: (-r["flagged_amount"], -r["flagged"], r["approver"]))
    return {"total": len(rows), "top": rows[:TOP_APPROVERS]}


def _concentration(spend: Counter, vendors: dict) -> dict:
    """How unevenly the spend is spread over vendors: the Lorenz curve, the Gini coefficient, the top ten."""
    values = sorted(spend.values())
    total = sum(values)
    n = len(values)
    if not n or total <= 0:
        return {"vendors": n, "gini": None, "lorenz": [], "top": [], "top10_share": None, "hhi": None}
    cumulative, running = [0.0], 0.0
    for v in values:
        running += v
        cumulative.append(running / total)
    area = sum((cumulative[i] + cumulative[i + 1]) / 2 for i in range(n)) / n
    picks = sorted({round(i * n / LORENZ_POINTS) for i in range(LORENZ_POINTS + 1)})
    top = spend.most_common(10)
    return {"vendors": n, "gini": 1 - 2 * area, "lorenz": [[i / n, cumulative[i]] for i in picks],
            "top10_share": sum(v for _, v in top) / total,
            "hhi": sum((v / total) ** 2 for v in values) * 10_000,
            "top": [{"vendor_id": k, "vendor_name": vendors.get(k, (k,))[0], "amount": v, "share": v / total}
                    for k, v in top]}


# ------------------------------------------------------------------- coverage
def coverage(conn: db.Database, configurations: dict[str, int] | None = None,
             approved_with_findings: int | None = None) -> dict:
    """What the latest results checked, and how they compare with the benchmark's answer key if there is one.

    A configuration without agents never evaluates the judgement clauses, and one without controls never
    evaluates the deterministic ones: an invoice approved under it was not checked against them, which the
    counts here make visible instead of reporting it as clean. The overview passes the two counts it already
    has from its own pass over the latest results.
    """
    version = active_version(conn)
    if configurations is None:
        configurations = {c: int(n) for c, n in conn.execute(
            "SELECT configuration, COUNT(*) FROM v_latest_results GROUP BY configuration ORDER BY configuration")}
    if approved_with_findings is None:
        approved_with_findings = int(conn.scalar(
            "SELECT COUNT(*) FROM v_latest_results WHERE flag_count > 0 AND route = 'approve'") or 0)
    agents = {c for c, p in PRESETS.items() if p.agents != "none"}
    controls = {c for c, p in PRESETS.items() if p.controls}
    judgement = judgement_clauses(conn, version)
    return {"configurations": dict(sorted(configurations.items())),
            "controls_run": sum(n for c, n in configurations.items() if c in controls),
            "judgement_run": sum(n for c, n in configurations.items() if c in agents),
            "judgement_clauses": judgement,
            "approved_with_findings": approved_with_findings,
            "answer_key": answer_key(conn, set(judgement), agents, controls)}


def answer_key(conn: db.Database, judgement: set[str], agents: set[str], controls: set[str]) -> dict | None:
    """The latest results against the benchmark labels, when the ledger is a benchmark ledger.

    An anomaly counts as found when its invoice has any kept finding. A missed anomaly is "not checked" when
    the configuration of its result could not evaluate the injected rule (a judgement rule under a
    configuration without agents), and "missed" otherwise. The labels hold for the policy version they were
    written for; results under another version are left out and counted, since a changed threshold makes an
    invoice anomalous or clean regardless of the labels.
    """
    if not conn.scalar("SELECT COUNT(*) FROM benchmark_labels"):
        return None
    key_policy = conn.scalar("SELECT value FROM meta WHERE key = 'labels_policy'") or BENCHMARK_POLICY
    total: Counter[str] = Counter()
    per: dict[str, Counter] = defaultdict(Counter)
    other_policy = 0
    for config, policy, label, clause_ids, found, n in conn.execute(
            "SELECT l.configuration, l.policy_version, b.label, b.clause_ids, "
            "CASE WHEN l.flag_count > 0 THEN 1 ELSE 0 END, COUNT(*) "
            "FROM v_latest_results l JOIN benchmark_labels b ON b.invoice_id = l.invoice_id "
            "GROUP BY l.configuration, l.policy_version, b.label, b.clause_ids, "
            "CASE WHEN l.flag_count > 0 THEN 1 ELSE 0 END"):
        n = int(n)
        if policy != key_policy:
            other_policy += n
            continue
        if label == "anomalous":
            if found:
                outcome = "found"
            else:
                checkable = config in agents or (config in controls and not set(_clauses(clause_ids)) & judgement)
                outcome = "missed" if checkable else "not_checked"
        else:
            outcome = "false_alarms" if found else "passed"
        total[outcome] += n
        per[config][outcome] += n
        if label == "hard_negative":
            total[f"hard_negative_{outcome}"] += n

    def summary(c: Counter) -> dict:
        tp, fp = c["found"], c["false_alarms"]
        fn = c["missed"] + c["not_checked"]
        return {"found": tp, "false_alarms": fp, "missed": c["missed"], "not_checked": c["not_checked"],
                "passed": c["passed"], "precision": tp / (tp + fp) if tp + fp else None,
                "recall": tp / (tp + fn) if tp + fn else None}

    return {**summary(total), "hard_negatives_flagged": total["hard_negative_false_alarms"],
            "policy_version": key_policy, "other_policy": other_policy,
            "by_configuration": {c: summary(v) for c, v in sorted(per.items())}}
