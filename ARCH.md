# AuditIQ: the complete architecture

This document describes AuditIQ from the ground up: what it does, every part it is made of, the exact logic of each
part, the data it stores, the technologies it uses, and how the parts talk to each other. It is written for two
readers:

- **a person** who wants to understand the whole system, and
- **another engineer or language model** that has to rebuild it from nothing. For that reader every algorithm is
  given precisely (formulas, thresholds, field names, prompt texts, table definitions), and Section 33 gives the
  order in which to build it, with a check for each step.

Everything here was taken from the code in this repository (`auditiq/`, `auditiq_bench/`, `evaluation/`, `app/`,
`frontend/`, `scripts/`, `deploy/`, `.github/`) as of 30 October 2026. Where the code and this document disagree,
the code is right. Numbers in Section 30 come from `RESULTS.md`, where each one is traced to the script that
produced it.

---

## Contents

1. [What AuditIQ is](#1-what-auditiq-is)
2. [Design principles](#2-design-principles)
3. [The system at a glance](#3-the-system-at-a-glance)
4. [Technology stack](#4-technology-stack)
5. [Repository layout](#5-repository-layout)
6. [The data: the ledger and the transaction](#6-the-data-the-ledger-and-the-transaction)
7. [The policy: clause registry, text and versions](#7-the-policy-clause-registry-text-and-versions)
8. [Evidence extraction and the vendor history](#8-evidence-extraction-and-the-vendor-history)
9. [The twelve deterministic controls](#9-the-twelve-deterministic-controls)
10. [The model client](#10-the-model-client)
11. [The agents, the single auditor and the challenger](#11-the-agents-the-single-auditor-and-the-challenger)
12. [The pipeline graph and the five configurations](#12-the-pipeline-graph-and-the-five-configurations)
13. [Confidence, risk scores and routing](#13-confidence-risk-scores-and-routing)
14. [The audit pack and the revisions](#14-the-audit-pack-and-the-revisions)
15. [Storage: the database layer and the schema](#15-storage-the-database-layer-and-the-schema)
16. [The batch audit service](#16-the-batch-audit-service)
17. [Policy documents: rendering, ingestion, compilation, model reading, simulation](#17-policy-documents)
18. [Policy search and the copilot](#18-policy-search-and-the-copilot)
19. [Kafka ingestion](#19-kafka-ingestion)
20. [The REST API](#20-the-rest-api)
21. [The web application](#21-the-web-application)
22. [The Streamlit dashboard](#22-the-streamlit-dashboard)
23. [The command line](#23-the-command-line)
24. [The benchmark: AuditIQ-Bench](#24-the-benchmark-auditiq-bench)
25. [The evaluation harness](#25-the-evaluation-harness)
26. [Configuration: every environment variable](#26-configuration-every-environment-variable)
27. [Deployment and local servers](#27-deployment-and-local-servers)
28. [Tests and continuous integration](#28-tests-and-continuous-integration)
29. [Security model](#29-security-model)
30. [What has been measured](#30-what-has-been-measured)
31. [Limits and open items](#31-limits-and-open-items)
32. [Glossary](#32-glossary)
33. [Rebuilding it: the order of work](#33-rebuilding-it-the-order-of-work)

---

## 1. What AuditIQ is

AuditIQ is a **procure-to-pay audit system**. A company buys goods and services from vendors. Each purchase leaves
a trail of documents: a **purchase order (PO)** saying what was ordered at what price, a **goods receipt note (GRN)**
saying what arrived, an **invoice** from the vendor asking to be paid, and an **approval log** showing who in the
company approved the invoice. AuditIQ examines invoices that have already been **approved but not yet paid**, and
for each one decides:

| Route | Meaning | Resulting state |
|---|---|---|
| `approve` | nothing wrong was found; pay without review | `AUTO_APPROVED` |
| `sample` | only weakly supported findings; a reproducible share is reviewed | `PENDING_REVIEW` or `NOT_SAMPLED` |
| `escalate` | a person must review before payment | `PENDING_REVIEW` |

Every decision carries:

- the **findings** (each names a numbered policy rule, called a *clause*, such as `2.1.1`),
- the **evidence** each finding quotes (record field and value, for example `invoice.amount = 4396685.58`),
- the **citation** of the rule in the policy PDF (document and page),
- the **revision** the finding requires (for example "obtain approval from a CFO"),
- the **risk scores** and the route,
- and an **audit trail**: every step that ran, who or what ran it, and what model calls cost.

The audit is driven by a **written policy** (an SOP document). The thresholds of the policy (tolerances, limits,
day counts) are read from the policy document itself, stored as data, and executed by code. Changing the policy
changes the audit without changing code.

The system has:

- a **pipeline** of deterministic controls plus optional language-model agents, built as a LangGraph state graph;
- a **database** (SQLite or PostgreSQL) holding the ledger, the policy versions and every audit result;
- a **REST API** (FastAPI) and a **web application** (React + TypeScript + React Three Fiber 3D views);
- a **Streamlit dashboard** (a lighter alternative UI);
- a **command line**;
- a **Kafka ingestion layer** so documents can stream in one at a time;
- a **copilot** that answers questions about the policy, an audited invoice, or the data;
- a **synthetic benchmark** (AuditIQ-Bench) with labelled anomalies, and an **evaluation harness**.

Who uses it: an **auditor/reviewer** works the review queue and records decisions; an **admin** loads ledgers and
adopts policies; a **viewer** reads. Researchers run the evaluation.

What it does **not** do: it does not block payments, post to an ERP, or send notifications. The review queue is
where its output meets a person.

---

## 2. Design principles

These seven rules shape every part. A rebuild must keep them.

1. **Controls first.** Anything a comparison of fields can decide is decided by code: twelve deterministic
   controls. A language model is only asked about the four clauses that need reading or judgement, and only after
   the controls have run. A model can *add* findings; it can never remove or change a control's finding.
2. **The policy is data.** Every threshold is stored once, in the *clause registry* (`policy/policy_v<version>.json`).
   The policy text the agents read is *rendered from* the registry; the controls *read* the registry; the benchmark
   generator *reads* the registry. No threshold is written in Python code.
3. **A finding must be checkable.** A finding names a clause and quotes evidence as `field` + `value`. Code checks
   that the clause exists and that every quoted value is really in the records.
4. **Narrow remits.** Each agent sees only the records its clauses need and may only raise findings on its own
   clauses. A finding outside its remit is discarded by code.
5. **Nothing is lost.** Results are added, never replaced. A finding the challenger removed is kept, with the
   reason. Every result records the configuration, policy version, model and prompt hash that produced it.
6. **The answer key stays outside.** No pipeline stage reads the labels of a generated dataset. The generator and
   the pipeline share no code (a test fails if one imports the other).
7. **No unmeasured numbers.** A number goes into a document only if a script of the repository produced it.
   Samples and pilots are labelled as such.

---

## 3. The system at a glance

### 3.1 Components

```
                    +--------------------------------------------------------------+
  INPUTS            |                         DATABASE                             |
                    |               (SQLite file or PostgreSQL 17)                 |
  ledger CSV /      |                                                              |
  .xlsx / .zip ---->|  LEDGER         POLICY STORE          AUDIT                  |
                    |  vendor_master  company_policies      audit_runs             |
  Kafka topics ---->|  purchase_ord.  policy_clauses        audit_results          |
  (stream workers)  |  goods_receipts policy_parameters     latest_results         |
                    |  invoices       policy_documents      audit_flags            |
  policy registry ->|  approval_logs  policy_chunks         audit_trail            |
  JSON + SOP PDFs   |                                       review_decisions       |
                    |  emails, email_mentions, stream_offsets, stream_log,         |
                    |  api_users, benchmark_labels, meta                           |
                    +---------------+--------------------------+-------------------+
                                    |                          ^
                                    v                          |
            +--------------------------------------------------+------------+
            |                  PIPELINE (LangGraph)                          |
            |  extraction -> controls -> 3 specialist agents (parallel)      |
            |     -> challenger -> confidence -> risk score & route          |
            |     -> [human review] -> audit pack                            |
            +------+-----------------------------+---------------------------+
                   | model calls                 | results
                   v                             |
     OpenAI-compatible chat endpoint             |
     (Ollama qwen2.5:7b locally, or hosted)      |
     + embedding endpoint (nomic-embed-text)     |
                                                 v
      +--------------+   +---------------------+   +-----------------+   +-------------+
      | REST API     |-->| Web app (React,     |   | Streamlit       |   | Command     |
      | (FastAPI)    |   | React Three Fiber)  |   | dashboard       |   | line        |
      +--------------+   +---------------------+   +-----------------+   +-------------+
```

### 3.2 What happens to one invoice

1. **Extraction** gathers the invoice, its PO, its GRN, its vendor, its approval log entries and the vendor's other
   invoices into one *transaction* (Section 6.3).
2. **Controls** run twelve deterministic checks against the active policy's registry (Section 9).
3. **Agents** (if the configuration has them) each make one model call about the judgement clauses of their
   remit (Section 11).
4. The **challenger** (if configured) makes one model call that tests each agent finding and keeps or removes it.
5. **Confidence** (if configured): each kept agent finding gets grounding *g*, clause validity *p* and agreement *a*
   from 3 re-runs; confidence *c* = (*g* + *p* + *a*)/3 (Section 13).
6. **Scoring**: two risk scores, R0 (count-based) and Rc (confidence-weighted), and a route.
7. **Human review**: an escalated invoice waits in the review queue (or pauses the graph in interactive use).
8. **Audit pack**: code assembles the record of the result; no model writes it.
9. **Storage**: one row in `audit_results`, its findings in `audit_flags`, its steps in `audit_trail`.

### 3.3 Data flows

| Flow | Path |
|---|---|
| Load a ledger | file -> `ledger_import.read` (checks) -> `ledger_import.load` -> ledger tables |
| Audit in batch | `service.audit_invoices` -> `db.extract_many` -> graph per invoice -> `db.save_result` |
| Audit one invoice from the web | `POST /api/invoices/{id}/audit` -> background job -> `service.audit_invoices` |
| Stream | publisher -> Kafka topic -> `stream.Worker` -> ledger tables -> graph -> `save_result` |
| Adopt a policy | PDF -> `policy_extract.build` (patterns) or `policy_llm.propose` (model + verification + person) -> `db.store_policy` + `policy_ingest.ingest` |
| Change the active policy | `db.set_active_policy` -> it governs the invoices from its effective date (`db.policy_timeline`); `POST /api/policy/apply` re-audits the invoices not under the version in force on their date |
| Review | queue -> `POST /api/results/{id}/decision` -> `db.record_decision` (state, pack, trail) |
| Ask | `copilot.answer` (retrieval + model) or `copilot.data_question` (model-written SELECT, guarded) |

---

## 4. Technology stack

### 4.1 Backend (Python)

| Technology | Version (declared) | Used for |
|---|---|---|
| Python | >= 3.11 (built and run on 3.11) | everything on the server side |
| LangGraph | >= 1.0 | the pipeline as a `StateGraph`; `interrupt` and a checkpointer for human review |
| httpx | >= 0.27 | HTTP client for the chat and embedding endpoints |
| python-dotenv | >= 1.2.2 | reading `.env` |
| NumPy | >= 2.0 | embeddings, metrics, bootstrap |
| pandas | >= 2.2 | reading CSVs, workbooks, metric frames |
| openpyxl | >= 3.1 | Excel workbooks for ledger import/export |
| psycopg (binary) | >= 3.2 | PostgreSQL driver |
| sqlite3 | standard library | SQLite backend, response cache |
| Faker | >= 20 | synthetic names in the benchmark generator (`en_IN` locale) |
| scikit-learn | >= 1.5 | TF-IDF retrieval; isolation forest and one-class SVM baselines |
| statsmodels | >= 0.14 | statistics in the evaluation |
| reportlab | >= 4 | rendering the policy PDFs |
| PyMuPDF (`pymupdf`/`fitz`) | >= 1.24.3 | reading PDFs with layout (font size, position, page) |
| Streamlit | >= 1.46 | the dashboard |
| Altair | >= 5 | dashboard charts |
| Matplotlib | >= 3.8 | evaluation figures |
| FastAPI | >= 0.115 | the REST API |
| Pydantic | >= 2 | request bodies |
| Uvicorn | >= 0.34 | ASGI server |
| python-multipart | >= 0.0.31 | file uploads |
| Starlette | >= 1.3.1 | under FastAPI (pinned for security fixes) |
| confluent-kafka | >= 2.6 (2.16.0 installed) | Kafka producer, consumer, admin client (librdkafka) |
| pytest, ruff | dev extras | tests and lint |

### 4.2 Frontend (TypeScript)

| Technology | Version (pinned) | Used for |
|---|---|---|
| Node | >= 20 | build |
| React / React DOM | 18.3.1 | UI |
| React Router DOM | 7.18.4 | client-side routes |
| three.js | 0.170.0 | 3D |
| @react-three/fiber | 8.17.10 | React renderer for three.js |
| @react-three/drei | 9.122.0 | helpers: `OrbitControls`, `Html` labels, `RoundedBox`, `ContactShadows` |
| TypeScript | 5.6.3 | types |
| Vite | 6.4.4 | dev server and build |
| Vitest | 4.1.11 + jsdom 25 | unit and page tests |
| @testing-library/react, user-event, jest-dom | 16.0.1, 14.5.2, 6.6.3 | page tests |
| @react-three/test-renderer | 8.2.1 | 3D scene tests without WebGL |
| Playwright | 1.63.0 | end-to-end tests in Chromium |
| ESLint + typescript-eslint | 9.39.5, 8.71.2 | lint |

### 4.3 Services and infrastructure

| Service | Version | Role |
|---|---|---|
| SQLite | bundled with Python | default store (one file, `.auditiq/auditiq.db`) |
| PostgreSQL | 17 | production store; parallel stream workers |
| Apache Kafka | 4.3.2, KRaft mode, one node | ingestion topics |
| Ollama | any recent | serves the local models over an OpenAI-compatible API |
| Chat model | `qwen2.5:7b-ctx12k` (Qwen 2.5 7B with a 12,288-token context, from `deploy/ollama/Modelfile`) | agents, challenger, copilot, policy reading |
| Embedding model | `nomic-embed-text` (with prefixes `search_query: ` / `search_document: `) | dense policy search |
| Docker / Compose | | container image; app + PostgreSQL + Kafka + workers |
| GitHub Actions | | CI: five jobs (Section 28) |

The development machine is a laptop (Intel Core i5-1235U, 12 logical CPUs, 16 GB RAM, no discrete GPU). A 7B model
on its CPU takes minutes per call; a second Ollama server on the integrated GPU
(`OLLAMA_HOST=127.0.0.1:11435 OLLAMA_IGPU_ENABLE=1`, Vulkan) is about 6 to 8 times faster at prompt processing.

---

## 5. Repository layout

The git repository root is `pp1/`. The project is `pp1/auditiq/`; commands run from there.

```
pp1/
  RESULTS.md            every measured result, with source file and command (the paper's source)
  REPORT.md             full methodology and results report, generated by evaluation/full_report.py
  ARCH.md               this document
  paper/                LaTeX papers (not part of the system)
  .github/workflows/ci.yml
  auditiq/
    auditiq/            the application package (imports nothing from auditiq_bench)
      __init__.py, __main__.py   version; `python -m auditiq` = cli.main
      config.py         load_env (.env unless AUDITIQ_NO_DOTENV), logging setup
      db.py             Database class over SQLite/PostgreSQL, schema, ledger loading, extraction, results, users
      datadict.py       meaning of every table and column; writes docs/DATA_DICTIONARY.md
      ledger_import.py  read + check a ledger from folder / zip / xlsx; export a workbook
      extraction.py     build transactions from CSV files; the field lists
      history.py        History (list + VendorIndex by number and date)
      controls.py       the twelve deterministic controls
      prompts.py        prompt templates and their hash
      agents.py         specialists, single auditor, challenger; history selection; JSON calls
      llm.py            LLMSettings, OpenAIChatClient, ResponseCache, extract_json, ScriptedClient
      graph.py          PipelineConfig, PRESETS C1..C5, build_graph, to_result
      scoring.py        evidence resolution, grounding, confidence, R0, Rc, route, risk level
      audit_pack.py     build_pack, render_markdown
      corrections.py    the revision each control finding requires
      service.py        batch audit: audit_invoices, store_result, workflow_status, run_summary
      policy.py         Policy object, registry loading, text rendering from the template
      policy_pdf.py     render Markdown policy to PDF (reportlab)
      policy_ingest.py  read PDF into chunks (rules, paragraphs, pages); citations
      policy_extract.py read thresholds from a template-worded PDF; build; adopt
      policy_llm.py     read a free-worded policy with a model; verify quotes and values; confirm; adopt
      simulation.py     dry run of a new policy over the stored ledger
      retrieval.py      TF-IDF + embeddings + RRF policy search; question rewriting
      copilot.py        policy / invoice / data questions with guards
      stream.py         Kafka topics, publisher, workers, status
      emails.py         parse, link and store vendor e-mails
      api.py            FastAPI app: auth, roles, jobs, endpoints, security headers
      apidoc.py         writes docs/API.md from the app
      cli.py            the command line
    auditiq_bench/      synthetic benchmark generator (imports nothing from auditiq)
      __main__.py       profiles of the datasets; generate + validate + write
      taxonomy.py       anomaly classes, hard-negative types, composition constants
      catalog.py        items, descriptions, vendor naming styles
      generator.py      Builder: vendors, purchases, documents, approvals, injections
      validate.py       independent recomputation of rule violations
      export.py, datasheet.py, overview.py   writing datasets, datasheets, docs/DATASETS.md
      correspondence.py synthetic vendor e-mails (mbox + labels)
    evaluation/         baselines, runners, metrics, statistics, reports (Section 25)
    app/dashboard.py    Streamlit dashboard
    frontend/           React application (Section 21)
    policy/             policy_v2.5.json, policy_v2.6.json, SOP_template.md, SOP_v2.x.md, build_policy.py,
                        pdf/ (rendered PDFs), variants/ and variants_heldout/ (evaluation policies), freeform/,
                        robustness/
    data/               six datasets (Section 24)
    results/            measured results (json + md per experiment), results.json
    scripts/            pg_local.py, kafka_local.py, e2e_server.py, reproduce.py
    deploy/             docker-compose.yml, postgres/ (compose + init.sql), ollama/Modelfile
    tests/              Python tests (Section 28)
    docs/               ARCHITECTURE, DEVELOPER, API (generated), DATA_DICTIONARY (generated), DATASETS
                        (generated), OPERATIONS, SECURITY, WEB, STREAMING, CODE_REVIEW, BASE_PAPERS,
                        FEATURE_POLICY_AS_DATA
    Dockerfile, pyproject.toml, .env.example, README.md, PLAN.md
    .auditiq/           local state, not versioned: auditiq.db, llm_cache.sqlite, uploads/
```

---

## 6. The data: the ledger and the transaction

### 6.1 The five ledger tables

A *ledger* is five tables that refer to each other. Columns marked **A** are *audited*: the controls and agents may
read them. All other columns are carried for people and the copilot only, so nothing in them can influence a
decision.

**`vendor_master`** (one row per vendor)

| Column | A | Meaning |
|---|---|---|
| `vendor_id` | A | `VEND` + 4 digits, primary key |
| `vendor_name` | A | registered name |
| `official_gstin` | A | registered 15-character GSTIN; first two characters are the state code |
| `pan_number` | | characters 3 to 12 of the GSTIN |
| `vendor_category` | A | Raw Materials, MRO, Logistics, IT Services, Utilities, Professional Services |
| `city`, `state`, `country` | | address |
| `gstin_status` | A | `Active` or `Suspended` |
| `kyc_status` | | `Verified` |
| `is_active` | | flag |
| `blacklisted` | A | flag, 1 when on the blacklist |
| `blacklist_status` | | copy of `blacklisted` |

**`purchase_orders`**: `po_id` (A, `PO` + 5 digits), `vendor_id` (A, FK), `po_date` (A), `amount` (A, before tax),
`po_amount`, `quantity` (A), `unit_price` (A), `tax_amount` (18% GST), `total_amount`, `currency`, `department`,
`requester`, `status`, `description` (A).

**`goods_receipts`**: `grn_id` (A, `GRN` + 5 digits), `po_id` (A, FK), `vendor_id` (FK), `receipt_date` (A),
`received_quantity` (A), `ordered_quantity` (A), `unit_price`, `amount` (A), `received_amount`, `received_by`,
`warehouse_location`, `quality_check`, `status`, `notes` (A, the receiver's free-text remark).

**`invoices`**: `invoice_id` (A, `INV` + 5 digits, in order of date), `vendor_id` (A, FK), `invoice_number` (A, the
vendor's own number), `date` (A), `invoice_date`, `due_date`, `amount` (A, before tax), `invoice_amount`,
`quantity` (A), `unit_price` (A), `currency`, `tax_amount`, `total_amount`, `gstin` (A, printed on the invoice),
`po_id` (A, nullable, **not** a foreign key), `grn_id` (A, nullable, not a foreign key), `department`,
`payment_terms`, `payment_status` (`Unpaid`), `approval_status` (`Approved`), `approved_by`, `description` (A).

`po_id` and `grn_id` are not foreign keys on purpose: an invoice may name an order that does not exist, and finding
that is the job of Rule 2.1.3.

**`approval_logs`**: `log_id` (A, `LOG` + 5 digits), `transaction_id` (A, the invoice id), `approver_name` (A),
`approver_role` (A: `Manager`, `Senior Manager`, `Director`, `CFO`), `timestamp` (A), `action_taken` (A:
`Escalated` or `Approved`; exactly one `Approved` per invoice and it is the last), `amount_limit` (A, the limit as the
approval system recorded it; Control 5.1.1 does **not** use it, it takes the limit from the active policy).

Money is Indian rupees with two decimals. Dates are `YYYY-MM-DD`. CSV files are UTF-8 with a header row; an empty
field means no value.

### 6.2 Field lists the pipeline reads (`extraction.py`)

```python
INVOICE_FIELDS = ["invoice_id", "vendor_id", "invoice_number", "date", "amount", "quantity",
                  "unit_price", "gstin", "po_id", "grn_id", "description"]
PO_FIELDS      = ["po_id", "vendor_id", "po_date", "amount", "quantity", "unit_price", "description"]
GRN_FIELDS     = ["grn_id", "po_id", "receipt_date", "received_quantity", "ordered_quantity", "amount", "notes"]
VENDOR_FIELDS  = ["vendor_id", "vendor_name", "vendor_category", "official_gstin", "blacklisted", "gstin_status"]
LOG_FIELDS     = ["log_id", "approver_name", "approver_role", "timestamp", "action_taken", "amount_limit"]
HISTORY_FIELDS = ["invoice_id", "invoice_number", "date", "amount", "quantity", "po_id", "grn_id", "description"]
NUMERIC  = {"amount", "unit_price", "amount_limit"}       # parsed as float
INTEGER  = {"quantity", "received_quantity", "ordered_quantity"}
BOOLEAN  = {"blacklisted"}                                # "true"/"t"/"1" -> True
NULLABLE = {"po_id", "grn_id"}                            # "" -> None
```

### 6.3 The transaction

Every stage after extraction sees exactly one object per invoice:

```json
{
  "invoice":  {"invoice_id": "INV40237", "vendor_id": "VEND1001", "invoice_number": "KUR/001",
               "date": "2025-04-03", "amount": 694181.12, "quantity": 12, "unit_price": 57848.43,
               "gstin": "27ABCDE1234F1Z5", "po_id": "PO20001", "grn_id": "GRN30001",
               "description": "..."},
  "po":       {"po_id": "PO20001", ...} | null,
  "grn":      {"grn_id": "GRN30001", ...} | null,
  "vendor":   {"vendor_id": "VEND1001", "vendor_name": "Kurian LLC", "vendor_category": "MRO",
               "official_gstin": "...", "blacklisted": false, "gstin_status": "Active"},
  "approvals": [ {log entry}, ... ]              // this invoice's entries, oldest first
  "vendor_history": [ {HISTORY_FIELDS + approver_role, approver_name}, ... ]   // the vendor's OTHER invoices
}
```

`vendor_history` holds the vendor's other invoices, oldest first (by `date`, then `invoice_id`), each with the role
and name of its last `Approved` entry. It is a `History` object (Section 8.2).

---

## 7. The policy: clause registry, text and versions

### 7.1 The clause registry

The registry is JSON, one file per version (`policy/policy_v2.5.json`):

```json
{
  "policy_name": "Procurement & Vendor Auditing SOP",
  "version": "2.5",
  "effective_date": "2025-04-01",
  "clauses": {
    "2.1.1": {"title": "Amount match", "severity": "high", "kind": "control",
              "params": {"amount_tolerance_pct": 1.0}},
    ...
  }
}
```

Every clause has a **title**, one **severity** (`low`, `medium`, `high`, `critical`), a **kind** (`control` = decided
by code, `judgement` = needs an agent) and **params**. The full version 2.5:

| Clause | Title | Severity | Kind | Parameters (v2.5) |
|---|---|---|---|---|
| 2.1.1 | Amount match | high | control | `amount_tolerance_pct`: 1.0 |
| 2.1.2 | Quantity match | high | control | |
| 2.1.3 | Missing reference | high | control | |
| 2.1.4 | Receipt remarks | high | judgement | |
| 2.1.5 | Description match | medium | judgement | |
| 2.2.1 | Exact duplicate | critical | control | |
| 2.2.2 | Near duplicate | critical | judgement | |
| 3.1.1 | GSTIN format | medium | control | `gstin_length`: 15 |
| 3.1.2 | GSTIN state code | medium | control | `state_code_min`: 1, `state_code_max`: 37 |
| 3.1.3 | GSTIN vendor match | high | control | |
| 4.1.1 | Same-day splitting | high | control | `max_invoices_per_vendor_per_day`: 3 |
| 4.1.2 | Structuring across days | high | judgement | `guide_window_days`: 7, `guide_band_pct`: 15 |
| 4.2.1 | Weekend date | medium | control | `non_business_days`: ["Saturday", "Sunday"] |
| 4.3.1 | Round amount | low | control | `round_amount_multiple`: 10000 |
| 4.4.1 | Blocked vendor | critical | control | `blocked_gstin_statuses`: ["Suspended"] |
| 5.1.1 | Approval limit | critical | control | `approval_limits`: {Manager: 100000, Senior Manager: 500000, Director: 2500000, CFO: 10000000} |

Twelve clauses are `control`, four are `judgement` (2.1.4, 2.1.5, 2.2.2, 4.1.2).

**Version 2.6** (effective 2026-04-01) differs in exactly three parameters: `amount_tolerance_pct` 1.0 -> 5.0,
`max_invoices_per_vendor_per_day` 3 -> 5, and the Manager approval limit 100000 -> 150000.

### 7.2 The policy text

The text the agents read (`policy/SOP_v<version>.md`) is rendered from the registry by
`policy.render_policy_text(registry, template)` with `policy/SOP_template.md`. The template has `{{...}}`
placeholders:

- `{{version}}`, `{{effective_date}}`;
- `{{<clause>.<param>}}` for a scalar parameter, formatted with thousands separators (`1,000,000`; `1.0` -> `1`);
- special values: `state_code_min`/`state_code_max` (two digits), `business_days` ("Monday to Friday" when the
  working days are one run, else a list), `non_business_days` ("Saturday or Sunday"), `round_amount_multiple`,
  `blocked_gstin_statuses`, `approval_limit_rows` (Markdown table rows `| Manager | 100,000 |`).

After rendering, every `**Rule X.Y.Z (SEVERITY)` in the text must match the registry exactly, both ways, or
rendering fails. So the text and the executed parameters cannot disagree.

The rule lines of the template (the compiler in Section 17.3 reads thresholds back out of these sentences):

```
## 2. Invoice, Purchase Order and Goods Receipt
### 2.1 Three-Way Match
- **Rule 2.1.1 (HIGH), amount match.** The invoice amount must equal the PO amount. A difference of up to
  {{2.1.1.amount_tolerance_pct}}% of the PO amount is tolerated. A larger difference, in either direction, is an exception.
- **Rule 2.1.2 (HIGH), quantity match.** The quantity billed on the invoice must not exceed the received quantity
  recorded on the GRN.
- **Rule 2.1.3 (HIGH), missing reference.** Every invoice must reference a PO and a GRN that exist in the records.
  An invoice with no PO reference, with no GRN reference, or with a reference that matches no record is an exception.
- **Rule 2.1.4 (HIGH), receipt remarks.** The remarks on a GRN are part of the receipt. If the remarks record that
  part of the delivery was rejected, damaged beyond use, returned or not delivered, the accepted quantity is reduced
  by that part. An invoice that bills more than the accepted quantity is an exception, even when the
  received-quantity field equals the billed quantity. Remarks that confirm that the full quantity was accepted are
  not an exception.
- **Rule 2.1.5 (MEDIUM), description match.** The goods or services described on the invoice must be those ordered
  on the PO. Different wording for the same goods or services is acceptable. A description of different goods or
  services is an exception.
### 2.2 Duplicate Invoices
- **Rule 2.2.1 (CRITICAL), exact duplicate.** An invoice whose invoice number has already been used by an earlier
  invoice from the same vendor is an exception.
- **Rule 2.2.2 (CRITICAL), near duplicate.** An invoice that bills the same PO and GRN for the same amount as an
  earlier invoice from the same vendor, under an invoice number that is a re-keyed form of the earlier number (for
  example changed case, separators or leading zeros, an added suffix, or transposed or substituted characters), is
  an exception. Consecutive invoice numbers for separate POs and separate deliveries are not duplicates, even when
  the amounts are equal.
## 3. GST Compliance
### 3.1 GST Identification Number (GSTIN)
- **Rule 3.1.1 (MEDIUM), format.** The GSTIN on the invoice must be exactly {{3.1.1.gstin_length}} alphanumeric characters.
- **Rule 3.1.2 (MEDIUM), state code.** The first two characters of the GSTIN must be a state code from
  {{state_code_min}} to {{state_code_max}}.
- **Rule 3.1.3 (HIGH), vendor match.** A GSTIN that satisfies Rules 3.1.1 and 3.1.2 must be identical to the GSTIN
  in the vendor master record. A malformed GSTIN is reported under Rule 3.1.1 or 3.1.2 only.
## 4. Vendor Behaviour
### 4.1 Splitting
- **Rule 4.1.1 (HIGH), same-day splitting.** A vendor may have at most {{4.1.1.max_invoices_per_vendor_per_day}}
  invoices dated on the same day. When there are more, every invoice of that vendor dated on that day is an exception.
- **Rule 4.1.2 (HIGH), structuring across days.** Invoices from one vendor for the same goods or services, dated on
  different days within a short period (as a guide, {{4.1.2.guide_window_days}} days), each just below the
  approval limit of the approver who approved it (as a guide, within {{4.1.2.guide_band_pct}}% of the limit) and
  together above that limit, are treated as one purchase divided to avoid a higher approval. Every invoice of the
  group is an exception. A single invoice near a limit is not an exception.
### 4.2 Timing
- **Rule 4.2.1 (MEDIUM), non-business day.** Business days are {{business_days}}. An invoice dated on a
  {{non_business_days}} is an exception.
### 4.3 Round Amounts
- **Rule 4.3.1 (LOW), round amount.** An invoice amount that is an exact multiple of INR {{round_amount_multiple}}
  is an exception.
### 4.4 Vendor Status
- **Rule 4.4.1 (CRITICAL), blocked vendor.** An invoice from a vendor whose master record is marked blacklisted, or
  whose GST registration status is {{blocked_gstin_statuses}}, is an exception.
## 5. Approval Hierarchy
### 5.1 Delegation of Authority
| Approver role | Approval limit (INR) |
{{approval_limit_rows}}
- **Rule 5.1.1 (CRITICAL), approval limit.** An invoice whose amount is greater than the approval limit of the role
  that approved it is an exception. An amount equal to the limit is within authority.
## 6. Next-Best Actions
...
```

The document header carries `**Version:** 2.5` and `**Effective Date:** 2025-04-01`.

### 7.3 The `Policy` object

```python
@dataclass(frozen=True)
class Policy:
    registry: dict      # the JSON above
    text: str           # the rendered SOP Markdown
    version  -> registry["version"]
    clauses  -> registry["clauses"]
    clause_ids(kind=None) -> list of ids, optionally of one kind
```

`load_policy(version)` reads `policy_v<v>.json` and `SOP_v<v>.md`. `derive_policy(base, version, date, overrides)`
makes a variant registry for experiments (a dict parameter such as approval limits is merged role by role).
`clause_texts(text)` returns `{clause_id: "Rule 2.1.2 (HIGH), quantity match. The quantity ..."}`.

In the database, a version is a row of `company_policies` (registry JSON + Markdown + `is_active`), plus one row per
clause in `policy_clauses` and one per parameter in `policy_parameters`. Exactly one version is active.
`db.store_policy(conn, policy, active)` replaces a version; **a version that was active stays active** when it is
stored again (which version is active changes only through `active=True` or `db.set_active_policy`).

---

## 8. Evidence extraction and the vendor history

### 8.1 Three ways to build transactions

| Function | Source | Vendor history of an invoice | Used by |
|---|---|---|---|
| `extraction.extract(dataset)` | CSV files of a dataset folder | all other invoices of the vendor | evaluation scripts |
| `db.extract_one(conn, id)` | database, six queries | all other invoices of the vendor in the store (plain list) | single audits, API |
| `db.extract_many(conn, ids)` | database, five whole-table reads joined in memory | all other invoices of the vendor | batch audits of 200+ invoices |
| `db.extract_arrived(conn, ids)` | database, only the rows of the batch's vendors | **only invoices before it in ledger order** `(date, invoice_id)` | Kafka invoice workers |

All four produce the same transaction shape. `extract_arrived` exists because on a stream a later invoice has not
arrived yet; ordering by `(date, invoice_id)` makes the result independent of how the stream is batched.

The approver attached to each history record is that invoice's **last** `Approved` log entry (ordered by
`timestamp`, then `log_id`).

### 8.2 `History` and `VendorIndex` (`history.py`)

A vendor can have hundreds of invoices; two controls (2.2.1 and 4.1.1) look through the history. To keep their cost
independent of history length:

```python
def number_key(value) -> str:            # how 2.2.1 compares invoice numbers
    return str(value or "").strip()

class VendorIndex:                       # built once per vendor, shared by its transactions
    by_number: dict[str, list[dict]]     # number_key(invoice_number) -> records, oldest first
    by_date:   dict[str, list[dict]]     # date -> records, oldest first

class History(list):                     # the other invoices, plus the vendor's index
    vendor_index: VendorIndex
```

The index includes the invoice itself; the controls exclude it. Pickling (`__reduce__`) is supported so worker
processes can receive it. A plain list works too (the controls fall back to scanning).

---

## 9. The twelve deterministic controls

`controls.py`. Each control is a pure function `control(txn, clauses) -> list[flag]`, where `clauses` is the
registry's `clauses` map. A control whose clause is not in the policy returns nothing (so removing a clause from
the registry switches the control off). No threshold is written in the file.

### 9.1 The flag

```python
{"clause": "2.1.1", "control": "amount_match", "severity": clauses["2.1.1"]["severity"],
 "source": "D", "confidence": 1.0,
 "evidence": [{"field": "invoice.amount", "value": 101500.0}, {"field": "po.amount", "value": 100000.0}],
 "message": "Invoice amount 101500.00 differs from PO amount 100000.00 by 1.50% (tolerance 1%)."}
```

`source` is `D` (deterministic) for a control and `L` for a model. Amounts are compared in **paise** (integer
hundredths: `paise(x) = int(round(float(x) * 100))`) so the arithmetic is exact.

### 9.2 The controls, in the order they run

| # | Function | Clause | Fires when | Evidence |
|---|---|---|---|---|
| 1 | `amount_match` | 2.1.1 | a PO exists, PO amount > 0, and `abs(inv - po) * 100 > tolerance_pct * po` (paise) | `invoice.amount`, `po.amount` |
| 2 | `quantity_match` | 2.1.2 | a GRN exists and `invoice.quantity > grn.received_quantity` | `invoice.quantity`, `grn.received_quantity` |
| 3 | `missing_reference` | 2.1.3 | `po_id` empty, or set but no PO record; same for `grn_id` (one flag listing every gap) | `invoice.po_id` and/or `invoice.grn_id` |
| 4 | `exact_duplicate` | 2.2.1 | an **earlier** invoice of the vendor has the same `number_key(invoice_number)`; earlier = date before, or same date and smaller `invoice_id`; the earliest such is named | `invoice.invoice_number`, `history.<orig>.invoice_number` |
| 5 | `gstin_format` | 3.1.1 | the invoice GSTIN is not exactly `gstin_length` characters matching `[A-Za-z0-9]+` | `invoice.gstin` |
| 6 | `gstin_state_code` | 3.1.2 | the first two characters are not digits, or the number is outside `state_code_min..state_code_max` | `invoice.gstin` |
| 7 | `gstin_vendor_match` | 3.1.3 | the GSTIN passes 3.1.1 and 3.1.2, the vendor has an `official_gstin`, and they differ | `invoice.gstin`, `vendor.official_gstin` |
| 8 | `same_day_splitting` | 4.1.1 | (vendor's other invoices dated the same day) + 1 > `max_invoices_per_vendor_per_day` | `invoice.date` + `history.<id>.date` for each other invoice that day |
| 9 | `non_business_day` | 4.2.1 | the weekday name of the invoice date is in `non_business_days` | `invoice.date` |
| 10 | `round_amount` | 4.3.1 | amount > 0 and `paise(amount) % (multiple * 100) == 0` | `invoice.amount` |
| 11 | `blocked_vendor` | 4.4.1 | vendor `blacklisted` is true, else `gstin_status` in `blocked_gstin_statuses` | `vendor.blacklisted` or `vendor.gstin_status` |
| 12 | `approval_limit` | 5.1.1 | the **approving entry** exists, its role has a limit in `approval_limits`, and `paise(amount) > paise(limit)` | `invoice.amount`, `approval.approver_role` |

Details that matter:

- **The approving entry** (`approving_entry(txn)`) is the entry with `action_taken == "Approved"` and the latest
  `timestamp` (ties go to the later entry in the list). An amount **equal** to the limit is within authority.
- **GSTIN checks** share one helper `gstin_checks(gstin, clauses) -> (text, format_ok, state_ok)`; a check whose
  clause is absent counts as passed. 3.1.3 runs only on a well-formed GSTIN, so a malformed one is reported once.
- **Same-day splitting** uses `history.vendor_index.by_date[day]` when present (minus the invoice itself), else
  scans the list. When it fires, *every* invoice of that day fires too (each sees the others).
- **Exact duplicate** fires on the later copy only; the original is not an exception.

`run_controls(txn, clauses)` runs all twelve and concatenates their flags.

---

## 10. The model client

`llm.py`. One client for any server that implements `POST {base_url}/chat/completions` in the OpenAI format: a
local Ollama (`http://localhost:11434/v1`), vLLM, a LiteLLM gateway, or a hosted provider. Nothing else in the
system knows which.

### 10.1 Settings (`LLMSettings.from_env`)

| Variable | Default | Meaning |
|---|---|---|
| `AUDITIQ_LLM_BASE_URL` | (required) | e.g. `http://localhost:11434/v1` |
| `AUDITIQ_LLM_MODEL` | (required) | exact model id, recorded with every result |
| `AUDITIQ_LLM_API_KEY` | empty | bearer token, optional locally |
| `AUDITIQ_LLM_TIMEOUT` | 600 | seconds per request (3600 on a CPU-only laptop) |
| `AUDITIQ_LLM_MAX_TOKENS` | 700 | longest reply requested |
| `AUDITIQ_LLM_JSON_MODE` | 1 | send `response_format: {"type": "json_object"}` |
| `AUDITIQ_LLM_SEND_SEED` | 1 | send the sample number as `seed` |
| `AUDITIQ_LLM_EXTRA_BODY` | `{}` | extra JSON fields merged into the request body |
| `AUDITIQ_LLM_CONTEXT` | unset | the server's context window; when set, oversize prompts are refused |

`LLMSettings.configured()` says whether base URL and model are set. Without a model, configuration C1 still works.

### 10.2 A request

Body: `{"model", "messages", "temperature", "max_tokens", ["response_format"], ["seed": sample], **extra_body}`.

- **Context guard.** With `AUDITIQ_LLM_CONTEXT` set, `needed = sum(len(content)) / 2.7 + max_tokens`; if
  `needed > limit` the call raises `LLMError` instead of letting a server silently truncate the prompt.
- **Cache.** `ResponseCache` is a SQLite file (`.auditiq/llm_cache.sqlite`, table `responses(key, model, request,
  text, prompt_tokens, completion_tokens, latency_ms, created_at)`). The key is the SHA-256 of the JSON (sorted
  keys) of `{"base_url", "sample", **body}`. A repeated request returns the stored reply with `cached=True` and makes
  no call; that is why C3, C4 and C5 share their agent calls and a repeated run is free. The cache is thread-safe.
- **Retries.** Up to `max_retries + 1` = 6 attempts. Transport errors, HTTP 408, 409, 429, 5xx and a 200 response
  that is not a completion are retried; a numeric `Retry-After` header is honoured (capped at 120 s); otherwise
  exponential backoff `min(2**attempt, 60)` seconds. Any other 4xx raises `LLMError` at once.
- **Reply.** `LLMResponse(text, prompt_tokens, completion_tokens, latency_ms, cached)` from `choices[0].message.content`
  and `usage`.

### 10.3 Reading JSON from a reply

`extract_json(text)` removes `<think>...</think>` blocks, then tries `json.JSONDecoder().raw_decode` at every `{`
until one decodes to a dict. So code fences and prose around the object are tolerated. No object raises
`ValueError`.

### 10.4 Determinism

Decisions are requested at temperature 0 with `seed` = sample number 0. The agreement re-runs use temperature 0.7
and samples 1, 2, 3, so each has a different cache key.

`ScriptedClient(responder)` is a test double that returns scripted text; it is never used to produce a result.

---

## 11. The agents, the single auditor and the challenger

`agents.py` and `prompts.py`.

### 11.1 The specialist agents

```python
@dataclass(frozen=True)
class AgentSpec:
    name: str
    title: str
    sections: tuple[str, ...]          # clause-id prefixes of the remit
    records: tuple[str, ...]           # records shown besides the invoice under audit
    history_fields: tuple[str, ...] = ()
    history_rules: tuple[str, ...] = ()   # how other invoices are chosen: "duplicates", "time"
```

| Agent (`name`) | Title | Sections | Remit under v2.5 (its judgement clauses) | Records shown | History columns | History rule |
|---|---|---|---|---|---|---|
| `math_approvals` | Math and Approvals agent | `2.1.`, `5.` | 2.1.4 receipt remarks, 2.1.5 description match | po, grn, approvals | none | |
| `tax_identity` | Tax and Identity agent | `2.2.`, `3.` | 2.2.2 near duplicate | vendor, history | invoice_id, invoice_number, date, amount, po_id, grn_id | duplicates |
| `vendor_intelligence` | Vendor Intelligence agent | `4.` | 4.1.2 structuring across days | vendor, approvals, history | invoice_id, date, amount, description, approver_role, approver_name | time |
| `single_auditor` (C2 only) | auditor | all | every clause | po, grn, vendor, approvals, history | all ten (`FULL_HISTORY`) | duplicates + time |

`remit(spec, policy)` = the clause ids of kind `judgement` whose id starts with one of the agent's sections. An
agent with an empty remit is left out of the graph. The invoice under audit is always shown.

### 11.2 Records as text (`render_records`)

```
INVOICE UNDER AUDIT
{"invoice_id": ..., ...}                 <- JSON of the invoice record

PURCHASE ORDER
{...} | none on record
GOODS RECEIPT NOTE
{...} | none on record
VENDOR MASTER RECORD
{...}
APPROVAL LOG (oldest first)
{...}                                    <- one JSON object per line, or "none on record"
OTHER INVOICES OF THE SAME VENDOR (<N> | the <k> most relevant of <N>; oldest first; one per line)
invoice_id | invoice_number | date | amount | ...
INV40001 | ROU-0146 | 2025-04-01 | 46763.75 | ...
```

Only the sections in the agent's `records` appear. Floats are printed with two decimals. Labels never reach this
function.

### 11.3 Bounded vendor history (`select_history`, cap 40)

Below 41 invoices, an agent sees all of them. Above, it sees the 40 that a fixed rule ranks first, re-sorted oldest
first, and the heading says "the 40 most relevant of N":

- **duplicates**: rank key `(not same_document, amount != invoice.amount, -similarity, day_gap, invoice_id)` where
  `same_document` = same `po_id` or `grn_id` as the invoice, `similarity` = `difflib.SequenceMatcher` ratio of the
  invoice numbers reduced to upper-case alphanumerics, `day_gap` = absolute days between the dates.
- **time**: rank key `(day_gap, invoice_id)`.
- Both rules: the union of the two selections.

The rule reads only the records, so a re-run sees the same invoices. `evaluation/history_cap.py` checks on every
dataset that no labelled case loses an invoice it depends on.

### 11.4 The prompts (exact text)

Every stage uses the same **system message** (so a server can cache the policy as a common prefix):

```
You work in an audit pipeline for vendor invoices. Each request states your task and gives the records of one
invoice, the INVOICE UNDER AUDIT. The policy below is the only source of rules. Apply each rule as it is written,
including what it says is not an exception.

POLICY (version {version})
{policy_text}
```

The **specialist task** (the user message starts with it):

```
TASK
You are the {title} of the pipeline.

Division of work
- Deterministic controls have already checked every rule that can be decided by comparing field values. Their
  findings are listed under CONTROL FINDINGS. They are final: do not repeat them and do not question them.
- Your remit is limited to {remit}. Do not report any other rule.

How to decide
- Report an exception only when the records show that the invoice under audit violates a rule of your remit as
  the policy defines it.
- Most invoices have no exception.

Evidence
- For every exception, cite the record fields it rests on, each with its value copied exactly from the records.
- Field paths: invoice.<field>, po.<field>, grn.<field>, vendor.<field>, approval.<field> (the approving entry of
  the approval log), history.<invoice_id>.<field> (another invoice of the same vendor).
- Never cite a value that is not in the records.

Output
Reply with one JSON object and nothing else:
{"flags": [{"clause": "<rule number>", "evidence": [{"field": "<field path>", "value": <value>}], "explanation": "<one sentence>"}]}
If the invoice under audit has no exception, reply {"flags": []}
```

`{remit}` becomes "this rule of the policy: Rule 2.2.2 (near duplicate)" or "these rules of the policy: Rule 2.1.4
(receipt remarks) and Rule 2.1.5 (description match)".

The **single auditor task** (C2): "TASK / You are the auditor. Audit the invoice under audit against every rule of
the policy. / How to decide / - Report every rule that the records show the invoice under audit violates, as the
policy defines it. / - Most invoices have no exception." followed by the same Evidence and Output sections.

The **challenger task**:

```
TASK
You are the challenger of the pipeline. Specialist agents have proposed the findings listed under PROPOSED
FINDINGS. Your only task is to test each proposed finding against the records and the policy.

Remove a proposed finding when at least one of these holds:
- a value it cites is not in the records;
- the records do not show that the invoice under audit violates the cited rule as the policy defines it;
- the policy says that the situation is not an exception.
Otherwise keep it.

Do not add findings. Do not rule on the CONTROL FINDINGS: they come from deterministic checks, are final, and are
shown only for context.

Output
Reply with one JSON object and nothing else, with exactly one verdict for every proposed finding:
{"verdicts": [{"id": <id of the proposed finding>, "verdict": "keep" or "remove", "reason": "<one sentence>"}]}
```

The **repair** message: "Your reply was not a JSON object of the required form. Reply again with the JSON object
only."

The **user message** is: task, then (if applicable) `CONTROL FINDINGS` with lines `- Rule 2.1.1: <message>` (or
`none`), then `PROPOSED FINDINGS` (challenger only) with one JSON per line
`{"id": 1, "clause": ..., "evidence": [...], "explanation": ...}`, then `RECORDS` and the rendered records.

No template contains a threshold, a rule number or a benchmark example; placeholders are filled with `str.replace`
(not `format`, because the templates contain literal JSON braces). `prompts.prompt_hash()` = first 16 hex digits
of the SHA-256 of all templates, stored with every run that calls a model.

### 11.5 One JSON call (`call_json`)

1. Call the model. 2. `extract_json` and check that `data[required_key]` is a list. 3. If not, append the bad reply
and the repair message and call once more. 4. After two failures return `None` (the stage *fails*: it contributes
nothing, counts in `failed_stages`, and the other stages go on). One cost record per call:
`{stage, agent, sample, attempt, ok, prompt_tokens, completion_tokens, latency_ms, cached}`.

### 11.6 From reply to flags (`parse_flags`)

For each item of `data["flags"]`:

- not a dict, or no clause -> dropped as `malformed`;
- `clause_id(item["clause"])` extracts the first `\d+(\.\d+)+` ("Rule 2.1.1", "SOP 2.1.1." -> "2.1.1");
- a clause that **exists** in the policy but is **outside the remit** -> dropped as `out_of_remit`;
- the same clause twice -> dropped as `repeated`;
- a clause that does **not** exist in the policy is **kept** (so clause validity *p* can see it);
- the flag becomes `{"clause", "source": "L", "agent", "evidence" (list or []), "message": explanation}` and is
  normalized: a valid clause takes the clause's severity from the registry; an unknown clause keeps the stated
  severity if valid, else `medium`.

### 11.7 The challenger (`run_challenger`)

- Not called when no agent raised a finding.
- It sees the records that the authors of the proposed findings saw (the union of their `records`, history columns
  and history rules), so a finding is tested against its author's evidence.
- A finding with a `remove` verdict (by integer id) goes to `removed` with `removed_by: "challenger"` and
  `removal_reason`. A finding without a valid verdict is **kept**; an unusable reply keeps **every** finding (the
  stage counts as failed).
- It can never touch a control finding.

---

## 12. The pipeline graph and the five configurations

`graph.py`.

### 12.1 Configuration

```python
@dataclass(frozen=True)
class PipelineConfig:
    name: str
    controls: bool = True
    agents: str = "specialists"     # "none" | "single" | "specialists"
    challenger: bool = True
    confidence: bool = True
    reruns: int = 3                 # m, agreement re-runs
    temperature: float = 0.0
    rerun_temperature: float = 0.7
    review: bool = False            # pause escalated invoices for a reviewer (needs a checkpointer)
    sample_rate: float = 1.0        # share of the sampled queue that is reviewed

PRESETS = {
  "C1": PipelineConfig("C1", agents="none", challenger=False, confidence=False),
  "C2": PipelineConfig("C2", controls=False, agents="single", challenger=False, confidence=False),
  "C3": PipelineConfig("C3", challenger=False, confidence=False),
  "C4": PipelineConfig("C4", confidence=False),
  "C5": PipelineConfig("C5"),
}
```

| | Controls | Agents | Challenger | Confidence | Model calls per invoice |
|---|---|---|---|---|---|
| C1 | yes | none | | | 0 |
| C2 | no | one prompt over the whole policy | | | 1 |
| C3 | yes | three specialists | | | 3 |
| C4 | yes | three specialists | yes | | 3, plus 1 when an agent raised a finding |
| C5 | yes | three specialists | yes | yes | as C4, plus 3 re-runs of each agent that has a kept finding |

C0 (the classical baselines) is not a pipeline (Section 25.2).

### 12.2 State

```python
class AuditState(TypedDict, total=False):
    txn: dict
    control_flags: list[dict]
    proposed: Annotated[list[dict], operator.add]   # agent flags before the challenger (parallel writers merge)
    kept: list[dict]
    removed: list[dict]
    flags: list[dict]                                # final flags with confidence terms
    score: dict
    review: dict
    audit_pack: dict
    calls: Annotated[list[dict], operator.add]       # one cost record per model call
    notes: Annotated[list[dict], operator.add]       # failed stages, dropped flags
```

### 12.3 Nodes and edges

```
START -> controls -> [math_approvals, tax_identity, vendor_intelligence]  (fan-out, parallel)
                                     \___________ ___________/
                                                 v
                                            challenger -> confidence -> risk_score -> [human_review] -> write_audit_pack -> END
```

- C1: `START -> controls -> confidence -> risk_score -> write_audit_pack`.
- C2: `START -> single_auditor -> confidence -> ...`.
- C3: specialists -> `confidence` (no challenger).
- `human_review` only when `config.review` is set.

Node behaviour:

| Node | Does |
|---|---|
| `controls` | `run_controls`, then `normalize_flag` each |
| specialist | `run_specialist` at temperature 0, sample 0 -> `proposed`, `calls`, `notes` |
| `single_auditor` | `run_single` |
| `challenger` | `run_challenger` -> `kept`, `removed` |
| `confidence` | agent flags = `kept` if the challenger ran, else `proposed`. With confidence on and agent flags present: re-run each originating agent `m` times (samples 1..m, temperature 0.7, in a thread pool of up to 6), record which clauses each re-run cites. Final flags = control flags with `confidence 1.0` + agent flags with `g`, `p` and (if confidence on) `a` and `confidence` |
| `risk_score` | `scoring.score(flags, options)` |
| `human_review` | `approve` -> `{"decision": "auto_approved"}`; `sample` and not in sample -> `not_sampled`; otherwise `interrupt({...})` and wait for the reviewer's decision |
| `write_audit_pack` | `build_pack(...)` |

`build_graph` refuses inconsistent configurations: agents without a client, no controls and no agents, review
without a checkpointer, confidence with zero re-runs.

### 12.4 The prediction record (`to_result`)

```python
{"invoice_id", "config", "policy_version", "model", "anomalous": bool(flags), "flags", "removed_flags",
 "r0", "rc", "route",
 "cost": {"llm_calls", "prompt_tokens", "completion_tokens", "latency_ms", "cache_hits"},
 "issues": {"failed_stages", "repaired_replies", "out_of_remit_flags", "malformed_flags"}}
```

This is the format the evaluation reads (one JSON line per invoice) and what `db.save_result` stores.

---

## 13. Confidence, risk scores and routing

`scoring.py`.

### 13.1 Evidence paths (`resolve(txn, path)`)

| Path | Resolves to |
|---|---|
| `invoice.amount`, `po.description`, `grn.notes`, `vendor.official_gstin` | that field of that record |
| `approval.approver_role` | that field of the approving entry |
| `approvals[0].action_taken` | that field of the n-th log entry |
| `history.INV40012.invoice_number` (or `vendor_history.`) | a field of another invoice of the vendor |

A whole record, a list, or a missing key is `MISSING`.

### 13.2 Comparing a quoted value (`same_value(stated, actual)`)

- `MISSING` -> false. Empty stated -> true only if the actual is empty or null. Null actual -> false.
- Booleans: compared as lower-case strings.
- If the record holds a **number**: the stated value is parsed as a number (removing commas, spaces, `₹`, `INR`,
  `Rs.`) and must be within `0.005 + 1e-9 * |actual|`. (An identifier like `"00123"` is never compared as a number,
  because the record holds a string.)
- Otherwise: case-insensitive string equality after stripping.

### 13.3 The three confidence terms

For a flag raised by a model:

- **g (grounding)** = 1 if the flag has at least one evidence item and every item resolves to a field whose value
  matches; else 0. A flag with no evidence is not grounded.
- **p (clause validity)** = 1 if the cited clause exists in the active policy.
- **a (agreement)** = the share of the *m* = 3 re-runs of the same agent that cite the same clause again.

```
c = (wg*g + wp*p + wa*a) / (wg + wp + wa)       with weights (1, 1, 1) by default
c = 1                                            for a control flag
```

Confidence measures whether a finding is supported and stable, not whether it is correct: a model that makes the
same mistake every time gets full agreement.

### 13.4 Scores and route

```
weights: critical 30, high 20, medium 10, low 5
floors:  critical 70, high 50         tau (threshold) = 50        theta = 2/3

R0 = min(100, sum of weights of the kept flags)
     then: any critical flag -> max(R0, 70); else any high flag -> max(R0, 50)

Rc = min(100, sum of weight * confidence)
     then floors applied only by flags with confidence >= theta (minus 1e-9)

route = "escalate" if Rc >= tau
        "sample"   if Rc < tau <= R0
        "approve"  if R0 < tau

risk_level (from Rc) = CRITICAL >= 70, HIGH >= 50, MEDIUM >= 30, else LOW
```

Without confidence (C1 to C4), Rc = R0. Since Rc never exceeds R0, confidence weighting never changes which invoices
are approved; it only moves invoices from mandatory review to sampled review. A test checks this on generated flags.
Note that one critical control finding alone gives R0 = 70 and so always escalates; one high finding gives 50 and
escalates; medium and low findings escalate only when their weights add up to 50.

### 13.5 Workflow states

| Route | State |
|---|---|
| `approve` | `AUTO_APPROVED` |
| `escalate` | `PENDING_REVIEW` |
| `sample` | `PENDING_REVIEW` if `in_sample(invoice_id, sample_rate)`, else `NOT_SAMPLED` |

`in_sample(id, rate)`: `int(sha256(id)[:8 hex], 16) / 2**32 < rate`. The draw is reproducible.

A reviewer's decision sets `REVIEW_APPROVED`, `REVIEW_REJECTED` or `REVIEW_OVERRIDDEN`. An override needs a written
justification.

---

## 14. The audit pack and the revisions

### 14.1 The pack (`audit_pack.build_pack`)

Assembled by code from verified flags. No model writes it, so it cannot state anything the pipeline did not
establish.

```json
{"invoice_id", "vendor_id", "vendor_name", "policy_version", "configuration", "model",
 "route", "risk_level", "count_based_risk": R0, "weighted_risk": Rc, "threshold": 50,
 "flags": [{"clause", "title" (or "clause not in the policy"), "severity",
            "source": "control" | "agent (<name>)", "confidence", "evidence", "message",
            "confidence_terms": {"g","p","a"} (agent flags only),
            "revision": {...} (control flags only),
            "citation": {"document", "page"} (added when stored, if the policy PDF was ingested)}],
 "removed_by_challenger": [{"clause", "agent", "message", "reason"}],
 "review": null | {"queue", "decision", "reviewer", "justification", "decided_at"},
 "recommended_action": "Approved automatically. No human review required."
                     | "Sampled-review queue: escalated only by weakly supported findings. Not approved automatically."
                     | "Escalated to a human reviewer. Payment is held until the review is recorded."}
```

`render_markdown(pack)` writes it as a readable report ("# Audit pack: INV...", vendor, policy, route and scores,
findings with source, citation, revision, evidence and confidence terms, removed findings, review).

### 14.2 Revisions (`corrections.correct`)

For each **control** finding, the revision is computed from the evidence and the policy (no model). A model's
finding gets no revision; it goes to the reviewer.

```
{"clause", "kind", "action", "changes": [{"field", "from", "to"}], "amount_at_issue"}
```

| Control | Kind | Revision |
|---|---|---|
| amount_match | `amend` | `invoice.amount` -> PO amount; "bill the PO amount; credit note for the difference" (or record why it is below). If the PO amount is above the approver's limit, also `approval.approver_role` -> the lowest role whose limit covers it |
| quantity_match | `amend` | `invoice.quantity` -> received quantity; money at issue = excess x unit price |
| missing_reference | `obtain` | obtain the missing PO and/or GRN; hold payment |
| exact_duplicate | `reject` | reject; paying would pay the amount twice; amount at issue = invoice amount |
| gstin_format / state_code / vendor_match | `amend` | `invoice.gstin` -> the vendor's registered GSTIN if that one is valid; else `obtain` a valid GSTIN |
| same_day_splitting | `consolidate` | treat the day's invoices as one purchase of their total, approved by the lowest role whose limit covers the total |
| non_business_day | `verify` | confirm the date with the vendor, obtain the delivery record |
| round_amount | `verify` | obtain the itemised bill |
| blocked_vendor | `hold` | hold payment until the vendor's standing is restored |
| approval_limit | `reapprove` | `approval.approver_role` -> lowest role whose limit covers the amount; above every limit: refer to the board |

`_role_for(amount, limits)` = the role with the lowest limit that is >= the amount. `corrections.apply(txn,
revision)` makes the changes on a copy; `evaluation/revisions.py` checks that every amended or re-approved invoice
then passes the rule it failed and raises no new finding.

---

## 15. Storage: the database layer and the schema

`db.py`.

### 15.1 One interface, two backends

```python
class Database:
    raw          # sqlite3.Connection or psycopg.Connection
    backend      # "sqlite" | "postgres"
    target       # path or URL
    execute(sql, params) / executemany / insert(sql, params, key) -> new id / scalar / frame (DataFrame)
    commit / rollback / close
    columns(table) -> {column: kind}       kind in text, integer, number, date, timestamp, blob
    relations() -> set of table and view names
```

SQL is written once with `?` placeholders; for PostgreSQL `?` becomes `%s` (and `%` is escaped). `insert` returns
the generated key (`lastrowid` on SQLite, `RETURNING key` on PostgreSQL).

`connect(target=None, read_only=False)`:

- target: argument, else `AUDITIQ_DATABASE_URL`, else `AUDITIQ_DB`, else `.auditiq/auditiq.db`.
- **PostgreSQL** (a `postgresql://` URL): psycopg 3, `connect_timeout=5`; `numeric` loaded as float and
  `date`/`timestamp` as ISO text, so the application sees the same values as on SQLite; rows are `Row` objects that
  behave like tuples with `keys()`; read-only adds `-c default_transaction_read_only=on`. Unreachable -> raises
  `DatabaseUnavailable` with instructions (the API answers 503).
- **SQLite**: `check_same_thread=False`, `row_factory = sqlite3.Row`, `PRAGMA foreign_keys = ON`; read-only opens
  `file:...?mode=ro`.
- A writable connection runs `ensure_schema`.

Column types per backend:

| Placeholder | SQLite | PostgreSQL |
|---|---|---|
| `{pk}` | `INTEGER PRIMARY KEY AUTOINCREMENT` | `BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY` |
| `{money}` | `REAL` | `NUMERIC(15,2)` |
| `{real}` | `REAL` | `DOUBLE PRECISION` |
| `{date}` | `TEXT` | `DATE` |
| `{timestamp}` | `TEXT` | `TIMESTAMP` |
| `{blob}` | `BLOB` | `BYTEA` |
| `{flag}` | `INTEGER` | `SMALLINT` |
| `{view}` | `CREATE VIEW IF NOT EXISTS` | `CREATE OR REPLACE VIEW` |

### 15.2 Schema creation

`SCHEMA_ID` = first 16 hex digits of the SHA-256 of the schema text. `meta(key='schema')` records the stamp
(`SCHEMA_ID`, plus `+auditiq_reader` on PostgreSQL when the copilot's role exists). `ensure_schema`: if the recorded
stamp differs, take `pg_advisory_xact_lock(4702315001)` on PostgreSQL, read again, then `create_schema` (drop and
re-create the views on SQLite, run every statement, back-fill `latest_results` from `MAX(result_id)` per invoice,
grant SELECT on the copilot's tables to `auditiq_reader` if it exists, write the stamp). An up-to-date database is
only read, so connections take no exclusive lock (re-creating views on every connection once deadlocked two web
requests).

### 15.3 Tables

The five ledger tables are in Section 6.1. The rest:

```sql
CREATE TABLE company_policies (version TEXT PRIMARY KEY, policy_name TEXT, effective_date {date},
  markdown_content TEXT NOT NULL, registry TEXT NOT NULL, is_active {flag} NOT NULL DEFAULT 0);
CREATE TABLE policy_clauses (version TEXT NOT NULL REFERENCES company_policies(version) ON DELETE CASCADE,
  clause_id TEXT NOT NULL, title TEXT NOT NULL, severity TEXT NOT NULL, kind TEXT NOT NULL,
  PRIMARY KEY (version, clause_id));
CREATE TABLE policy_parameters (version TEXT NOT NULL, clause_id TEXT NOT NULL, param_name TEXT NOT NULL,
  param_value TEXT NOT NULL,                          -- JSON
  PRIMARY KEY (version, clause_id, param_name),
  FOREIGN KEY (version, clause_id) REFERENCES policy_clauses(version, clause_id) ON DELETE CASCADE);
CREATE TABLE policy_documents (doc_id {pk}, file_name TEXT NOT NULL UNIQUE, title TEXT, version TEXT,
  pages INTEGER, sha256 TEXT, ingested_at {timestamp});
CREATE TABLE policy_chunks (chunk_id {pk}, doc_id BIGINT NOT NULL REFERENCES policy_documents(doc_id) ON DELETE CASCADE,
  version TEXT, position INTEGER NOT NULL, kind TEXT NOT NULL,            -- 'clause' | 'text'
  clause_id TEXT, section TEXT, page INTEGER, text TEXT NOT NULL,
  verified {flag},                                    -- clause text == registry text of that version
  embedding {blob}, embed_model TEXT);                -- float32 unit vector as bytes

CREATE TABLE audit_runs (run_id {pk}, configuration TEXT NOT NULL, policy_version TEXT NOT NULL, model TEXT,
  prompt_hash TEXT, note TEXT, started_at {timestamp}, finished_at {timestamp});
CREATE TABLE audit_results (result_id {pk},
  run_id BIGINT NOT NULL REFERENCES audit_runs(run_id) ON DELETE CASCADE,
  invoice_id TEXT NOT NULL REFERENCES invoices(invoice_id), vendor_id TEXT,
  route TEXT NOT NULL, risk_level TEXT, r0 {real}, rc {real}, flag_count INTEGER,
  workflow_status TEXT NOT NULL, llm_calls INTEGER, prompt_tokens INTEGER, completion_tokens INTEGER,
  latency_ms {real}, failed_stages INTEGER, audit_pack TEXT NOT NULL, created_at {timestamp},
  UNIQUE (run_id, invoice_id));                       -- one result per invoice per run
CREATE INDEX idx_results_invoice ON audit_results(invoice_id);
CREATE INDEX idx_results_status ON audit_results(workflow_status);
CREATE TABLE latest_results (invoice_id TEXT PRIMARY KEY REFERENCES invoices(invoice_id),
  result_id BIGINT NOT NULL REFERENCES audit_results(result_id) ON DELETE CASCADE);
CREATE UNIQUE INDEX idx_latest_result ON latest_results(result_id);
CREATE TABLE audit_flags (flag_id {pk}, result_id BIGINT NOT NULL REFERENCES audit_results(result_id) ON DELETE CASCADE,
  clause TEXT, severity TEXT, source TEXT,            -- 'D' | 'L'
  agent TEXT,                                         -- control function name or agent name
  status TEXT NOT NULL,                               -- 'kept' | 'removed'
  g INTEGER, p INTEGER, a {real}, confidence {real}, message TEXT, evidence TEXT, removal_reason TEXT);
CREATE INDEX idx_flags_result ON audit_flags(result_id);
CREATE TABLE audit_trail (entry_id {pk}, result_id BIGINT NOT NULL REFERENCES audit_results(result_id) ON DELETE CASCADE,
  seq INTEGER NOT NULL, stage TEXT NOT NULL, actor TEXT, detail TEXT,
  prompt_tokens INTEGER, completion_tokens INTEGER, latency_ms {real});
CREATE INDEX idx_trail_result ON audit_trail(result_id);
CREATE TABLE review_decisions (decision_id {pk},
  result_id BIGINT NOT NULL REFERENCES audit_results(result_id) ON DELETE CASCADE,
  decision TEXT NOT NULL, reviewer TEXT NOT NULL, justification TEXT, decided_at {timestamp});

CREATE TABLE benchmark_labels (invoice_id TEXT PRIMARY KEY, label TEXT, class_id TEXT, clause_ids TEXT,
  severity TEXT, group_id TEXT, related_invoice_id TEXT, hard_negative_type TEXT, note TEXT);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);   -- 'dataset', 'schema'
CREATE TABLE api_users (user_id {pk}, name TEXT NOT NULL UNIQUE, role TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE, created_at {timestamp}, disabled {flag} NOT NULL DEFAULT 0);

CREATE TABLE emails (message_id TEXT PRIMARY KEY, sender TEXT, sender_domain TEXT, recipient TEXT, subject TEXT,
  sent_at {timestamp}, body TEXT, invoice_id TEXT, vendor_id TEXT, received_at {timestamp});
CREATE INDEX idx_emails_invoice ON emails(invoice_id);
CREATE TABLE email_mentions (message_id TEXT NOT NULL, mention TEXT NOT NULL, PRIMARY KEY (message_id, mention));
CREATE INDEX idx_email_mentions ON email_mentions(mention);
CREATE TABLE stream_offsets (consumer_group TEXT NOT NULL, topic TEXT NOT NULL, partition_no INTEGER NOT NULL,
  next_offset BIGINT NOT NULL, PRIMARY KEY (consumer_group, topic, partition_no));
CREATE TABLE stream_log (topic TEXT NOT NULL, partition_no INTEGER NOT NULL, kafka_offset BIGINT NOT NULL,
  doc_key TEXT, produced_ms BIGINT, processed_ms BIGINT, outcome TEXT NOT NULL, detail TEXT, result_id BIGINT,
  PRIMARY KEY (topic, partition_no, kafka_offset));

CREATE INDEX idx_invoices_vendor_date ON invoices(vendor_id, date);
CREATE INDEX idx_approvals_transaction ON approval_logs(transaction_id);
```

### 15.4 Views

```sql
{view} v_latest_results AS
SELECT r.*, u.configuration, u.policy_version, u.model
FROM latest_results m JOIN audit_results r ON r.result_id = m.result_id
JOIN audit_runs u ON u.run_id = r.run_id;

{view} v_review_queue AS
SELECT l.result_id, l.invoice_id, l.vendor_id, v.vendor_name, i.date AS invoice_date, i.amount,
       l.route, l.risk_level, l.r0, l.rc, l.flag_count, l.configuration, l.created_at
FROM v_latest_results l JOIN invoices i ON i.invoice_id = l.invoice_id
JOIN vendor_master v ON v.vendor_id = l.vendor_id
WHERE l.workflow_status = 'PENDING_REVIEW';
```

`latest_results` is maintained on every save (upsert). It exists because finding "the latest result per invoice"
with a `MAX()` subquery was too slow on a 500,000-invoice store.

### 15.5 Writing results (`save_result`)

1. Insert the `audit_results` row (counts from the result, the pack as JSON, `created_at`).
2. Upsert `latest_results(invoice_id, result_id)` (a later result has a larger id).
3. Insert every kept flag (`status='kept'`) and every challenger-removed flag (`status='removed'`) into
   `audit_flags`, with `agent` = agent name or control name, evidence as JSON.
4. Insert the trail: `(extraction, code, "invoice, PO, GRN, vendor, approval log, vendor history")`,
   `(controls, code, "<n> flag(s): <clauses>" or "0 flags")`, one entry per model call
   (`stage`, agent, "sample s, attempt a, valid reply|invalid reply[, from cache]", tokens, latency),
   `(scoring, code, "count-based R0, weighted Rc, route X")`.

`record_decision(conn, result_id, decision, reviewer, justification)`: decision in approve/reject/override; reviewer
required; override needs a justification; the result must be `PENDING_REVIEW`. It inserts `review_decisions`, sets
the new state, writes the decision into the pack's `review`, and appends a `review` trail entry with the reviewer as
actor.

### 15.6 Loading a ledger

`load_dataset(conn, folder)` / `load_frames(conn, frames, name, replace=True)`: with `replace`, delete (in order)
`email_mentions, emails, review_decisions, audit_trail, audit_flags, latest_results, audit_results, audit_runs,
benchmark_labels, approval_logs, invoices, goods_receipts, purchase_orders, vendor_master`; then insert each table
(and `labels.csv` into `benchmark_labels`), converting text values with `typed(kind, column, value)`
(`BOOLEAN_COLUMNS` = is_active, blacklisted, blacklist_status -> 0/1; po_id/grn_id "" -> NULL; number/integer
parsed; empty date -> NULL); record `meta.dataset = name`.

`upsert_records(conn, table, key, records)` inserts text records or updates the row with the same key
(`ON CONFLICT (key) DO UPDATE`), used by the stream workers.

### 15.7 Users

`ROLES = ("viewer", "reviewer", "admin")`, each including the ones before it. `add_user(name, role)` creates a token
with `secrets.token_urlsafe(32)`, stores only `sha256(token)`, and returns the token once. `user_for_token`,
`has_users`, `list_users`, `disable_user`.

---

## 16. The batch audit service

`service.py`.

```python
audit_invoices(conn, config, policy, client, invoice_ids, *, sample_rate=1.0, workers=1, note="", progress=None) -> run_id
```

1. Build the graph once. Start a run (`audit_runs` row with configuration, policy version, model, prompt hash
   when a model is used, note).
2. Read the citations of the policy version (`clause_citations`: clause -> document, page).
3. Transactions: `extract_many` for 200+ invoices (`BULK = 200`), else `extract_one` per invoice.
4. `workers == 1`: invoke the graph per invoice. Otherwise a thread pool runs the graph (the time goes to model
   calls), while this thread alone reads and writes the database; at most `2 * workers` in flight.
5. `store_result(conn, run_id, state, config, policy, model, citations, sample_rate)`: add the citation to each
   pack flag, `to_result`, `workflow_status(route, id, sample_rate)`, `save_result(commit=False)`.
6. Commit every 200 results and at the end; finish the run (`finished_at`).

`run_summary(conn, run_id)` returns counts of invoices, flags, model calls, tokens, failed stages and states.

---

## 17. Policy documents

A policy reaches the system as a PDF. Five modules handle documents.

```
policy_v2.5.json --build_policy.py--> SOP_v2.5.md --policy_pdf.py--> Procurement_Audit_SOP_v2.5.pdf
                                                                          |
               clause registry <----- verified against ----- policy_ingest.py --> policy_chunks (citations, search)
                                                                          |
                     new PDF --policy_extract.build (patterns)--> registry --adopt--> new policy version
                     new PDF --policy_llm.propose (model) --verify (code) --decide (person)--> new policy version
                     new registry --simulation.simulate--> what would change on the stored ledger
```

### 17.1 Rendering PDFs (`policy_pdf.py`)

Markdown -> reportlab flowables (headings, paragraphs, bullet rules, tables; body font size 10) -> PDF with a title
and a footer `"<name> | version <v> | page N"`. `make_sample_pdfs()` writes `Procurement_Audit_SOP_v2.5.pdf`,
`Procurement_Audit_SOP_v2.6.pdf` and `Audit_Review_Procedure_v1.0.pdf` (a non-policy procedure document) into
`policy/pdf/`.

### 17.2 Ingestion: PDF to chunks (`policy_ingest.py`)

1. **`read_lines(path)`**: PyMuPDF `page.get_text("dict")`; each text line with its page, the largest span font
   size and its left x; lines without any letter or digit are skipped (bullet marks); within a page, sorted by
   `(round(y), x)`. Also returns the page count and the title from the PDF metadata.
2. **`chunk_lines(lines)`**:
   - body size = the font size covering the most characters; drop lines smaller than body size - 0.5 and footer
     lines matching `\|\s*page \d+\s*$`; margin = the smallest x of the body;
   - a line at least 1 point larger than body is a **heading**: it closes the current chunk and becomes the section
     (a heading that wraps continues at the same size);
   - a line matching `^Rule (\d+(?:\.\d+)+) \((\w+)\),` starts a **clause chunk**; indented lines (x > margin + 3)
     continue it;
   - any other line goes to a **text chunk** of the current section; lines before the first numbered section
     (`^(\d+(?:\.\d+)*)\.?\s+(\S.*)$`) form the document **header**.
   Each chunk: `{kind, clause_id, section, page (where it starts), text (whitespace collapsed)}`.
3. **`ingest(conn, path)`**: the version is read from the header (`Version:\s*(\d+(?:\.\d+)*)`). If that version is
   stored, each clause chunk's text is compared with the registry's rendered rule text (`clause_texts`):
   `verified = 1` if identical, else `0` (reported: the PDF and the applied policy would disagree). Replaces any
   earlier ingestion of the same file name; stores the SHA-256 of the file. Returns pages, chunks, clauses,
   unverified and missing clauses.
4. **`clause_citations(conn, version)`** -> `{clause: {document, page, text, verified}}`, used to cite findings.

### 17.3 Compiling a template-worded policy (`policy_extract.py`)

The thresholds are read from the wording of the rules **by pattern, no model**. One regular expression per
parameter, matched against its rule's text (`NUMBER = (\d[\d,]*(?:\.\d+)?)`):

| Clause | Parameter | Pattern |
|---|---|---|
| 2.1.1 | amount_tolerance_pct | `difference of up to {NUMBER}\s*% of the PO amount` |
| 3.1.1 | gstin_length | `exactly {NUMBER} alphanumeric characters` |
| 3.1.2 | state_code_min / max | `state code from {NUMBER} to \d+` / `state code from \d+ to {NUMBER}` |
| 4.1.1 | max_invoices_per_vendor_per_day | `at most {NUMBER} invoices dated on the same day` |
| 4.1.2 | guide_window_days / guide_band_pct | `as a guide, {NUMBER} days` / `within {NUMBER}\s*% of the limit` |
| 4.2.1 | non_business_days | `dated on a (.+?) is an exception` -> split on `,`, `or`, `and` |
| 4.3.1 | round_amount_multiple | `exact multiple of INR {NUMBER}` |
| 4.4.1 | blocked_gstin_statuses | `registration status is (.+?), is an exception` -> words |
| 5.1.1 | approval_limits | the table text `Approver role Approval limit (INR) <role> <number> ...` (rows `([A-Za-z][A-Za-z ]*?)\s+{NUMBER}`) |

`build(path, reference_registry) -> Extraction(file, title, version, pages, registry, text, problems, changes)`.
The **reference** registry (the active version by default) defines which rules the system can execute. Problems
that make a document unusable (it is then **refused** with every reason):

- no `Version:` in the header;
- a rule stated more than once;
- a rule the system executes is missing from the document;
- a rule in the document that the system has no control or agent for;
- a parameter not found in its rule's wording; no approval-limit table;
- a severity that is not low/medium/high/critical; a non-business day that is not a weekday name; a role of the
  reference with no limit in the table.

Severities and every parameter come from the document; titles and kinds come from the reference. Values are cast
to the reference's types. `changes` lists every parameter (and severity) that differs from the reference.
The policy text stored for the agents is rebuilt from the document's own wording (`policy_markdown`).

`adopt(conn, path, reference_version=None, activate=False, replace=False)`: build; if unusable, return the report
unchanged; if the version is stored with **other** parameters and not `replace`, refuse; else `store_policy`
(inactive), `policy_ingest.ingest` the document for citations, and activate if asked.

### 17.4 Reading a free-worded policy with a model (`policy_llm.py`)

For a policy in the organisation's own words. Three safeguards: **the model proposes, code verifies, a person
confirms.**

1. **Propose.** The model receives the list of rules the system executes, each described **without numbers**
   (e.g. 2.1.1: "the invoice amount must equal the purchase-order amount, within a tolerance"; parameters described
   e.g. "the tolerance in percent of the purchase-order amount (a number)"), and the document page by page
   (`[page N]` blocks). System message: never invent text, every quote copied character for character, never guess
   a number, a value must be written in one of your quotes for that rule. Reply:
   `{"version", "rules": [{"clause", "quotes": [<=3 passages, <=40 words], "values": {param: value}}]}`.
   Called with `max_tokens=2500`.
2. **Verify** (code). A quote must occur in the document after normalization (whitespace collapsed, typographic
   quotes and dashes made plain, case-folded) and be at least 8 characters; its page is recorded. A value is coerced
   to the reference type (limits per role, all roles present, positive; lists of words; weekday names; numbers in
   range; integers where the reference is an integer). A value is **verified** only if it is *written in a
   verified quote of its rule*, in any of its forms: digits, with commas, Indian grouping (`1,00,000`), two-digit
   form, number words two to twenty, `N lakh(s)`, `N crore(s)`. Otherwise the item is **needs attention** (with the
   reason) or **missing**. The version comes from the document text, not the model.
3. **Decide** (person). The reviewer can supply passages for rules the model did not locate (they must occur in the
   document), accept all verified values, and supply or correct any value. Nothing is stored while a value is open.
4. **Adopt**: requires the reviewer's name; stores the version with an `adoption` record (model, reviewer, time,
   which values the person supplied); the located passages become the citation chunks (`verified` NULL).

The verification catches a value the document does not state; it cannot catch a real quote that belongs to another
rule; that is what the person is for.

### 17.5 Simulating a policy before adoption (`simulation.py`)

`simulate(conn, registry, examples=20)`: extract every invoice of the stored ledger once; run the twelve controls and
C1 scoring under the **active** registry and under the **new** one, in memory; nothing is stored. Returns
`{active_version, new_version, invoices, decisions_moved (set of violated rules changed), newly_flagged, cleared,
routes {before, after}, route_changes {"approve -> escalate": n}, findings_by_rule [{rule, before, after}],
amount_newly_held (sum of amounts newly escalated), examples}`. Judgement rules are not simulated (they need a
model). For control rules the prediction is exact: it equals what adopting the document and re-auditing produces.

---

## 18. Policy search and the copilot

### 18.1 The index (`retrieval.PolicyIndex`)

Indexes the chunks of one policy version (default: the active one) plus documents that carry no version. Each
chunk is indexed as `"<section>. <text>"`.

| Ranking | How |
|---|---|
| **lexical** | TF-IDF over words (sublinear tf, 1-2 grams, English stop words) and over characters (`char_wb`, 3-5 grams); score = 0.5 x word cosine + 0.5 x char cosine |
| **dense** | cosine of unit-length embeddings from an OpenAI-compatible `POST /embeddings` (`AUDITIQ_EMBED_MODEL`, base URL and key default to the chat ones; query and document prefixes) |
| **hybrid** | reciprocal rank fusion: `1/(60 + lexical_rank) + 1/(60 + dense_rank)` |
| **rewrite** | before ranking, the chat model restates the question in the documents' vocabulary; it sees only the section and rule titles. Reply `{"restatement", "titles": [<=3]}`, appended to the question |

`mode="auto"`: lexical when no embeddings; with embeddings, **dense** for the question as asked and **hybrid** for a
restated one (chosen on the development half of 32 paraphrased questions, `results/retrieval.md`). Embeddings are
computed by `policy embed` (`embed_chunks`, batches of 16) and stored per chunk with the model's name; the index uses
them only if every chunk has one from the configured model.

The API's search endpoint restates the question when a chat model is configured and reports the restatement.

### 18.2 The copilot (`copilot.py`)

**Policy and invoice questions** (`answer(question, conn, index, client, k=4, invoice_id=None)`):

1. Retrieve `k` passages (restating the question when a model is available).
2. If an invoice id is given or found in the question (`\bINV\d{3,}\b`), load its latest audit pack. The passages
   of the clauses its findings cite are put **first** (a question such as "why was it flagged" names no rule, so
   retrieval by wording alone finds the wrong rules).
3. Without a model, return the passages only. With one, the system message says: use only the PASSAGES and the
   AUDIT RECORD; the audit record is the authority on what was found; name only the rules its findings cite; if the
   documents do not answer, say so; cite passage numbers `[n]` after every statement. Reply
   `{"answer", "passages_used": [n]}`; sources = the passages used (valid numbers only).

**Data questions** (`data_question(question, target, client)`): the model writes **one SELECT** (dialect named),
given the schema of the readable tables and guidance (outcome is in `v_latest_results`; `v_review_queue` lists what
waits; `approval_status` is not the audit outcome; at most 200 rows). Reply `{"sql": ["..."], "explanation"}`. Up to
two attempts (the error goes back to the model once). Four guards:

1. `check_sql`: one statement, starts with `SELECT` or `WITH`, no `;` inside.
2. Name check: the statement may not name any table or view outside the allow-list (`invoices, vendor_master,
   purchase_orders, goods_receipts, approval_logs, v_latest_results, v_review_queue, audit_flags,
   review_decisions, policy_clauses`, plus `audit_results, audit_runs, latest_results` read through the views), nor
   any catalogue (`sqlite_master`, `pg_catalog`, `information_schema`, `pg_*`). `benchmark_labels` is never
   readable.
3. Escaping functions refused: `set_config, current_setting, query_to_xml*, cursor_to_xml*, table_to_xml*,
   schema_to_xml*, database_to_xml*, ts_stat, dblink*, lo_*`, and `U&'...'` Unicode-escaped strings (these once let
   a statement switch role and read the labels).
4. Execution read-only with limits: on SQLite a read-only connection, an **authorizer** that allows SELECT and
   FUNCTION and denies reading any forbidden table, and a progress handler that stops after 10 s; on PostgreSQL a
   read-only transaction, `statement_timeout = 10000`, and `SET ROLE auditiq_reader` (a role with SELECT on the
   allow-list only); without that role, data questions are refused. At most 200 rows are returned.

---

## 19. Kafka ingestion

`stream.py`, `emails.py`, `auditiq_bench/correspondence.py`, `scripts/kafka_local.py`. Full write-up:
`docs/STREAMING.md`.

### 19.1 Topics

Four topics, each with `AUDITIQ_KAFKA_PARTITIONS` partitions (default 4), named `<prefix>.<kind>` with
`AUDITIQ_KAFKA_PREFIX` (default `auditiq`):

| Topic | One message | Key | Value | Written to |
|---|---|---|---|---|
| `auditiq.vendor` | a vendor master record | vendor id | JSON `{"vendor": {...text fields}}` | `vendor_master` |
| `auditiq.invoice` | an invoice packet | vendor id | JSON `{"invoice", "po", "grn", "approvals": [...]}` (text fields) | ledger tables, then an audit |
| `auditiq.email` | a vendor e-mail | Message-ID | raw RFC 5322 MIME bytes | `emails`, `email_mentions` |
| `auditiq.compliance` | a policy document | file name | JSON `{"file", "pdf": base64, "activate": bool}` | a policy version |

Keying invoices by vendor puts all of a vendor's invoices on one partition, in publication order (ledger order).
`ensure_topics(settings, partitions)` creates missing topics and adds partitions to smaller ones (Kafka cannot
remove partitions; adding them re-maps some keys for new messages). Replication: `AUDITIQ_KAFKA_REPLICATION`
(default 1).

### 19.2 Publisher

`Publisher(settings)`: confluent-kafka `Producer` with `enable.idempotence=True`, `acks=all`, `linger.ms=20`,
`compression.type=lz4`. A full local queue (`BufferError`) waits on `poll(0.5)`; `close()` flushes and raises if
any message was not delivered. `publish_ledger(publisher, dataset, limit)` sends the vendor feed, then the invoices
sorted by `(date, invoice_id)` with their PO, GRN and approval entries. `publish_mailbox(publisher, mbox)` sends
every message of an mbox file. `publish_policy(publisher, pdf, activate)`.

### 19.3 Workers

`Worker(settings, conn, kind, config=C1, client=None, batch=500, sample_rate=1.0, vendor_wait=60.0).run(idle_exit,
max_messages)`. A worker consumes one topic in the group `<prefix>-<kind>-workers`, keeps no state of its own, and
writes everything to the database. Consumer settings: `enable.auto.commit=False`, `auto.offset.reset=earliest`,
`max.poll.interval.ms=1800000` (a batch audited with a model can take minutes).

**Exactly once into the database.**

1. A batch (up to 500 messages) and everything it writes form **one database transaction**, which also updates
   `stream_offsets(group, topic, partition) = last offset + 1`.
2. On partition assignment, the worker starts from the offset **stored in the database**, not Kafka's.
3. **Fencing**: the offset row is updated only `WHERE next_offset <= <first offset of this batch>`; if no row moves
   and the insert finds a row already there, another worker has processed past this batch: the batch is rolled
   back (`Fenced`) and the worker seeks to the stored offsets.
4. After the commit, offsets are also committed to Kafka (asynchronously), only so that lag can be shown.

On SQLite the worker opens the transaction with `BEGIN IMMEDIATE` (taking the write lock at once; two workers that
each read and then try to write would deadlock) and sets `busy_timeout = 60000`. Each message runs in a
`SAVEPOINT`; a failing message is rolled back to its savepoint, logged with outcome `error` and the reason, and the
partition goes on. Every processed message gets a `stream_log` row: topic, partition, offset, key, produced time
(Kafka create time, ms), processed time, outcome (`stored`, `audited`, `adopted`, `refused`, `error`), detail,
result id.

**Per topic:**

- **vendor**: `upsert_records(vendor_master)`.
- **invoice**: (a) use the policy version in force on the invoice's date (one graph and one run per version);
  when the timeline changes, finish the runs and rebuild the graphs. (b) If an
  invoice's vendor is not known yet (it comes through another topic), the partition **waits**: processing stops at
  that message and the consumer seeks back to it; after `vendor_wait` seconds without the vendor, it is logged as an
  error and skipped. (c) Upsert PO, GRN, invoice, approvals. (d) Extract with `extract_arrived` (history = only
  earlier invoices). (e) Audit and store (`store_result`) in a savepoint. (f) **Completed same-day groups**: if the
  invoice gets a same-day splitting finding, the other invoices named in its evidence whose latest result lacks that
  finding are audited again (with `extract_one`, the full arrived history), because they were within the limit when
  they arrived. Their results go to a second run of the worker ("invoices audited again when a later invoice
  completed their same-day group"). (g) Link waiting e-mails (below).
  A run holds one result per invoice; an invoice published twice starts a new run.
- **email**: `emails.store(conn, raw)`.
- **compliance**: write the PDF to a temporary file and `policy_extract.adopt(..., activate)`; outcome `adopted`
  (detail "version 2.6, active") or `refused` (the problems). Adoption commits by itself, so it runs outside the
  per-message savepoint; re-adopting the same document is harmless.

`status(settings, conn, timeout)` -> per topic: partitions, messages (sum of high watermarks), processed (sum of
stored offsets), lag, outcome counts.

### 19.4 Vendor e-mails (`emails.py`)

- `parse(raw)`: Python `email` package (`policy.default`): Message-ID, sender (lower case) and its domain,
  recipient, subject, `Date` as `YYYY-MM-DD HH:MM:SS`, plain-text body.
- Invoice numbers in text: `\b(?=[A-Z0-9/-]*\d)(?=[A-Z0-9/-]*[A-Z])[A-Z0-9]+(?:[-/][A-Z0-9]+)*\b`
  (case-insensitive: letters and digits, both present, parts joined by `-` or `/`; dates and amounts have no
  letters, words no digits). Tokens are looked up as written.
- `link(conn, mail)`: numbers in the subject first, then the body; among invoices with a matching
  `invoice_number`, the latest dated on or before the e-mail (a duplicate shares the number).
- `store(conn, raw)`: upsert into `emails`; record every mentioned token in `email_mentions`.
- `link_waiting(conn, numbers)`: when invoices arrive, link the stored unlinked e-mails that mention their numbers.
- **Race on PostgreSQL**: an e-mail and its invoice written at the same moment by two workers cannot see each
  other's uncommitted rows. Both sides take `pg_advisory_xact_lock(4702315002)` for linking (the e-mail worker at
  the start of its batch, the invoice worker at the very end of its batch), so the later transaction sees the
  earlier one's rows.

### 19.5 Synthetic correspondence (`auditiq_bench/correspondence.py`)

`python -m auditiq_bench.correspondence --dataset <ledger> --out <file.mbox> [--seed 7]` writes an mbox and
`<file>.labels.csv` (`message_id, category, suspicious, invoice_id, vendor_id`). Per invoice (in date order):
`invoice_submission` with probability 0.35; `payment_reminder` for unpaid invoices with probability 0.06; a
`quantity_query` when the GRN's received quantity is below the billed quantity. Per vendor (its latest unpaid
invoice): a legitimate `bank_change` (probability 0.08) from the vendor's domain, or a **suspicious** one
(probability 0.03) from a look-alike domain (`<name>-accounts`, `<name>s`, `pay-<name>`, or an `i` changed to `l`),
urgent, asking to pay to a new account. Every address is under `.example` (RFC 2606). Same ledger and seed, same
file.

### 19.6 Running

`python scripts/kafka_local.py init|start|stop|status|reset` runs a one-node KRaft broker without Docker (Java 17+):
the release unpacked to `%LOCALAPPDATA%\auditiq\kafka`, data in `kafka-data`, listeners on `127.0.0.1:9092`
(controller 9093), `auto.create.topics.enable=false`, `log.retention.hours=-1` (segment deletion is unreliable on
Windows), started by calling Java directly with classpath `libs/*` (the release's `.bat` scripts overflow cmd's
line length in a long folder). `init` writes `AUDITIQ_KAFKA_BOOTSTRAP` and `AUDITIQ_TEST_KAFKA_BOOTSTRAP` to `.env`.

CLI: `stream topics [--partitions]`, `stream publish --dataset D [--limit N] --emails M --policy P.pdf [--activate]`,
`stream work [--topic invoice|email|vendor|compliance|all] [--processes N] [--config C1..C5] [--batch 500]
[--idle-exit S]` (one process per worker), `stream status`. API: `GET /api/stream`. A ledger can arrive entirely
through Kafka: `setup` without `--dataset` stores only the policy versions.

---

## 20. The REST API

`api.py`, FastAPI. `python -m auditiq serve [--host 127.0.0.1] [--port 8000]` runs it with uvicorn and also serves
the built web application (`frontend/dist`) with client-side routes (any non-API path returns `index.html`).

### 20.1 The app factory

`create_app(target=None, token=None, frontend=..., cors_origins=None)`. State: the database target, the shared token
(`AUDITIQ_API_TOKEN`), the jobs, the pending policy proposals. CORS origins from `AUDITIQ_CORS_ORIGINS` (default the
Vite dev server `http://localhost:5173,http://127.0.0.1:5173`). Every request opens its own database connection
(so the API holds no state between requests and works on both backends). Interactive docs at `/api/docs`.

### 20.2 Who is asking (authentication and roles)

`principal(request)`:

1. If a shared token is set and the header equals `Bearer <token>` (compared with `hmac.compare_digest`, constant
   time): **admin**, via "shared token".
2. Else, a user whose token's SHA-256 matches `api_users.token_hash` and is not disabled: that user's role, via
   "account".
3. Else, if the server has **neither** a shared token **nor** any user: **admin**, via "open" (a local single-user
   setup).
4. Else 401 with `WWW-Authenticate: Bearer`.

`require(role)` is a dependency: 403 when the caller's role ranks below (viewer < reviewer < admin). A review
decision recorded with an account uses the **account's name** as reviewer, whatever the body says.

### 20.3 Security headers

On every response: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`. On
web pages (not `/api/`), a Content-Security-Policy:

```
default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:;
font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'self';
form-action 'self'; frame-ancestors 'none'
```

(`'unsafe-inline'` styles because the 3D labels are positioned with style attributes.) `/assets/*` (content-hashed
build files) get `Cache-Control: public, max-age=31536000, immutable`; `index.html` is served with `no-cache`.

Error mapping: `DatabaseUnavailable` -> 503, `LLMError` -> 502 ("the model did not answer"), `JobConflict` -> 409.
Errors carry `detail` (a message, or `{"message", "problems"}`).

### 20.4 Background jobs

Long work runs on a daemon thread with its own connection. The request answers **202** with the job;
`GET /api/jobs/{id}` returns `{id, kind, status (queued|running|done|failed), done, total, result, error, seconds}`.
The 200 most recent finished jobs are kept in memory. Jobs that would change the ledger under one another are
refused with **409**:

| Job kind | Refused while one of these runs |
|---|---|
| `load-ledger` | load-ledger, apply-policy, audit, simulate |
| `apply-policy` | load-ledger, apply-policy |
| `audit` | load-ledger |
| `simulate` | load-ledger |

### 20.5 The 38 endpoints

| Method | Path | Role | What it does |
|---|---|---|---|
| GET | `/api/health` | open | status, version, backend, ledger name, active policy version, model name (503 when the database is down) |
| GET | `/api/me` | viewer | who is calling: `{name, role, via}` |
| GET | `/api/overview` | viewer | counts by state, route and risk level; findings by rule (rule, title, severity, source, count); 10 recent runs; 10 vendors with most invoices waiting; the 14 newest steps of the audit trail; invoices, vendors, audited, findings, reviewed; `coverage`: latest results per configuration, invoices checked by the controls and by the agents, findings approved without review, and on a benchmark ledger the answer key per configuration, scored only under the labels' policy version (docs/ANALYTICS.md) |
| GET | `/api/risk-map` | viewer | one point per vendor: category, invoices, amount, invoices waiting, findings, max risk (Rc) of its latest results, blacklisted |
| GET | `/api/analytics` | viewer | monthly volume, spend by category and month, Benford first-digit and first-two-digits tests (MAD with Nigrini's thresholds, z per digit, chi-square), invoices by quarter-decade of amount and just under / just over each approval limit, weekdays, findings by category and rule, top approvers, spend concentration (Lorenz, Gini, HHI, top ten) |
| GET | `/api/policy/graph?version=` | viewer | the policy knowledge graph of a version (default: active): nodes (version, sections, rules, parameters, roles, control functions and agents, pages, other versions) and edges (has section, has rule, sets, limit, checked by, stated on, changes); 404 for an unknown version |
| GET | `/api/policy/graph/ask?q=&version=` | viewer | what the question names, the facts the graph derives (routing an amount, the structuring band, round amounts, limits, changes, sets, checkers) with their citations, their passages, and the nodes used; 400 when empty |
| GET | `/api/rings?limit=` | viewer | collusion rings (identity links; approval links that pass a one-sided binomial test against the role's rate, Benjamini-Hochberg at FDR 1 %), single-vendor groups, the 40-pair watch list with p and q, leads for drawing, the tests and the rate of each role, the identity checks |
| GET | `/api/stream` | viewer | Kafka topics: messages, processed, lag, outcomes; `{configured: false}` without a broker; `error` when it does not answer |
| GET | `/api/system` | viewer | what is running: the store, the Kafka broker (answers or not), the chat model (asked whether it answers, 2 s, kept 20 s), the embedding model and how many passages it embedded, the active policy |
| GET | `/api/stream/sources` | viewer | the ledgers, mailboxes and policy documents the server can publish |
| POST | `/api/stream/publish` | admin | job: publish a ledger (first `limit` invoices), a mailbox or a policy document to the topics; 409 for a ledger that would replace the store's invoices with different ones under the same numbers |
| POST | `/api/stream/work` | admin | job: run the workers of the topics chosen until each has been idle for `idle_exit` s |
| GET | `/api/stream/log?limit=&topic=` | viewer | the newest messages the workers processed: partition, offset, key, outcome, detail, result, time from produced to processed |
| GET | `/api/stream/peek?kind=&n=` | viewer | the newest messages of a topic as they sit in Kafka, with the fields that identify each |
| GET | `/api/rag/trace?q=&k=` | viewer | every step of retrieval for a question: what the graph recognises, its facts, each passage's lexical, dense and fused score and rank, the context Ask AI would send, the passages and the question in three principal components |
| GET | `/api/knowledge` | viewer | the documents, every passage (page, kind, rule, whether it matches the registry, embedding model, its point in the map), the registry of every version |
| GET | `/api/ai` | viewer | the agents and their remits, the configurations, what each stage of the stored trails cost, the invoices whose latest result came from the agents |
| GET | `/api/pipeline` | open | the 11 stages (id, label, kind code/llm/person, feature) and the stage list of each configuration, for the 3D diagram |
| GET | `/api/queue?limit=&level=` | viewer | invoices waiting for review (max 2,000; of one risk level when asked), highest Rc first; `levels` counts the whole queue per level with the amount at stake; each with the rules its kept findings break (most severe first); `rules` = titles in the active policy |
| GET | `/api/invoices?q=&limit=` | viewer | search by invoice id or vendor name (LIKE), with the latest route, level, Rc and state |
| GET | `/api/invoices/{id}?with_label=` | viewer | records, vendor history (last 40 of N), vendor e-mails, latest result with pack and trail; the benchmark label on request; id must match `^[A-Z0-9_-]{1,40}$` |
| POST | `/api/results/{id}/decision` | reviewer | approve / reject / override (+ reviewer, justification) |
| POST | `/api/invoices/{id}/audit` | reviewer | job: audit one invoice again with C1..C5 under the version in force on its date (C2..C5 need a model that answers, else 400) |
| GET | `/api/policy` | viewer | versions, the active one's clauses and parameters, ingested documents, the timeline (which version governs the invoices of which dates, how many each governs, how many were audited under another version or not at all) |
| POST | `/api/policy/activate` | admin | make a stored version active: it governs the invoices from its effective date |
| POST | `/api/policy/preview` | admin | upload a PDF (<= 20 MB, must start with `%PDF`): what it states, changes against the active version, problems; nothing stored; returns an upload id |
| POST | `/api/policy/adopt` | admin | adopt a previewed document (activate, replace) |
| POST | `/api/policy/simulate` | admin | job: dry run of a previewed document over the ledger |
| POST | `/api/policy/propose` | admin | job: the model reads a free-worded document (needs a model) |
| POST | `/api/policy/confirm` | admin | adopt a proposal after the reviewer's confirmation, values and passages (422 with the open items) |
| POST | `/api/policy/apply` | admin | job: re-audit with C1, each under the version in force on its date, the invoices whose result is not under that version, those the active version governs and those never audited |
| POST | `/api/ledger` | admin | job: replace the ledger from an .xlsx or .zip (<= 100 MB, must start with `PK`, requires `replace=true`); checked first, nothing replaced on any problem |
| GET | `/api/search?q=&k=` | viewer | policy search (restated by the model when configured): mode, restatement, hits |
| POST | `/api/copilot/ask` | viewer | job: policy / invoice question |
| POST | `/api/copilot/data` | viewer | job: data question (needs a model) |
| GET | `/api/jobs/{id}` | viewer | job status |
| GET | `/api/results` | viewer | measured results read from `results/` (benchmark metrics, per-class detection, policy change, scalability incl. the 500k ledger, policy reading, pilots) |

`docs/API.md` is generated from the app by `python -m auditiq.apidoc` (role read from each dependency's
`required_role`), and a test checks it is current.

---

The answers of `/api/overview`, `/api/risk-map`, `/api/analytics` and `/api/rings` are kept per server process by
`StoreCache` with a fingerprint of the store (ledger name, newest result, newest review decision, policy versions
and parameters, Kafka offsets, the labels' policy): an audit, a decision, a ledger load, a policy change or a
streamed batch makes the next request compute afresh.

**The policy knowledge graph** (`auditiq/policy_graph.py`, docs/POLICY_GRAPH.md) is built per request from the
clause registry, the documents and the code that checks each rule, with no model. Ask AI passes it to
`copilot.answer`: its facts go to the model as a FACTS block labelled [F1], [F2], and the passages they cite come
before the retrieved ones (`merge_passages`). Evaluated against the passage rankers by `evaluation/graph_eval.py`.

## 21. The web application

`frontend/`. A single-page app that uses the API only.

### 21.1 Build and runtime

- Vite dev server on 5173 proxies `/api` to `http://127.0.0.1:8000`. `npm run build` = `tsc -b && vite build` into
  `dist/` (source maps on). Manual chunks: React + router in one chunk, three.js/R3F/drei in another that loads
  only with a page that draws 3D.
- Every page is lazy-loaded (`React.lazy`) inside a `Layout` with a sidebar.
- `api/client.ts`: `request<T>(path, init)` adds `Authorization: Bearer <token>` from `sessionStorage`, parses
  JSON, turns errors into `ApiError(status, message, problems)`. `waitForJob(job, onProgress, intervalMs=1000)`
  polls `/api/jobs/{id}` until done or failed. Every endpoint has a typed function; types are in `api/types.ts`.
- `lib/useApi(load, deps)` -> `{data, error, loading, reload}`; `notifyStoreChanged()` fires a window event so the
  sidebar's status refreshes after a ledger or policy change.
- When the API answers 401, the layout shows a token form (stored in `sessionStorage` for the tab).

### 21.2 Routes and pages

| Route | Page | Content |
|---|---|---|
| `/` | Overview | six KPI cards (invoices + vendors, audited, approved automatically, waiting, findings, reviewed) and eight forensic signals; **audit coverage and quality** (configurations, controls and agents coverage, notices, the answer key per configuration); the composition of the audit (risk level, route, workflow as stacked bars); the **risk constellation** (3D) with legend; the vendor risk matrix and the monthly trend; findings by rule (table with severity and share); the escalation queue; vendors with most invoices waiting; the audit trail's newest steps; high-risk vendors; recent runs with durations; **load a ledger** (file, confirm replacement, job progress, problems, then "audit it with the controls") |
| `/review` | Review queue | the **queue constellation** (3D) of the waiting invoices with legend; filters (text, risk level); table (invoice link, vendor, date, amount, route badge, risk meter, findings, configuration) |
| `/invoice`, `/invoice/:id` | Invoices | search; for one invoice: route and both risk meters, recommended action, every finding (rule, title, severity, source, confidence, evidence, citation, revision), findings removed by the challenger, records in tabs (Invoice, PO, GRN, Vendor, Approvals, Vendor history), the decision form (approve/reject/override; justification required for override; reviewer from the account), "audit again" with a configuration (C2..C5 only with a model), the audit trail (tokens and seconds per model call), the vendor e-mails that name the invoice (collapsible), and the benchmark answer key on request |
| `/policy` | Policy | versions with activate; the **policy knowledge graph** (3D, version chooser, "Ask the graph" with examples, facts with citations, the relations of a node, every relation as a table); the active rules and parameters; **adopt a document** (upload PDF -> preview with changes and problems -> simulate the impact (decisions that would move, route changes, findings by rule now and under the document) -> adopt and activate; for a free-worded document with a model: the model's proposal with verified / needs-attention values, quotes and pages, passages and values supplied by the reviewer, confirm); ingested documents; **policy search** with the model's restatement shown |
| `/analytics` | Analytics | eight KPIs; monthly volume; the **spend skyline** (3D, category by month); Benford (first digit / first two digits, with the MAD, chi-square and the digits that differ); amounts against the approval limits (log histogram with the limits and the 10 % bands) and just under / just over each limit; weekdays; the Lorenz curve with the ten largest vendors; findings by category and rule (heat table); approvers |
| `/rings` | Collusion rings | eight KPIs (rings, pairs and approvers tested, most unusual pair, identity checks); the **collusion network** (3D) of the rings, or of the leads below significance when none passes, with the list and the detail of the one chosen; the watch list; the tests and the rate of each role; single-vendor groups; how rings are found |
| `/ask` | Ask AI | ask about the policy or an invoice (examples taken from the queue); answer with numbered citations, the facts of the policy graph ([F1]...) and the passages; ask about the data (the SQL, explanation and rows). `/copilot` redirects here |
| `/pipeline` | Pipeline | eight KPIs; the **architecture diagram** (SVG from `lib/architecture.ts`: 10 subsystems, 51 components with files and live figures, 43 connections drawn as rounded orthogonal runs with animated flow; hover traces a component's connections, click shows its description, files and connections; a configuration chooser dims the stages it does not run); the configurations compared stage by stage; tabs C1..C5 with the **pipeline** in 3D (stages lit for the configuration, flowing dots on the edges) and the stage list; the **Kafka ingestion** panel (four topic cards: processed of messages, partitions, lag, outcomes) |
| `/results` | Results | KPIs; detection table on every benchmark ledger with 95% intervals; per-class detection heat table; the **policy-change** bars (3D) with the table; scalability line chart (throughput vs workers) and table by ledger size; policies read in their own wording; real-model pilots and samples |

### 21.3 The 3D views

All are React Three Fiber scenes inside `SceneFrame`: a `Canvas` (`dpr [1,2]`, perspective camera fov 45), a dark
canvas `#060a14` with fog (18 to 42), ambient 0.35 + directional 1.1 + an indigo point light, `OrbitControls`
(no pan, distance 5 to 32, max polar angle pi/2.05, optional auto-rotation at 0.35). A fallback message replaces the
canvas when the browser has no WebGL, and an error boundary does the same if the scene fails. Labels and tooltips
are drei `Html` elements. Every 3D view has a table with the same data on the page.

**Spend skyline** (`three/SpendSkyline.tsx`, `skylineLayout`): one box per category and month, months along x
(step 0.92), categories along z (step 1.15), the tallest five units, colour from dark to light teal by the square
root of its share of the largest, amber above 0.85. **Collusion network** (`three/RingNetwork.tsx`,
`networkLayout`): ring centres on a golden-angle spiral (`r = 1.9 sqrt(i + 0.5)`), members start on a small circle
around their centre and settle over 240 steps of repulsion within the ring, springs along links (rest length 0.9)
and a pull to the centre, each step capped by a falling temperature; vendors are spheres coloured by risk and sized
by spend, approvers diamonds, links one `lineSegments` geometry coloured by kind; a chosen ring dims the others.

**Shared constellation layout** (`three/layout.ts`, `placeInSectors`): one sector per group around a circle,
sectors sorted by name, `sector = 2*pi / groups`; within a group, items sorted by weight then id; for item i of n:
`angle = c*sector + sector * (0.12 + 0.76 * frac(i * 0.618034))` (golden-ratio jitter, stable between visits),
`radius = 2.2 + 7.5 * i/(n-1)`, `height = 0.15 + risk/100 * 4.2`; point size scaled by
`density = min(1, sqrt(250 / items))` so large ledgers do not merge into a surface.

| View | Points | Group (sector) | Weight / radius | Height | Size | Colour | Stem / pulse | Click |
|---|---|---|---|---|---|---|---|---|
| Risk constellation (Overview) | vendors | spending category | invoices | max Rc | `0.035 + 0.024*log2(1+invoices)` | risk colour; violet if blacklisted | stem + pulse when invoices wait | invoices of the vendor |
| Queue constellation (Review) | waiting invoices | most severe rule broken (label: rule number + title) | amount | Rc | `0.04 + 0.014*log2(1 + amount/10000)` | risk colour | stem always; pulse when Rc >= 70 | opens the invoice |

Both draw all points as **one instanced mesh** (`PointField`: one sphere geometry, per-instance matrix and colour),
with an instanced mesh of thin cylinders for the stems, so thousands of points cost one draw call. A dark floor
disc (radius 11) with a polar grid; sector labels at radius 11.6; a tooltip on hover.

Risk colours: below 30 `#34d399`, 30-49 `#fbbf24`, 50-69 `#fb923c`, 70+ `#f87171`, blacklisted `#a78bfa`.

**Pipeline** (`PipelineScene`): one rounded box per stage at
`x = (column - 3.5) * 3.1 + (column > 2 ? 0.7 : -0.7)`, `y = 0.6`, `z = depth * 1.9 - 0.95` (columns: extraction 0,
controls 1, the three agents and the single auditor 2 at depths -1.4, 0, 1.4, 2.8, challenger 3, confidence 4,
risk 5, review 6, pack 7). Colours by kind: code teal `#2dd4bf`, model violet `#a78bfa`, person amber `#fbbf24`;
stages the configuration does not run are faint. Edges between consecutive layers (the three agents fan out and in)
are quadratic Bezier curves with three dots moving along them; a rotating ring marks the controls ("the extra
feature"). Agent labels sit to the right of their boxes.

**Policy change** (`PolicyBars`): one bar per policy document on an arc, sorted by value;
`angle = pi * (0.15 + 0.7 * i/(n-1))`, `height = 0.08 + value/max * 6`, position `(cos*-8, h/2, sin*-4.5)`;
colour from teal to red by `value / 0.3`; value labels above the bars. Value = share of invoices a frozen system
decides against the policy in force.

### 21.4 Look

A light theme for the pages (background `#f3f5f9`, white cards with a soft shadow, ink `#0f172a`, brand indigo
`#4f46e5`, teal `#0d9488`, a white sidebar with an indigo active item) and the 3D views on their own dark canvas, as
dark cards inside the light pages. Fonts: Inter / Segoe UI / system. All colours are CSS custom properties in
`styles.css`.

### 21.5 Tests

36 Vitest tests: the client (token, errors, uploads, job polling), formatting helpers, the 3D layout geometry, the
scenes in `@react-three/test-renderer` (one instance per point, stems only where asked, a clicked point handed to
the page, stages per configuration, bars per policy), and every page against a mocked fetch. 10 Playwright tests in
Chromium against the real server on a fresh store (`scripts/e2e_server.py`): upload and audit a ledger, a review
decision, a re-audit, adopt and apply a policy, search, results, pipeline, copilot, routes; an error in the browser
console fails a test.

---

## 22. The Streamlit dashboard

`app/dashboard.py` (`streamlit run app/dashboard.py`), the lighter alternative to the web app, reading the same
database through the same modules. Pages: **Overview** (counts by status, findings by rule, loading a ledger),
**Review queue** (waiting results and the decision form), **Invoice** (audit pack and trail, audit again),
**Policy** (versions, clauses and parameters, adopting a document, policy search), **Copilot**.

---

## 23. The command line

`python -m auditiq [--db <sqlite path | postgresql URL>] <command>`. Every command closes the connections it opened
(a connection left open on PostgreSQL keeps its locks).

| Command | Does |
|---|---|
| `setup [--dataset D] [--policies 2.5 2.6]` | load a ledger (folder, zip or xlsx; checked first) if given; store the policy versions (first active); render and ingest the sample PDFs; embed the chunks if an embedding model is configured |
| `ledger check\|import\|export` | check or replace the ledger; export a dataset as a workbook |
| `policy make-pdfs\|ingest\|adopt\|simulate\|embed\|activate\|search` | documents: render, ingest, adopt (`--activate`, `--replace`, `--reference`; `--llm` with `--accept-verified`, `--set RULE.PARAM=V`, `--quote RULE=PASSAGE`, `--reviewer`, `--version`), simulate, embed, activate a version, search (`-k`, `--mode`) |
| `run --config C1..C5 [--invoice ...] [--unaudited] [--limit] [--workers] [--sample-rate] [--note] [--no-cache]` | batch audit, prints the run summary |
| `audit --invoice ID --config C [--review] [--dataset D]` | audit one invoice and print the pack; nothing stored; `--review` pauses at the human review (LangGraph `interrupt` with an in-memory checkpointer) and asks for the decision |
| `show --invoice ID` | stored pack (Markdown) and trail |
| `queue` / `decide --result N --decision D --reviewer R [--justification]` | the review queue and decisions |
| `ask "..."` / `ask-data "..."` | copilot |
| `serve [--host] [--port]` | API and web app |
| `export --out DIR` | every table as CSV |
| `status` | backend, ledger, row count of every table |
| `user add NAME --role R \| list \| disable NAME` | API users (the token is printed once) |
| `stream topics\|publish\|work\|status` | Kafka (Section 19) |
| `graph --config C` | the pipeline as a Mermaid diagram |
| `check-llm` | one request to the configured model |

`python -m auditiq_bench` generates the datasets; `python -m evaluation.<script>` runs an experiment.

---

## 24. The benchmark: AuditIQ-Bench

`auditiq_bench/`. Synthetic procurement ledgers with a labelled answer key. It shares **no code** with the pipeline
(it reads only the policy registry, which is data), and a dataset that fails its own validation is not written.

### 24.1 The datasets

| Dataset | Seed | Vendors | Invoices | Anomalous | Hard negatives | Purpose |
|---|---|---|---|---|---|---|
| `bench_seed_101`, `_202`, `_303` | 101, 202, 303 | 250 | 5,000 | 420 (8.4%) | 120 | results are reported as mean and spread over these three |
| `pilot_seed_909` | 909 | 250 | 5,000 | 420 | 120 | development: the only ledger on which prompts and settings may be tried |
| `swap_seed_404` | 404 | 250 | 5,000 | 150 (3.0%) | 0 | policy swap: 150 boundary invoices anomalous under v2.5, clean under v2.6 |
| `large_seed_505` | 505 | 1,000 | 20,000 | 420 (2.1%) | 240 | demonstration ledger; precision at a realistic anomaly rate |
| `huge_seed_606` (on request) | 606 | 15,000 | 500,000 | 2% | | scale; files kept outside the repository, hashes committed |

Files of a dataset: the five ledger CSVs, `labels.csv` (`invoice_id, label, class_id, clause_ids, severity, group_id,
related_invoice_id, hard_negative_type, note`), `eval_subset.csv` (`invoice_id, stratum, weight`), `manifest.json`
(seed, versions, period, counts, SHA-256 of every file) and a generated `README.md` datasheet. The same seed gives
byte-identical files.

### 24.2 How a ledger is built (`generator.Builder`)

1. **Vendors**: name (Faker `en_IN`), state, PAN, GSTIN built from state code + PAN, one of six categories, its own
   invoice-number style and prefix, a log-normal business weight (few large vendors, many small ones). A few
   vendors are blocked (blacklisted or suspended).
2. **Purchases**: an item from the vendor's category (36 items, 6 per category), quantity and unit price;
   amounts log-normal per category, between 3,000 and 4,500,000.
3. **Documents**: PO first, GRN some business days later, invoice after the GRN; the invoice describes the item in
   the vendor's words; all in financial year 2025-26.
4. **Approval**: approved by the lowest role whose policy limit covers the amount (sometimes the one above), with
   `Escalated` entries from the role below for some invoices above Manager level.
5. **Injection**: each anomaly and hard negative is built by the same steps with one thing changed, and its label is
   written by the injecting function. Clean invoices are kept clear of the structuring rule with a wider margin than
   its guide (no two invoices of a vendor within 20% of the same limit within 10 days unless they form a J2 group).
6. **Validation** (`validate.py`, independent of the controls): recomputes from the finished tables which
   rule-defined clauses each invoice violates and requires equality with the labels in both directions; checks the
   structure of the judgement classes and that no unlabelled invoice falls into their definitions.

Composition of a benchmark ledger: 30 invoices of each of 14 classes, 24 of each of 5 hard-negative types, the rest
ordinary clean (Profile defaults `PER_CLASS = 30`, `PER_HARD_NEGATIVE_TYPE = 24`).

### 24.3 Anomaly classes

| Class | Anomaly | Clause | Kind |
|---|---|---|---|
| R1 | invoice amount differs from PO beyond the tolerance (unit price changed) | 2.1.1 | rule |
| R2 | billed quantity exceeds received quantity | 2.1.2 | rule |
| R3 | duplicate invoice number of the same vendor (same PO, GRN, amount; only the later is anomalous) | 2.2.1 | rule |
| R4 | malformed GSTIN or invalid state code | 3.1.1, 3.1.2 | rule |
| R5 | invoice GSTIN differs from the vendor master (well formed) | 3.1.3 | rule |
| R6 | more invoices on one day than allowed (every invoice of the day, shared `group_id`) | 4.1.1 | rule |
| R7 | amount above the approver's limit, no escalation | 5.1.1 | rule |
| R8 | missing PO or GRN reference, or a PO not on record | 2.1.3 | rule |
| R9 | blacklisted or suspended vendor | 4.4.1 | rule |
| R10 | weekend date (half) or round amount (half) | 4.2.1, 4.3.1 | rule |
| J1 | near duplicate: re-keyed number (separators, leading zeros, suffix, swapped digits, O for 0, lower case) | 2.2.2 | judgement |
| J2 | three invoices for the same goods on different days within the window, each just below the approver's limit, together above it | 4.1.2 | judgement |
| J3 | invoice describes different goods from the PO (amounts agree) | 2.1.5 | judgement |
| J4 | GRN remark says units were rejected/returned while the quantity fields show the full quantity | 2.1.4 | judgement |

Hard negatives (clean, built to resemble a class): `HN_TOLERANCE` (variance just inside tolerance), `HN_DAILY_LIMIT`
(count exactly at the daily limit), `HN_NEAR_LIMIT` (amount just inside an approval limit), `HN_SIMILAR_NUMBER`
(consecutive numbers, equal amounts, separate deliveries), `HN_RECURRING` (identical monthly amounts).

### 24.4 The evaluation subset

Model configurations are expensive per invoice, so `eval_subset.csv` lists what they audit: every anomalous
invoice, every hard negative, every clean invoice a duplicate copies, and a random sample of 600 ordinary clean
invoices. Weights: 1 for the complete strata, N/n for the sampled ordinary invoices (N ordinary in the ledger, n
sampled), so the weights sum to the ledger size and a weighted rate on the subset estimates the rate on the whole
ledger. The agents still see the whole ledger as vendor history.

---

## 25. The evaluation harness

`evaluation/`.

### 25.1 Scripts

| Script | Produces |
|---|---|
| `run_all` | C0 and C1 on every dataset, the policy swap, construction checks -> `results/summary.md`, `results/<ledger>/metrics.json` |
| `run_c0` | the classical baselines |
| `run_config` | one configuration over a dataset, one prediction per invoice (JSONL), resumable |
| `run_pilot` | every configuration on a sample, side by side (`--ids-file`, `--tag`) |
| `run_full` | full benchmark runs of the model configurations (needs a fast endpoint) |
| `report` | metrics with bootstrap intervals, McNemar exact tests with Holm correction |
| `policy_change` | 14 policy documents read and applied to five ledgers against frozen thresholds |
| `policy_heldout` | 20 randomly generated held-out policy documents |
| `policy_robustness` | 16 edited documents: harmless edits must be read, defective ones refused |
| `policy_llm_eval` | a model reading 6 free-worded policies, and what the code check catches |
| `application_demo` | a policy change through the application on 20,000 invoices |
| `ledger_runs` | each ledger loaded from a workbook and audited through the store |
| `scalability` | control-stage throughput against worker processes and ledger size |
| `history_cap` | that the 40-invoice history cap loses no labelled case |
| `retrieval_eval` | policy search on 48 fixed questions |
| `revisions` | every control finding's revision resolves it |
| `huge` | every no-model measurement on the 500,000-invoice ledger |
| `stream_eval` | a ledger and its e-mails through Kafka, against the batch audit, with 1/2/4 workers |
| `collect_results` | `results/results.json`, every result with its source files and command |
| `full_report` | `../REPORT.md`, generated from the result files (no number typed by hand) |
| `figures` | `results/figures/*.png` |
| `scripts/reproduce.py` | re-runs the no-model steps in a temporary folder and compares every file with the committed one |

### 25.2 C0: the classical baselines (`run_c0.py`)

- **Isolation forest**, fitted without labels on all invoices; **one-class SVM**, fitted on (up to 4,000) clean
  invoices.
- 21 generic tabular features, none of which encodes a policy threshold: log amount, amount/PO, billed minus
  received, ordered minus received, missing PO, missing GRN, weekday, weekend, vendor invoices on the same day /
  within a week / with the same number / same amount / same PO, amount/approver limit, approval entries, GSTIN equals
  master, GSTIN length, blacklisted, registration active, trailing zeros of the amount, amount vs the vendor's usual
  (z-score of log amounts). Standardized.
- Threshold by **five-fold cross-fitting**, stratified by class: each fold is decided with the threshold that
  maximizes F1 on the other four, so no invoice is scored with a threshold tuned on its own label.
- They decide only anomalous or not; they name no clause.

### 25.3 Metrics (`metrics.py`)

All metrics are **ratios of weighted sums** over invoices (weights from the evaluation subset, or 1).

- Detection: an invoice is predicted anomalous when it has any kept finding. Recall, precision, F1, accuracy,
  flagged share, false-positive rate overall, on **ordinary** clean invoices and on **hard negatives** separately,
  precision projected to a 2% prevalence.
- Per class: share detected, and precision/recall/F1 by the clause a finding cites; macro F1 for rule and judgement
  classes; citation correctness; the share of model findings that name a violated rule; exact match.
- Routing: escalation precision and recall (against critical/high truth), escalated, sampled and approved shares.
- Cost per invoice: model calls, tokens, latency (unweighted).
- **Intervals**: percentile bootstrap, 1,000 resamples, within strata when the frame has strata; 95%.
- **Comparisons**: McNemar's exact test on paired per-invoice correctness, Holm-corrected across pairs.

---

## 26. Configuration: every environment variable

Read from the environment, then from `.env` (unless `AUDITIQ_NO_DOTENV` is set; the container and the tests set
it). The environment wins over `.env`.

| Variable | Default | Used by |
|---|---|---|
| `AUDITIQ_DATABASE_URL` | unset | PostgreSQL URL; when set, the store |
| `AUDITIQ_DB` | `.auditiq/auditiq.db` | SQLite file, when no URL |
| `AUDITIQ_TEST_DATABASE_URL` | unset | tests: PostgreSQL test database (each test in its own schema) |
| `AUDITIQ_LLM_BASE_URL`, `_MODEL`, `_API_KEY`, `_TIMEOUT`, `_MAX_TOKENS`, `_JSON_MODE`, `_SEND_SEED`, `_EXTRA_BODY`, `_CONTEXT` | see 10.1 | chat model |
| `AUDITIQ_EMBED_MODEL` | unset | embedding model (dense search) |
| `AUDITIQ_EMBED_BASE_URL`, `AUDITIQ_EMBED_API_KEY` | the chat ones | embedding endpoint |
| `AUDITIQ_EMBED_QUERY_PREFIX`, `AUDITIQ_EMBED_DOCUMENT_PREFIX` | empty | e.g. `"search_query: "`, `"search_document: "` for nomic-embed-text |
| `AUDITIQ_API_TOKEN` | unset | shared admin token of the API |
| `AUDITIQ_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | browser origins allowed |
| `AUDITIQ_LOG_LEVEL` | `INFO` | logging |
| `AUDITIQ_NO_DOTENV` | unset | do not read `.env` |
| `AUDITIQ_KAFKA_BOOTSTRAP` | unset | Kafka broker; the stream commands need it |
| `AUDITIQ_KAFKA_PREFIX` | `auditiq` | topic and group prefix |
| `AUDITIQ_KAFKA_PARTITIONS` | 4 | partitions per topic |
| `AUDITIQ_KAFKA_REPLICATION` | 1 | replicas per partition |
| `AUDITIQ_TEST_KAFKA_BOOTSTRAP` | unset | tests: broker (each test with its own topics) |
| `AUDITIQ_REQUIRE_KAFKA` | unset | CI: a missing broker fails the stream tests instead of skipping them |
| `AUDITIQ_PG_HOME`, `AUDITIQ_PG_DATA`, `AUDITIQ_PG_PORT` | `%LOCALAPPDATA%/auditiq/pgsql`, `.../pgdata`, 5544 | `scripts/pg_local.py` |
| `AUDITIQ_KAFKA_HOME`, `AUDITIQ_KAFKA_DATA`, `AUDITIQ_KAFKA_PORT` | `%LOCALAPPDATA%/auditiq/kafka`, `.../kafka-data`, 9092 | `scripts/kafka_local.py` |

---

## 27. Deployment and local servers

### 27.1 Local, without containers

```bash
pip install -e ".[dev]"                                  # from auditiq/
python -m auditiq setup --dataset data/large_seed_505    # SQLite, ledger, policies, PDFs
python -m auditiq run --config C1                        # audit every invoice with the controls
cd frontend && npm ci && npm run build && cd ..
python -m auditiq serve                                  # http://127.0.0.1:8000
```

- **PostgreSQL without a service**: `python scripts/pg_local.py init|start|stop|status` runs PostgreSQL 17 from the
  official Windows zip on port 5544; `init` creates the superuser `auditiq` with a random SCRAM password, the
  databases `auditiq` and `auditiq_test`, the role `auditiq_reader`, and writes the two URLs to `.env` (the password
  is never printed).
- **Kafka without Docker**: `python scripts/kafka_local.py ...` (Section 19.6).
- **Model**: Ollama; `ollama create qwen2.5:7b-ctx12k -f deploy/ollama/Modelfile` (Qwen 2.5 7B with
  `num_ctx 12288`), `ollama pull nomic-embed-text`; `.env`: `AUDITIQ_LLM_BASE_URL=http://localhost:11434/v1`,
  `AUDITIQ_LLM_MODEL=qwen2.5:7b-ctx12k`, `AUDITIQ_LLM_CONTEXT=12288`, `AUDITIQ_LLM_TIMEOUT=3600`,
  `AUDITIQ_EMBED_MODEL=nomic-embed-text` with the two prefixes; then `python -m auditiq policy embed`.

### 27.2 The container image (`Dockerfile`)

Two stages: `node:20-slim` runs `npm ci` and `npm run build`; `python:3.11-slim` copies the project (code, policy,
data, results), `pip install -e .`, creates the unprivileged user `auditiq` (uid 1000) that may write only
`/app/.auditiq` and `/app/policy/pdf`, copies `frontend/dist`, sets `AUDITIQ_NO_DOTENV=1`, exposes 8000, has a health
check on `/api/health`, and runs `python -m auditiq serve --host 0.0.0.0 --port 8000`.

### 27.3 Compose (`deploy/docker-compose.yml`)

| Service | Image | Notes |
|---|---|---|
| `postgres` | postgres:17 | `POSTGRES_PASSWORD` required; `init.sql` creates `auditiq_reader`; volume `auditiq_data`; health check `pg_isready` |
| `app` | built from `Dockerfile` | `AUDITIQ_DATABASE_URL` to `postgres`, token, CORS, optional model, `AUDITIQ_KAFKA_BOOTSTRAP=kafka:9092`; port `127.0.0.1:8000` |
| `kafka` | apache/kafka:4.3.2 | one KRaft node: listeners `PLAINTEXT://:9092`, `CONTROLLER://:9093`, advertised `kafka:9092`, 4 partitions, no auto-create, replication 1; volume `kafka_data`; health check `kafka-broker-api-versions.sh` |
| `workers` | built from `Dockerfile` | `python -m auditiq stream work --processes 2`; health check disabled (it serves no HTTP) |

```bash
docker compose -f deploy/docker-compose.yml up -d --build --wait
docker compose -f deploy/docker-compose.yml exec app python -m auditiq setup --dataset data/large_seed_505
docker compose -f deploy/docker-compose.yml exec app python -m auditiq run --config C1
docker compose -f deploy/docker-compose.yml exec app python -m auditiq user add "A. Auditor" --role reviewer
```

Put a reverse proxy with HTTPS in front before anyone else uses it.

---

## 28. Tests and continuous integration

### 28.1 Python tests (`tests/`, pytest)

The tests generate their own small datasets (a 1,200-invoice ledger of 60 vendors, a 150-invoice swap ledger) and
never read `data/`. Every test that needs a store gets a new one; tests marked with the `backend` fixture run once
on SQLite and once on PostgreSQL (each in its own schema of the test database, dropped afterwards). No test calls a
model (a `ScriptedClient` stands in). 410 tests at the last full run.

| File | Covers |
|---|---|
| `test_controls.py` | every control: clean, violating, threshold read from the registry; the vendor index against the plain list |
| `test_corrections.py` | every kind of revision; an amended or re-approved invoice passes its rule |
| `test_simulation.py` | the dry run predicts the routes and findings of the audit under the new policy |
| `test_scoring.py` | confidence, R0 and Rc, routing; Rc never above R0 |
| `test_pipeline.py` | the model stages with a scripted model, the configurations, human review, remit and malformed handling |
| `test_db.py` | loading, extraction, the policy store, results, the queue, 32 simultaneous connections |
| `test_ledger_import.py` | workbooks and zip archives, refusals with reasons, zip bombs |
| `test_policy_change.py` | from a policy document to executed controls; refusals |
| `test_policy_docs.py` | PDFs, ingestion, search, the copilot and every guard of its SQL |
| `test_policy_llm.py` | reading a policy in its own wording with a scripted model |
| `test_llm.py` | the client: cache, retries, a 200 that is not a completion, the context guard |
| `test_api.py` | every endpoint on both backends, users and roles, the shared token, uploads, jobs and conflicts, headers, CSP |
| `test_cli.py` | the command line end to end; every connection closed |
| `test_stream.py` | Kafka against a real broker: a streamed ledger equals the batch audit on both backends; exactly once; vendor wait; bad messages; policy documents; two workers; e-mail linking |
| `test_dashboard.py` | the Streamlit pages, headless |
| `test_generator.py` | the generator and its validator; no import between pipeline and generator |
| `test_eval.py`, `test_run_full.py`, `test_huge.py`, `test_reproduce.py` | the evaluation harness |
| `test_docs.py`, `test_results.py`, `test_packaging.py` | generated documents current; results.json matches its sources; every import is a declared dependency |

### 28.2 CI (`.github/workflows/ci.yml`, five jobs on every push)

| Job | Steps |
|---|---|
| `test` | services PostgreSQL 17 and Kafka 4.3.2; `pip install -e ".[dev]"`; `ruff check`; `pip-audit` (8 Pillow advisories ignored by name: Pillow is held below 13 by Streamlit and no uploaded image is decoded); create `auditiq_reader`; wait for the broker; `pytest` (with `AUDITIQ_REQUIRE_KAFKA=1`) |
| `frontend` | `npm ci`, lint, typecheck, test, build, `npm audit --omit=dev --audit-level=high` |
| `e2e` | install, build, Playwright in Chromium against the real server |
| `compose` | PostgreSQL from `deploy/postgres/docker-compose.yml`; the whole test suite against it (with timeouts and failure annotations); a ledger set up and audited |
| `container` | build the image and start app + PostgreSQL + Kafka + workers from the compose file; set up and audit a ledger inside; check `/api/health`, 401 without token, overview counts with the token (5,000 audited, 300 findings, postgres), the SPA and its CSP header; send vendor e-mails through the e-mail topic and wait until the workers have stored them all |

---

## 29. Security model

| Area | Guard |
|---|---|
| API access | users with roles (viewer < reviewer < admin), tokens stored as SHA-256 only, shown once; a shared admin token compared in constant time; open only when neither exists |
| Browser | token in `sessionStorage`; CSP on pages; `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`; CORS only for configured origins |
| Uploads | PDF <= 20 MB starting `%PDF`; ledger <= 100 MB, `.xlsx`/`.zip` starting `PK`; archives that would unpack beyond 300 MB refused before unpacking; file names sanitized; uploads referred to by a hex id |
| Ledger | checked before anything is replaced; replacement needs `replace=true` |
| Model output | JSON of the expected shape only; remit enforced by code; the challenger can only remove; controls unaffected by any model output; every escalation waits for a person |
| Copilot SQL | single SELECT, allow-list, refused escaping functions, read-only with limits, authorizer / read-only role; labels never readable |
| Policies | refused unless every executed rule's thresholds are read; model-read values need a verified quote and a named person |
| Records | results only added; decisions stored with reviewer; override needs justification; full trail |
| Secrets | `.env` ignored by git; passwords never printed; tests never read application settings |
| Not protected | no sign-in service, TLS, rate limit or body-size limit of its own (use a reverse proxy); prompt injection can still mislead a judgement (not a control); hosted models receive invoice records; jobs live in one process's memory; the SQLite file is protected only by file permissions |

---

## 30. What has been measured

From `RESULTS.md` (each number has a script and a result file behind it).

| # | Question | Result |
|---|---|---|
| 1 | Thresholds read correctly from policy documents? | 14 documents: 196/196 values, 224/224 rules. 20 held-out: 280/280 values, 320/320 rules |
| 2 | Does the audit follow the policy in force? | 0 wrong decisions in 560,000 audits (14 documents) and in 800,000 (20 held-out) |
| 3 | Cost of not updating thresholds | up to 30.7% of 40,000 invoices decided against the policy in force |
| 4 | Refusing what cannot be executed | 16 edited documents: 7/7 harmless edits read, 9/9 defective ones refused |
| 5 | A policy change in the application | strict policy on 20,000 invoices: findings 300 -> 6,546; waiting 240 -> 6,353; no code edited |
| 6 | Controls vs anomaly detectors | F1 0.833 at precision 1.000 vs 0.536 (isolation forest) and 0.498 (one-class SVM); FPR on hard negatives 0.000 vs 0.403 and 0.481 |
| 7 | At a realistic anomaly rate (2.1%) | F1 0.833 vs 0.211 and 0.429 |
| 8 | Speed of the control stage | ~18 µs per invoice; 172,226 invoices/s with 8 processes |
| 9 | A model reading free-worded policies | 6 documents, 84 values: 80 proposed right; code verified 56, held back 24 right, caught 2 wrong, passed 2 |
| 10 | The model stages (90-invoice sample, ledger 202, integrated GPU) | agents (C3) found 34/60 judgement anomalies; C3 significantly better than one prompt (C2), Holm p < 0.001; challenger gain not significant |
| 11 | Policy search | hybrid after rewriting: rank-1 0.625, top-3 0.938 on 16 held-out paraphrases |
| 12 | Every ledger through the deployed system | 300 findings per benchmark ledger, every rule-defined anomaly found, 240 escalated, no finding on any hard negative or ordinary invoice |
| 13 | 500,000 invoices | F1 0.833 at precision 1.000; 0 wrong in 7,000,000 policy audits; load 36 s, audit and store 708 s; 18.4 µs per invoice; every web page within 5.5 s |
| 14 | Revisions (AuditBench) | 1,200 control findings revised; 600/600 amendments and re-approvals resolve their finding |
| 15 | Policy simulation (Liu et al.) | the dry run predicts what adoption produces (6,353 for review under the strict policy) |
| 16 | Kafka | 5,000 invoices, 250 vendors, 2,105 e-mails: every invoice has the batch findings on both backends with 1, 2 or 4 workers; on PostgreSQL 4 workers 18.04 s vs 27.2 s for one (1.51x) |

The controls' recall is 0.714 by construction: they decide the ten rule classes (R1 to R10) and not the four
judgement classes, which are the agents' job. The language-model configurations were measured on samples only
(20, 34 and 90 invoices), not on full ledgers.

---

## 31. Limits and open items

**Limits of the design**

- The agents judge one invoice at a time with at most 40 of the vendor's other invoices; a pattern spread wider is
  out of view.
- Confidence rewards stability, not correctness.
- The controls are exactly as good as the registry: a clause missing from it is not checked.
- The API is one process; its jobs live in memory. Users have tokens and roles, not passwords or single sign-on.
- The data is synthetic; each anomalous invoice carries exactly one clean anomaly, and classes have equal counts.
- In the generated ledgers J1 can be found without judgement (an invoice that is not the first on its PO is always
  a duplicate); whether to make it a rule class is undecided.
- "Distributed" is by design: every measurement ran on one laptop.

**Open items** (`PLAN.md`)

- **B10**: full benchmark runs of C2 to C5 need a GPU or a hosted endpoint (`evaluation/run_full.py` is ready).
- **C28**, the rest of the Review-1 deck ("AuditIQ 2.0"): built are the Kafka layer, the review queue, policy-as-code
  for GST rules and human escalation. Not built: an e-mail triage agent (e-mails are stored and linked, not
  judged), a FinBERT invoice classifier, a gradient-boosted vendor risk scorer, a compliance agent with retrieval,
  an orchestrator that fuses agent outputs with agreement-based routing, ISA 230 predicates, a hash-chained audit
  log, OCR of scanned invoices, and a measurement of audit-cycle time.

---

## 32. Glossary

| Term | Meaning |
|---|---|
| Clause / rule | a numbered rule of the policy, e.g. 2.1.1 |
| Clause registry | the JSON of a policy version: every clause with title, severity, kind and parameters |
| Control | a deterministic check executed by code for one control clause |
| Judgement clause | a clause that needs reading (2.1.4, 2.1.5, 2.2.2, 4.1.2), given to an agent |
| Agent / specialist | one structured model call with a narrow remit |
| Remit | the judgement clauses an agent may report |
| Challenger | a model call that keeps or removes each agent finding |
| Flag / finding | a reported exception: clause, evidence, message, severity, source |
| Evidence | `{field, value}` pairs quoting the records |
| g, p, a, c | grounding, clause validity, agreement, confidence |
| R0, Rc | count-based and confidence-weighted risk scores |
| Route | approve, sample, escalate |
| Audit pack | the stored record of one audited invoice |
| Revision | what a control finding requires (amend, reapprove, consolidate, reject, hold, obtain, verify) |
| Run | one configuration applied under one policy version |
| C0..C5 | classical baselines; controls; one prompt; specialists; + challenger; + confidence |
| GSTIN | India's 15-character GST identification number; first two characters are the state code |
| PO, GRN | purchase order, goods receipt note |
| Hard negative | a clean invoice built to look like an anomaly |
| Evaluation subset | the weighted sample of a ledger the model configurations audit |
| Topic, partition, consumer group | Kafka: a named stream, a unit of order and parallelism, a set of workers sharing a topic |

---

## 33. Rebuilding it: the order of work

Each step lists what to build and the check that proves it before moving on. Python 3.11, a fresh virtual
environment, the dependencies of Section 4.

1. **Policy data.** Write `policy_v2.5.json` (Section 7.1) and `policy_v2.6.json` (three parameters changed). Write
   `SOP_template.md` with the rule sentences of Section 7.2 and `render_policy_text`. *Check:* rendering both versions
   succeeds, and the rule/severity cross-check fails when you change a severity in the text only.
2. **Benchmark generator** (Section 24) reading only the registry; vendors, purchases, documents, approvals; the 14
   injections and 5 hard negatives; an independent validator; manifests with SHA-256. *Check:* two runs with the same
   seed give identical files; the validator's recomputed rule violations equal the labels exactly.
3. **Extraction** (Section 6.2, 8): transactions from the CSV files, `History` with `VendorIndex`. *Check:* every
   invoice's history excludes itself and is sorted by (date, id).
4. **Controls** (Section 9). *Check:* on a benchmark ledger, the set of clauses flagged per invoice equals the labels'
   `clause_ids` for every R-class invoice; no flag on any hard negative or ordinary invoice; F1 = 0.833 with
   precision 1.000 (recall 0.714 = 300 of 420, because J1 to J4 are not control classes).
5. **Scoring** (Section 13). *Check:* Rc <= R0 on random flag sets; one critical control flag escalates; a weekend
   date alone (medium, 10) approves.
6. **Audit pack and revisions** (Section 14). *Check:* applying every `amend`/`reapprove` revision makes the invoice
   pass the failed rule with no new finding.
7. **Database layer** (Section 15) for SQLite first, then PostgreSQL with the type map and loaders. *Check:* load a
   ledger, `extract_one` and `extract_many` give the same transactions; schema creation is idempotent and stamped.
8. **Batch service and CLI** `setup`, `run`, `show`, `queue`, `decide` (Sections 16, 23). *Check:* `run --config C1`
   on a benchmark ledger stores 5,000 results with 300 findings and 240 escalated.
9. **Model client** (Section 10) with cache, retries, context guard, `extract_json`. *Check:* a repeated request makes
   no HTTP call; a 429 with `Retry-After` is retried; a 400 fails at once.
10. **Prompts and agents** (Section 11), with remit enforcement, repair, challenger rules. *Check with a scripted
    client:* an out-of-remit flag is dropped; an unknown clause is kept; a challenger without a verdict keeps the
    finding; an unusable reply keeps all.
11. **The graph** (Section 12) and the five presets; human review with `interrupt` and a checkpointer. *Check:* C1
    makes 0 calls, C3 three, C4 four when an agent finds something; C5 adds 3 re-runs per agent with a kept finding.
12. **Policy documents** (Section 17): PDF rendering, ingestion with chunking and verification, citations, the
    pattern compiler with every refusal, adoption, the model reader with verification and confirmation, the
    simulation. *Check:* the rendered v2.6 PDF compiles back to exactly the v2.6 registry; deleting a rule or a
    threshold sentence makes adoption refuse with that reason; the simulation of v2.6 equals what adopting it and
    re-auditing produces.
13. **Retrieval and copilot** (Section 18) with all four SQL guards. *Check:* a query naming `benchmark_labels`, using
    `set_config`, or with two statements is refused; on SQLite the authorizer denies reading a forbidden table at
    execution even if a name slipped past the check.
14. **REST API** (Section 20): auth and roles, headers and CSP, jobs and conflicts, every endpoint, the generated API
    reference. *Check:* each endpoint on both backends; 401/403 by role; 409 for conflicting jobs.
15. **Web application** (Section 21): client, pages, the 3D views with fallbacks. *Check:* page tests against a
    mocked API; Playwright against the real server.
16. **Kafka layer** (Section 19): topics, publisher, workers with stored offsets, fencing, vendor wait, re-audit of
    completed same-day groups, e-mails with deferred linking and the advisory lock, compliance documents, status,
    the local broker script. *Check:* a ledger streamed into an empty store ends with exactly the batch audit's
    findings on SQLite and PostgreSQL; a second worker run processes nothing; two workers process each invoice once.
17. **Evaluation** (Section 25): C0 with cross-fitting, weighted metrics, bootstrap, McNemar with Holm, the experiment
    scripts, `results.json` and the generated report. *Check:* `scripts/reproduce.py` regenerates every no-model result
    file identical to the committed one (apart from dates and timings).
18. **Deployment and CI** (Sections 27, 28). *Check:* all five CI jobs green.

Throughout: keep principle 2 (no threshold in code) and principle 6 (pipeline and generator share no code), and let
no number into a document that a script did not produce.
