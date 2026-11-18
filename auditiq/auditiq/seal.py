"""Tamper evidence for the audit record: every result sealed, every trail entry chained, every finished run sealed.

Audit documentation must show that it was not changed after the fact (ISA 230). Three hashes (SHA-256 over a
canonical JSON encoding) make a change visible:

    result seal   when a result is stored (audit_results.seal): its decision (route, risk level, scores, workflow
                  state, cost), its audit pack as it was then, and every finding stored with it (audit_flags,
                  kept and removed, in order)
    entry hash    every audit-trail entry (audit_trail.entry_hash), over the entry and the hash before it: the
                  first entry of a result over the result's seal, each later one over its predecessor. The
                  reviewer's decision is such an entry, so the review extends the chain instead of breaking it
    run seal      when a run finishes (audit_runs.seal): the run's configuration, policy version, model, prompts,
                  times, and the seal of every result it produced, in order. A result removed from a finished
                  run, or added to it later, changes it

``verify`` recomputes all three from what the store holds. The review is the one legitimate later change to a
result (it sets the workflow state and adds the decision to the pack): the seal covers the pack without its
``review`` entry and the state the result had when it was stored, and the check requires a reviewed result's state
to be the one its chained review entry records. Rows stored before sealing existed have no hashes and are
counted as unsealed, not as altered.

What this does not do: a person with write access who recomputes every hash after changing a row is not caught,
and a run deleted whole leaves nothing to check against. Both need the hashes kept outside the store (an export,
write-once storage or a published digest of the run seals), which ``digest`` gives in one value.
"""
from __future__ import annotations

import hashlib
import json

RESULT_INTS = ("run_id", "flag_count", "llm_calls", "prompt_tokens", "completion_tokens", "failed_stages")
RESULT_FLOATS = ("r0", "rc", "latency_ms")
RESULT_TEXT = ("invoice_id", "vendor_id", "route", "risk_level", "workflow_status", "created_at")
RESULT_FIELDS = RESULT_INTS + RESULT_FLOATS + RESULT_TEXT
FLAG_FIELDS = ("clause", "severity", "source", "agent", "status", "g", "p", "a", "confidence", "message",
               "evidence", "removal_reason")
ENTRY_FIELDS = ("seq", "stage", "actor", "detail", "prompt_tokens", "completion_tokens", "latency_ms")
RUN_FIELDS = ("run_id", "configuration", "policy_version", "model", "prompt_hash", "note", "started_at", "finished_at")
SHOW = 20                   # altered items listed by id; the counts cover all


def _int(x):
    return None if x is None else int(x)


def _float(x):
    return None if x is None else float(x)


def _text(x):
    return None if x is None else str(x)


def digest(value) -> str:
    """SHA-256 of a canonical JSON encoding: sorted keys, no spaces, the characters as they are."""
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def result_record(row) -> dict:
    """The sealed fields of a result, with one type each whatever the backend returns (REAL 50.0 and int 50 alike).
    The evidence fingerprint is sealed with the result when it has one (results stored from 18 November 2026 on)."""
    out = {k: _int(row[k]) for k in RESULT_INTS}
    out.update({k: _float(row[k]) for k in RESULT_FLOATS})
    out.update({k: _text(row[k]) for k in RESULT_TEXT})
    if "evidence" in row.keys() and row["evidence"] is not None:
        out["evidence"] = str(row["evidence"])
    return out


# ------------------------------------------------------------------ evidence
# The records an audit read for an invoice, each fingerprinted apart, so that a later change to the ledger shows which
# of them changed. The vendor's other invoices are not among them: they grow as the ledger does.
EVIDENCE_PARTS = ("invoice", "po", "grn", "vendor", "approvals")


def evidence(txn: dict) -> str:
    """The fingerprint of the records an audit of ``txn`` read: per record, the first 128 bits of the SHA-256 of its
    canonical JSON, as a JSON object. Sealed with the result, it shows later whether the ledger still holds them."""
    return json.dumps({part: digest(txn.get(part))[:32] for part in EVIDENCE_PARTS}, sort_keys=True,
                      separators=(",", ":"))


def evidence_drift(conn, run_id: int | None = None) -> dict:
    """Whether the ledger still holds the records the latest results were based on (re-performance of the
    extraction): each latest result's evidence fingerprint against the records the store holds now. A result whose
    records changed no longer describes its invoice and should be audited again; the parts say which record moved."""
    from . import db

    where, params = ("AND l.run_id = ?", [run_id]) if run_id is not None else ("", [])
    rows = conn.execute(f"SELECT l.invoice_id, l.evidence FROM v_latest_results l WHERE 1 = 1 {where} "
                        "ORDER BY l.invoice_id", params).fetchall()
    stored = {r[0]: r[1] for r in rows if r[1] is not None}
    present = {r[0] for r in conn.execute("SELECT invoice_id FROM invoices")}
    ids = [i for i in stored if i in present]
    changed: list[dict] = []
    parts: dict[str, int] = {p: 0 for p in EVIDENCE_PARTS}
    for txn in db.extract_many(conn, ids, history=False) if ids else []:
        invoice_id = txn["invoice"]["invoice_id"]
        before, now = json.loads(stored[invoice_id]), json.loads(evidence(txn))
        moved = [p for p in EVIDENCE_PARTS if before.get(p) != now.get(p)]
        if moved:
            changed.append({"invoice_id": invoice_id, "changed": moved})
            for p in moved:
                parts[p] += 1
    return {"checked": len(rows), "fingerprinted": len(stored), "without_fingerprint": len(rows) - len(stored),
            "unchanged": len(ids) - len(changed), "changed": len(changed), "changed_by_record": parts,
            "missing": len(stored) - len(ids), "changed_invoices": changed[:SHOW], "current": not changed}


