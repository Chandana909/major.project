"""The audit copilot: questions about the policy, about an audited invoice, and about the data.

    answer()         retrieves policy passages (and the audit pack of an invoice
                     named in the question) and has the model answer from them,
                     citing the passages it used. Without a model it returns the
                     passages alone.
    data_question()  has the model write one SELECT statement, checks it, and
                     runs it on a read-only connection that can see the ledger
                     and the audit results and nothing else.

Neither function can change the database, and neither can read the benchmark
labels. Four guards stand between a model-written statement and the data:
the statement must be a single SELECT; it may not name a table outside the
allow-list; it may not call a function that changes the session's role or runs
a query given as text (`set_config`, `query_to_xml`, `ts_stat` and the like);
and it runs read-only with a row limit and a time limit. On SQLite an
authorizer also refuses every other table at execution. On PostgreSQL the
statement runs as the role `auditiq_reader`, which holds SELECT on the
allow-list only; without that role a data question is refused, because the
application's own user can read everything. (A text such as an invoice
description reaches the model, so a statement must be treated as written by
someone who wants the labels: `set_config('role', ...)` followed by
`query_to_xml('select ... from bench' || 'mark_labels', ...)` read them before
these functions were refused.)
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

from . import db
from .agents import call_json
from .audit_pack import render_markdown
from .case_graph import CaseGraph
from .llm import ChatClient
from .policy_graph import PolicyGraph, merge_passages
from .retrieval import Hit, PolicyIndex

INVOICE_ID = re.compile(r"\bINV\d{3,}\b", re.IGNORECASE)

ANSWER_SYSTEM = """\
You answer the questions of an auditor about a procurement policy, about audited invoices and about what the audit found in the ledger. Use only what is in the user message: the FACTS, the LEDGER FACTS, the PASSAGES and, when present, the AUDIT RECORD.

- The FACTS are read by code from the policy's clause registry ([F1], [F2], ...) and are exact: prefer them for limits, thresholds, which role may approve an amount and what changed between versions.
- The LEDGER FACTS ([C1], [C2], ...) are computed by code from the audited ledger and are exact. For a question about vendors, invoices, approvers, rings, counts or amounts in the ledger, answer from them: name every vendor, approver and number the question asks for that they give. They describe the ledger, not the policy, so the PASSAGES need not mention any vendor or approver, and passages that say nothing about the question do not make it unanswerable. Never state a name, count or amount about the ledger that no ledger fact gives.
- The AUDIT RECORD is the authority on what was found for an invoice: name only the rules its findings cite, and never say that an invoice was flagged under a rule the record does not name.

Cite each fact you use by its label, such as [F1] or [C1], and each passage you use by its number in square brackets. Only if none of the FACTS, the LEDGER FACTS, the PASSAGES and the AUDIT RECORD contain the answer, say that the documents do not answer the question.

Reply with one JSON object and nothing else:
{"answer": "<a few sentences, with [F#], [C#] and [n] citations>", "passages_used": [<numbers of the passages used; an empty list when the answer rests on facts only>]}"""

SQL_SYSTEM = """\
You write one {dialect} SELECT statement that answers the question of an auditor about the audit database described below.

Rules
- One statement, SELECT only. Use only the tables and columns listed.
- The outcome of the audit is in v_latest_results, one row per audited invoice: its route and its workflow_status. Join it to invoices or vendor_master on invoice_id or vendor_id.
- v_review_queue lists exactly the invoices that are waiting for review, with the vendor name.
- invoices.approval_status and approval_logs describe the approval of the payment in the ledger. They say nothing about the audit or the review.
- Return at most {limit} rows; add an ORDER BY when the question asks for a ranking.

DATABASE
{schema}

