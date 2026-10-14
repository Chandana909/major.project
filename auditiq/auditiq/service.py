"""Batch audit over the database: extract, audit, store, queue for review.

One run audits a list of invoices with one configuration and one policy
version. Every result is stored with its flags and its audit trail. An invoice
whose route calls for a human gets the state PENDING_REVIEW and stays in the
review queue until a decision is recorded (db.record_decision); the queue is in
the database, so it survives a restart.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from . import db, prompts
from .graph import PipelineConfig, build_graph, in_sample, to_result
from .llm import ChatClient
from .policy import Policy
from .policy_ingest import clause_citations

log = logging.getLogger(__name__)
BULK = 200      # from this many invoices on, the ledger is read in bulk


def workflow_status(route: str, invoice_id: str, sample_rate: float) -> str:
    """Where a result goes after scoring: approved, queued for review, or left unsampled."""
    if route == "approve":
        return db.AUTO_APPROVED
    if route == "sample" and not in_sample(invoice_id, sample_rate):
        return db.NOT_SAMPLED
    return db.PENDING_REVIEW


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
    done = 0

    def store(state: dict) -> None:
        nonlocal done
        for flag in state["audit_pack"]["flags"]:
            source = citations.get(flag["clause"])
            if source:
                flag["citation"] = {"document": source["document"], "page": source["page"]}
        result = to_result(state, config, policy, model)
        status = workflow_status(result["route"], result["invoice_id"], sample_rate)
        db.save_result(conn, run_id, state, result, status, commit=False)
        done += 1
        if done % 200 == 0:
            conn.commit()
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