def flag_record(flag) -> list:
    f = {k: flag[k] for k in FLAG_FIELDS}
    return [_text(f["clause"]), _text(f["severity"]), _text(f["source"]), _text(f["agent"]), _text(f["status"]),
            _int(f["g"]), _int(f["p"]), _float(f["a"]), _float(f["confidence"]), _text(f["message"]),
            _text(f["evidence"]), _text(f["removal_reason"])]


def entry_record(entry) -> list:
    e = {k: entry[k] for k in ENTRY_FIELDS}
    return [_int(e["seq"]), _text(e["stage"]), _text(e["actor"]), _text(e["detail"]), _int(e["prompt_tokens"]),
            _int(e["completion_tokens"]), _float(e["latency_ms"])]


def pack_without_review(pack: dict) -> dict:
    return {k: v for k, v in pack.items() if k != "review"}


def result_seal(record: dict, pack: dict, flags: list[list]) -> str:
    return digest({"result": record, "pack": pack_without_review(pack), "flags": flags})


def entry_hash(previous: str, entry: list) -> str:
    return digest([previous, entry])


def run_seal(run: dict, results: list[tuple[int, str]]) -> str:
    return digest({"run": {k: run[k] for k in RUN_FIELDS}, "results": [[int(i), s] for i, s in results]})


def chain(seal: str, entries: list[list]) -> list[str]:
    """The hash of each entry of a result's trail, in order, from the result's seal."""
    out, previous = [], seal
    for entry in entries:
        previous = entry_hash(previous, entry)
        out.append(previous)
    return out


def _review_decision(detail: str | None) -> str | None:
    """The decision a review entry records ("approve", "reject" or "override", before any justification)."""
    return (detail or "").split(":", 1)[0].strip() or None


CHUNK = 5000                # sealed results checked per round of queries: memory stays bounded on any store


def verify(conn, run_id: int | None = None, result_ids: list[int] | None = None) -> dict:
    """Recompute every seal and hash of the store (or of one run, or of some results) and compare.

    Results stored before sealing are only counted. The sealed ones are read in chunks of ``CHUNK`` by result id, each
    with its findings and its trail, so that a store of any size is checked in bounded memory."""
    where, params = "", []
    if result_ids is not None:
        if not result_ids:
            return _report(0, 0, [], [], 0, 0, [], 0, {}, [])
        where, params = f"AND r.result_id IN ({', '.join('?' for _ in result_ids)})", list(result_ids)
    elif run_id is not None:
        where, params = "AND r.run_id = ?", [run_id]
    unsealed = int(conn.scalar(f"SELECT COUNT(*) FROM audit_results r WHERE r.seal IS NULL {where}", params) or 0)
    entries_unsealed = int(conn.scalar(
        f"SELECT COUNT(*) FROM audit_trail t JOIN audit_results r ON r.result_id = t.result_id WHERE r.seal IS NULL "
        f"{where}", params) or 0)
    ids = [int(r[0]) for r in conn.execute(
        f"SELECT r.result_id FROM audit_results r WHERE r.seal IS NOT NULL {where} ORDER BY r.result_id", params)]

    sealed, altered, inconsistent = 0, [], []
    entries, entries_broken = entries_unsealed, []
    for start in range(0, len(ids), CHUNK):
        low, high = ids[start], ids[min(start + CHUNK, len(ids)) - 1]
        span, span_params = f"r.seal IS NOT NULL AND r.result_id BETWEEN ? AND ? {where}", [low, high, *params]
        results = conn.execute(f"SELECT r.* FROM audit_results r WHERE {span} ORDER BY r.result_id",
                               span_params).fetchall()
        flags: dict[int, list] = {}
        for f in conn.execute(f"SELECT f.* FROM audit_flags f JOIN audit_results r ON r.result_id = f.result_id "
                              f"WHERE {span} ORDER BY f.result_id, f.flag_id", span_params):
            flags.setdefault(int(f["result_id"]), []).append(flag_record(f))
        trails: dict[int, list] = {}
        for e in conn.execute(f"SELECT t.* FROM audit_trail t JOIN audit_results r ON r.result_id = t.result_id "
                              f"WHERE {span} ORDER BY t.result_id, t.seq, t.entry_id", span_params):
            trails.setdefault(int(e["result_id"]), []).append(e)
        outcome = _check(results, flags, trails)
        sealed += outcome["sealed"]
        altered += outcome["altered"]
        inconsistent += outcome["inconsistent"]
        entries += outcome["entries"]
        entries_unsealed += outcome["entries_unsealed"]
        entries_broken += outcome["entries_broken"]
    runs = _check_runs(conn, run_id) if result_ids is None else ({}, [])
    return _report(unsealed + len(ids), sealed, altered, inconsistent, unsealed, entries, entries_broken,
                   entries_unsealed, runs[0], runs[1])


