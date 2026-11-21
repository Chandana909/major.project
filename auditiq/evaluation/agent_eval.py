"""The audit agent's rules planner on questions with answers known from the ledger, the answer key and the manifest.

    python -m evaluation.agent_eval                   results/agent/agent.md and agent.json

The ledger is collusion_seed_707 (5,000 invoices, two approver rings and two shell-vendor pairs planted, listed in its
manifest). It is loaded, audited under C1 with the policy in force, its vendor correspondence (seed 7) is stored, and
one approved result is edited in the database (its route set to escalate), so that a question about tampering has
something to find.

The questions are in evaluation/agent_questions.json: 17 intents, each with a dev wording (used while the planner
was written) and a test wording (written afterwards and frozen before the first test run; the planner is not
changed for a test failure). Slots are filled from the store with a fixed seed. The gold answer of every question is
computed here with this script's own SQL, or taken from the answer key (labels.csv), the generated mailbox's labels
or the ledger's manifest; never with the agent's tools. An answer is right when it contains every gold value (ids,
names, rule titles, numbers with their digits; "any of" where the question allows several). The agent runs in the
rules mode: no model.

What this measures is whether the planner picks tools that answer these questions and the tools answer them right.
The questions were written by the author of the planner, so the test wording is a paraphrase by the same person:
questions phrased in ways the planner's words do not cover fail, and how often real auditors phrase them so is not
measured here.
"""
from __future__ import annotations

import json
import random
import re
import shutil
import statistics
import tempfile
import time
from pathlib import Path

from auditiq import audit_agent, db, service, triage
from auditiq.graph import PRESETS
from auditiq.policy import PROJECT_ROOT, load_policy
from auditiq.screen import Screen
from auditiq_bench import correspondence

LEDGER = PROJECT_ROOT / "data" / "collusion_seed_707"
QUESTIONS = PROJECT_ROOT / "evaluation" / "agent_questions.json"
OUT = PROJECT_ROOT / "results" / "agent"
AMOUNTS = ["75,000", "3,50,000", "12,00,000", "40,00,000"]
CLAUSES = ["4.1.2", "5.1.1", "2.2.2"]
SEED = 11


def digits(text: str) -> str:
    """Text with the thousands separators of numbers removed (7,38,300 and 738,300 both become 738300)."""
    return re.sub(r"(?<=\d),(?=\d)", "", text)


def contains(answer: str, value: str) -> bool:
    a, v = digits(answer).lower(), digits(value).lower()
    if re.fullmatch(r"\d+", v):
        return re.search(rf"(?<![\d.]){v}(?![\d])", a) is not None
    return v in a


def build(folder: Path) -> tuple[Path, list[dict]]:
    target = folder / "agent.db"
    conn = db.connect(target)
    try:
        db.load_dataset(conn, LEDGER)
        db.store_policy(conn, load_policy("2.5"), active=True)
        db.store_policy(conn, load_policy("2.6"))
        service.audit_in_force(conn, PRESETS["C1"], None, db.invoice_ids(conn))
        messages, labels = correspondence.generate(LEDGER, seed=7)
        box = folder / "mail.mbox"
        correspondence.write(messages, labels, box)
        triage.load_mailbox(conn, box)
        first = conn.scalar("SELECT MIN(result_id) FROM audit_results WHERE route = 'approve'")
        conn.execute("UPDATE audit_results SET route = 'escalate' WHERE result_id = ?", (first,))
        conn.commit()
    finally:
        conn.close()
    return target, labels


def slots(conn: db.Database, rng: random.Random) -> dict[str, list]:
    pending = [r[0] for r in conn.execute("SELECT invoice_id FROM v_review_queue ORDER BY invoice_id")]
    approved = [r[0] for r in conn.execute(
        "SELECT DISTINCT transaction_id FROM approval_logs WHERE action_taken = 'Approved' ORDER BY transaction_id")]
    only_limit = [r[0] for r in conn.execute(
        "SELECT l.invoice_id FROM v_latest_results l JOIN audit_flags f ON f.result_id = l.result_id AND f.status = "
        "'kept' GROUP BY l.invoice_id HAVING COUNT(*) = 1 AND MIN(f.clause) = '5.1.1' ORDER BY l.invoice_id")]
    vendors = [r[0] for r in conn.execute(
        "SELECT v.vendor_name FROM vendor_master v JOIN invoices i ON i.vendor_id = v.vendor_id GROUP BY v.vendor_name "
        "HAVING COUNT(*) >= 5 ORDER BY v.vendor_name")]
    vendors = [v for v in vendors if sum(1 for w in vendors if w == v) == 1]
    return {"escalated_invoice": rng.sample(pending, 3), "audited_invoice": rng.sample(approved, 3),
            "amount": AMOUNTS, "clause": CLAUSES, "limit_invoice": rng.sample(only_limit, 2),
            "vendor": rng.sample(vendors, 2)}


