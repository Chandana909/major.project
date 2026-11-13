"""Check an audited ledger against its ground truth: what the audit captured, and whether it is right.

    python -m evaluation.final_check --db <store> [--ledger data/final_seed_2025] [--out results/final_seed_2025]

The store is the one a run of ``start.bat`` made (kept under %LOCALAPPDATA%/auditiq/live), or any store the ledger
was audited into. The ground truth is the ledger's ``labels.csv`` and the rings of its ``manifest.json``, which the
pipeline never reads. The check reports

    score spread   how many different risk scores the ledger produces and how much of it any one value takes;
                   a ledger whose findings all score alike tells nothing, and the check fails on it
    clauses        per rule: labelled, flagged, true and false positives, precision and recall
    invoices       the share whose findings equal the labelled rules exactly, and the hard negatives flagged
    violations     invoices with one, two, three and four labelled violations: their scores and detection
    rings          the planted rings and whether the ring detector found them

and writes ``verification.json`` and ``verification.md``. The deterministic configuration (C1) decides the rules; the
judgement classes (J1 to J4, and the structuring of 4.1.2) need a model, so they are listed apart.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from auditiq import db, rings
from auditiq_bench.taxonomy import CLASSES

ROOT = Path(__file__).resolve().parents[1]
FLAGS = """SELECT r.invoice_id, f.clause FROM v_latest_results r JOIN audit_flags f ON f.result_id = r.result_id
           WHERE COALESCE(f.removal_reason, '') = ''"""
RULE_CLAUSES = sorted({c for k in CLASSES.values() if k.kind == "rule" for c in k.clauses})
JUDGEMENT_CLAUSES = sorted({c for k in CLASSES.values() if k.kind == "judgement" for c in k.clauses})
MAX_SHARE = 0.60            # no single score may take more than this share of the invoices with a finding
MIN_DISTINCT = 8            # and at least this many different scores must occur


def ratio(a: float, b: float) -> float | None:
    return a / b if b else None


def pct(x: float | None) -> str:
    return "–" if x is None else f"{x:.1%}"


def load(conn: db.Database, ledger: Path):
    labels = pd.read_csv(ledger / "labels.csv", dtype=str, keep_default_na=False).set_index("invoice_id")
    results = pd.DataFrame(conn.execute("SELECT invoice_id, rc, risk_level, route FROM v_latest_results").fetchall(),
                           columns=["invoice_id", "score", "level", "route"]).set_index("invoice_id")
    flagged: dict[str, set[str]] = defaultdict(set)
    for invoice_id, clause in conn.execute(FLAGS).fetchall():
        flagged[invoice_id].add(clause)
    return labels, results, flagged


def score_spread(results: pd.DataFrame) -> dict:
    scores = results["score"].round(1)
    flagged = scores[scores > 0]
    counts = Counter(flagged)
    top = counts.most_common(1)[0] if counts else (None, 0)
    bins = pd.cut(scores, bins=[-1, 0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
                  labels=["0", "1–10", "11–20", "21–30", "31–40", "41–50", "51–60", "61–70", "71–80", "81–90", "91–100"])
    return {"invoices": int(len(scores)), "with_finding": int(len(flagged)), "distinct": len(counts),
            "most_common_score": top[0], "most_common_share": ratio(top[1], len(flagged)),
            "histogram": {str(k): int(v) for k, v in bins.value_counts(sort=False).items()},
            "values": {str(k): int(v) for k, v in sorted(counts.items())},
            "levels": results["level"].value_counts().to_dict(), "routes": results["route"].value_counts().to_dict(),
            "passed": len(counts) >= MIN_DISTINCT and (top[1] / len(flagged) if len(flagged) else 1) <= MAX_SHARE}


def clause_table(labels: pd.DataFrame, flagged: dict[str, set[str]], clauses: list[str]) -> list[dict]:
    truth = {i: set(filter(None, c.split("|"))) for i, c in labels["clause_ids"].items()}
    rows = []
    for clause in clauses:
        tp = fp = fn = 0
        for invoice_id in labels.index:
            labelled, found = clause in truth[invoice_id], clause in flagged.get(invoice_id, ())
            tp += labelled and found
            fp += found and not labelled
            fn += labelled and not found
        rows.append({"clause": clause, "labelled": tp + fn, "flagged": tp + fp, "tp": tp, "fp": fp, "fn": fn,
                     "precision": ratio(tp, tp + fp), "recall": ratio(tp, tp + fn)})
    return rows


def invoice_level(labels: pd.DataFrame, results: pd.DataFrame, flagged: dict[str, set[str]]) -> dict:
    rule = set(RULE_CLAUSES)
    exact = total = 0
    for invoice_id, text in labels["clause_ids"].items():
        want = set(filter(None, text.split("|"))) & rule
        if want or flagged.get(invoice_id, set()) & rule:
            total += 1
            exact += want == flagged.get(invoice_id, set()) & rule
    hard = labels.index[labels["label"] == "hard_negative"]
    clean = labels.index[labels["label"] == "clean"]
    hit = lambda ids: sum(bool(flagged.get(i, set()) & rule) for i in ids)          # noqa: E731
    return {"rule_invoices": total, "exact": exact, "exact_share": ratio(exact, total),
            "hard_negatives": len(hard), "hard_negatives_flagged": hit(hard),
            "clean": len(clean), "clean_flagged": hit(clean), "clean_flag_rate": ratio(hit(clean), len(clean))}


def by_violations(labels: pd.DataFrame, results: pd.DataFrame, flagged: dict[str, set[str]]) -> list[dict]:
    rows, anomalous = [], labels[labels["label"] == "anomalous"]
    count = anomalous["clause_ids"].map(lambda s: len(s.split("|")))
    for n in sorted(count.unique()):
        ids = anomalous.index[count == n]
        scores = results.reindex(ids)["score"].dropna()
        rows.append({"violations": int(n), "invoices": len(ids), "mean_score": float(scores.mean()),
                     "min_score": float(scores.min()), "max_score": float(scores.max()),
                     "distinct": int(scores.nunique()), "flagged": sum(bool(flagged.get(i)) for i in ids)})
    return rows


def ring_recovery(conn: db.Database, manifest: dict) -> dict:
    found = rings.find_rings(conn, limit=200)
    groups = [(set(r["vendors"]), set(r["approvers"])) for r in found["rings"]]
    planted = []
    for ring in manifest.get("rings", []):
        vendors, approver = set(ring["vendors"]), ring.get("approver")
        best = max(((len(vendors & v) / len(vendors), approver in a if approver else None) for v, a in groups),
                   default=(0.0, None))
        planted.append({"id": ring["id"], "kind": ring["kind"], "vendors": len(vendors), "approver": approver,
                        "vendors_found": best[0], "approver_found": best[1],
                        "found": best[0] >= 0.75 and best[1] is not False})
    planted_vendors = {v for r in manifest.get("rings", []) for v in r["vendors"]}
    extra = sum(1 for v, _ in groups if not v & planted_vendors)
    return {"detected": found["total_rings"], "planted": planted, "recovered": sum(p["found"] for p in planted),
            "detected_outside_planted": extra}


def render(report: dict, name: str) -> str:
    s, i = report["score_spread"], report["invoices"]
    lines = [f"# Verification of `{name}` against its ground truth", "",
             f"{s['invoices']:,} invoices audited; {s['with_finding']:,} with a finding.", "",
             "## Score spread", "",
             f"{s['distinct']} different risk scores occur among the invoices with a finding; the most common "
             f"({s['most_common_score']}) takes {pct(s['most_common_share'])} of them. The check requires at least "
             f"{MIN_DISTINCT} different scores and no value above {MAX_SHARE:.0%}: **{'passed' if s['passed'] else 'FAILED'}**.",
             "", "| Score | " + " | ".join(s["histogram"]) + " |", "|---|" + "---|" * len(s["histogram"]),
             "| Invoices | " + " | ".join(f"{v:,}" for v in s["histogram"].values()) + " |", "",
             "Risk levels: " + ", ".join(f"{k.lower()} {v:,}" for k, v in s["levels"].items()) + ". Routes: "
             + ", ".join(f"{k} {v:,}" for k, v in s["routes"].items()) + ".", "",
             "## Rules decided by the controls", "",
             "| Clause | Labelled | Flagged | True positive | False positive | Missed | Precision | Recall |",
             "|---|---|---|---|---|---|---|---|"]
    lines += [f"| {r['clause']} | {r['labelled']:,} | {r['flagged']:,} | {r['tp']:,} | {r['fp']:,} | {r['fn']:,} "
              f"| {pct(r['precision'])} | {pct(r['recall'])} |" for r in report["rule_clauses"]]
    lines += ["", f"Invoices with a rule violation (labelled or found): {i['rule_invoices']:,}; their findings equal the "
              f"labelled rules exactly on {pct(i['exact_share'])}. Hard negatives flagged: {i['hard_negatives_flagged']} of "
              f"{i['hard_negatives']}. Ordinary clean invoices flagged: {i['clean_flagged']} of {i['clean']:,} "
              f"({pct(i['clean_flag_rate'])}).", "",
              "## Judgement classes (need a model, C2 to C5)", "",
              "| Clause | Labelled | Flagged by the controls |", "|---|---|---|"]
    lines += [f"| {r['clause']} | {r['labelled']:,} | {r['flagged']:,} |" for r in report["judgement_clauses"]]
    lines += ["", "## By number of labelled violations on the invoice", "",
              "| Violations | Invoices | Flagged | Mean score | Lowest | Highest | Distinct scores |", "|---|---|---|---|---|---|---|"]
    lines += [f"| {r['violations']} | {r['invoices']:,} | {r['flagged']:,} | {r['mean_score']:.1f} | {r['min_score']:.0f} "
              f"| {r['max_score']:.0f} | {r['distinct']} |" for r in report["by_violations"]]
    r = report["rings"]
    lines += ["", "## Planted rings", "",
              f"{r['recovered']} of {len(r['planted'])} planted rings were recovered by the detector; it reports "
              f"{r['detected']} rings in all, {r['detected_outside_planted']} of them without a planted vendor.", "",
              "| Ring | Kind | Vendors | Approver | Vendors found | Approver found | Recovered |", "|---|---|---|---|---|---|---|"]
    lines += [f"| {p['id']} | {p['kind']} | {p['vendors']} | {p['approver'] or ''} | {pct(p['vendors_found'])} "
              f"| {'' if p['approver_found'] is None else ('yes' if p['approver_found'] else 'no')} "
              f"| {'yes' if p['found'] else 'no'} |" for p in r["planted"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", required=True, help="the store the ledger was audited into")
    parser.add_argument("--ledger", default=str(ROOT / "data" / "final_seed_2025"))
    parser.add_argument("--out", help="where verification.json and .md go (default results/<ledger name>)")
    args = parser.parse_args(argv)
    ledger = Path(args.ledger)
    out = Path(args.out) if args.out else ROOT / "results" / ledger.name
    conn = db.connect(args.db)
    labels, results, flagged = load(conn, ledger)
    manifest = json.loads((ledger / "manifest.json").read_text(encoding="utf-8"))
    judgement = clause_table(labels, flagged, JUDGEMENT_CLAUSES)
    report: dict[str, Any] = {"ledger": ledger.name, "score_spread": score_spread(results),
              "rule_clauses": clause_table(labels, flagged, RULE_CLAUSES), "judgement_clauses": judgement,
              "invoices": invoice_level(labels, results, flagged), "by_violations": by_violations(labels, results, flagged),
              "rings": ring_recovery(conn, manifest)}
    out.mkdir(parents=True, exist_ok=True)
    (out / "verification.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    text = render(report, ledger.name)
    (out / "verification.md").write_text(text, encoding="utf-8")
    print(text.encode("ascii", "replace").decode() if sys.stdout.encoding != "utf-8" else text)
    conn.close()
    return 0 if report["score_spread"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
