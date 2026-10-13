"""AuditIQ dashboard.

    streamlit run app/dashboard.py

Reads and writes the database of the command line (.auditiq/auditiq.db, or the
file named in AUDITIQ_DB). Run `python -m auditiq setup --dataset <folder>` and
`python -m auditiq run --config C1` first.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auditiq import copilot, db, service  # noqa: E402
from auditiq.audit_pack import render_markdown  # noqa: E402
from auditiq.config import configure_logging  # noqa: E402
from auditiq.graph import PRESETS  # noqa: E402
from auditiq.llm import LLMSettings, OpenAIChatClient, ResponseCache  # noqa: E402
from auditiq.retrieval import EndpointEmbedder, PolicyIndex  # noqa: E402

configure_logging()
PAGES = ["Overview", "Review queue", "Invoice", "Policy", "Copilot"]
STATES = {
    db.AUTO_APPROVED: "Approved automatically",
    db.PENDING_REVIEW: "Waiting for review",
    db.NOT_SAMPLED: "Sampled queue, not selected",
    "REVIEW_APPROVED": "Approved by reviewer",
    "REVIEW_REJECTED": "Rejected by reviewer",
    "REVIEW_OVERRIDDEN": "Overridden by reviewer",
}
# One hue for a single series (validated against both chart surfaces); text stays in ink colours.
BAR = {"light": "#2a78d6", "dark": "#3987e5"}
INK = {"light": "#52514e", "dark": "#c3c2b7"}

st.set_page_config(page_title="AuditIQ", layout="wide")


def frame(conn, sql: str, params: tuple = ()) -> pd.DataFrame:
    return conn.frame(sql, params)


def scalar(conn, sql: str, params: tuple = ()):
    return conn.scalar(sql, params)


def theme() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:
        return "light"


def chat_client() -> OpenAIChatClient | None:
    """The configured model, or None; the pages work without one."""
    try:
        return OpenAIChatClient(LLMSettings.from_env(), ResponseCache())
    except RuntimeError:
        return None


def show_pack(conn, row) -> None:
    # The pack's own headings are page-level; inside a page they become sub-headings.
    text = render_markdown(json.loads(row["audit_pack"]))
    st.markdown(text.replace("\n## ", "\n#### ").replace("# Audit pack", "### Audit pack", 1))
    st.caption(f"{STATES.get(row['workflow_status'], row['workflow_status'])} · result {row['result_id']} · "
               f"run {row['run_id']} ({row['configuration']}, {row['model'] or 'no model'}) · {row['created_at']}")
    with st.expander("Audit trail"):
        st.dataframe(frame(conn, "SELECT seq AS step, stage, actor, detail, prompt_tokens, completion_tokens, "
                                 "latency_ms FROM audit_trail WHERE result_id = ? ORDER BY seq",
                           (int(row["result_id"]),)), hide_index=True, width="stretch")


def show_records(conn, invoice_id: str) -> None:
    txn = db.extract_one(conn, invoice_id)
    for title, record in (("Invoice", txn["invoice"]), ("Purchase order", txn["po"]),
                          ("Goods receipt note", txn["grn"]), ("Vendor", txn["vendor"])):
        st.markdown(f"**{title}**")
        if record is None:
            st.write("None on record.")
        else:
            st.dataframe(pd.DataFrame([record]), hide_index=True, width="stretch")
    st.markdown("**Approval log**")
    st.dataframe(pd.DataFrame(txn["approvals"]), hide_index=True, width="stretch")
    st.markdown(f"**Other invoices of the vendor** ({len(txn['vendor_history'])})")
    st.dataframe(pd.DataFrame(txn["vendor_history"]), hide_index=True, width="stretch", height=240)


# ---------------------------------------------------------------- overview
def page_overview(conn) -> None:
    st.title("Audit overview")
    dataset = conn.execute("SELECT value FROM meta WHERE key = 'dataset'").fetchone()
    policy = conn.execute("SELECT version FROM company_policies WHERE is_active = 1").fetchone()
    st.caption(f"Ledger: {dataset[0] if dataset else 'none loaded'} · active policy: "
               f"{'version ' + policy[0] if policy else 'none'}")

    states = {r[0]: int(r[1]) for r in conn.execute(
        "SELECT workflow_status, COUNT(*) FROM v_latest_results GROUP BY workflow_status")}
    reviewed = sum(n for state, n in states.items() if state.startswith("REVIEW_"))
    tiles = [
        ("Invoices in the ledger", scalar(conn, "SELECT COUNT(*) FROM invoices")),
        ("Audited", sum(states.values())),
        ("Auto-approved", states.get(db.AUTO_APPROVED, 0)),
        ("Waiting for review", states.get(db.PENDING_REVIEW, 0)),
        ("Reviewed", reviewed),
        ("Findings", scalar(conn, "SELECT COUNT(*) FROM audit_flags f JOIN v_latest_results l "
                                  "ON l.result_id = f.result_id WHERE f.status = 'kept'")),
    ]
    # Two rows of three, so that a count keeps all its digits in a narrow window.
    for column, (label, value) in zip(st.columns(3) + st.columns(3), tiles):
        column.metric(label, f"{value:,}")

    findings = frame(conn, """
        SELECT f.clause AS rule, COALESCE(c.title, 'not in the policy') AS title, f.severity,
               CASE f.source WHEN 'D' THEN 'control' ELSE 'agent' END AS source, COUNT(*) AS findings
        FROM audit_flags f
        JOIN v_latest_results l ON l.result_id = f.result_id
        LEFT JOIN policy_clauses c ON c.version = l.policy_version AND c.clause_id = f.clause
        WHERE f.status = 'kept'
        GROUP BY f.clause, c.title, f.severity, source ORDER BY findings DESC""")
    st.subheader("Findings by rule")
    if findings.empty:
        st.info("No audit result yet. Run `python -m auditiq run --config C1`.")
    else:
        findings["label"] = findings["rule"] + " " + findings["title"]
        mode = theme()
        base = alt.Chart(findings).encode(
            y=alt.Y("label:N", sort="-x", title=None,
                    axis=alt.Axis(labelLimit=280, labelOverlap=False, labelColor=INK[mode])),
            x=alt.X("findings:Q", title="Findings", axis=alt.Axis(tickMinStep=1, labelColor=INK[mode],
                                                                 titleColor=INK[mode])),
            tooltip=[alt.Tooltip("rule:N", title="Rule"), alt.Tooltip("title:N", title="Title"),
                     alt.Tooltip("severity:N", title="Severity"), alt.Tooltip("source:N", title="Found by"),
                     alt.Tooltip("findings:Q", title="Findings", format=",")])
        bars = base.mark_bar(color=BAR[mode], cornerRadiusEnd=4, height={"band": 0.72})
        values = base.mark_text(align="left", dx=5, color=INK[mode]).encode(text=alt.Text("findings:Q", format=","))
        # A fixed step per rule, so that every rule keeps its own row and label.
        st.altair_chart((bars + values).properties(height=alt.Step(28)), width="stretch")
        with st.expander("As a table"):
            st.dataframe(findings[["rule", "title", "severity", "source", "findings"]], hide_index=True,
                         width="stretch")

    left, right = st.columns(2)
    left.subheader("Vendors with the most invoices waiting for review")
    left.dataframe(frame(conn, "SELECT vendor_name AS vendor, COUNT(*) AS waiting, ROUND(SUM(amount), 2) AS amount "
                               "FROM v_review_queue GROUP BY vendor_name ORDER BY waiting DESC, amount DESC LIMIT 10"),
                   hide_index=True, width="stretch")
    right.subheader("Audit runs")
    right.dataframe(frame(conn, "SELECT u.run_id AS run, u.configuration, u.policy_version AS policy, "
                                "COALESCE(u.model, 'none') AS model, COUNT(r.result_id) AS invoices, u.started_at "
                                "FROM audit_runs u LEFT JOIN audit_results r ON r.run_id = u.run_id "
                                "GROUP BY u.run_id ORDER BY u.run_id DESC LIMIT 10"),
                    hide_index=True, width="stretch")


# ------------------------------------------------------------ review queue
def page_queue(conn) -> None:
    st.title("Review queue")
    queue = pd.DataFrame([dict(r) for r in db.review_queue(conn)])
    if queue.empty:
        st.success("No invoice is waiting for review.")
        return
    st.caption(f"{len(queue):,} invoices are waiting. Highest weighted risk first.")
    st.dataframe(queue[["invoice_id", "vendor_name", "invoice_date", "amount", "route", "rc", "r0", "flag_count",
                        "configuration"]].rename(columns={"rc": "weighted_risk", "r0": "count_based_risk",
                                                          "flag_count": "findings"}),
                 hide_index=True, width="stretch", height=260)
    invoice_id = st.selectbox("Invoice to review", queue["invoice_id"])
    row = db.latest_result(conn, invoice_id)
    pack, records = st.columns([3, 2])
    with pack:
        show_pack(conn, row)
    with records:
        with st.expander("Records", expanded=True):
            show_records(conn, invoice_id)

    with st.form("decision"):
        st.subheader("Decision")
        decision = st.radio("Decision", ["approve", "reject", "override"], horizontal=True,
                            captions=["The findings do not prevent payment.", "Not to be paid as submitted.",
                                      "Set the findings aside; needs a justification."])
        reviewer = st.text_input("Reviewer")
        justification = st.text_area("Justification")
        if st.form_submit_button("Record decision"):
            try:
                db.record_decision(conn, int(row["result_id"]), decision, reviewer, justification)
            except ValueError as error:
                st.error(str(error))
            else:
                st.session_state["notice"] = f"Recorded: {decision} on {invoice_id} by {reviewer.strip()}."
                st.rerun()


# ----------------------------------------------------------------- invoice
def page_invoice(conn) -> None:
    st.title("Invoice")
    first = conn.execute("SELECT invoice_id FROM invoices ORDER BY invoice_id LIMIT 1").fetchone()
    invoice_id = st.text_input("Invoice id", value=first[0] if first else "").strip().upper()
    if not invoice_id:
        return
    if db.extract_one(conn, invoice_id) is None:
        st.error(f"{invoice_id} is not in the ledger.")
        return
    row = db.latest_result(conn, invoice_id)
    client = chat_client()
    options = list(PRESETS) if client else ["C1"]
    left, right = st.columns([3, 2])
    with left:
        st.subheader("Audit result")
        if row is None:
            st.info("This invoice has not been audited.")
        else:
            show_pack(conn, row)
        config = st.selectbox("Configuration", options, help="C1 uses the controls only. The others call the model; "
                                                             "on a laptop CPU that takes minutes.")
        if st.button("Audit this invoice now"):
            with st.spinner(f"Auditing with {config}"):
                service.audit_invoices(conn, PRESETS[config], db.read_policy(conn),
                                       client if PRESETS[config].agents != "none" else None, [invoice_id])
            st.rerun()
    with right:
        st.subheader("Records")
        show_records(conn, invoice_id)


# ------------------------------------------------------------------ policy
def policy_index(conn) -> PolicyIndex | None:
    try:
        return PolicyIndex.from_db(conn, embedder=EndpointEmbedder.from_env())
    except ValueError:
        return None


def show_hits(hits) -> None:
    for i, hit in enumerate(hits, start=1):
        st.markdown(f"**[{i}] {hit.source}**")
        st.write(hit.text)


def page_policy(conn) -> None:
    st.title("Policy")
    versions = [r[0] for r in conn.execute("SELECT version FROM company_policies ORDER BY version")]
    if not versions:
        st.info("No policy is stored. Run `python -m auditiq setup --dataset <folder>`.")
        return
    active = scalar(conn, "SELECT version FROM company_policies WHERE is_active = 1")
    choice = st.selectbox("Active version", versions, index=versions.index(active),
                          help="The version that the next audit applies.")
    if choice != active and st.button(f"Make version {choice} active"):
        db.set_active_policy(conn, choice)
        st.rerun()

    st.subheader("Search the policy documents")
    index = policy_index(conn)
    if index is None:
        st.info("No policy document has been ingested.")
    else:
        client = chat_client()
        ranking = ("meaning (embeddings)" if "dense" in index.modes
                   else "wording only: no embedding model is configured")
        st.caption(f"{len(index.chunks)} passages of version {active} and the procedure documents. Ranking by {ranking}.")
        question = st.text_input("Question or keywords", placeholder="bill raised on the weekend")
        restate = st.checkbox("Let the model restate the question in the policy's wording first",
                              disabled=client is None, help="Needs a configured model.")
        if question:
            with st.spinner("Searching"):
                show_hits(index.search(question, k=4, client=client if restate else None))

    st.subheader(f"Rules of version {active}")
    rules = frame(conn, "SELECT clause_id AS rule, title, severity, "
                        "CASE kind WHEN 'control' THEN 'control' ELSE 'agent' END AS decided_by "
                        "FROM policy_clauses WHERE version = ? ORDER BY clause_id", (active,))
    parameters: dict[str, list[str]] = {}
    for row in conn.execute("SELECT clause_id, param_name, param_value FROM policy_parameters WHERE version = ? "
                            "ORDER BY clause_id, param_name", (active,)):
        parameters.setdefault(row["clause_id"], []).append(f"{row['param_name']} = {row['param_value']}")
    rules["parameters"] = rules["rule"].map(lambda rule: "; ".join(parameters.get(rule, [])))
    st.dataframe(rules, hide_index=True, width="stretch")
    st.subheader("Ingested documents")
    st.dataframe(frame(conn, """
        SELECT d.file_name AS document, d.version, d.pages, COUNT(c.chunk_id) AS passages,
               SUM(CASE WHEN c.kind = 'clause' THEN 1 ELSE 0 END) AS rules,
               SUM(COALESCE(c.verified, 0)) AS rules_matching_the_registry,
               MAX(COALESCE(c.embed_model, 'none')) AS embedding_model, d.ingested_at
        FROM policy_documents d LEFT JOIN policy_chunks c ON c.doc_id = d.doc_id GROUP BY d.doc_id ORDER BY d.file_name"""),
        hide_index=True, width="stretch")


# ----------------------------------------------------------------- copilot
def page_copilot(conn) -> None:
    st.title("Copilot")
    client = chat_client()
    if client is None:
        st.warning("No model is configured (see .env.example). Policy questions return the retrieved passages; "
                   "data questions need a model.")
    else:
        st.caption(f"Model: {client.settings.model}. Answers come from the retrieved passages and the stored audit "
                   "packs; data questions run as one read-only SELECT.")
    policy_tab, data_tab = st.tabs(["Policy and invoices", "Data"])
    with policy_tab:
        question = st.text_input("Question", placeholder="Why is INV40005 escalated?", key="policy_question")
        if question:
            index = policy_index(conn)
            if index is None:
                st.info("No policy document has been ingested.")
            else:
                with st.spinner("Answering"):
                    out = copilot.answer(question, conn, index, client)
                if out["answer"]:
                    st.write(out["answer"])
                    st.caption("Sources: " + ("; ".join(h.source for h in out["sources"]) or "none cited"))
                with st.expander("Retrieved passages", expanded=out["answer"] is None):
                    show_hits(out["passages"])
                if out["invoice_id"] and out["audit_pack"] is None:
                    st.info(f"{out['invoice_id']} has no stored audit result.")
    with data_tab:
        question = st.text_input("Question", placeholder="Which five vendors have the most escalated invoices?",
                                 key="data_question", disabled=client is None)
        if question and client is not None:
            with st.spinner("Writing and running the query"):
                out = copilot.data_question(question, db.default_target(), client)
            st.code(out["sql"] or "", language="sql")
            if out["error"]:
                st.error(f"Not run: {out['error']}")
            else:
                st.dataframe(pd.DataFrame(out["rows"], columns=out["columns"]), hide_index=True, width="stretch")
                st.caption(out["explanation"])


def main() -> None:
    try:
        conn = db.connect()
    except db.DatabaseUnavailable as error:
        st.error(str(error))
        st.stop()
    try:
        st.sidebar.title("AuditIQ")
        page = st.sidebar.radio("Page", PAGES)
        notice = st.session_state.pop("notice", None)
        if notice:
            st.success(notice)
        {"Overview": page_overview, "Review queue": page_queue, "Invoice": page_invoice,
         "Policy": page_policy, "Copilot": page_copilot}[page](conn)
    finally:
        conn.close()


main()