def _check(results, flags: dict[int, list], trails: dict[int, list]) -> dict:
    """Recompute the seals of some sealed results and the hashes of their trails."""
    from . import db

    sealed, altered, inconsistent, entries, entries_unsealed, entries_broken = 0, [], [], 0, 0, []
    for r in results:
        result_id = int(r["result_id"])
        trail = trails.get(result_id, [])
        entries += len(trail)
        record = result_record(r)
        reviews = [e for e in trail if e["stage"] == "review"]
        if reviews:
            # A reviewed result was waiting for review when it was sealed, and its state is the decision recorded.
            decision = _review_decision(reviews[-1]["detail"])
            if record["workflow_status"] != db.REVIEWED.get(decision or ""):
                inconsistent.append(result_id)
            record["workflow_status"] = db.PENDING_REVIEW
        try:
            pack = json.loads(r["audit_pack"])
        except (TypeError, ValueError):
            pack = {"unreadable": str(r["audit_pack"])}
        if result_seal(record, pack, flags.get(result_id, [])) != r["seal"]:
            altered.append(result_id)
        else:
            sealed += 1
        expected = chain(r["seal"], [entry_record(e) for e in trail])
        for e, h in zip(trail, expected):
            if e["entry_hash"] is None:
                entries_unsealed += 1
            elif e["entry_hash"] != h:
                entries_broken.append(int(e["entry_id"]))
    return {"sealed": sealed, "altered": altered, "inconsistent": inconsistent, "entries": entries,
            "entries_unsealed": entries_unsealed, "entries_broken": entries_broken}


def _check_runs(conn, run_id: int | None) -> tuple[dict, list[int]]:
    """Recompute the seal of every finished run (or of one) over its results' stored seals."""
    run_where, run_params = ("WHERE u.run_id = ?", [run_id]) if run_id is not None else ("", [])
    runs_sealed, runs_open, runs_altered, runs_unsealed = 0, 0, [], 0
    members: dict[int, list] = {}
    for rid, result_id, seal in conn.execute(
            f"SELECT r.run_id, r.result_id, r.seal FROM audit_results r JOIN audit_runs u ON u.run_id = r.run_id "
            f"{run_where} ORDER BY r.run_id, r.result_id", run_params):
        members.setdefault(int(rid), []).append((int(result_id), seal))
    for u in conn.execute(f"SELECT u.* FROM audit_runs u {run_where} ORDER BY u.run_id", run_params).fetchall():
        if u["finished_at"] is None:
            runs_open += 1
        elif u["seal"] is None:
            runs_unsealed += 1
        elif run_seal(dict(zip(u.keys(), u)), members.get(int(u["run_id"]), [])) != u["seal"]:
            runs_altered.append(int(u["run_id"]))
        else:
            runs_sealed += 1
    return {"sealed": runs_sealed, "open": runs_open, "unsealed": runs_unsealed}, runs_altered


def _report(results: int, sealed: int, altered: list[int], inconsistent: list[int], unsealed: int, entries: int,
            entries_broken: list[int], entries_unsealed: int, runs: dict, runs_altered: list[int]) -> dict:
    intact = not altered and not inconsistent and not entries_broken and not runs_altered
    return {"intact": intact,
            "results": {"checked": results, "sealed": sealed, "unsealed": unsealed, "altered": len(altered),
                        "altered_ids": altered[:SHOW], "review_inconsistent": len(inconsistent),
                        "review_inconsistent_ids": inconsistent[:SHOW]},
            "entries": {"checked": entries, "broken": len(entries_broken), "broken_ids": entries_broken[:SHOW],
                        "unsealed": entries_unsealed},
            "runs": {**{"sealed": 0, "open": 0, "unsealed": 0}, **runs, "altered": len(runs_altered),
                     "altered_ids": runs_altered[:SHOW]}}


def run_digest(conn) -> str | None:
    """One value for the whole store: the digest of every finished run's seal, in run order. Kept outside the store
    (printed in a report, sent to the auditee, written to write-once storage), it shows later that no sealed run was
    changed or deleted."""
    seals = [[int(r), s] for r, s in conn.execute(
        "SELECT run_id, seal FROM audit_runs WHERE seal IS NOT NULL ORDER BY run_id")]
    return digest(seals) if seals else None
