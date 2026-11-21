"""The trail investigator against faults planted in an audited store, and against a store run properly.

    python -m evaluation.investigator_eval              results/investigator/investigator.md and .json

A ledger (bench_seed_101) is loaded and audited under configuration C1 with the policy in force. Two copies of that
store are then worked on, with a clock the script controls:

    clean      three reviewers decide 60 invoices of the queue, three minutes apart, each with a written reason;
               none of them approved an invoice in the ledger; critical invoices are rejected, others approved
    planted    the same, and in addition, each fault at known places:
               documentation  8 critical invoices approved with the reason "ok"
               pace           12 decisions by one reviewer, 5 seconds apart
               segregation    5 decisions taken by the invoice's own approver
               overrides      3 critical invoices of one vendor cleared by one reviewer
               superseded     3 invoices rejected, then audited again under policy v2.6 whatever their date, which
                              lets them through (and puts them under a version that does not govern them)
               flips          3 results stored for invoices with the same configuration, policy and records but
                              another route (what a model's inconsistency or a forged row looks like)
               integrity      2 results edited in the database, 1 trail entry edited
               completeness   the controls entry deleted from 2 trails (which also breaks their chains)
               evidence       4 invoice descriptions changed in the ledger after the audit
               coverage       3 invoices added to the ledger after the audit (never audited), and the 3 of
                              "superseded"
               model failures 2 results stored by a model configuration with 2 failed stages each

The investigator runs on both copies. Each planted fault is looked for at its place (a result, an invoice, a
reviewer); a place it reports that was not planted is counted as extra. The backlog check is run separately with the
clock six days after the audit. The faults are planted exactly as the checks define them, so this shows that the
checks find what they say they find and stay quiet on a store run properly; it does not show how often such faults
happen, or that a determined insider who also recomputes the seals would be caught.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

from auditiq import db, investigator, service
from auditiq.graph import PRESETS, audit, to_result
from auditiq.policy import PROJECT_ROOT, load_policy

LEDGER = PROJECT_ROOT / "data" / "bench_seed_101"
OUT = PROJECT_ROOT / "results" / "investigator"
GOOD = "Checked the PO, the goods receipt and the approval log against the finding; documented in the file."


class Clock:
    """db.now replaced by a clock that moves only when told to."""

    def __init__(self, start: datetime):
        self.at = start
        self._real = db.now

    def __enter__(self):
        db.now = lambda: self.at.strftime("%Y-%m-%d %H:%M:%S")
        return self

    def __exit__(self, *_):
        db.now = self._real

    def tick(self, seconds: float) -> None:
        self.at += timedelta(seconds=seconds)


def base_store(folder: Path) -> tuple[Path, datetime]:
    target = folder / "base.db"
    conn = db.connect(target)
    try:
        db.load_dataset(conn, LEDGER)
        db.store_policy(conn, load_policy("2.5"), active=True)
        db.store_policy(conn, load_policy("2.6"))
        service.audit_in_force(conn, PRESETS["C1"], None, db.invoice_ids(conn))
        audited = datetime.fromisoformat(str(conn.scalar("SELECT MAX(created_at) FROM audit_results")))
    finally:
        conn.close()
    return target, audited


def queue(conn: db.Database) -> list[dict]:
    rows = [dict(zip(r.keys(), tuple(r))) for r in conn.execute(
        "SELECT q.result_id, q.invoice_id, q.vendor_id, q.risk_level, q.amount FROM v_review_queue q "
        "ORDER BY q.invoice_id").fetchall()]
    critical = {int(r[0]) for r in conn.execute(
        "SELECT DISTINCT result_id FROM audit_flags WHERE status = 'kept' AND severity = 'critical'")}
    for r in rows:
        r["critical"] = int(r["result_id"]) in critical or r["risk_level"] == "CRITICAL"
    return rows


def decide_clean(conn: db.Database, clock: Clock, items: list[dict]) -> list[int]:
    reviewers = ["Asha Verma (audit)", "Bilal Khan (audit)", "Chitra Rao (audit)"]
    done = []
    for k, item in enumerate(items):
        clock.tick(180)
        db.record_decision(conn, int(item["result_id"]), "reject" if item["critical"] else "approve",
                           reviewers[k % 3], GOOD)
        done.append(int(item["result_id"]))
    return done


def fabricate(conn: db.Database, invoice_ids: list[str], route: str, configuration: str = "C1",
              failed_stages: int = 0) -> list[int]:
    """Results stored for the invoices as if by a run of ``configuration``, with a given route: the same records and
    policy, another outcome."""
    policy = db.read_policy(conn, "2.5")
    run_id = db.start_run(conn, configuration, policy.version, None, None, "planted by evaluation.investigator_eval")
    ids = []
    for txn in db.extract_many(conn, invoice_ids):
        state = audit(txn, PRESETS["C1"], policy)
        result = to_result(state, PRESETS["C1"], policy)
        result["route"] = route
        result["issues"]["failed_stages"] = failed_stages
        status = db.AUTO_APPROVED if route == "approve" else db.PENDING_REVIEW
        ids.append(db.save_result(conn, run_id, state, result, status))
    db.finish_run(conn, run_id)
    return ids


def plant(conn: db.Database, clock: Clock, pending: list[dict], used: set[int]) -> dict:
    """Plant every fault; returns where each one is."""
    free = [p for p in pending if int(p["result_id"]) not in used]
    take = lambda pred, n: [p for p in free if pred(p) and not p.get("taken")][:n]   # noqa: E731

    def mark(items):
        for p in items:
            p["taken"] = True
        return items

    planted: dict[str, set] = {k: set() for k in ("documentation", "pace", "segregation", "overrides", "superseded",
                                                   "flips", "integrity", "completeness", "evidence", "coverage",
                                                   "model_failures")}
    # documentation: critical invoices approved with the reason "ok"
    for p in mark(take(lambda p: p["critical"], 8)):
        clock.tick(240)
        db.record_decision(conn, int(p["result_id"]), "approve", "Dev Malhotra (audit)", "ok")
        planted["documentation"].add(int(p["result_id"]))
        planted["overrides"].add(int(p["result_id"]))
    # pace: twelve decisions five seconds apart
    clock.tick(600)
    for p in mark(take(lambda p: not p["critical"], 12)):
        clock.tick(5)
        db.record_decision(conn, int(p["result_id"]), "approve", "Esha Pillai (audit)", GOOD)
    planted["pace"].add("Esha Pillai (audit)")
    # segregation: the invoice's own approver decides
    for p in mark(take(lambda p: not p["critical"], 5)):
        clock.tick(240)
        approver = conn.scalar("SELECT approver_name FROM approval_logs WHERE transaction_id = ? AND action_taken = "
                               "'Approved' ORDER BY timestamp DESC LIMIT 1", (p["invoice_id"],))
        db.record_decision(conn, int(p["result_id"]), "reject", approver, GOOD)
        planted["segregation"].add(int(p["result_id"]))
    # overrides: one reviewer clears three critical invoices of one vendor
    by_vendor: dict[str, list[dict]] = {}
    for p in free:
        if p["critical"] and not p.get("taken"):
            by_vendor.setdefault(p["vendor_id"], []).append(p)
    vendor = next(v for v, items in sorted(by_vendor.items()) if len(items) >= 3)
    for p in mark(by_vendor[vendor][:3]):
        clock.tick(240)
        db.record_decision(conn, int(p["result_id"]), "approve", "Farah Siddiqui (audit)", GOOD)
        planted["overrides"].add(int(p["result_id"]))
    planted["overrides_pair"] = {("Farah Siddiqui (audit)", vendor)}
    # superseded: rejected, then audited under v2.6 regardless of date, which approves them
    v26 = db.read_policy(conn, "2.6")
    candidates = [p for p in free if not p.get("taken")]
    relaxed = []
    for txn in db.extract_many(conn, [p["invoice_id"] for p in candidates]):
        state = audit(txn, PRESETS["C1"], v26)
        if state["score"]["route"] == "approve":
            relaxed.append(txn["invoice"]["invoice_id"])
        if len(relaxed) == 3:
            break
    for p in mark([p for p in candidates if p["invoice_id"] in relaxed]):
        clock.tick(240)
        db.record_decision(conn, int(p["result_id"]), "reject", "Gopal Iyer (audit)", GOOD)
        planted["superseded"].add(p["invoice_id"])
        planted["coverage"].add(p["invoice_id"])
        planted["flips"].add(p["invoice_id"])
    clock.tick(300)
    service.audit_invoices(conn, PRESETS["C1"], v26, None, relaxed, note="audited again under v2.6")
    # flips without a cause: forged results with another route
    flipped = [p["invoice_id"] for p in mark(take(lambda p: not p["critical"], 3))]
    clock.tick(300)
    fabricate(conn, flipped, "approve")
    planted["flips"].update(flipped)
    # model failures: results of a model configuration with failed stages
    failing = [p["invoice_id"] for p in mark(take(lambda p: True, 2))]
    clock.tick(300)
    fabricate(conn, failing, "escalate", configuration="C3", failed_stages=2)
    planted["model_failures"].update(failing)
    # integrity: two results and one trail entry edited in the database
    edited = [p for p in mark(take(lambda p: True, 3))]
    for p in edited[:2]:
        conn.execute("UPDATE audit_results SET risk_level = 'LOW' WHERE result_id = ?", (int(p["result_id"]),))
        planted["integrity"].add(int(p["result_id"]))
    entry = conn.scalar("SELECT MIN(entry_id) FROM audit_trail WHERE result_id = ? AND stage = 'scoring'",
                        (int(edited[2]["result_id"]),))
    conn.execute("UPDATE audit_trail SET detail = 'count-based 0.0, weighted 0.0, route approve' WHERE entry_id = ?",
                 (entry,))
    planted["integrity"].add(int(edited[2]["result_id"]))
    # completeness: the controls entry deleted from two trails
    for p in mark(take(lambda p: True, 2)):
        conn.execute("DELETE FROM audit_trail WHERE result_id = ? AND stage = 'controls'", (int(p["result_id"]),))
        planted["completeness"].add(int(p["result_id"]))
        planted["integrity"].add(int(p["result_id"]))
    # evidence: four descriptions changed after the audit
    for p in mark(take(lambda p: True, 4)):
        conn.execute("UPDATE invoices SET description = description || ' (amended)' WHERE invoice_id = ?",
                     (p["invoice_id"],))
        planted["evidence"].add(p["invoice_id"])
    # coverage: three invoices added after the audit
    for k, source in enumerate(conn.execute("SELECT invoice_id FROM invoices ORDER BY invoice_id LIMIT 3").fetchall()):
        new_id = f"INV9{k:04d}"
        columns = list(conn.columns("invoices"))
        values = conn.execute(f"SELECT {', '.join(columns)} FROM invoices WHERE invoice_id = ?", (source[0],)).fetchone()
        row = dict(zip(columns, tuple(values)))
        row.update(invoice_id=new_id, invoice_number=f"ADDED-{k}")
        conn.execute(f"INSERT INTO invoices ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                     [row[c] for c in columns])
        planted["coverage"].add(new_id)
    conn.commit()
    return planted


def found_places(report: dict, conn: db.Database) -> dict[str, set]:
    by_key = {c["key"]: c for c in report["checks"]}
    entry_result = dict(conn.execute("SELECT entry_id, result_id FROM audit_trail").fetchall())
    places: dict[str, set] = {}
    integrity = set()
    for item in by_key["integrity"]["items"]:
        if "result_id" in item:
            integrity.add(int(item["result_id"]))
        elif "entry_id" in item and item["entry_id"] in entry_result:
            integrity.add(int(entry_result[item["entry_id"]]))
    places["integrity"] = integrity
    for key in ("completeness", "documentation", "segregation"):
        places[key] = {int(i["result_id"]) for i in by_key[key]["items"]}
    places["overrides"] = {int(i["result_id"]) for i in by_key["overrides"]["items"]}
    places["overrides_pair"] = {(i["reviewer"], i["vendor_id"]) for i in by_key["overrides"]["items"] if i["repeated"]}
    for key in ("evidence", "coverage", "model_failures", "superseded", "flips"):
        places[key] = {i["invoice_id"] for i in by_key[key]["items"]}
    places["pace"] = {i["reviewer"] for i in by_key["pace"]["items"]}
    places["flips_unexplained"] = {i["invoice_id"] for i in by_key["flips"]["items"] if i["unexplained"]}
    return places


def compare(planted: dict[str, set], found: dict[str, set]) -> dict:
    out = {}
    for key in found:
        want = planted.get(key, set())
        got = found[key]
        out[key] = {"planted": len(want), "found": len(want & got), "missed": sorted(map(str, want - got)),
                    "extra": sorted(map(str, got - want))}
    return out


def main() -> None:
    folder = Path(tempfile.mkdtemp(prefix="investigator_eval_"))
    started = time.time()
    try:
        base, audited = base_store(folder)
        results = {}
        for scenario in ("clean", "planted"):
            target = folder / f"{scenario}.db"
            shutil.copy(base, target)
            conn = db.connect(target)
            try:
                with Clock(audited + timedelta(minutes=5)) as clock:
                    pending = queue(conn)
                    sample = [p for p in pending if not p["critical"]][:40] + [p for p in pending if p["critical"]][:20]
                    used = set(decide_clean(conn, clock, sample))
                    planted = plant(conn, clock, pending, used) if scenario == "planted" else {}
                    if scenario == "planted":
                        planted["flips_unexplained"] = planted["flips"] - planted["superseded"]
                    report = investigator.investigate(conn, now=clock.at + timedelta(hours=1))
                found = found_places(report, conn)
                results[scenario] = {"status": {c["key"]: c["status"] for c in report["checks"]},
                                     "verdict": report["verdict"], "comparison": compare(planted, found),
                                     "counts": {c["key"]: c["count"] for c in report["checks"]}}
                late = investigator.investigate(conn, now=audited + timedelta(days=6))
                waiting = int(conn.scalar("SELECT COUNT(*) FROM v_review_queue") or 0)
                backlog = next(c for c in late["checks"] if c["key"] == "backlog")
                results[scenario]["backlog_after_six_days"] = {"waiting": waiting, "reported_late": backlog["count"]}
                results[scenario]["backlog_after_one_hour"] = results[scenario]["counts"]["backlog"]
            finally:
                conn.close()
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    report = {"date": time.strftime("%Y-%m-%d"), "ledger": LEDGER.name, "seconds": round(time.time() - started, 1),
              "scenarios": results}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "investigator.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    (OUT / "investigator.md").write_text(render(report), encoding="utf-8", newline="\n")
    print(f"wrote {OUT / 'investigator.md'}")


def render(report: dict) -> str:
    clean, planted = report["scenarios"]["clean"], report["scenarios"]["planted"]
    lines = ["# The trail investigator against planted faults", "",
             f"Generated by `python -m evaluation.investigator_eval` on {report['date']} ({report['seconds']} s). Ledger "
             f"`{report['ledger']}`, audited under C1; the scenarios are described in the script's docstring. The "
             "faults are planted as the checks define them: this shows that each check finds what it says and stays "
             "quiet on a store run properly, not how often such faults occur.", "",
             "| Check | Planted | Found at its place | Missed | Extra places | Places reported on the clean store |",
             "|---|---|---|---|---|---|"]
    for key, row in planted["comparison"].items():
        lines.append(f"| {key} | {row['planted']} | {row['found']} | {len(row['missed'])} | {len(row['extra'])} | "
                     f"{clean['comparison'][key]['found'] + len(clean['comparison'][key]['extra'])} |")
    lines += ["", f"Clean store: {clean['verdict']}", "", f"Planted store: {planted['verdict']}", "",
              "Status of each check (clean / planted): " + "; ".join(
                  f"{k} {clean['status'][k]} / {planted['status'][k]}" for k in planted["status"]), "",
              f"Backlog: one hour after the decisions no review is late on either store "
              f"({clean['backlog_after_one_hour']} and {planted['backlog_after_one_hour']}); six days after the audit, "
              f"{clean['backlog_after_six_days']['reported_late']:,} of {clean['backlog_after_six_days']['waiting']:,} "
              f"waiting reviews are reported late on the clean store and "
              f"{planted['backlog_after_six_days']['reported_late']:,} of {planted['backlog_after_six_days']['waiting']:,} "
              "on the planted one.", ""]
    extras = {k: v["extra"] for k, v in planted["comparison"].items() if v["extra"]}
    if extras:
        lines += ["Extra places on the planted store (reported, not planted as that fault):", ""]
        lines += [f"- {k}: {', '.join(v[:12])}" for k, v in extras.items()]
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
