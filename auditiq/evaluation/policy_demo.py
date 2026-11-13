"""The demonstration policies: how the output of the audit changes when only the policy document changes.

    python -m evaluation.policy_demo [--ledger data/final_seed_2025]

For the baseline policy (v2.5) and each demonstration policy of ``auditiq/policy_demo.py`` the script

 1. writes the policy as a PDF (policy/demo/) and reads it back as the system does on upload, comparing every
    value read with the value the document states;
 2. audits every invoice of the ledger with the deterministic controls (configuration C1) under the policy read
    from the PDF, with the scores, levels and routes of the application;
 3. compares the result with the ground truth of the ledger (``labels.csv``, written for the baseline): the frauds
    of the ledger that still raise a finding, and the invoices without a fraud that now do;
 4. finds invoices that the policies judge most differently, and lists their outcome under each policy.

It writes results/policy_demo/policy_demo.json and policy_demo.md. The judgement rules (2.1.4, 2.1.5, 2.2.2, 4.1.2)
need a model and are not part of C1; the rules decided by the controls are the twelve of the Overview.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

import pandas as pd

from auditiq import policy_demo, policy_extract, scoring
from auditiq.controls import run_controls
from auditiq.extraction import extract
from auditiq.policy import PROJECT_ROOT, load_policy
from auditiq_bench.taxonomy import CLASSES
from evaluation.policy_change import count_parameters, matching_parameters

OPTIONS = scoring.ScoringOptions(use_confidence=False)           # configuration C1
RULE_CLAUSES = {c for k in CLASSES.values() if k.kind == "rule" for c in k.clauses}
LEVELS = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
BINS = [(0, 0), (1, 10), (11, 30), (31, 50), (51, 69), (70, 79), (80, 89), (90, 100)]


def audit(transactions: list[dict], clauses: dict) -> dict[str, dict]:
    """Every invoice under one policy: its findings, score, level and route."""
    out = {}
    for txn in transactions:
        flags = [scoring.normalize_flag(f, clauses) for f in run_controls(txn, clauses)]
        for flag in flags:
            flag["confidence"] = 1.0
        result = scoring.score(flags, OPTIONS)
        out[txn["invoice"]["invoice_id"]] = {"rules": sorted(f["clause"] for f in flags), "score": result["rc"],
                                             "level": result["risk_level"], "route": result["route"]}
    return out


def summarise(audited: dict[str, dict], amounts: dict[str, float]) -> dict:
    flagged = [i for i, r in audited.items() if r["rules"]]
    scores = Counter(round(audited[i]["score"]) for i in flagged)
    rules = Counter(rule for r in audited.values() for rule in r["rules"])
    escalated = [i for i, r in audited.items() if r["route"] == "escalate"]
    return {"invoices": len(audited), "with_findings": len(flagged), "escalated": len(escalated),
            "approved": len(audited) - len(escalated),
            "amount_escalated": round(sum(amounts[i] for i in escalated), 2),
            "levels": {level: sum(r["level"] == level for r in audited.values()) for level in LEVELS},
            "findings": sum(rules.values()), "by_rule": dict(sorted(rules.items())),
            "distinct_scores": len(scores), "score_values": {str(k): v for k, v in sorted(scores.items())},
            "histogram": {f"{lo}-{hi}" if lo != hi else "0": sum(v for k, v in scores.items() if lo <= k <= hi)
                          for lo, hi in BINS[1:]}}


def against_truth(audited: dict[str, dict], labels: pd.DataFrame) -> dict:
    """Frauds of the ledger still found, and clean invoices wrongly raised. The labels hold for the baseline."""
    truth = {i: set(filter(None, c.split("|"))) & RULE_CLAUSES for i, c in labels["clause_ids"].items()}
    fraud = [i for i in labels.index if labels.at[i, "label"] == "anomalous" and truth[i]]
    clean = [i for i in labels.index if labels.at[i, "label"] != "anomalous"]
    found = [i for i in fraud if audited[i]["rules"]]
    escalated = [i for i in fraud if audited[i]["route"] == "escalate"]
    alarms = [i for i in clean if audited[i]["rules"]]
    needless = [i for i in clean if audited[i]["route"] == "escalate"]
    return {"frauds": len(fraud), "frauds_with_a_finding": len(found), "frauds_escalated": len(escalated),
            "frauds_missed": len(fraud) - len(found), "clean_invoices": len(clean), "clean_with_a_finding": len(alarms),
            "clean_escalated": len(needless)}


def compare(base: dict[str, dict], other: dict[str, dict]) -> dict:
    moved = sum(base[i]["rules"] != other[i]["rules"] for i in base)
    routes = Counter(f"{base[i]['route']} -> {other[i]['route']}" for i in base if base[i]["route"] != other[i]["route"])
    higher = sum(other[i]["score"] > base[i]["score"] for i in base)
    lower = sum(other[i]["score"] < base[i]["score"] for i in base)
    return {"decisions_moved": moved, "route_changes": dict(routes.most_common()), "score_higher": higher,
            "score_lower": lower, "newly_flagged": sum(not base[i]["rules"] and bool(other[i]["rules"]) for i in base),
            "cleared": sum(bool(base[i]["rules"]) and not other[i]["rules"] for i in base)}


def showcase(audits: dict[str, dict[str, dict]], amounts: dict[str, float], count: int = 5) -> list[dict]:
    """The invoices the policies judge most differently: the most different scores, then the widest range, then the
    largest amount. An invoice every policy treats alike is never shown."""
    keys = list(audits)

    def spread(i: str) -> tuple:
        scores = [round(audits[k][i]["score"]) for k in keys]
        return (-len(set(scores)), -(max(scores) - min(scores)), -amounts[i], i)

    ranked = sorted(audits[keys[0]], key=spread)
    return [{"invoice_id": i, "amount": amounts[i],
             "outcomes": {k: {kk: audits[k][i][kk] for kk in ("rules", "score", "level", "route")} for k in keys}}
            for i in ranked[:count]]


def render(result: dict) -> str:
    names = list(result["policies"])
    base = result["policies"]["Baseline v2.5"]
    lines = [f"# Demonstration policies on `{result['ledger']}`", "",
             f"{result['invoices']:,} invoices audited by the controls (configuration C1) under each policy read from its "
             "PDF. The same ledger and the same code; only the document changes.", "",
             "## What each policy states", "", "| Policy | Version | Values read | Changes from the baseline | Story |",
             "|---|---|---|---|---|"]
    for name in names:
        p = result["policies"][name]
        lines.append(f"| {name} | {p['version']} | {p['values_read']}/{p['values']} | {p['changes']} | {p['story']} |")
    lines += ["", "## How the output changes", "",
              "| Policy | Invoices with findings | Held for review | Money held | Critical | High | Medium | Different scores |",
              "|---|---|---|---|---|---|---|---|"]
    for name in names:
        p = result["policies"][name]
        s = p["summary"]
        lines.append(f"| {name} | {s['with_findings']:,} | {s['escalated']:,} | ₹{s['amount_escalated'] / 1e7:,.1f} Cr "
                     f"| {s['levels']['CRITICAL']:,} | {s['levels']['HIGH']:,} | {s['levels']['MEDIUM']:,} | {s['distinct_scores']} |")
    lines += ["", "## Against the frauds of the ledger", "",
              f"The ledger's answer key names {base['truth']['frauds']:,} frauds the controls can decide and "
              f"{base['truth']['clean_invoices']:,} invoices without a fraud. The key was written for the baseline: under another "
              "policy a baseline fraud that falls inside the new limits is no longer an exception of that company, and an "
              "invoice the baseline accepts may break the new rules. The table says what the choice of policy costs or hides.", "",
              "| Policy | Baseline frauds still raised | Baseline frauds no longer raised | Held for review | Invoices without a fraud now raised | Of them held |",
              "|---|---|---|---|---|---|"]
    for name in names:
        t = result["policies"][name]["truth"]
        lines.append(f"| {name} | {t['frauds_with_a_finding']:,} | {t['frauds_missed']:,} | {t['frauds_escalated']:,} "
                     f"| {t['clean_with_a_finding']:,} | {t['clean_escalated']:,} |")
    lines += ["", "## Against the baseline, invoice by invoice", "",
              "| Policy | Decisions moved | Newly flagged | Cleared | Score higher | Score lower | Route changes |",
              "|---|---|---|---|---|---|---|"]
    for name in names[1:]:
        c = result["policies"][name]["against_baseline"]
        routes = "; ".join(f"{k}: {v:,}" for k, v in c["route_changes"].items()) or "none"
        lines.append(f"| {name} | {c['decisions_moved']:,} | {c['newly_flagged']:,} | {c['cleared']:,} "
                     f"| {c['score_higher']:,} | {c['score_lower']:,} | {routes} |")
    rules = sorted({r for p in result["policies"].values() for r in p["summary"]["by_rule"]})
    lines += ["", "## Findings by rule", "", "| Rule | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for rule in rules:
        lines.append(f"| {rule} | " + " | ".join(f"{result['policies'][n]['summary']['by_rule'].get(rule, 0):,}" for n in names) + " |")
    lines += ["", "## One invoice, five verdicts", "",
              "The invoices the policies judge most differently (score and route under each policy).", ""]
    for row in result["showcase"]:
        lines += [f"**{row['invoice_id']}**, ₹{row['amount']:,.2f}", "", "| Policy | Rules | Score | Level | Route |",
                  "|---|---|---|---|---|"]
        lines += [f"| {n} | {', '.join(o['rules']) or 'none'} | {o['score']:.0f} | {o['level']} | {o['route']} |"
                  for n, o in row["outcomes"].items()]
        lines.append("")
    refused = result["refused"]
    lines += ["## A policy that is refused", "",
              f"`{refused['file']}` leaves out rules. The system reads it and refuses it, with the reasons:", ""]
    lines += [f"- {p}" for p in refused["problems"]]
    return "\n".join(lines) + "\n"


def change_text(change: dict) -> str:
    def show(v):
        return ", ".join(f"{k} {x:,.0f}" for k, x in v.items()) if isinstance(v, dict) else (
            ", ".join(v) if isinstance(v, list) else f"{v:g}" if isinstance(v, float) else str(v))
    return f"Rule {change['clause']}, {change['parameter'].replace('_', ' ')}: {show(change['from'])} to {show(change['to'])}"


def guide(result: dict) -> str:
    """docs/POLICY_DEMO.md: how to run the demonstration, with the numbers of the measured run."""
    base = result["policies"]["Baseline v2.5"]["summary"]
    lines = [
        "# Demonstration policies", "",
        "Five company policies, each a PDF, to show that the audit follows the document: the same ledger, the same code, "
        "a different policy uploaded, a different result. The numbers below are measured by "
        "`python -m evaluation.policy_demo` on the ledger `" + result["ledger"] + "` "
        f"({result['invoices']:,} invoices), the controls of configuration C1 deciding the twelve rules they decide. "
        "The documents are in `policy/demo/`; `auditiq/policy_demo.py` renders them.", "",
        "## The demonstration, step by step", "",
        "1. Start the application with `start.bat`. The Overview shows the baseline policy (v2.5): "
        f"{base['with_findings']:,} invoices with findings, {base['escalated']:,} held for review.",
        "2. Open **Policy**. Upload one PDF from `policy/demo/`. The page reads it and shows what it states and what "
        "differs from the policy in force, rule by rule.",
        "3. Choose **Simulate**: every invoice of the ledger is audited in memory under the document and compared with "
        "the policy in force. Nothing is stored. The result says how many decisions move and how many invoices "
        "newly need a reviewer. The comparison is with the policy in force at that moment, so activate the baseline "
        "(version 2.5) and apply it between two demonstrations if the numbers are to be read against it.",
        "4. Choose **Adopt and activate**, then **Apply**. The ledger is audited again under the new policy; the "
        "Overview, the review queue, the risk levels, the analytics and the vendor rings all follow it.",
        "5. Upload the next policy and compare. To return, activate version 2.5 and apply again.",
        "6. Upload `Draft_Incomplete_v5.99.pdf`: the system refuses it and says which rules the document leaves out.", "",
        "## The policies", "",
        "| Policy | File | What it changes from the baseline |", "|---|---|---|"]
    for name, p in result["policies"].items():
        if name.startswith("Baseline"):
            continue
        lines.append(f"| **{name}** (v{p['version']}) | `{p['file']}` | " + "; ".join(change_text(c) for c in p["change_list"]) + " |")
    lines += ["", "## What happens", ""]
    for name, p in result["policies"].items():
        if name.startswith("Baseline"):
            continue
        s, t, c = p["summary"], p["truth"], p["against_baseline"]
        lines += [f"### {name}", "", p["story"], "",
                  f"{s['with_findings']:,} invoices have findings (baseline {base['with_findings']:,}) and {s['escalated']:,} "
                  f"are held for review (baseline {base['escalated']:,}), ₹{s['amount_escalated'] / 1e7:,.1f} Cr "
                  f"against ₹{base['amount_escalated'] / 1e7:,.1f} Cr. Risk levels: {s['levels']['CRITICAL']:,} critical, "
                  f"{s['levels']['HIGH']:,} high, {s['levels']['MEDIUM']:,} medium. Against the baseline: "
                  f"{c['decisions_moved']:,} decisions move, {c['score_higher']:,} invoices score higher and {c['score_lower']:,} "
                  f"lower. {t['frauds_missed']:,} of the baseline's {t['frauds']:,} frauds are no longer raised; "
                  f"{t['clean_with_a_finding']:,} invoices the baseline accepts are now raised.", "",
                  "What it shows: " + p["shows"], ""]
    lines += ["## One invoice, many verdicts", ""]
    row = result["showcase"][0]
    lines += [f"{row['invoice_id']} (₹{row['amount']:,.2f}) breaks the same rules wherever it is read, yet its score and the "
              "rules it breaks depend on the policy:", "", "| Policy | Rules | Score | Level | Route |", "|---|---|---|---|---|"]
    lines += [f"| {n} | {', '.join(o['rules']) or 'none'} | {o['score']:.0f} | {o['level']} | {o['route']} |"
              for n, o in row["outcomes"].items()]
    lines += ["", "The full comparison is in `results/policy_demo/policy_demo.md`.", "",
              "## A word of caution on reading the numbers", "",
              "- The answer key of a ledger is written for one policy (the baseline). Under another policy a baseline "
              "fraud that is inside the new limits is not an exception of that company; the tables say what a policy "
              "hides or adds, not which policy is right.",
              "- The judgement rules (2.1.4, 2.1.5, 2.2.2, 4.1.2) need a model and are not part of these figures.",
              "- Each policy takes effect on 2025-04-01, so the one chosen governs the whole financial year of the ledger.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ledger", type=Path, default=PROJECT_ROOT / "data" / "final_seed_2025")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "results" / "policy_demo")
    args = parser.parse_args(argv)

    base = load_policy(policy_demo.BASELINE).registry
    documents = [("Baseline v2.5", None, base, "The procurement SOP of the project.")]
    paths = {p.name: p for p in policy_demo.write_all()}
    for scenario in policy_demo.SCENARIOS:
        pdf = paths[policy_demo.pdf_name(scenario)]
        read = policy_extract.build(pdf, base)
        assert read.usable, (scenario.name, read.problems)
        intended = policy_demo.registry_of(scenario, base)
        documents.append((f"{scenario.name}", scenario, read.registry, scenario.shows, intended, read))

    labels = pd.read_csv(args.ledger / "labels.csv", dtype=str, keep_default_na=False).set_index("invoice_id")
    transactions = extract(args.ledger)
    amounts = {t["invoice"]["invoice_id"]: float(t["invoice"]["amount"] or 0) for t in transactions}
    audits, result = {}, {"ledger": args.ledger.name, "invoices": len(transactions),
                          "produced": time.strftime("%Y-%m-%d %H:%M"), "policies": {}}
    for entry in documents:
        name, scenario, registry = entry[0], entry[1], entry[2]
        began = time.perf_counter()
        audited = audit(transactions, registry["clauses"])
        seconds = time.perf_counter() - began
        audits[name] = audited
        row = {"version": registry["version"], "story": entry[3] if scenario is None else scenario.story,
               "shows": "" if scenario is None else scenario.shows, "seconds": round(seconds, 2),
               "summary": summarise(audited, amounts), "truth": against_truth(audited, labels), "values": 0,
               "values_read": 0, "changes": 0}
        if scenario is not None:
            intended, read = entry[4], entry[5]
            row.update(values=count_parameters(intended), values_read=matching_parameters(read.registry, intended),
                       changes=len(read.changes), file=policy_demo.pdf_name(scenario), change_list=read.changes)
        result["policies"][name] = row
        print(f"{name}: {row['summary']['with_findings']:,} invoices with findings, {row['summary']['escalated']:,} held, "
              f"{row['summary']['distinct_scores']} different scores", flush=True)
    for name in list(audits)[1:]:
        result["policies"][name]["against_baseline"] = compare(audits["Baseline v2.5"], audits[name])
    result["showcase"] = showcase(audits, amounts)
    draft = policy_extract.build(paths["Draft_Incomplete_v5.99.pdf"], base)
    result["refused"] = {"file": "Draft_Incomplete_v5.99.pdf", "usable": draft.usable, "problems": draft.problems}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "policy_demo.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8", newline="\n")
    text = render(result)
    (args.out / "policy_demo.md").write_text(text, encoding="utf-8", newline="\n")
    (PROJECT_ROOT / "docs" / "POLICY_DEMO.md").write_text(guide(result), encoding="utf-8", newline="\n")
    print(f"wrote {args.out / 'policy_demo.md'} and docs/POLICY_DEMO.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
