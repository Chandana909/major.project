"""Evaluate retrieval over the audit graph on questions about the ledger, against policy-only retrieval.

    python -m evaluation.case_graph_eval --db <store> [--ledger data/final_seed_2025]

The store is one a run of ``start.bat`` made (the ledger audited by the controls, configuration C1, under the policy
the answer key was written for). Every expected answer is computed from the ledger's files, never from the audit:
the labels (``labels.csv``), the vendor master, the approval log and the planted rings of ``manifest.json``. A
retrieval is judged on what it hands the reader, as the policy-graph evaluation does: the facts the graph computes
from the audit, against the facts and passages that policy retrieval (the graph of the policy and the ranker over
the policy documents) gives for the same question.

Question types, with how each is judged
    invoice     "why was INV... flagged?"            the set of rules the facts cite for the invoice equals the labelled rules
    vendor      "how many invoices of X have findings?"   the count the facts state equals the count in the labels
    approver    "how many approvals above own limit did X make?"   the count equals the one computed from the approval log
    rule        "how many invoices break rule R?"    the count equals the one in the labels
    rings       "which approvers are in collusion rings?"   share of the planted approvers the facts name (recall)
    members     "which vendors are in the ring around X?"   share of the planted ring's vendors the facts name (recall)
    identity    "which vendors share the same PAN?"  share of the planted shell vendors the facts name (recall)
    blocked     "which blacklisted vendors billed most?"   share of the five largest blocked vendors the facts name (recall)

Policy-only retrieval counts as right when the expected rules, names or number appear in the text it gives; it has
no way to compute a count or know a vendor, so this is generous to it.

Honesty about the method: the recognisers of ``auditiq/case_graph.py`` were built looking at six questions (why was
INV53478 flagged; which approvers approved the most invoices above their own limit; which fraudulent vendors are
blacklisted; which vendors share the same PAN; which vendors have number mismatches; what do we know about an
approver). The questions here name other invoices, vendors and approvers, drawn at random (``--seed``), in wordings
written before the run. Nothing was changed after seeing the result; failures are listed.
"""
from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter
from pathlib import Path

import pandas as pd

from auditiq import db
from auditiq.case_graph import CaseGraph
from auditiq.policy_graph import PolicyGraph
from auditiq.retrieval import PolicyIndex
from auditiq_bench.taxonomy import CLASSES

ROOT = Path(__file__).resolve().parents[1]
RULE_CLAUSES = {c for k in CLASSES.values() if k.kind == "rule" for c in k.clauses}

INVOICE_TEMPLATES = ["Why was {x} flagged?", "What is wrong with invoice {x}?", "Explain the findings on {x}.",
                     "Which rules does {x} break and why?"]
VENDOR_TEMPLATES = ["How many invoices of {x} carry findings?", "How many of the invoices from {x} were flagged?"]
APPROVER_TEMPLATES = ["How many approvals above their own limit did {x} make?",
                      "Has {x} approved invoices over their limit, and how many?"]
RULE_EXPLICIT = "How many invoices break rule {x}?"
RULE_EVERYDAY = {"5.1.1": "How many invoices were approved above the approver's limit?",
                 "4.4.1": "How many invoices came from blacklisted vendors?",
                 "2.2.1": "How many exact duplicate invoices are there?",
                 "4.2.1": "How many invoices are dated on a weekend?",
                 "4.3.1": "How many invoices have a round amount?",
                 "4.1.1": "How many invoices were split on the same day?"}
RINGS_QUESTIONS = ["Which approvers are involved in collusion rings?", "Which approvers belong to rings with vendors?"]
IDENTITY_QUESTIONS = ["Which vendors share the same PAN?", "Which vendor records are registered twice?"]
BLOCKED_QUESTIONS = ["Which blacklisted vendors billed the most?", "Which fraudulent vendors, blocked or blacklisted, have the largest invoices?"]


def truth(ledger: Path) -> dict:
    """What the ledger's files say, computed without the audit."""
    labels = pd.read_csv(ledger / "labels.csv", dtype=str, keep_default_na=False).set_index("invoice_id")
    invoices = pd.read_csv(ledger / "invoices.csv", dtype=str, keep_default_na=False).set_index("invoice_id")
    logs = pd.read_csv(ledger / "approval_logs.csv", dtype=str, keep_default_na=False)
    vendors = pd.read_csv(ledger / "vendor_master.csv", dtype=str, keep_default_na=False).set_index("vendor_id")
    manifest = json.loads((ledger / "manifest.json").read_text(encoding="utf-8"))
    rules = {i: set(filter(None, c.split("|"))) & RULE_CLAUSES for i, c in labels["clause_ids"].items()}
    approved = logs[logs["action_taken"] == "Approved"].sort_values(["timestamp", "log_id"]).groupby("transaction_id").last()
    over: Counter = Counter()
    for invoice_id, row in approved.iterrows():
        if invoice_id in invoices.index and float(invoices.at[invoice_id, "amount"]) > float(row["amount_limit"]):
            over[row["approver_name"]] += 1
    amount = invoices["amount"].astype(float)
    per_vendor_flagged = Counter(invoices.at[i, "vendor_id"] for i, r in rules.items() if r)
    per_vendor_amount = amount.groupby(invoices["vendor_id"]).sum()
    blocked = [v for v, row in vendors.iterrows() if row["blacklisted"] == "True" or row["gstin_status"] != "Active"]
    top_blocked = sorted(blocked, key=lambda v: -per_vendor_amount.get(v, 0.0))[:5]
    rule_counts = Counter(c for r in rules.values() for c in r)
    return {"labels": labels, "rules": rules, "invoices": invoices, "vendors": vendors, "over": over,
            "vendor_flagged": per_vendor_flagged, "rule_counts": rule_counts, "approved": approved,
            "rings": manifest["rings"], "top_blocked": top_blocked}


