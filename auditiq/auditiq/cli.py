"""Command line of AuditIQ.

Set up the database (ledger, policy versions, policy PDFs):
    python -m auditiq setup --dataset data/large_seed_505
    python -m auditiq ledger import ledger.xlsx            replace the ledger (workbook, .zip of CSVs or folder)
    python -m auditiq ledger export data/large_seed_505 ledger.xlsx

Audit:
    python -m auditiq run --config C1                      every invoice, controls only
    python -m auditiq run --config C5 --invoice INV40042   one or more invoices, full pipeline
    python -m auditiq audit --invoice INV40042 --config C5 --review
    python -m auditiq show --invoice INV40042              stored audit pack and audit trail

Review:
    python -m auditiq queue
    python -m auditiq decide --result 17 --decision approve --reviewer "A. Auditor"

Policy documents and questions:
    python -m auditiq policy search "bill raised on the weekend"
    python -m auditiq policy adopt company_policy.pdf --activate   thresholds are read from the document
    python -m auditiq ask "Why is INV40042 high risk?"
    python -m auditiq ask-data "Which five vendors have the most escalated invoices?"

Other:
    python -m auditiq serve                                REST API and web frontend on http://127.0.0.1:8000
    python -m auditiq status                               backend, ledger, row counts
    python -m auditiq export --out exports                 every table as CSV
    python -m auditiq graph --config C5
    python -m auditiq check-llm

Configuration C1 needs no model. The others, `ask` and `ask-data` read the
model from the environment (see .env.example).
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from . import copilot, db, ledger_import, policy_extract, policy_ingest, policy_llm, service, simulation
from .audit_pack import render_markdown
from .config import configure_logging
from .extraction import extract
from .graph import PRESETS, build_graph, preset
from .llm import LLMError, LLMSettings, OpenAIChatClient, ResponseCache
from .policy import load_policy
from .policy_pdf import PDF_DIR, make_sample_pdfs
from .retrieval import EndpointEmbedder, PolicyIndex, embed_chunks


def make_client(use_cache: bool = True) -> OpenAIChatClient:
    return OpenAIChatClient(LLMSettings.from_env(), ResponseCache() if use_cache else None)


_opened: list[db.Database] = []     # closed by main() when the command ends


def open_db(args: argparse.Namespace):
    conn = db.connect(getattr(args, "db", None))
    _opened.append(conn)
    return conn


def table(rows: list[dict], columns: list[str]) -> str:
    if not rows:
        return "(none)"
    cells = [[str(r[c]) if r[c] is not None else "" for c in columns] for r in rows]
    widths = [max(len(c), *(len(row[i]) for row in cells)) for i, c in enumerate(columns)]
    line = lambda values: "  ".join(v.ljust(w) for v, w in zip(values, widths)).rstrip()  # noqa: E731
    return "\n".join([line(columns), line(["-" * w for w in widths]), *(line(row) for row in cells)])


# ------------------------------------------------------------------- setup
def cmd_setup(args: argparse.Namespace) -> int:
    conn = open_db(args)
    ledger = ledger_import.read(Path(args.dataset), conn)
    if not ledger.usable:
        for problem in ledger.problems:
            print(f"problem: {problem}", file=sys.stderr)
        print("the ledger was not loaded", file=sys.stderr)
        return 1
    counts = ledger_import.load(conn, ledger)
    print(f"ledger loaded from {args.dataset}: " + ", ".join(f"{n} {t}" for t, n in counts.items()))
    for version in args.policies:
        db.store_policy(conn, load_policy(version), active=(version == args.policies[0]))
    print(f"policy versions stored: {', '.join(args.policies)} (active: {args.policies[0]})")
    pdfs = make_sample_pdfs()
    for report in (policy_ingest.ingest(conn, p) for p in pdfs):
        problem = ""
        if report["unverified"] or report["missing_clauses"]:
            problem = f"  MISMATCH with the registry: {report['unverified'] + report['missing_clauses']}"
        print(f"ingested {report['file']}: {report['pages']} pages, {report['chunks']} chunks, "
              f"{report['clauses']} clauses{problem}")
    embedder = EndpointEmbedder.from_env()
    if embedder is None:
        print("no embedding model configured (AUDITIQ_EMBED_MODEL): policy search is lexical only")
    else:
        print(f"embedded {embed_chunks(conn, embedder)} chunks with {embedder.name}")
    return 0


def cmd_ledger(args: argparse.Namespace) -> int:
    if args.action == "export":
        if len(args.arguments) != 2:
            print("give the dataset folder and the workbook to write", file=sys.stderr)
            return 2
        print(f"wrote {ledger_import.export_workbook(*args.arguments)}")
        return 0
    if len(args.arguments) != 1:
        print("give one workbook, zip archive or dataset folder", file=sys.stderr)
        return 2
    conn = open_db(args)
    ledger = ledger_import.read(Path(args.arguments[0]), conn)
    for problem in ledger.problems:
        print(f"problem: {problem}", file=sys.stderr)
    if not ledger.usable:
        print("the ledger was not loaded", file=sys.stderr)
        return 1
    if args.action == "check":
        print(f"{ledger.name}: usable; " + ", ".join(f"{n} {t}" for t, n in ledger.counts().items()))
        return 0
    counts = ledger_import.load(conn, ledger)
    print(f"ledger {ledger.name} loaded: " + ", ".join(f"{n} {t}" for t, n in counts.items()))
    print("the previous ledger and its audit results were replaced; audit it with `run --config C1`")
    return 0


def cmd_policy(args: argparse.Namespace) -> int:
    conn = open_db(args)
    if args.action == "make-pdfs":
        for path in make_sample_pdfs():
            print(f"wrote {path}")
    elif args.action == "ingest":
        files = [Path(f) for f in args.arguments] or sorted(PDF_DIR.glob("*.pdf"))
        for path in files:
            print(json.dumps(policy_ingest.ingest(conn, path)))
    elif args.action == "adopt":
        # A policy document becomes a policy version: its thresholds are read from its wording.
        if len(args.arguments) != 1:
            print("give one policy PDF", file=sys.stderr)
            return 2
        if args.llm:
            return adopt_with_model(conn, Path(args.arguments[0]), args)
        report = policy_extract.adopt(conn, Path(args.arguments[0]), reference_version=args.reference,
                                      activate=args.activate, replace=args.replace)
        print(f"{report['file']}: version {report['version']}, {report['pages']} page(s); compared with version "
              f"{report['reference_version']}")
        for change in report["changes"]:
            print(f"  Rule {change['clause']} {change['parameter']}: {change['from']} -> {change['to']}")
        if not report["changes"]:
            print("  no parameter differs")
        for problem in report["problems"]:
            print(f"  problem: {problem}", file=sys.stderr)
        if not report["adopted"]:
            print("not adopted", file=sys.stderr)
            return 1
        print(f"adopted as policy version {report['version']} ({report['rules']} rules)"
              + ("; now the active version" if report.get("active") else "; activate it with: policy activate "
                 + str(report["version"])))
    elif args.action == "simulate":
        # What the document would do to the stored ledger, before it is adopted; nothing is stored.
        if len(args.arguments) != 1:
            print("give one policy PDF", file=sys.stderr)
            return 2
        found = policy_extract.build(Path(args.arguments[0]), db.read_policy(conn).registry)
        if not found.usable:
            for problem in found.problems:
                print(f"  problem: {problem}", file=sys.stderr)
            print("the document cannot be executed", file=sys.stderr)
            return 1
        out = simulation.simulate(conn, found.registry)
        print(f"{found.file}: version {found.version} against the active version {out['active_version']}, "
              f"on {out['invoices']:,} invoices (dry run: nothing is stored)")
        print(f"  decisions moved: {out['decisions_moved']:,} (newly flagged {out['newly_flagged']:,}, cleared "
              f"{out['cleared']:,})")
        for change, n in out["route_changes"].items():
            print(f"  {change}: {n:,}")
        print(f"  amount newly held for review: {out['amount_newly_held']:,.2f}")
        print(table([r for r in out["findings_by_rule"] if r["before"] != r["after"]], ["rule", "before", "after"]))
    elif args.action == "embed":
        embedder = EndpointEmbedder.from_env()
        if embedder is None:
            print("Set AUDITIQ_EMBED_MODEL (and an endpoint) first; see .env.example.", file=sys.stderr)
            return 2
        print(f"embedded {embed_chunks(conn, embedder)} chunks with {embedder.name}")
    elif args.action == "activate":
        db.set_active_policy(conn, args.arguments[0])
        print(f"active policy version: {args.arguments[0]}")
    elif args.action == "search":
        index = PolicyIndex.from_db(conn, embedder=EndpointEmbedder.from_env())
        mode = args.mode if args.mode != "auto" else index.default_mode()
        print(f"ranking: {mode}\n")
        for i, hit in enumerate(index.search(" ".join(args.arguments), k=args.k, mode=args.mode), start=1):
            print(f"[{i}] {hit.source}\n    {hit.text}\n")
    return 0


def adopt_with_model(conn, path: Path, args: argparse.Namespace) -> int:
    """A policy in its own wording: the model proposes, code verifies, the named reviewer confirms."""
    reference = db.read_policy(conn, args.reference).registry
    settings = dataclasses.replace(LLMSettings.from_env(), max_tokens=2500)      # the reply lists every rule
    client = OpenAIChatClient(settings, ResponseCache())
    proposal = policy_llm.propose(path, reference, client)
    print(f"{proposal.file}: version {proposal.version or 'not stated'}, {proposal.pages} page(s); read by "
          f"{proposal.model}; compared with version {reference['version']}")
    print(table([{"rule": i["clause"], "parameter": i["parameter"], "proposed": json.dumps(i["value"]),
                  f"version {reference['version']}": json.dumps(i["reference"]), "status": i["status"],
                  "page": i["page"] or "", "reason or quote": i["reason"] or i["quote"][:70]} for i in proposal.items],
                ["rule", "parameter", "proposed", f"version {reference['version']}", "status", "page", "reason or quote"]))
    for problem in proposal.problems:
        print(f"  problem: {problem}", file=sys.stderr)
    passages = dict(item.split("=", 1) for item in args.quote or [])
    for clause in policy_llm.add_passages(proposal, passages):
        print(f"  the passage given for rule {clause} is not in the document", file=sys.stderr)
    try:
        overrides = {tuple(key.rsplit(".", 1)): json.loads(value)
                     for key, value in (item.split("=", 1) for item in args.set or [])}
        values, still_open = policy_llm.decide(proposal, accept_verified=args.accept_verified, overrides=overrides)
    except (ValueError, StopIteration) as error:
        print(f"error in --set: {error}", file=sys.stderr)
        return 2
    still_open += proposal.problems
    if still_open or not args.reviewer:
        for line in still_open:
            print(f"  open: {line}")
        print("not adopted. To adopt, confirm the verified values with --accept-verified, supply any other value "
              "with --set <rule>.<parameter>=<value>, give the passage of a rule that was not located with "
              "--quote <rule>=<passage>, and name yourself with --reviewer.")
        return 1
    report = policy_llm.adopt(conn, path, proposal, reference, values, args.reviewer, version=args.version,
                              activate=args.activate, replace=args.replace)
    for problem in report["problems"]:
        print(f"  problem: {problem}", file=sys.stderr)
    if not report["adopted"]:
        print("not adopted", file=sys.stderr)
        return 1
    print(f"adopted as policy version {report['version']} ({report['rules']} rules), confirmed by {args.reviewer}"
          + ("; now the active version" if report["active"] else ""))
    return 0


# ------------------------------------------------------------------- audit
def cmd_run(args: argparse.Namespace) -> int:
    conn = open_db(args)
    config = PRESETS[args.config]
    policy = db.read_policy(conn, args.policy)
    ids = args.invoice or db.invoice_ids(conn, only_unaudited=args.unaudited, limit=args.limit)
    if not ids:
        print("no invoice to audit")
        return 0
    client = make_client(not args.no_cache) if config.agents != "none" else None

    def progress(done: int, total: int) -> None:
        if done % 1000 == 0 or done == total:
            print(f"  {done}/{total}", flush=True)

    print(f"auditing {len(ids)} invoice(s) with {config.name} under policy v{policy.version}")
    run_id = service.audit_invoices(conn, config, policy, client, ids, sample_rate=args.sample_rate,
                                    workers=args.workers, note=args.note, progress=progress)
    print(json.dumps(service.run_summary(conn, run_id), indent=1))
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    config = preset(args.config, review=args.review, sample_rate=args.sample_rate)
    if args.dataset:
        policy = load_policy(args.policy or "2.5")
        txn = next((t for t in extract(Path(args.dataset)) if t["invoice"]["invoice_id"] == args.invoice), None)
    else:
        conn = open_db(args)
        policy = db.read_policy(conn, args.policy)
        txn = db.extract_one(conn, args.invoice)
    if txn is None:
        print(f"{args.invoice} was not found", file=sys.stderr)
        return 2
    client = make_client(not args.no_cache) if config.agents != "none" else None
    graph = build_graph(config, policy, client, checkpointer=InMemorySaver() if args.review else None)
    thread = {"configurable": {"thread_id": args.invoice}}
    state = graph.invoke({"txn": txn}, thread)

    if "__interrupt__" in state:
        request = state["__interrupt__"][0].value
        print(f"\n{request['invoice_id']} is in the {request['route']} queue "
              f"(weighted risk {request['score']['rc']:.1f}, count-based risk {request['score']['r0']:.1f}).")
        for f in request["flags"]:
            print(f"  - Rule {f['clause']} ({f['severity']}): {f.get('message', '')}")
        decision = ""
        while decision not in ("approve", "reject", "override"):
            decision = input("Decision [approve / reject / override]: ").strip().lower()
        reviewer = input("Reviewer: ").strip()
        justification = input("Justification: ").strip()
        state = graph.invoke(Command(resume={"decision": decision, "reviewer": reviewer,
                                             "justification": justification}), thread)

    pack = state["audit_pack"]
    print(json.dumps(pack, indent=2, ensure_ascii=False) if args.json else render_markdown(pack))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    conn = open_db(args)
    row = db.latest_result(conn, args.invoice)
    if row is None:
        print(f"{args.invoice} has no stored audit result", file=sys.stderr)
        return 2
    print(render_markdown(json.loads(row["audit_pack"])))
    print(f"State: {row['workflow_status']} | result {row['result_id']} | run {row['run_id']} "
          f"({row['configuration']}, {row['model'] or 'no model'}) | {row['created_at']}\n")
    trail = conn.execute("SELECT seq, stage, actor, detail, prompt_tokens, latency_ms FROM audit_trail "
                         "WHERE result_id = ? ORDER BY seq", (row["result_id"],)).fetchall()
    print("Audit trail\n" + table([dict(t) for t in trail], ["seq", "stage", "actor", "detail", "prompt_tokens", "latency_ms"]))
    return 0


# ------------------------------------------------------------------ review
def cmd_queue(args: argparse.Namespace) -> int:
    rows = [dict(r) for r in db.review_queue(open_db(args))]
    print(f"{len(rows)} invoice(s) waiting for review")
    print(table(rows[: args.limit], ["result_id", "invoice_id", "vendor_name", "invoice_date", "amount", "route",
                                     "rc", "r0", "flag_count", "configuration"]))
    return 0


def cmd_decide(args: argparse.Namespace) -> int:
    try:
        db.record_decision(open_db(args), args.result, args.decision, args.reviewer, args.justification)
    except (KeyError, ValueError) as error:
        print(error, file=sys.stderr)
        return 2
    print(f"recorded: {args.decision} by {args.reviewer} on result {args.result}")
    return 0


# --------------------------------------------------------------- questions
def cmd_ask(args: argparse.Namespace) -> int:
    conn = open_db(args)
    index = PolicyIndex.from_db(conn, embedder=EndpointEmbedder.from_env())
    client = None if args.no_llm else make_client(not args.no_cache)
    out = copilot.answer(" ".join(args.question), conn, index, client, k=args.k, invoice_id=args.invoice)
    if out["answer"]:
        print(out["answer"] + "\n")
        print("Sources: " + ("; ".join(h.source for h in out["sources"]) or "none cited"))
    else:
        for i, hit in enumerate(out["passages"], start=1):
            print(f"[{i}] {hit.source}\n    {hit.text}\n")
    if out["invoice_id"] and out["audit_pack"] is None:
        print(f"\n{out['invoice_id']} has no stored audit result.")
    return 0


def cmd_ask_data(args: argparse.Namespace) -> int:
    out = copilot.data_question(" ".join(args.question), args.db or db.default_target(),
                                make_client(not args.no_cache))
    print(f"SQL: {out['sql']}\n")
    if out["error"]:
        print(f"Not run: {out['error']}", file=sys.stderr)
        return 2
    print(table([dict(zip(out["columns"], row)) for row in out["rows"]], out["columns"]))
    if out["explanation"]:
        print(f"\n{out['explanation']}")
    return 0


# ------------------------------------------------------------------- other
def cmd_serve(args: argparse.Namespace) -> int:
    from .api import FRONTEND, serve
    print(f"AuditIQ API on http://{args.host}:{args.port}/api (documentation at /api/docs)")
    if (FRONTEND / "index.html").exists():
        print(f"web frontend on http://{args.host}:{args.port}/")
    else:
        print("the web frontend is not built: run `npm install` and `npm run build` in frontend/")
    serve(args.host, args.port, target=args.db)
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    conn = open_db(args)
    out = Path(args.out)
    counts = db.export_tables(conn, out, args.tables or None)
    for name, n in counts.items():
        print(f"{name}.csv  {n:,} rows")
    # A note beside the files, so that the folder explains itself.
    dataset = conn.scalar("SELECT value FROM meta WHERE key = 'dataset'") or "none loaded"
    policy = conn.scalar("SELECT version FROM company_policies WHERE is_active = 1") or "none"
    runs = conn.execute("SELECT u.run_id, u.configuration, u.policy_version, COALESCE(u.model, 'no model'), "
                        "COUNT(r.result_id) FROM audit_runs u LEFT JOIN audit_results r ON r.run_id = u.run_id "
                        "GROUP BY u.run_id, u.configuration, u.policy_version, u.model ORDER BY u.run_id").fetchall()
    lines = ["# Export of the AuditIQ database", "",
             f"Written by `python -m auditiq export` on {db.now()} from the {conn.backend} database. "
             f"Ledger: `{dataset}`. Active policy: version {policy}.", "",
             "One CSV file per table, UTF-8 with a header row; an empty field is NULL. The embedding vectors of "
             "`policy_chunks` are left out. Every table and column is described in `docs/DATA_DICTIONARY.md`.", "",
             "| File | Rows |", "|---|---|"]
    lines += [f"| `{name}.csv` | {n:,} |" for name, n in counts.items()]
    if runs:
        lines += ["", "| Run | Configuration | Policy | Model | Results |", "|---|---|---|---|---|"]
        lines += [f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]:,} |" for r in runs]
    (out / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"written to {args.out}")
    return 0


def cmd_user(args: argparse.Namespace) -> int:
    """Users of the REST API: add one (its token is printed once), list them, disable one."""
    conn = open_db(args)
    if args.action == "add":
        if not args.name:
            print("give the user's name", file=sys.stderr)
            return 2
        try:
            token = db.add_user(conn, args.name, args.role)
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        print(f"user {args.name.strip()} added with the role {args.role}. Their token, shown only now:\n{token}")
    elif args.action == "list":
        print(table(db.list_users(conn), ["name", "role", "created_at", "disabled"]))
    else:
        try:
            db.disable_user(conn, args.name or "")
        except KeyError as error:
            print(f"error: {str(error).strip(chr(39))}", file=sys.stderr)
            return 2
        print(f"user {args.name} disabled")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    conn = open_db(args)
    where = conn.target if conn.backend == "sqlite" else conn.target.split("@")[-1]     # never print a password
    dataset = conn.scalar("SELECT value FROM meta WHERE key = 'dataset'")
    policy = conn.scalar("SELECT version FROM company_policies WHERE is_active = 1")
    print(f"backend   {conn.backend}")
    print(f"location  {where}")
    print(f"ledger    {dataset or 'none loaded'}")
    print(f"policy    {('version ' + policy) if policy else 'none'}")
    print(table([{"table": t, "rows": f"{conn.scalar(f'SELECT COUNT(*) FROM {t}'):,}"} for t in db.ALL_TABLES],
                ["table", "rows"]))
    return 0


def cmd_graph(args: argparse.Namespace) -> int:
    from .llm import ScriptedClient
    config = preset(args.config, review=args.review)
    client = ScriptedClient(lambda *_: "{}") if config.agents != "none" else None   # never called
    graph = build_graph(config, load_policy(args.policy or "2.5"), client,
                        checkpointer=InMemorySaver() if args.review else None)
    print(graph.get_graph().draw_mermaid())
    return 0


def cmd_check_llm(args: argparse.Namespace) -> int:
    client = make_client(use_cache=False)
    reply = client.complete([{"role": "user", "content": 'Reply with the JSON object {"ok": true} and nothing else.'}])
    print(f"endpoint  {client.settings.base_url}\nmodel     {client.settings.model}\n"
          f"reply     {reply.text.strip()[:200]}\ntokens    {reply.prompt_tokens} in, {reply.completion_tokens} out\n"
          f"latency   {reply.latency_ms:.0f} ms")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="auditiq", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=None, help="SQLite file or postgresql:// URL (default: AUDITIQ_DATABASE_URL, "
                                               "else AUDITIQ_DB, else .auditiq/auditiq.db)")
    sub = ap.add_subparsers(dest="command", required=True)

    setup = sub.add_parser("setup", help="load a dataset, the policy versions and the policy PDFs into the database")
    setup.add_argument("--dataset", required=True, help="folder with the five record tables as CSV, a .zip "
                                                     "archive of them, or an .xlsx workbook with one sheet each")
    setup.add_argument("--policies", nargs="+", default=["2.5", "2.6"], help="versions to store; the first is active")
    setup.set_defaults(run=cmd_setup)

    led = sub.add_parser("ledger", help="check or import a ledger (workbook, zip of CSVs, folder); export one")
    led.add_argument("action", choices=["check", "import", "export"])
    led.add_argument("arguments", nargs="+", help="check/import: the ledger; export: the dataset folder and "
                                                  "the workbook to write")
    led.set_defaults(run=cmd_ledger)

    pol = sub.add_parser("policy", help="policy documents: make-pdfs, ingest, adopt, simulate, embed, activate, search")
    pol.add_argument("action", choices=["make-pdfs", "ingest", "adopt", "simulate", "embed", "activate", "search"])
    pol.add_argument("arguments", nargs="*", help="files to ingest, the PDF to adopt or simulate, the version to activate, "
                                                  "or the search text")
    pol.add_argument("--activate", action="store_true", help="adopt: make the adopted version the active one")
    pol.add_argument("--replace", action="store_true", help="adopt: replace a stored version of the same number")
    pol.add_argument("--reference", default=None, help="adopt: the version that defines the executable rules "
                                                       "(default: the active one)")
    pol.add_argument("--llm", action="store_true", help="adopt: the document is not in the template's wording; let "
                                                        "the model propose the thresholds for confirmation")
    pol.add_argument("--accept-verified", action="store_true", help="adopt --llm: accept every value that was "
                                                                    "verified against the document")
    pol.add_argument("--set", action="append", metavar="RULE.PARAMETER=VALUE", help="adopt --llm: supply a value")
    pol.add_argument("--quote", action="append", metavar="RULE=PASSAGE", help="adopt --llm: the passage of the "
                                                                         "document that states a rule the model did not locate")
    pol.add_argument("--reviewer", default="", help="adopt --llm: the person who confirms the values")
    pol.add_argument("--version", default=None, help="adopt --llm: version number, if the document states none")
    pol.add_argument("-k", type=int, default=5)
    pol.add_argument("--mode", choices=["auto", "lexical", "dense", "hybrid"], default="auto")
    pol.set_defaults(run=cmd_policy)

    run = sub.add_parser("run", help="audit invoices from the database and store the results")
    run.add_argument("--config", choices=list(PRESETS), default="C1")
    run.add_argument("--policy", default=None, help="policy version (default: the active one)")
    run.add_argument("--invoice", nargs="+", help="invoice ids (default: all)")
    run.add_argument("--unaudited", action="store_true", help="only invoices without a stored result")
    run.add_argument("--limit", type=int)
    run.add_argument("--workers", type=int, default=1)
    run.add_argument("--sample-rate", type=float, default=1.0, help="reviewed share of the sampled queue")
    run.add_argument("--note", default="")
    run.add_argument("--no-cache", action="store_true")
    run.set_defaults(run=cmd_run)

    audit = sub.add_parser("audit", help="audit one invoice and print its audit pack (nothing is stored)")
    audit.add_argument("--invoice", required=True)
    audit.add_argument("--dataset", help="read the records from this CSV folder, not from the database")
    audit.add_argument("--config", choices=list(PRESETS), default="C5")
    audit.add_argument("--policy", default=None)
    audit.add_argument("--review", action="store_true", help="pause an escalated invoice for a decision")
    audit.add_argument("--sample-rate", type=float, default=1.0)
    audit.add_argument("--json", action="store_true", help="print the pack as JSON")
    audit.add_argument("--no-cache", action="store_true")
    audit.set_defaults(run=cmd_audit)

    show = sub.add_parser("show", help="print the stored audit pack and audit trail of an invoice")
    show.add_argument("--invoice", required=True)
    show.set_defaults(run=cmd_show)

    queue = sub.add_parser("queue", help="list the invoices waiting for review")
    queue.add_argument("--limit", type=int, default=25)
    queue.set_defaults(run=cmd_queue)

    decide = sub.add_parser("decide", help="record a reviewer's decision")
    decide.add_argument("--result", type=int, required=True)
    decide.add_argument("--decision", choices=["approve", "reject", "override"], required=True)
    decide.add_argument("--reviewer", required=True)
    decide.add_argument("--justification", default="")
    decide.set_defaults(run=cmd_decide)

    ask = sub.add_parser("ask", help="ask about the policy or about an audited invoice")
    ask.add_argument("question", nargs="+")
    ask.add_argument("--invoice")
    ask.add_argument("-k", type=int, default=4)
    ask.add_argument("--no-llm", action="store_true", help="show the retrieved passages only")
    ask.add_argument("--no-cache", action="store_true")
    ask.set_defaults(run=cmd_ask)

    ask_data = sub.add_parser("ask-data", help="ask a question that one read-only SELECT can answer")
    ask_data.add_argument("question", nargs="+")
    ask_data.add_argument("--no-cache", action="store_true")
    ask_data.set_defaults(run=cmd_ask_data)

    serve_cmd = sub.add_parser("serve", help="run the REST API and the web frontend")
    serve_cmd.add_argument("--host", default="127.0.0.1")
    serve_cmd.add_argument("--port", type=int, default=8000)
    serve_cmd.set_defaults(run=cmd_serve)

    export = sub.add_parser("export", help="write the tables of the database as CSV files")
    export.add_argument("--out", required=True, help="folder for the CSV files")
    export.add_argument("--tables", nargs="*", help="tables to export (default: all)")
    export.set_defaults(run=cmd_export)

    status = sub.add_parser("status", help="show the backend, the loaded ledger and the row count of every table")
    status.set_defaults(run=cmd_status)

    user = sub.add_parser("user", help="users of the REST API and their roles: add (prints the token once), list, "
                                       "disable")
    user.add_argument("action", choices=["add", "list", "disable"])
    user.add_argument("name", nargs="?", default="")
    user.add_argument("--role", choices=list(db.ROLES), default="reviewer",
                      help="viewer reads; reviewer also decides and audits again; admin also changes policy and ledger")
    user.set_defaults(run=cmd_user)

    graph = sub.add_parser("graph", help="print the pipeline of a configuration as a Mermaid diagram")
    graph.add_argument("--config", choices=list(PRESETS), default="C5")
    graph.add_argument("--policy", default=None)
    graph.add_argument("--review", action="store_true")
    graph.set_defaults(run=cmd_graph)

    check = sub.add_parser("check-llm", help="send one request to the configured model")
    check.set_defaults(run=cmd_check_llm)

    args = ap.parse_args(argv)
    configure_logging()
    try:
        return args.run(args)
    except (db.DatabaseUnavailable, LLMError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    finally:
        # A connection left open would hold its transaction, and its locks, until the garbage collector
        # finds it; a command run in a longer process (the tests) must not leave one behind.
        while _opened:
            _opened.pop().close()


if __name__ == "__main__":
    raise SystemExit(main())