def limits(conn: db.Database) -> list[tuple[float, str]]:
    rows = conn.execute("SELECT param_value FROM policy_parameters WHERE version = '2.5' AND clause_id = '5.1.1' "
                        "AND param_name = 'approval_limits'").fetchone()
    return sorted((float(v), r) for r, v in json.loads(rows[0]).items())


def role_for(conn: db.Database, amount: float) -> str:
    return next(r for v, r in limits(conn) if v >= amount)


def gold(conn: db.Database, intent: str, value, mail_labels: list[dict], manifest: dict,
         answer_key: dict[str, str]) -> dict:
    """What a right answer must contain: {"all": [...]} or {"any": [...]}, or both, or {"each_any": [[...], ...]}."""
    if intent == "why_flagged":
        rules = [r[0] for r in conn.execute(
            "SELECT DISTINCT f.clause FROM audit_flags f JOIN latest_results m ON m.result_id = f.result_id WHERE "
            "m.invoice_id = ? AND f.status = 'kept' ORDER BY f.clause", (value,))]
        return {"all": rules}
    if intent in ("approver", "story"):
        name = conn.scalar("SELECT approver_name FROM approval_logs WHERE transaction_id = ? AND action_taken = "
                           "'Approved' ORDER BY timestamp DESC, log_id DESC LIMIT 1", (value,))
        if intent == "approver":
            return {"all": [name]}
        route = conn.scalar("SELECT r.route FROM latest_results m JOIN audit_results r ON r.result_id = m.result_id "
                            "WHERE m.invoice_id = ?", (value,))
        return {"all": [name, route]}
    if intent == "approval_role":
        return {"all": [role_for(conn, float(value.replace(",", "")))]}
    if intent == "waiting":
        return {"all": [str(conn.scalar("SELECT COUNT(*) FROM v_review_queue"))]}
    if intent == "top_findings_vendor":
        rows = conn.execute("SELECT r.vendor_id, COUNT(*) AS n FROM audit_flags f JOIN latest_results m ON "
                            "m.result_id = f.result_id JOIN audit_results r ON r.result_id = m.result_id WHERE "
                            "f.status = 'kept' GROUP BY r.vendor_id ORDER BY n DESC").fetchall()
        return {"any": [v for v, n in rows if n == rows[0][1]]}
    if intent == "top_amount_vendor":
        rows = conn.execute("SELECT vendor_id, SUM(amount) AS s FROM invoices GROUP BY vendor_id ORDER BY s DESC "
                            "LIMIT 1").fetchall()
        return {"all": [rows[0][0]]}
    if intent == "rule_text":
        return {"all": [json.loads(open(PROJECT_ROOT / "policy" / "policy_v2.5.json", encoding="utf-8").read())
                        ["clauses"][value]["title"]]}
    if intent == "redirection":
        return {"all": sorted({m["invoice_id"] for m in mail_labels if m["suspicious"]})}
    if intent == "tamper":
        return {"all": ["The sealed record (fail)"]}
    if intent == "near_duplicates":
        return {"any": sorted(i for i, c in answer_key.items() if c == "J1")}
    if intent == "counterfactual":
        amount = float(conn.scalar("SELECT amount FROM invoices WHERE invoice_id = ?", (value,)))
        return {"all": [role_for(conn, amount)]}
    if intent == "vendor_profile":
        n = conn.scalar("SELECT COUNT(*) FROM invoices i JOIN vendor_master v ON v.vendor_id = i.vendor_id WHERE "
                        "v.vendor_name = ?", (value,))
        return {"all": [str(n)]}
    if intent == "rings":
        return {"each_any": [ring["vendors"] for ring in manifest["rings"]]}
    if intent == "screen":
        return {"any": sorted(i for i, c in answer_key.items() if c in ("J1", "J2", "J3", "J4"))}
    if intent == "critical_queue":
        return {"all": [conn.scalar("SELECT invoice_id FROM v_review_queue WHERE risk_level = 'CRITICAL' "
                                    "ORDER BY rc DESC, invoice_id LIMIT 1")]}
    if intent == "flagged_count":
        return {"all": [str(conn.scalar("SELECT COUNT(*) FROM v_latest_results WHERE flag_count > 0"))]}
    raise KeyError(intent)