def questions(t: dict, rng: random.Random) -> list[dict]:
    """The question set: types, wordings and entities drawn with ``rng``."""
    out: list[dict] = []
    flagged = [i for i, r in t["rules"].items() if r]
    multi = [i for i in flagged if len(t["rules"][i]) >= 2]
    single = [i for i in flagged if len(t["rules"][i]) == 1]
    for n, i in enumerate(rng.sample(multi, 12) + rng.sample(single, 8)):
        out.append({"type": "invoice", "q": INVOICE_TEMPLATES[n % 4].format(x=i), "invoice": i, "expected": sorted(t["rules"][i])})
    vendors = rng.sample(sorted(t["vendor_flagged"]), 14)
    for n, v in enumerate(vendors):
        out.append({"type": "vendor", "q": VENDOR_TEMPLATES[n % 2].format(x=t["vendors"].at[v, "vendor_name"]), "vendor": v,
                    "expected": t["vendor_flagged"][v]})
    for n, name in enumerate(rng.sample(sorted(t["over"]), min(14, len(t["over"])))):
        out.append({"type": "approver", "q": APPROVER_TEMPLATES[n % 2].format(x=name), "approver": name, "expected": t["over"][name]})
    for clause in sorted(t["rule_counts"]):
        if clause in RULE_EVERYDAY:
            out.append({"type": "rule", "q": RULE_EVERYDAY[clause], "clause": clause, "expected": t["rule_counts"][clause], "wording": "everyday"})
        out.append({"type": "rule", "q": RULE_EXPLICIT.format(x=clause), "clause": clause, "expected": t["rule_counts"][clause], "wording": "rule number"})
    approver_rings = [r for r in t["rings"] if r["kind"] == "approver"]
    for q in RINGS_QUESTIONS:
        out.append({"type": "rings", "q": q, "expected": sorted(r["approver"] for r in approver_rings)})
    for r in approver_rings:
        out.append({"type": "members", "q": f"Which vendors are in the ring around {r['approver']}?", "approver": r["approver"],
                    "expected": sorted(r["vendors"])})
    shell = sorted({v for r in t["rings"] if r["kind"] == "identity" for v in r["vendors"]})
    for q in IDENTITY_QUESTIONS:
        out.append({"type": "identity", "q": q, "expected": shell})
    for q in BLOCKED_QUESTIONS:
        out.append({"type": "blocked", "q": q, "expected": sorted(t["top_blocked"])})
    return out


def number_in(text: str, n: int) -> bool:
    return re.search(rf"(?<![\d,.]){n}(?![\d,])", text) is not None


def judge_case(item: dict, answer, names: dict[str, str]) -> dict:
    """The result of the audit graph for one question: what it states, and whether that is right."""
    facts = answer.facts
    union = lambda key: {x for f in facts for x in f.data.get(key, [])}           # noqa: E731
    kind = item["type"]
    if kind == "invoice":
        got = next((set(f.data["rules"]) for f in facts if f.data.get("invoices") == [item["invoice"]]), None)
        want = set(item["expected"])
        return {"ok": got == want, "complete": got is not None and want <= got, "got": sorted(got) if got is not None else None}
    if kind == "vendor":
        got = next((f.data["flagged"] for f in facts if f.kind == "vendor" and f.data["vendors"][0] == item["vendor"]), None)
        return {"ok": got == item["expected"], "got": got}
    if kind == "approver":
        got = next((f.data["over_limit"] for f in facts if f.kind == "approver" and f.data["approvers"] == [item["approver"]]), None)
        return {"ok": got == item["expected"], "got": got}
    if kind == "rule":
        got = next((f.data["flagged"] for f in facts if f.kind == "rule" and f.clause == item["clause"]), None)
        return {"ok": got == item["expected"], "got": got}
    if kind == "members":
        # The vendors the facts attribute to this approver: its own tested links, in the approver's fact and in the
        # ring's (which says whose vendors are whose when a ring joins several approvers).
        found = {v for f in facts if f.kind in ("ring", "approver") and item["approver"] in f.data.get("approvers", [])
                 for v in (f.data["by_approver"][item["approver"]] if "by_approver" in f.data else f.data.get("vendors", []))}
    else:
        found = union("approvers") if kind == "rings" else union("vendors")
    want = set(item["expected"])
    recall = len(want & found) / len(want) if want else 1.0
    precision = len(want & found) / len(found) if found else 0.0
    return {"ok": want <= found, "recall": recall, "precision": precision, "named": len(found), "missed": sorted(want - found)}