Reply with one JSON object and nothing else:
{{"sql": ["<the statement>"], "explanation": "<one sentence on what the rows show>"}}"""

# Tables and views the copilot may read. The benchmark labels, the policy
# chunks and the bookkeeping table are not among them.
READABLE = ["invoices", "vendor_master", "purchase_orders", "goods_receipts", "approval_logs", "v_latest_results",
            "v_review_queue", "audit_flags", "review_decisions", "policy_clauses"]
UNDERLYING = ["audit_results", "audit_runs", "latest_results"]          # read through the views
ROW_LIMIT = 200
TIME_LIMIT_S = 10.0


# --------------------------------------------------------- policy questions
def passages_text(hits: list[Hit]) -> str:
    return "\n".join(f"[{i}] {hit.source}: {hit.text}" for i, hit in enumerate(hits, start=1))


def answer(question: str, conn: db.Database, index: PolicyIndex, client: ChatClient | None = None,
           k: int = 4, invoice_id: str | None = None, graph: PolicyGraph | None = None,
           cases: CaseGraph | None = None) -> dict:
    """Answer a question from the policy documents and, for a named invoice, its stored audit pack.

    With a model, the question is first restated in the documents' vocabulary,
    which is what lets a question in everyday words find the right passage.
    With the policy graph, its facts (limits, the role an amount needs, what
    changed between versions, what checks a rule) come too, and the passages
    they cite come before the retrieved ones (docs/POLICY_GRAPH.md).
    """
    hits = index.search(question, k=k, client=client)
    linked = graph.query(question, index) if graph is not None else None
    ledger = cases.query(question) if cases is not None else None
    if linked is not None:
        hits = merge_passages(linked.passages, hits, k)
    found = invoice_id or (INVOICE_ID.search(question).group(0).upper() if INVOICE_ID.search(question) else None)
    pack = None
    if found:
        row = db.latest_result(conn, found)
        pack = json.loads(row["audit_pack"]) if row else None
    if pack:
        # For an audited invoice, the passages of the rules its findings cite come first: a question such as
        # "why was it flagged" names no rule, so retrieval by its wording alone finds the wrong ones.
        cited = list(dict.fromkeys(f["clause"] for f in pack.get("flags", [])))
        first = [hit for clause in cited for hit in index.passages_of(clause)]
        hits = (first + [h for h in hits if h.clause_id not in cited])[: max(k, len(first))]
    out = {"question": question, "passages": hits, "invoice_id": found, "audit_pack": pack,
           "answer": None, "sources": [], "calls": [], "facts": linked.facts if linked else [],
           "graph_nodes": linked.nodes if linked else [], "case_facts": ledger.facts if ledger else [],
           "case_nodes": ledger.nodes if ledger else []}
    if client is None:
        return out
    user = f"QUESTION\n{question}\n\n"
    if linked is not None and linked.facts:
        user += f"FACTS\n{linked.facts_text()}\n\n"
    if ledger is not None and ledger.facts:
        user += f"LEDGER FACTS\n{ledger.facts_text()}\n\n"
    user += f"PASSAGES\n{passages_text(hits)}"
    if found:
        user += "\n\nAUDIT RECORD\n" + (render_markdown(pack) if pack else f"{found} has not been audited.")
    data, calls = call_json(client, [{"role": "system", "content": ANSWER_SYSTEM}, {"role": "user", "content": user}],
                            "passages_used", stage="copilot", agent="copilot", temperature=0.0)
    out["calls"] = calls
    if data is None or not isinstance(data.get("answer"), str):
        out["answer"] = "The model did not return a usable answer; the retrieved passages are shown below."
        return out
    used = [n for n in data["passages_used"] if isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= len(hits)]
    out["answer"] = data["answer"].strip()
    out["sources"] = [hits[n - 1] for n in dict.fromkeys(used)]
    return out


# ----------------------------------------------------------- data questions
def schema_text(conn: db.Database) -> str:
    lines = []
    for table in READABLE:
        columns = [f"{name} {kind}" for name, kind in conn.columns(table).items() if name != "audit_pack"]
        lines.append(f"{table}({', '.join(columns)})")
    lines.append("Values: route is approve, sample or escalate. workflow_status is AUTO_APPROVED, PENDING_REVIEW, "
                 "NOT_SAMPLED, REVIEW_APPROVED, REVIEW_REJECTED or REVIEW_OVERRIDDEN. severity is critical, high, "
                 "medium or low. audit_flags.source is D for a control and L for an LLM agent; "
                 "audit_flags.status is kept or removed. Flags such as blacklisted are 0 or 1. "
                 "Dates are YYYY-MM-DD. approval_logs.action_taken is exactly 'Approved' or 'Escalated' (capital "
                 "first letter); approval_logs.amount_limit is the limit of the approver's role, and "
                 "approval_logs.transaction_id is the invoice_id. audit_flags.clause is a rule number and "
                 "audit_flags joins to v_latest_results on result_id.")
    rules = conn.execute("SELECT clause_id, title, severity FROM policy_clauses WHERE version = "
                         "(SELECT version FROM company_policies WHERE is_active = 1 LIMIT 1) ORDER BY clause_id").fetchall()
    if rules:
        lines.append("Rules (audit_flags.clause): " + "; ".join(f"{c} {t} ({s})" for c, t, s in rules)
                     + ". An invoice approved above its approver's limit is a finding of rule 5.1.1; a vendor "
                       "registered twice shows as two vendor_master rows with the same pan_number.")
    return "\n".join(lines)


class UnsafeQuery(ValueError):
    pass


# Functions a SELECT could use to leave the guards behind: change the role or a setting, run a query given as a
# string (which the name check cannot see), or reach files and other servers. Also refused: identifiers and
# strings written with Unicode escapes (U&"..."), which could spell any of these names.
ESCAPING_FUNCTIONS = re.compile(
    r"\b(set_config|current_setting|query_to_xml\w*|cursor_to_xml\w*|table_to_xml\w*|schema_to_xml\w*|"
    r"database_to_xml\w*|ts_stat|dblink\w*|lo_\w+)\s*\(|\bU&['\"]", re.IGNORECASE)


def check_sql(sql: str) -> str:
    """Reject anything that is not a single SELECT statement. Returns the statement without a trailing semicolon."""
    statement = sql.strip().rstrip(";").strip()
    if not statement:
        raise UnsafeQuery("the statement is empty")
    if ";" in statement:
        raise UnsafeQuery("only one statement is allowed")
    if not re.match(r"(?is)^\s*(select|with)\b", statement):
        raise UnsafeQuery("only SELECT statements are allowed")
    return statement


def run_select(target: Path | str, sql: str, limit: int = ROW_LIMIT) -> tuple[list[str], list[tuple]]:
    """Run a checked SELECT on a read-only connection restricted to the readable tables."""
    statement = check_sql(sql)
    conn = db.connect(target, read_only=True)
    try:
        allowed = {t.lower() for t in READABLE + UNDERLYING}
        # Every table and view that is not readable, plus the database's own
        # catalogue. A name that is neither (a CTE, a subquery alias) is fine.
        catalogue = {"sqlite_master", "sqlite_schema", "sqlite_temp_master", "sqlite_sequence",
                     "pg_catalog", "information_schema"}
        forbidden = (conn.relations() - allowed) | catalogue
        pattern = r"\b(" + "|".join(sorted(map(re.escape, forbidden))) + r")\b|\bpg_\w+"
        named = re.search(pattern, statement, re.IGNORECASE)
        if named:
            raise UnsafeQuery(f"the statement refers to {named.group(0)}, which the copilot may not read")
        escaping = ESCAPING_FUNCTIONS.search(statement)
        if escaping:
            raise UnsafeQuery(f"the statement uses {escaping.group(0).rstrip('(').strip()}, which the copilot may "
                              "not call")
        if conn.backend == "sqlite":
            deadline = time.monotonic() + TIME_LIMIT_S

            def authorize(action, arg1, arg2, database, source):
                if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION):
                    return sqlite3.SQLITE_OK
                if action == sqlite3.SQLITE_READ:
                    return sqlite3.SQLITE_DENY if (arg1 or "").lower() in forbidden else sqlite3.SQLITE_OK
                return sqlite3.SQLITE_DENY

            conn.raw.set_authorizer(authorize)
            conn.raw.set_progress_handler(lambda: time.monotonic() > deadline, 10000)
        else:
            if not conn.scalar("SELECT 1 FROM pg_roles WHERE rolname = ?", (db.READER_ROLE,)):
                raise UnsafeQuery(f"on PostgreSQL the copilot's data questions run as the role {db.READER_ROLE}, "
                                  "which this server does not have (`python scripts/pg_local.py init` and "
                                  "deploy/postgres/init.sql create it)")
            conn.execute(f"SET statement_timeout = {int(TIME_LIMIT_S * 1000)}")
            conn.execute(f"SET ROLE {db.READER_ROLE}")
        cursor = conn.execute(statement)
        columns = [d[0] for d in cursor.description or []]
        return columns, [tuple(r) for r in cursor.fetchmany(limit)]
    except UnsafeQuery:
        raise
    except Exception as error:                        # any database error: report it, never raise it raw
        raise UnsafeQuery(str(error).strip().splitlines()[0]) from error
    finally:
        conn.close()


def data_question(question: str, target: Path | str, client: ChatClient) -> dict:
    """Answer a question about the data with one model-written, checked, read-only SELECT."""
    conn = db.connect(target, read_only=True)
    try:
        dialect = "SQLite" if conn.backend == "sqlite" else "PostgreSQL"
        system = SQL_SYSTEM.format(dialect=dialect, limit=ROW_LIMIT, schema=schema_text(conn))
    finally:
        conn.close()
    messages = [{"role": "system", "content": system}, {"role": "user", "content": question}]
    out = {"question": question, "sql": None, "explanation": "", "columns": [], "rows": [], "error": None, "calls": []}
    for attempt in range(2):
        data, calls = call_json(client, messages, "sql", stage="copilot", agent="sql", temperature=0.0)
        out["calls"] += calls
        if data is None or not data["sql"] or not isinstance(data["sql"][0], str):
            out["error"] = "the model did not return a statement"
            return out
        out["sql"], out["explanation"] = data["sql"][0], str(data.get("explanation") or "")
        try:
            out["columns"], out["rows"] = run_select(target, out["sql"])
            out["error"] = None
            if out["rows"] or attempt:
                if not out["rows"]:
                    # The statement ran and found nothing: say so, rather than show a model's description of rows
                    # that do not exist.
                    out["explanation"] = ("The statement ran and returned no rows. Either nothing matches, or a "
                                          "condition does not match how the data is written; check the statement.")
                return out
            messages = messages + [{"role": "assistant", "content": json.dumps(data)},
                                   {"role": "user", "content": "That statement returned no rows. A condition may "
                                                               "not match the values listed in the database "
                                                               "description. Reply again with a corrected "
                                                               "statement, or the same one if nothing matches."}]
        except UnsafeQuery as error:
            out["error"] = str(error)
            messages = messages + [{"role": "assistant", "content": json.dumps(data)},
                                   {"role": "user", "content": f"That statement was rejected: {error}. "
                                                               "Reply again with a corrected statement."}]
    return out
