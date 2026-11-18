"""The audit of a labelled ledger judged as an audit team would judge it: workload, money, ranking and repeatability.

    python -m evaluation.industry --db <store> [--c0 <dir of C0-IF.jsonl, C0-SVM.jsonl>] [--name final_seed_2025]

``evaluation.final_check`` asks whether each rule is decided right. This asks what the audit means for the people who
run it, from the store's latest results and the answer key in ``benchmark_labels`` (which the pipeline never reads):

    workload     how many invoices, and how much of the spend, go to a person; how many of those are anomalous
    money        the share of the anomalous spend that reaches a person
    missed       the anomalous invoices approved without a person, by class, and why (no finding, or a finding
                 whose score routes it to approval)
    ranking      how well the risk score orders the ledger for a reviewer with a fixed budget: precision in the
                 top k, average precision and ROC AUC, next to the classical detectors of ``evaluation.run_c0`` when
                 their predictions are given (theirs are out-of-fold scores; the controls use no label at all)
    hard negatives  the near-miss invoices sent to a person, by type
    repeatability   whether the last two complete C1 runs in the store agree on every invoice
    latency      the API's answer times on this store (first request, then the median and 95th percentile of 20)
    Benford      the first-digit test of the ledger's amounts
    sealed record   the seals of results, trail entries and runs verified (auditiq/seal.py), and how long it took
    leads        the invoices listed under the judgement rules 2.2.2 and 4.1.2 (auditiq/leads.py), against the key
    sampling     a monetary-unit sample of the approved invoices (auditiq/sampling.py) from 1,000 random starts:
                 how often its upper limit covers the true anomalous amount, and how often it supports reliance,
                 as approved and with the anomalous invoices removed

Writes ``industry.json`` and ``industry.md`` into ``--out`` (default results/<name>/). Nothing is audited.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score

from auditiq import analytics, audit_program, db, leads, reliability, sampling, seal, workpapers

ROOT = Path(__file__).resolve().parents[1]
BUDGETS = (100, 250, 500, 1000, 2000)
ENDPOINTS = ("/api/overview", "/api/queue", "/api/risk-map", "/api/analytics", "/api/rings", "/api/case-graph",
             "/api/invoices?q=INV41", "/api/policy", "/api/leads", "/api/sampling?seed=1", "/api/trail/verify")
TO_A_PERSON = ("escalate", "sample")


def share(a: float, b: float) -> float | None:
    return round(a / b, 4) if b else None


def pct(x: float | None) -> str:
    return "–" if x is None else f"{x:.1%}"


def money(x: float) -> str:
    return f"₹{x:,.0f}"


def expected_precision_at(scores: np.ndarray, positive: np.ndarray, k: int) -> float:
    """Precision of the k highest scores, with ties broken at random: the tied group that straddles k contributes
    its mean, so a score with few distinct values is not credited with an ordering it does not have."""
    k = min(k, len(scores))
    order = np.argsort(-scores, kind="stable")
    s, p = scores[order], positive[order].astype(float)
    cut = s[k - 1]
    above = s > cut
    tied = s == cut
    taken = int(above.sum())
    hits = p[above].sum() + (k - taken) * p[tied].mean()
    return float(hits / k)


def ranking(scores: np.ndarray, positive: np.ndarray) -> dict:
    return {"average_precision": round(float(average_precision_score(positive, scores)), 4),
            "roc_auc": round(float(roc_auc_score(positive, scores)), 4),
            "distinct_scores": int(len(np.unique(scores))),
            "precision_at": {str(k): round(expected_precision_at(scores, positive, k), 4) for k in BUDGETS}}


def latest(conn: db.Database):
    return conn.execute(
        "SELECT l.invoice_id, l.route, l.rc, l.flag_count, l.risk_level, i.amount, b.label, b.class_id, "
        "b.hard_negative_type FROM v_latest_results l JOIN invoices i ON i.invoice_id = l.invoice_id "
        "JOIN benchmark_labels b ON b.invoice_id = l.invoice_id ORDER BY l.invoice_id").fetchall()


def repeatability(conn: db.Database) -> dict | None:
    """The last two C1 runs that each audited the whole ledger, compared invoice by invoice."""
    n = conn.scalar("SELECT COUNT(*) FROM invoices")
    runs = [r[0] for r in conn.execute(
        "SELECT u.run_id FROM audit_runs u JOIN audit_results r ON r.run_id = u.run_id WHERE u.configuration = 'C1' "
        "GROUP BY u.run_id HAVING COUNT(*) = ? ORDER BY u.run_id DESC LIMIT 2", (n,))]
    if len(runs) < 2:
        return None

    def of(run_id: int) -> dict:
        found: dict[str, list] = {}
        for invoice_id, route, rc, level, clause, status in conn.execute(
                "SELECT r.invoice_id, r.route, r.rc, r.risk_level, f.clause, f.status FROM audit_results r "
                "LEFT JOIN audit_flags f ON f.result_id = r.result_id WHERE r.run_id = ?", (run_id,)):
            entry = found.setdefault(invoice_id, [route, rc, level, []])
            if clause is not None:
                entry[3].append((clause, status))
        return {i: (e[0], e[1], e[2], tuple(sorted(e[3]))) for i, e in found.items()}

    a, b = of(runs[1]), of(runs[0])
    differ = sorted(i for i in a if a[i] != b.get(i))
    return {"runs": [runs[1], runs[0]], "invoices": len(a), "differ": len(differ), "examples": differ[:5]}


def latency(target: str) -> list[dict]:
    from fastapi.testclient import TestClient

    from auditiq.api import create_app
    client = TestClient(create_app(target, token="", frontend=None))
    out = []
    for path in ENDPOINTS:
        times, status = [], None
        for _ in range(21):
            start = time.perf_counter()
            reply = client.get(path, headers={"Accept-Encoding": "gzip"})
            times.append((time.perf_counter() - start) * 1000)
            status = reply.status_code
        warm = np.array(times[1:])
        out.append({"endpoint": path, "status": status, "first_ms": round(times[0], 1),
                    "median_ms": round(float(np.median(warm)), 1), "p95_ms": round(float(np.percentile(warm, 95)), 1),
                    "bytes_on_the_wire": int(reply.headers.get("content-length", len(reply.content)))})
    return out


def evaluate(conn: db.Database, target: str, c0: Path | None) -> dict:
    rows = latest(conn)
    labels = Counter(r["label"] for r in rows)
    anomalous = [r for r in rows if r["label"] == "anomalous"]
    sent = [r for r in rows if r["route"] in TO_A_PERSON]
    spend = sum(r["amount"] or 0 for r in rows)
    bad_spend = sum(r["amount"] or 0 for r in anomalous)
    caught = [r for r in anomalous if r["route"] in TO_A_PERSON]
    missed = [r for r in anomalous if r["route"] not in TO_A_PERSON]
    out: dict = {
        "dataset": conn.scalar("SELECT value FROM meta WHERE key = 'dataset'"),
        "invoices": len(rows), "labels": dict(labels),
        "workload": {"to_a_person": len(sent), "to_a_person_share": share(len(sent), len(rows)),
                     "spend_to_a_person_share": share(sum(r["amount"] or 0 for r in sent), spend),
                     "anomalous_among_them": sum(r["label"] == "anomalous" for r in sent),
                     "queue_precision": share(sum(r["label"] == "anomalous" for r in sent), len(sent)),
                     "clean_to_a_person": sum(r["label"] == "clean" for r in sent),
                     "hard_negative_to_a_person": sum(r["label"] == "hard_negative" for r in sent)},
        "money": {"spend": round(spend, 2), "anomalous_spend": round(bad_spend, 2),
                  "anomalous_spend_to_a_person": round(sum(r["amount"] or 0 for r in caught), 2),
                  "anomalous_spend_to_a_person_share": share(sum(r["amount"] or 0 for r in caught), bad_spend),
                  "invoice_recall": share(len(caught), len(anomalous))},
    }
    by_class: dict[str, Counter] = {}
    for r in anomalous:
        c = by_class.setdefault(r["class_id"] or "?", Counter())
        c["labelled"] += 1
        c["to_a_person"] += r["route"] in TO_A_PERSON
        if r["route"] not in TO_A_PERSON:
            c["approved_no_finding" if not r["flag_count"] else "approved_with_finding"] += 1
    out["by_class"] = {k: dict(v) for k, v in sorted(by_class.items(), key=lambda kv: (kv[0][0], int(kv[0][1:] or 0)))}
    out["missed"] = {"approved_no_finding": sum(not r["flag_count"] for r in missed),
                     "approved_with_finding": sum(bool(r["flag_count"]) for r in missed),
                     "levels_of_approved_with_finding": dict(Counter(r["risk_level"] for r in missed if r["flag_count"]))}
    hn = Counter(r["hard_negative_type"] for r in rows if r["label"] == "hard_negative")
    hn_sent = Counter(r["hard_negative_type"] for r in sent if r["label"] == "hard_negative")
    out["hard_negatives"] = {t: {"invoices": n, "to_a_person": hn_sent[t]} for t, n in sorted(hn.items())}

    positive = np.array([r["label"] == "anomalous" for r in rows])
    ids = [r["invoice_id"] for r in rows]
    out["ranking"] = {"C1 risk score": ranking(np.array([float(r["rc"] or 0) for r in rows]), positive)}
    for name in ("C0-IF", "C0-SVM"):
        path = c0 / f"{name}.jsonl" if c0 else None
        if path and path.exists():
            scores = {}
            for line in path.read_text(encoding="utf-8").splitlines():
                p = json.loads(line)
                scores[p["invoice_id"]] = p["score"]
            out["ranking"][name] = ranking(np.array([scores[i] for i in ids]), positive)
    out["repeatability"] = repeatability(conn)
    out["benford_first_digit"] = {k: v for k, v in analytics.ledger_analytics(conn)["benford"]["first"].items()
                                  if k in ("mad", "conformity", "chi2", "dof")}
    out["sealed_record"] = sealed_record(conn)
    out["leads"] = judgement_leads(conn)
    out["sampling"] = monetary_unit_sampling(conn)
    out["reliability"] = data_reliability(conn)
    out["program"] = program_against_key(conn)
    out["workpapers"] = working_papers(conn)
    out["latency"] = latency(target)
    return out


def data_reliability(conn: db.Database) -> dict:
    start = time.perf_counter()
    found = reliability.ledger_reliability(conn)
    return {"seconds": round(time.perf_counter() - start, 2), "summary": found["summary"],
            "exceptions": {c["id"]: c["exceptions"] for c in found["checks"] if c["exceptions"]},
            "fingerprint": found["fingerprint"]["ledger"]}


def program_against_key(conn: db.Database) -> dict:
    found = audit_program.program(conn, leads=leads.judgement_leads(conn))
    return {"untested": found["untested"], "schemes": (found["answer_key"] or {}).get("schemes", {})}


def working_papers(conn: db.Database) -> dict:
    """The working papers built twice from the same store: the time it takes, and whether the digest repeats."""
    start = time.perf_counter()
    first = workpapers.engagement(conn)
    seconds = time.perf_counter() - start
    again = workpapers.engagement(conn)
    return {"seconds": round(seconds, 1), "digest": first["digest"], "repeats": first["digest"] == again["digest"],
            "seed": first["seed"], "findings": len(first["data"]["findings"]), "queue": len(first["data"]["queue"]),
            "bytes": len(workpapers.to_xlsx(first))}


def sealed_record(conn: db.Database) -> dict:
    """The seals of the store verified, with the time it took, and the evidence of the latest results re-performed."""
    start = time.perf_counter()
    report = seal.verify(conn)
    seconds = time.perf_counter() - start
    start = time.perf_counter()
    drift = seal.evidence_drift(conn)
    return {**report, "seconds": round(seconds, 2), "digest": seal.run_digest(conn),
            "evidence": {k: drift[k] for k in ("fingerprinted", "unchanged", "changed", "without_fingerprint")},
            "evidence_seconds": round(time.perf_counter() - start, 2)}


def judgement_leads(conn: db.Database) -> dict:
    found = leads.judgement_leads(conn)
    return {"near_duplicates": {k: found["near_duplicates"][k] for k in ("invoices", "amount", "approved")},
            "structuring": {k: found["structuring"][k] for k in ("count", "invoices", "amount", "approved")},
            "answer_key": found["answer_key"]}


def monetary_unit_sampling(conn: db.Database, starts: int = 1000) -> dict | None:
    """A monetary-unit sample of the approved invoices at 95 % and a tolerable 2 %, drawn from ``starts`` random
    starts and examined with the answer key; and the same plan on the approved invoices without the anomalous ones, to
    show that the bound supports reliance when the approval is right."""
    items = sampling.population(conn)
    truth = sampling._answer_key_misstatement(conn)
    if not items or truth is None:
        return None
    amounts = np.array([a for _, a, *_ in items])
    misstated = np.array([truth.get(i[0], 0.0) for i in items])
    the_plan = sampling.plan(float(amounts.sum()), len(items), confidence=0.95, tolerable_pct=2.0)
    clean = misstated == 0
    clean_plan = sampling.plan(float(amounts[clean].sum()), int(clean.sum()), confidence=0.95, tolerable_pct=2.0)
    return {"plan": the_plan, "as_approved": sampling.repeated(amounts, misstated, the_plan, starts=starts),
            "anomalies_removed": sampling.repeated(amounts[clean], misstated[clean], clean_plan, starts=starts)}


def markdown(r: dict) -> str:
    w, m = r["workload"], r["money"]
    lines = [f"# `{r['dataset']}` from the auditors' side", "",
             "Source: `python -m evaluation.industry` on a store audited with C1 (controls only). The answer key is the "
             "ledger's labels, which the audit never reads. Numbers are counts of the store's latest results.", "",
             "## Workload and outcome", "",
             f"{r['invoices']:,} invoices ({', '.join(f'{v:,} {k}' for k, v in sorted(r['labels'].items()))}).", "",
             "| Measure | Value |", "|---|---|",
             f"| Invoices sent to a person | {w['to_a_person']:,} ({pct(w['to_a_person_share'])}) |",
             f"| Share of the spend sent to a person | {pct(w['spend_to_a_person_share'])} |",
             f"| Of those, anomalous (queue precision) | {w['anomalous_among_them']:,} ({pct(w['queue_precision'])}) |",
             f"| Clean invoices sent to a person | {w['clean_to_a_person']:,} |",
             f"| Hard negatives sent to a person | {w['hard_negative_to_a_person']:,} |",
             f"| Anomalous invoices sent to a person (recall) | {pct(m['invoice_recall'])} |",
             f"| Anomalous spend | {money(m['anomalous_spend'])} of {money(m['spend'])} |",
             f"| Anomalous spend sent to a person | {money(m['anomalous_spend_to_a_person'])} "
             f"({pct(m['anomalous_spend_to_a_person_share'])}) |", "",
             "## Anomalous invoices by class", "",
             "| Class | Labelled | Sent to a person | Approved, no finding | Approved with a finding |", "|---|---|---|---|---|",
             *[f"| {k} | {v.get('labelled', 0):,} | {v.get('to_a_person', 0):,} | {v.get('approved_no_finding', 0):,} | "
               f"{v.get('approved_with_finding', 0):,} |" for k, v in r["by_class"].items()], "",
             f"Approved without a person: {r['missed']['approved_no_finding']:,} with no finding (the judgement classes "
             f"J1 to J4 need a model; C1 runs none) and {r['missed']['approved_with_finding']:,} with a finding whose score "
             f"routes it to approval (risk levels {r['missed']['levels_of_approved_with_finding']}).", "",
             "## Ranking for a review budget", "",
             "Precision in the top k is the expected value with ties broken at random. C0 scores are out-of-fold "
             "(each invoice scored by a threshold fitted without its label); the C1 score uses no label at all.", "",
             "| Ranker | Distinct scores | Average precision | ROC AUC | " + " | ".join(f"P@{k}" for k in BUDGETS) + " |",
             "|---|---|---|---|" + "---|" * len(BUDGETS),
             *[f"| {name} | {x['distinct_scores']:,} | {x['average_precision']:.3f} | {x['roc_auc']:.3f} | "
               + " | ".join(pct(x["precision_at"][str(k)]) for k in BUDGETS) + " |" for name, x in r["ranking"].items()],
             "", "## Hard negatives (near misses that break no rule)", "",
             "| Type | Invoices | Sent to a person |", "|---|---|---|",
             *[f"| {t} | {v['invoices']} | {v['to_a_person']} |" for t, v in r["hard_negatives"].items()], ""]
    rep = r["repeatability"]
    lines += ["## Repeatability", "",
              (f"Runs {rep['runs'][0]} and {rep['runs'][1]} (C1, every invoice): {rep['differ']:,} of {rep['invoices']:,} "
               "invoices differ in route, score, risk level or findings." if rep else
               "Fewer than two complete C1 runs in the store: not checked."), "",
              "## Benford's law, first digit", "",
              f"MAD {r['benford_first_digit']['mad']:.4f}: {r['benford_first_digit']['conformity']} "
              f"(chi-square {r['benford_first_digit']['chi2']:.1f}, {r['benford_first_digit']['dof']} degrees of freedom).", ""]
    s = r["sealed_record"]
    lines += ["## The sealed record", "",
              f"`auditiq/seal.py`, verified in {s['seconds']:.1f} s: **{'intact' if s['intact'] else 'ALTERED'}**. Results: "
              f"{s['results']['sealed']:,} sealed and intact, {s['results']['altered']:,} altered, "
              f"{s['results']['unsealed']:,} stored before sealing. Trail entries: {s['entries']['checked']:,}, "
              f"{s['entries']['broken']:,} broken. Runs: {s['runs']['sealed']:,} sealed, {s['runs']['altered']:,} altered, "
              f"{s['runs']['unsealed']:,} finished before sealing. Digest of the sealed runs: `{s['digest']}`.", "",
              f"Evidence re-performed in {s['evidence_seconds']:.1f} s: of {s['evidence']['fingerprinted']:,} latest "
              f"results with an evidence fingerprint, {s['evidence']['unchanged']:,} still match the ledger and "
              f"{s['evidence']['changed']:,} were based on records changed since; "
              f"{s['evidence']['without_fingerprint']:,} were stored before evidence was fingerprinted.", ""]
    rl = r["reliability"]
    lines += ["## Data reliability of the ledger (ISA 500)", "",
              f"`auditiq/reliability.py`, {rl['seconds']:.1f} s: {rl['summary']['without_exceptions']} of "
              f"{rl['summary']['checks']} checks without exceptions; "
              f"{'reliable' if rl['summary']['reliable'] else 'NOT reliable'}: {rl['summary']['conclusion']}. "
              f"Exceptions: {', '.join(f'{k} {v:,}' for k, v in rl['exceptions'].items()) or 'none'}. "
              f"Ledger fingerprint `{rl['fingerprint']}`.", ""]
    pg = r["program"]
    lines += ["## Fraud schemes against the answer key (`auditiq/audit_program.py`)", "",
              "A labelled invoice counts for a scheme when a kept finding (or a lead) names a rule that addresses "
              "that scheme. Which rule addresses which scheme is the program's written judgement.", "",
              "| Scheme | Labelled | Found by a rule | Listed by a lead only | Missed | Reached |", "|---|---|---|---|---|---|",
              *[f"| {s} | {v['labelled']:,} | {v['found']:,} | {v['lead_only']:,} | {v['missed']:,} | {pct(v['reached'])} |"
                for s, v in pg["schemes"].items()], "",
              f"Untested: assertions {', '.join(pg['untested']['assertions']) or 'none'}; schemes "
              f"{', '.join(pg['untested']['schemes']) or 'none'}.", ""]
    wp = r["workpapers"]
    lines += ["## Working papers (`auditiq/workpapers.py`)", "",
              f"Built in {wp['seconds']:.1f} s ({wp['bytes']:,} bytes as a workbook): {wp['findings']:,} findings, "
              f"{wp['queue']:,} invoices waiting for review, sample seed {wp['seed']} (from the digest of the sealed "
              f"runs). Built twice from the same store, the report digest {'repeats' if wp['repeats'] else 'DIFFERS'}: "
              f"`{wp['digest']}`.", ""]
    ld = r["leads"]
    lines += ["## Leads under the judgement rules (2.2.2, 4.1.2)", "",
              "`auditiq/leads.py`: invoices listed for a reviewer, with the policy's guide values; not findings. "
              "Held-out ledgers: `results/leads/leads.md`.", "",
              "| Rule | Listed invoices | Amount | Approved without a person | Labelled | Recall | Precision | Listed otherwise |",
              "|---|---|---|---|---|---|---|---|"]
    for clause, key in (("2.2.2", "near_duplicates"), ("4.1.2", "structuring")):
        k = (ld["answer_key"] or {}).get(clause) or {}
        lines.append(f"| {clause} | {ld[key]['invoices']:,} | {money(ld[key]['amount'])} | {ld[key]['approved']:,} | "
                     f"{k.get('labelled', '–')} | {pct(k.get('recall'))} | {pct(k.get('precision'))} | "
                     f"{', '.join(f'{a} {b}' for a, b in (k.get('listed_otherwise') or {}).items()) or 'none'} |")
    lines.append("")
    mus = r["sampling"]
    if mus:
        p, a, c = mus["plan"], mus["as_approved"], mus["anomalies_removed"]
        lines += ["## Monetary-unit sampling of the approved invoices (ISA 530)", "",
                  f"`auditiq/sampling.py`: {p['items']:,} invoices approved without a person, {money(p['book_value'])}; "
                  f"95 % confidence, tolerable misstatement 2 % ({money(p['tolerable'])}), no expected misstatement: "
                  f"sample of {p['size']}, interval {money(p['interval'])}. The answer key stands in for the examination "
                  f"(an anomalous invoice misstated in full), over {a['starts']:,} random starts.", "",
                  "| Population | True misstatement | Upper limit covers it | Upper limit within tolerable (reliance) | "
                  "Misstatements found per sample | Median upper limit |", "|---|---|---|---|---|---|",
                  f"| As approved | {money(a['true_misstatement'])} | {pct(a['bound_holds_share'])} | "
                  f"{pct(a['within_tolerable_share'])} | {a['misstatements_found_mean']:.2f} "
                  f"({a['misstatements_found_range'][0]} to {a['misstatements_found_range'][1]}) | "
                  f"{money(a['upper_limit_median'])} |",
                  f"| Anomalous invoices removed | {money(c['true_misstatement'])} | {pct(c['bound_holds_share'])} | "
                  f"{pct(c['within_tolerable_share'])} | {c['misstatements_found_mean']:.2f} | "
                  f"{money(c['upper_limit_median'])} |", "",
                  "The approved population holds more anomalous money than the tolerable misstatement, so an auditor "
                  "should not rely on the approval, and the sample says so in the share of draws in the fourth column; "
                  "with the anomalies removed it supports reliance.", ""]
    lines += [
              "## API answer times on this store", "",
              "In-process (FastAPI test client, no network), gzip accepted; the store's analyses are cached until it "
              "changes, so the first request computes and the others read the cache.", "",
              "| Endpoint | Status | First (ms) | Median (ms) | 95th percentile (ms) | Bytes on the wire |", "|---|---|---|---|---|---|",
              *[f"| `{x['endpoint']}` | {x['status']} | {x['first_ms']:,.0f} | {x['median_ms']:,.1f} | {x['p95_ms']:,.1f} | "
                f"{x['bytes_on_the_wire']:,} |" for x in r["latency"]], ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--c0", type=Path, help="folder with C0-IF.jsonl and C0-SVM.jsonl of the same ledger")
    ap.add_argument("--name", default="final_seed_2025")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    os.environ.setdefault("AUDITIQ_NO_DOTENV", "1")
    conn = db.connect(args.db, read_only=True)
    try:
        report = evaluate(conn, args.db, args.c0)
    finally:
        conn.close()
    out = args.out or ROOT / "results" / args.name
    out.mkdir(parents=True, exist_ok=True)
    (out / "industry.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "industry.md").write_text(markdown(report), encoding="utf-8")
    print(f"wrote {out / 'industry.md'}")


if __name__ == "__main__":
    main()
