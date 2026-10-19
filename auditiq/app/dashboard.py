"""AuditIQ dashboard.

    streamlit run app/dashboard.py

Reads and writes the database of the command line (.auditiq/auditiq.db, or the
file named in AUDITIQ_DB). Run `python -m auditiq setup --dataset <folder>` and
`python -m auditiq run --config C1` first.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auditiq import copilot, db, ledger_import, policy_extract, policy_llm, service  # noqa: E402
from auditiq.audit_pack import render_markdown  # noqa: E402
from auditiq.config import configure_logging  # noqa: E402
from auditiq.graph import PRESETS  # noqa: E402
from auditiq.llm import LLMSettings, OpenAIChatClient, ResponseCache  # noqa: E402
from auditiq.policy import POLICY_DIR, PROJECT_ROOT  # noqa: E402
from auditiq.retrieval import EndpointEmbedder, PolicyIndex  # noqa: E402

configure_logging()
PAGES = ["Overview", "Review queue", "Invoice", "Policy", "Copilot"]
# Policy documents offered for adoption besides an upload, and where uploads are kept.
POLICY_FOLDERS = [POLICY_DIR / "pdf", POLICY_DIR / "variants", POLICY_DIR / "freeform" / "pdf"]
UPLOADS = PROJECT_ROOT / ".auditiq" / "uploads"
DATA_DIR = PROJECT_ROOT / "data"
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
    audit_new_ledger(conn)

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
    load_ledger(conn)


def load_ledger(conn) -> None:
    """Replace the ledger with a workbook, a zip archive of CSV files or a dataset of the project; then audit it."""
    st.subheader("Load a ledger")
    st.caption("An Excel workbook with one sheet per table (vendor_master, purchase_orders, goods_receipts, invoices, "
               "approval_logs), or a .zip archive of the same tables as CSV files. The file is checked first; a ledger "
               "with any problem replaces nothing.")
    known = {folder.name: folder for folder in sorted(DATA_DIR.iterdir()) if (folder / "invoices.csv").exists()} \
        if DATA_DIR.exists() else {}
    upload = st.file_uploader("Ledger file", type=["xlsx", "zip"])
    pick = st.selectbox("or a dataset of the project", ["(none)", *known])
    if upload is not None:
        UPLOADS.mkdir(parents=True, exist_ok=True)
        source = UPLOADS / f"ledger_{Path(upload.name).name}"
        source.write_bytes(upload.getvalue())
        name = Path(upload.name).stem
    elif pick != "(none)":
        source, name = known[pick], pick
    else:
        return

    ledger = ledger_import.read(source, conn)
    ledger.name = name
    if not ledger.usable:
        st.error("This ledger cannot be loaded; nothing was replaced.")
        for problem in ledger.problems:
            st.error(problem)
        return
    counts = ledger.counts()
    st.info(f"{name}: {counts.get('invoices', 0):,} invoices from {counts.get('vendor_master', 0):,} vendors, "
            f"checked and ready to load.")
    confirm = st.checkbox("Replace the current ledger with its audit results and review decisions")
    if st.button("Load the ledger", disabled=not confirm):
        ledger_import.load(conn, ledger)
        st.session_state["notice"] = f"Ledger {name} loaded: {counts.get('invoices', 0):,} invoices, not yet audited."
        st.rerun()


def audit_new_ledger(conn) -> None:
    """A ledger that has just been loaded has no result: offer to audit every invoice with the controls."""
    invoices = scalar(conn, "SELECT COUNT(*) FROM invoices")
    if not invoices or scalar(conn, "SELECT COUNT(*) FROM v_latest_results"):
        return
    st.warning(f"None of the {invoices:,} invoices of this ledger has been audited yet.")
    if st.button("Audit every invoice with the controls"):
        bar = st.progress(0.0, text="Auditing")
        run_id = service.audit_invoices(
            conn, PRESETS["C1"], db.read_policy(conn), None, db.invoice_ids(conn), note="ledger audited from the dashboard",
            progress=lambda done, total: bar.progress(done / total, text=f"Auditing: {done:,} of {total:,}")
            if done % 200 == 0 or done == total else None)
        summary = service.run_summary(conn, run_id)
        st.session_state["notice"] = (f"{summary['invoices']:,} invoices audited with the controls: "
                                      f"{summary['flags']:,} findings, "
                                      f"{summary['states'].get(db.PENDING_REVIEW, 0):,} waiting for review.")
        st.rerun()


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


def adopt_policy_document(conn, active: str) -> None:
    """A policy PDF becomes a policy version: its thresholds are read from its wording."""
    st.subheader("Adopt a policy document")
    st.caption("The thresholds are read from the wording of the document and compared with the active version. "
               "Nothing is stored until you adopt it.")
    known = {str(p.relative_to(PROJECT_ROOT)): p for folder in POLICY_FOLDERS if folder.exists()
             for p in sorted(folder.glob("*.pdf"))}
    upload = st.file_uploader("Policy PDF", type="pdf")
    pick = st.selectbox("or a document in the policy folder", ["(none)", *known])
    if upload is not None:
        UPLOADS.mkdir(parents=True, exist_ok=True)
        path = UPLOADS / Path(upload.name).name
        path.write_bytes(upload.getvalue())
    elif pick != "(none)":
        path = known[pick]
    else:
        return

    found = policy_extract.build(path, db.read_policy(conn).registry)
    st.markdown(f"**{found.title}**: version {found.version or 'not stated'}, {found.pages} page(s).")
    for problem in found.problems:
        st.error(problem)
    if not found.usable:
        st.warning("This document cannot be adopted as it is: its rules are not in the wording the system reads by "
                   "pattern.")
        adopt_with_model(conn, path)
        return
    if found.changes:
        rows = []
        for c in found.changes:
            if isinstance(c["to"], dict):                 # one row per role whose limit differs
                rows += [{"rule": c["clause"], "parameter": f"{c['parameter']}: {role}",
                          f"version {active}": json.dumps(c["from"].get(role)), "this document": json.dumps(limit)}
                         for role, limit in c["to"].items() if c["from"].get(role) != limit]
            else:
                rows.append({"rule": c["clause"], "parameter": c["parameter"],
                             f"version {active}": json.dumps(c["from"]), "this document": json.dumps(c["to"])})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.info(f"Every threshold of this document equals version {active}.")
    activate = st.checkbox("Make it the active version", value=True)
    replace = st.checkbox("Replace the stored version of the same number, if there is one")
    if st.button(f"Adopt version {found.version}"):
        report = policy_extract.adopt(conn, path, activate=activate, replace=replace)
        if report["adopted"]:
            st.session_state["notice"] = (f"Policy version {report['version']} adopted from {report['file']}"
                                          + (" and made active." if activate else "."))
            st.rerun()
        for problem in report["problems"]:
            st.error(problem)


def adopt_with_model(conn, path: Path) -> None:
    """A policy in its own wording: the model proposes, code verifies, the reviewer confirms."""
    client = chat_client()
    if client is None:
        st.info("With a configured model the system can read a policy in its own wording and propose the thresholds "
                "for your confirmation.")
        return
    key = f"proposal:{path.name}"
    reference = db.read_policy(conn).registry
    if st.button("Let the model read this document"):
        reader = OpenAIChatClient(dataclasses.replace(client.settings, max_tokens=2500), ResponseCache())
        with st.spinner("The model is reading the document. Without a GPU this takes several minutes."):
            st.session_state[key] = policy_llm.propose(path, reference, reader)
    proposal = st.session_state.get(key)
    if proposal is None:
        return
    st.caption(f"Read by {proposal.model}. A value is verified when its quote is in the document word for word and "
               "the value is written in that quote. Verified does not mean right: compare each value with its quote.")
    for problem in proposal.problems:
        st.error(problem)
    st.dataframe(pd.DataFrame([{"rule": i["clause"], "parameter": i["parameter"], "proposed": json.dumps(i["value"]),
                                f"version {reference['version']}": json.dumps(i["reference"]), "status": i["status"],
                                "page": i["page"], "quote, or why it is held back": i["reason"] or i["quote"]}
                               for i in proposal.items]), hide_index=True, width="stretch")
    with st.form("confirm_policy"):
        typed = {(i["clause"], i["parameter"]): st.text_input(
            f"Rule {i['clause']} {i['parameter']}: your value (as JSON)", key=f"value:{path.name}:{i['clause']}:{i['parameter']}")
            for i in proposal.items if i["status"] != policy_llm.VERIFIED}
        passages = {clause: st.text_input(f"Rule {clause}: the passage of the document that states it",
                                          key=f"passage:{path.name}:{clause}")
                    for clause, rule in proposal.rules.items() if not rule["located"]}
        accept = st.checkbox("I have compared every verified value with its quote and accept them")
        reviewer = st.text_input("Your name")
        version = st.text_input("Version", value=proposal.version or "")
        activate = st.checkbox("Make it the active version", value=True)
        if st.form_submit_button("Adopt the confirmed policy"):
            for clause in policy_llm.add_passages(proposal, {c: text for c, text in passages.items() if text.strip()}):
                st.error(f"The passage given for rule {clause} is not in the document.")
            try:
                overrides = {name: json.loads(raw) for name, raw in typed.items() if raw.strip()}
                values, still_open = policy_llm.decide(proposal, accept_verified=accept, overrides=overrides)
            except ValueError as error:
                st.error(f"A typed value could not be used: {error}")
                return
            for line in still_open:
                st.error(line)
            if still_open:
                return
            report = policy_llm.adopt(conn, path, proposal, reference, values, reviewer, version=version.strip() or None,
                                      activate=activate)
            if report["adopted"]:
                st.session_state.pop(key, None)
                st.session_state["notice"] = (f"Policy version {report['version']} adopted from {report['file']}, "
                                              f"confirmed by {reviewer.strip()}" + (" and made active." if activate else "."))
                st.rerun()
            for problem in report["problems"]:
                st.error(problem)


def apply_policy_to_ledger(conn, active: str) -> None:
    """Audit every invoice again with the controls, so that the stored results follow the active policy."""
    audited = scalar(conn, "SELECT COUNT(*) FROM v_latest_results")
    stale = scalar(conn, "SELECT COUNT(*) FROM v_latest_results WHERE policy_version <> ?", (active,))
    if not audited or not stale:
        return
    st.warning(f"{stale:,} of {audited:,} audited invoices were last audited under another policy version than "
               f"{active}. Their results do not yet follow the active policy.")
    if st.button(f"Audit the ledger under version {active} (controls only)"):
        ids = db.invoice_ids(conn)
        bar = st.progress(0.0, text="Auditing")
        run_id = service.audit_invoices(
            conn, PRESETS["C1"], db.read_policy(conn), None, ids, note=f"policy version {active} applied from the dashboard",
            progress=lambda done, total: bar.progress(done / total, text=f"Auditing: {done:,} of {total:,}")
            if done % 200 == 0 or done == total else None)
        summary = service.run_summary(conn, run_id)
        st.session_state["notice"] = (f"{summary['invoices']:,} invoices audited under version {active}: "
                                      f"{summary['flags']:,} findings, "
                                      f"{summary['states'].get(db.PENDING_REVIEW, 0):,} waiting for review.")
        st.rerun()


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
    adoption = db.read_policy(conn).registry.get("adoption")
    if adoption:
        # A version read from a document with a model's help says who answered for it.
        supplied = adoption.get("values_supplied_by_the_person") or []
        st.caption(f"Version {active} was read from a policy document by {adoption['model']} and confirmed by "
                   f"{adoption['confirmed_by']} on {adoption['confirmed_at']}."
                   + (f" Values typed by the reviewer: {', '.join(supplied)}." if supplied else ""))

    adopt_policy_document(conn, active)
    apply_policy_to_ledger(conn, active)

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
