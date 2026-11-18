"""Batch audit over the database: extract, audit, store, queue for review.

One run audits a list of invoices with one configuration and one policy
version. Every result is stored with its flags and its audit trail. An invoice
whose route calls for a human gets the state PENDING_REVIEW and stays in the
review queue until a decision is recorded (db.record_decision); the queue is in
the database, so it survives a restart.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from . import db, prompts
from .graph import PipelineConfig, build_graph, in_sample, to_result
from .llm import ChatClient
from .policy import Policy
from .policy_ingest import clause_citations

log = logging.getLogger(__name__)
BULK = 200      # from this many invoices on, the ledger is read in bulk
# A run commits its results about once a second, not after a fixed number of invoices. A commit waits for the disk
# (75 ms each on a laptop on battery, 18 November 2026): committing every 200 invoices made the commits most of a
# controls-only run. A second keeps every transaction short, so a reader of the store never waits long for one.
COMMIT_SECONDS = 1.0


def workflow_status(route: str, invoice_id: str, sample_rate: float) -> str:
    """Where a result goes after scoring: approved, queued for review, or left unsampled."""
    if route == "approve":
        return db.AUTO_APPROVED
    if route == "sample" and not in_sample(invoice_id, sample_rate):
        return db.NOT_SAMPLED
    return db.PENDING_REVIEW


def store_result(conn: db.Database, run_id: int, state: dict, config: PipelineConfig, policy: Policy,
                 model: str | None, citations: dict, sample_rate: float = 1.0) -> int:
    """Store one audited invoice (not committed): cite where each flagged clause stands in the policy documents,
    decide its workflow state, and save the result. Returns the result id."""
    for flag in state["audit_pack"]["flags"]:
        source = citations.get(flag["clause"])
        if source:
            flag["citation"] = {"document": source["document"], "page": source["page"]}
    result = to_result(state, config, policy, model)
    status = workflow_status(result["route"], result["invoice_id"], sample_rate)
    return db.save_result(conn, run_id, state, result, status, commit=False)


def audit_invoices(conn: db.Database, config: PipelineConfig, policy: Policy,
                   client: ChatClient | None, invoice_ids: list[str], *, sample_rate: float = 1.0,
                   workers: int = 1, note: str = "",
                   progress: Callable[[int, int], None] | None = None) -> int:
    """Audit the given invoices and store the results. Returns the run id."""
    graph = build_graph(config, policy, client)
    model = getattr(client, "model", None)
    run_id = db.start_run(conn, config.name, policy.version, model,
                          prompts.prompt_hash() if config.agents != "none" else None, note)
    log.info("run %d: %s under policy %s, %d invoice(s), model %s", run_id, config.name, policy.version,
             len(invoice_ids), model or "none")
    # Where each clause stands in the ingested policy documents (empty if none was ingested).
    citations = clause_citations(conn, policy.version)
    done, committed = 0, time.monotonic()

    def store(state: dict) -> None:
        nonlocal done, committed
        store_result(conn, run_id, state, config, policy, model, citations, sample_rate)
        done += 1
        if time.monotonic() - committed >= COMMIT_SECONDS:
            conn.commit()
            committed = time.monotonic()
        if progress:
            progress(done, len(invoice_ids))

    def transactions():
        if len(invoice_ids) >= BULK:
            yield from db.extract_many(conn, invoice_ids)       # the ledger is read once, not once per invoice
            return
        for invoice_id in invoice_ids:
            txn = db.extract_one(conn, invoice_id)
            if txn is None:
                raise KeyError(f"invoice {invoice_id} is not in the database")
            yield txn

    if workers <= 1:
        for txn in transactions():
            store(graph.invoke({"txn": txn}))
    else:
        # The database is read and written in this thread only; the worker
        # threads run the graph, where the time goes to model calls.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            running = set()
            for txn in transactions():
                running.add(pool.submit(graph.invoke, {"txn": txn}))
                if len(running) >= 2 * workers:
                    finished, running = wait(running, return_when=FIRST_COMPLETED)
                    for future in finished:
                        store(future.result())
            for future in wait(running).done:
                store(future.result())
    conn.commit()
    db.finish_run(conn, run_id)
    log.info("run %d: finished, %d result(s) stored", run_id, done)
    return run_id


def audit_in_force(conn: db.Database, config: PipelineConfig, client: ChatClient | None, invoice_ids: list[str],
                   *, progress: Callable[[int, int], None] | None = None, **options) -> list[int]:
    """Audit invoices, each under the policy version in force on its date (``db.policy_timeline``): one run per
    version, in the order the versions took effect. Returns the run ids. ``audit_invoices`` with a policy of
    one's choosing audits every invoice under that policy instead, whatever its date (an experiment, a what-if)."""
    timeline = db.policy_timeline(conn)
    if not timeline:
        raise KeyError("no active policy in the database")
    governing = db.versions_in_force(conn, invoice_ids)
    groups: dict[str, list[str]] = {}
    for invoice_id in invoice_ids:
        if invoice_id not in governing:
            raise KeyError(f"invoice {invoice_id} is not in the database")
        groups.setdefault(governing[invoice_id], []).append(invoice_id)
    order = [version for _, version in timeline]
    runs, base, total = [], 0, len(invoice_ids)
    for version in sorted(groups, key=order.index):
        group = groups[version]
        step = (lambda done, _of, base=base: progress(base + done, total)) if progress else None
        runs.append(audit_invoices(conn, config, db.read_policy(conn, version), client, group, progress=step,
                                   **options))
        base += len(group)
    return runs