def judge_policy(item: dict, text: str, names: dict[str, str]) -> dict:
    """Policy-only retrieval: right when the expected rules, names or number appear in what it gives."""
    kind = item["type"]
    if kind == "invoice":
        found = {c for c in item["expected"] if re.search(rf"(?<![\d.]){re.escape(c)}(?![\d.]*\d)", text)}
        return {"ok": found == set(item["expected"]) and item["invoice"] in text}
    if kind in ("vendor", "approver", "rule"):
        entity = item.get("vendor") or item.get("approver")
        named = (names.get(entity, entity) in text) if entity else True
        return {"ok": named and number_in(text, item["expected"])}
    want = set(item["expected"])
    found = {x for x in want if x in text or names.get(x, x) in text}
    return {"ok": want <= found, "recall": len(found) / len(want) if want else 1.0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", required=True, help="the store the ledger was audited into")
    parser.add_argument("--ledger", type=Path, default=ROOT / "data" / "final_seed_2025")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "case_graph")
    args = parser.parse_args(argv)

    t = truth(args.ledger)
    names = {v: row["vendor_name"] for v, row in t["vendors"].iterrows()}
    items = questions(t, random.Random(args.seed))
    conn = db.connect(args.db)
    cases, policy, index = CaseGraph.from_db(conn), PolicyGraph.from_db(conn), PolicyIndex.from_db(conn)
    rows = []
    for item in items:
        answer = cases.query(item["q"])
        linked = policy.query(item["q"], index)
        context = "\n".join([f.text for f in linked.facts] + [h.text for h in linked.passages]
                            + [h.text for h in index.search(item["q"], k=5)])
        ours, base = judge_case(item, answer, names), judge_policy(item, context, names)
        rows.append({**{k: v for k, v in item.items() if k != "expected"}, "expected": item["expected"],
                     "audit_graph": ours, "policy_only": base, "facts": len(answer.facts)})
    conn.close()

    summary = {}
    for kind in dict.fromkeys(r["type"] for r in rows):
        group = [r for r in rows if r["type"] == kind]
        entry = {"questions": len(group), "audit_graph_right": sum(r["audit_graph"]["ok"] for r in group),
                 "policy_only_right": sum(r["policy_only"]["ok"] for r in group)}
        if kind == "invoice":
            entry["audit_graph_complete"] = sum(r["audit_graph"]["complete"] for r in group)
        if "recall" in group[0]["audit_graph"]:
            entry["audit_graph_mean_recall"] = sum(r["audit_graph"]["recall"] for r in group) / len(group)
            entry["audit_graph_mean_precision"] = sum(r["audit_graph"]["precision"] for r in group) / len(group)
            entry["audit_graph_mean_named"] = sum(r["audit_graph"]["named"] for r in group) / len(group)
            entry["expected_size"] = sum(len(r["expected"]) for r in group) / len(group)
            entry["policy_only_mean_recall"] = sum(r["policy_only"]["recall"] for r in group) / len(group)
        summary[kind] = entry
    total = {"questions": len(rows), "audit_graph_right": sum(r["audit_graph"]["ok"] for r in rows),
             "policy_only_right": sum(r["policy_only"]["ok"] for r in rows)}
    result = {"ledger": args.ledger.name, "seed": args.seed, "summary": summary, "total": total, "rows": rows}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "case_graph_eval.json").write_text(json.dumps(result, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")
    lines = [f"# Audit graph retrieval on `{args.ledger.name}`", "",
             f"{total['questions']} questions in eight types; expected answers computed from the ledger's files (seed {args.seed}). "
             f"Audit graph right on {total['audit_graph_right']} of {total['questions']}, policy-only retrieval on {total['policy_only_right']}.", "",
             "| Type | Questions | Audit graph right | Policy-only right | Audit graph recall | Audit graph precision | Names given (planted) | Policy-only recall |",
             "|---|---|---|---|---|---|---|---|"]
    for kind, e in summary.items():
        lines.append(f"| {kind} | {e['questions']} | {e['audit_graph_right']} | {e['policy_only_right']} | "
                     f"{e['audit_graph_mean_recall']:.2f} | {e['audit_graph_mean_precision']:.2f} | "
                     f"{e['audit_graph_mean_named']:.1f} ({e['expected_size']:.1f}) | {e['policy_only_mean_recall']:.2f} |"
                     if "audit_graph_mean_recall" in e else
                     f"| {kind} | {e['questions']} | {e['audit_graph_right']} | {e['policy_only_right']} | | | | |")
    wrong = [r for r in rows if not r["audit_graph"]["ok"]]
    lines += ["", f"## Questions the audit graph got wrong ({len(wrong)})", ""]
    lines += [f"- ({r['type']}) {r['q']} expected {r['expected']}, got {r['audit_graph'].get('got', r['audit_graph'].get('missed'))}" for r in wrong] or ["None."]
    (args.out / "case_graph_eval.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