def right(answer: str, want: dict) -> bool:
    ok = all(contains(answer, str(v)) for v in want.get("all", []))
    if "any" in want:
        ok = ok and any(contains(answer, str(v)) for v in want["any"])
    if "each_any" in want:
        ok = ok and all(any(contains(answer, str(v)) for v in group) for group in want["each_any"])
    return ok


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "both"], default="both",
                    help="dev: only the dev wording, printed and not written (for working on the planner)")
    args = ap.parse_args()
    spec = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    manifest = json.loads((LEDGER / "manifest.json").read_text(encoding="utf-8"))
    import pandas as pd
    key = pd.read_csv(LEDGER / "labels.csv", dtype=str, keep_default_na=False)
    answer_key = dict(zip(key["invoice_id"], key["class_id"]))
    folder = Path(tempfile.mkdtemp(prefix="agent_eval_"))
    model = Screen.load()
    started = time.time()
    try:
        target, mail_labels = build(folder)
        conn = db.connect(target)
        try:
            filled = slots(conn, random.Random(SEED))
            shared: dict = {}
            rows = []
            for split in ("dev",) if args.split == "dev" else ("dev", "test"):
                for item in spec["intents"]:
                    values = filled[item["slot"]] if item["slot"] else [None]
                    for value in values:
                        question = item[split].format(invoice=value, amount=value, clause=value, vendor=value)
                        want = gold(conn, item["intent"], value, mail_labels, manifest, answer_key)
                        t0 = time.perf_counter()
                        out = audit_agent.ask(question, conn, mode="rules", screen=model, shared=shared)
                        ms = (time.perf_counter() - t0) * 1000
                        tools = [s["tool"] for s in out["steps"]]
                        rows.append({"split": split, "intent": item["intent"], "question": question,
                                     "gold": want, "right": right(out["answer"], want), "tools": tools,
                                     "expected_tool": item["expect_tool"], "tool_chosen": item["expect_tool"] in tools,
                                     "ms": round(ms, 1), "answer": out["answer"][:600]})
        finally:
            conn.close()
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if args.split == "dev":
        for r in rows:
            print(("RIGHT " if r["right"] else "WRONG ") + r["question"], r["tools"], "" if r["right"] else r["gold"])
        return
    report = {"date": time.strftime("%Y-%m-%d"), "ledger": LEDGER.name, "seconds": round(time.time() - started, 1),
              "summary": {split: {"questions": sum(r["split"] == split for r in rows),
                                  "right": sum(r["right"] for r in rows if r["split"] == split),
                                  "tool_chosen": sum(r["tool_chosen"] for r in rows if r["split"] == split),
                                  "median_ms": statistics.median(r["ms"] for r in rows if r["split"] == split)}
                          for split in ("dev", "test")},
              "questions": rows}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "agent.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT / "agent.md").write_text(render(report), encoding="utf-8", newline="\n")
    print(f"wrote {OUT / 'agent.md'}")


def render(report: dict) -> str:
    s = report["summary"]
    lines = ["# The audit agent on questions with known answers", "",
             f"Generated by `python -m evaluation.agent_eval` on {report['date']} ({report['seconds']} s), rules mode "
             f"(no model), ledger `{report['ledger']}`. The questions and the protocol are in the script's docstring "
             "and `evaluation/agent_questions.json`; the test wording was written by the planner's author.", "",
             "| Wording | Questions | Answered right | Expected tool chosen | Median time |", "|---|---|---|---|---|"]
    for split in ("dev", "test"):
        lines.append(f"| {split} | {s[split]['questions']} | {s[split]['right']} ({s[split]['right'] / s[split]['questions']:.1%}) | "
                     f"{s[split]['tool_chosen']} | {s[split]['median_ms']:.0f} ms |")
    lines += ["", "| Intent | Dev right | Test right | Test tools |", "|---|---|---|---|"]
    intents = list(dict.fromkeys(r["intent"] for r in report["questions"]))
    for intent in intents:
        dev = [r for r in report["questions"] if r["intent"] == intent and r["split"] == "dev"]
        test = [r for r in report["questions"] if r["intent"] == intent and r["split"] == "test"]
        lines.append(f"| {intent} | {sum(r['right'] for r in dev)} of {len(dev)} | {sum(r['right'] for r in test)} of "
                     f"{len(test)} | {', '.join(dict.fromkeys(t for r in test for t in r['tools'])) or 'none'} |")
    wrong = [r for r in report["questions"] if not r["right"]]
    if wrong:
        lines += ["", "## Questions answered wrongly", ""]
        for r in wrong:
            lines.append(f"- ({r['split']}) {r['question']}: tools {', '.join(r['tools']) or 'none'}; needed "
                         f"{json.dumps(r['gold'], ensure_ascii=False)[:160]}")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