def out_of_line(conn: db.Database) -> tuple[list[str], int]:
    """The invoices to audit so that every result follows the policy timeline: those the active version governs
    (its parameters may have changed), those last audited under a version that does not govern their date, and
    those never audited. Returns them, and how many invoices keep their results."""
    active = conn.scalar("SELECT version FROM company_policies WHERE is_active = 1")
    governing = db.versions_in_force(conn)
    latest = dict(conn.execute("SELECT invoice_id, policy_version FROM v_latest_results").fetchall())
    ids = sorted(i for i, v in governing.items() if v == active or latest.get(i) != v)
    return ids, len(governing) - len(ids)


def runs_summary(conn: db.Database, run_ids: list[int]) -> dict:
    """The totals of several runs, and per run its policy version and size."""
    parts = [run_summary(conn, run_id) for run_id in run_ids]
    versions = dict(conn.execute(
        f"SELECT run_id, policy_version FROM audit_runs WHERE run_id IN ({', '.join('?' for _ in run_ids)})",
        run_ids).fetchall()) if run_ids else {}
    states: dict[str, int] = {}
    for part in parts:
        for state, n in part["states"].items():
            states[state] = states.get(state, 0) + n
    totals = {key: sum(part[key] for part in parts)
              for key in ("invoices", "flags", "llm_calls", "prompt_tokens", "completion_tokens", "failed_stages")}
    return {"runs": [{"run_id": part["run_id"], "policy_version": versions.get(part["run_id"]),
                      "invoices": part["invoices"]} for part in parts], **totals, "states": states}


def run_summary(conn: db.Database, run_id: int) -> dict:
    rows = conn.execute(
        "SELECT workflow_status, COUNT(*) AS n FROM audit_results WHERE run_id = ? GROUP BY workflow_status",
        (run_id,)).fetchall()
    totals = conn.execute(
        "SELECT COUNT(*) AS invoices, COALESCE(SUM(flag_count), 0) AS flags, COALESCE(SUM(llm_calls), 0) AS llm_calls, "
        "COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens, COALESCE(SUM(completion_tokens), 0) AS completion_tokens, "
        "COALESCE(SUM(failed_stages), 0) AS failed_stages FROM audit_results WHERE run_id = ?", (run_id,)).fetchone()
    return {"run_id": run_id, **{k: int(totals[k]) for k in totals.keys()},
            "states": {r["workflow_status"]: int(r["n"]) for r in rows}}
