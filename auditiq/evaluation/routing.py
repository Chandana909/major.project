"""Where the audit sends the invoices of a store, checked against the answer key and the policy timeline.

    python -m evaluation.routing --db .auditiq/demo.db --name demo
    python -m evaluation.routing --db huge.db --name huge_run2 --run 2      # one run instead of the latest results

For each invoice's latest result (or the results of one run): the route and the risk level; with the benchmark's
answer key, the route of every label (anomalous, hard negative, clean); and the policy version each result was made
under against the version in force on the invoice's date. Writes results/routing_<name>.json and .md. Nothing is
audited: this reads what the store holds.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from auditiq import db

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ("escalate", "sample", "approve")
LEVELS = ("CRITICAL", "HIGH", "MEDIUM", "LOW")


def evaluate(conn: db.Database, run: int | None = None) -> dict:
    source = ("v_latest_results" if run is None else
              f"(SELECT r.*, u.configuration, u.policy_version FROM audit_results r "
              f"JOIN audit_runs u ON u.run_id = r.run_id WHERE r.run_id = {int(run)})")
    rows = conn.execute(
        f"SELECT x.invoice_id, x.route, x.risk_level, x.flag_count, x.configuration, x.policy_version, "
        f"CAST(i.date AS TEXT), b.label FROM {source} x JOIN invoices i ON i.invoice_id = x.invoice_id "
        "LEFT JOIN benchmark_labels b ON b.invoice_id = x.invoice_id").fetchall()
    timeline = db.policy_timeline(conn)
    routes, levels, configurations = Counter(), Counter(), Counter()
    by_label: dict[str, Counter] = {}
    versions, approved_with_findings = Counter(), 0
    for _invoice, route, level, flags, configuration, version, day, label in rows:
        routes[route] += 1
        levels[level] += 1
        configurations[configuration] += 1
        approved_with_findings += route == "approve" and bool(flags)
        if label:
            by_label.setdefault(label, Counter())[route] += 1
        versions[(version, db.version_in_force(timeline, day))] += 1
    audited = len(rows)
    to_person = routes["escalate"] + routes["sample"]
    out = {
        "dataset": conn.scalar("SELECT value FROM meta WHERE key = 'dataset'"),
        "run": run, "audited": audited,
        "routes": {r: routes[r] for r in ROUTES}, "risk_levels": {lv: levels[lv] for lv in LEVELS},
        "configurations": dict(sorted(configurations.items())),
        "to_a_person": to_person, "to_a_person_share": round(to_person / audited, 4) if audited else None,
        "approved_with_findings": approved_with_findings,
        "policy": {"timeline": [{"from": start or None, "version": v} for start, v in timeline],
                   "results": [{"made_under": made, "in_force": force, "invoices": n}
                               for (made, force), n in sorted(versions.items(), key=lambda kv: -kv[1])],
                   "not_under_the_version_in_force": sum(n for (made, force), n in versions.items() if made != force)},
    }
    if by_label:
        out["answer_key"] = {label: {r: c[r] for r in ROUTES} for label, c in sorted(by_label.items())}
        anomalous = by_label.get("anomalous", Counter())
        sent = sum(c["escalate"] + c["sample"] for c in by_label.values())
        out["sent_to_a_person_that_are_anomalous"] = round((anomalous["escalate"] + anomalous["sample"]) / sent, 4) if sent else None
        out["clean_sent_to_a_person"] = by_label.get("clean", Counter())["escalate"] + by_label.get("clean", Counter())["sample"]
    return out


def markdown(name: str, r: dict) -> str:
    share = f"{r['to_a_person_share']:.1%}" if r["to_a_person_share"] is not None else "–"
    where = f"run {r['run']}" if r["run"] else "latest results"
    lines = [f"# Routing of `{r['dataset']}` ({name})", "",
             f"Source: `python -m evaluation.routing` on the store, {where}.",
             "", f"{r['audited']:,} invoices audited; **{r['to_a_person']:,} ({share}) sent to a person** "
             f"(escalated or sampled); {r['approved_with_findings']:,} approved automatically with a finding recorded.", "",
             "| Route | Invoices |", "|---|---|", *[f"| {k} | {v:,} |" for k, v in r["routes"].items()], "",
             "| Risk level | Invoices |", "|---|---|", *[f"| {k} | {v:,} |" for k, v in r["risk_levels"].items()], ""]
    if "answer_key" in r:
        lines += ["| Answer key | Escalated | Sampled | Approved |", "|---|---|---|---|",
                  *[f"| {label} | {c['escalate']:,} | {c['sample']:,} | {c['approve']:,} |" for label, c in r["answer_key"].items()],
                  "", f"Of the invoices sent to a person, {r['sent_to_a_person_that_are_anomalous']:.1%} are anomalous in the "
                  f"answer key; {r['clean_sent_to_a_person']:,} clean invoices were sent to a person.", ""]
    lines += ["| Result made under | Version in force on the invoice's date | Invoices |", "|---|---|---|",
              *[f"| v{x['made_under']} | v{x['in_force']} | {x['invoices']:,} |" for x in r["policy"]["results"]], "",
              f"Results not under the version in force on the invoice's date: {r['policy']['not_under_the_version_in_force']:,}.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", required=True)
    parser.add_argument("--name", required=True, help="results/routing_<name>.json and .md")
    parser.add_argument("--run", type=int, help="the results of this run instead of the latest results")
    args = parser.parse_args()
    conn = db.connect(args.db, read_only=True)
    try:
        result = evaluate(conn, args.run)
    finally:
        conn.close()
    out = ROOT / "results"
    (out / f"routing_{args.name}.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    (out / f"routing_{args.name}.md").write_text(markdown(args.name, result), encoding="utf-8")
    print(markdown(args.name, result))


if __name__ == "__main__":
    main()
