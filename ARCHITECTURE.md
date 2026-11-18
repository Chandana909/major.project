# AuditIQ: architecture, decisions, data and operation

**Status of this file: 14 November 2026.** Repository: https://github.com/Chandana909/major.project (the git root is the
folder `pp1/`; the project is `pp1/auditiq/`, and every command below runs from there unless it says otherwise).

## How to use this file

This file is written so that a reader (a person or another language model) with **no other access to the project** can
understand what AuditIQ is, why it was built the way it was, what data it runs on, how to run it, what it measured,
and what it cannot do, and can answer detailed questions about it from this file alone.

It has two halves.

- **Parts 1 to 11 (the context, the reasoning and the operating knowledge)** were written on 14 November 2026 from the
  code, the generated datasets, the result files and the project's design records. They answer *what, why, with what
  alternatives, on what data, how to run it, what was found.*
- **Part 12 (the technical reference, sections R1 to R33)** is the complete engineering description of every module,
  formula, prompt, table, endpoint and test. It was written on 30 October to 4 November 2026 and was checked against the
  code on 14 November, with the differences found since then patched in (section 3.5 lists them).

Rules this file follows, which you can rely on when answering:

1. **Every number has a source.** A number is a count of something in the repository, an output of a script of the
   repository, or arithmetic on those. Where a number comes from a result file, the file is named. Nothing is estimated
   unless the text says "expected" or "estimated".
2. **Three labels mark how firm a result is.** *Measured*: a script of the repository produced it on the data stated.
   *Pilot* or *sample*: measured, but on 20, 34 or 90 invoices, so no difference between configurations may be claimed from
   it. *Expected*: a target set before measurement; never a result.
3. **Where the code and this file disagree, the code is right.** Section 3.5 lists the statements of the older
   documents that the code has overtaken.
4. **Limits are stated next to the results**, and section 10 collects them, with the questions people ask most.

If you are asked about something this file does not cover, say so; do not guess. The names of files to look at are given
throughout (all paths relative to `pp1/auditiq/` unless they begin with `pp1/`).

---

## Contents

**Part I. Orientation**
1. [What AuditIQ is](#1-what-auditiq-is)
2. [The words you need](#2-the-words-you-need)
3. [How the project got here: what changed between versions](#3-how-the-project-got-here-what-changed-between-versions)

**Part II. Why it is built this way**
4. [The decisions, the alternatives and the reasons](#4-the-decisions-the-alternatives-and-the-reasons)

**Part III. Running it**
5. [How to run it](#5-how-to-run-it)

**Part IV. The data**
6. [The datasets, how to find them and how to read them](#6-the-datasets-how-to-find-them-and-how-to-read-them)
7. [How the errors are designed](#7-how-the-errors-are-designed)

**Part V. What the system finds and shows**
8. [Analytics, coverage and rings](#8-analytics-coverage-and-rings)
9. [The knowledge layer: two graphs, retrieval and Ask AI](#9-the-knowledge-layer-two-graphs-retrieval-and-ask-ai)
10. [The demonstration policies](#10-the-demonstration-policies)

**Part VI. Evidence and honesty**
11. [What has been measured](#11-what-has-been-measured)
12. [Limits, open decisions and the questions people ask](#12-limits-open-decisions-and-the-questions-people-ask)
13. [The repository and its documents](#13-the-repository-and-its-documents)

**Part VII. The technical reference**
14. [Reference sections R1 to R33](#r1-what-auditiq-is) (the table of contents of the reference follows its first
    heading)

---

# Part I. Orientation

## 1. What AuditIQ is

AuditIQ is a **procure-to-pay audit system**. A company buys goods and services from vendors. Each purchase leaves a trail
of documents: a **purchase order** (what was ordered, at what price), a **goods receipt note** (what actually arrived), the
vendor's **invoice** (what is being billed), the **approval log** (who approved paying it, with what authority) and the
**vendor master** record (who the vendor is: name, tax identity, whether blacklisted). An **audit** compares these
documents with each other and with the company's written **procurement policy**, and finds the invoices that should not
be paid without a closer look: an invoice for more than was ordered, more goods billed than received, the same invoice
paid twice, a tax number that does not match the vendor's, an invoice approved by someone whose limit is lower than the
amount, a vendor that is blacklisted, invoices split to stay under an approval limit, and vendors and approvers who seem to
work together.

AuditIQ audits invoices that have been approved and not yet paid. For each invoice it gathers the five kinds of record, the
vendor's other invoices and the policy, and decides:

- **approve**: nothing in it needs a person;
- **sample**: review it if the sampling picks it (only configurations that use model confidence produce this route);
- **escalate**: a person must review it before it is paid.

Every decision comes with a **risk score** (0 to 100), a **risk level** (LOW, MEDIUM, HIGH, CRITICAL), its **findings**
(each names the policy rule it breaks, quotes the field values it rests on, and cites the policy document and page), a
**revision** (what would put the invoice right, for example "obtain a credit note for 24,559.84") and an **audit trail**
of every step. A person reviews the escalated invoices and records approve, reject or override with a justification.

**What kind of system it is**

| Aspect | Answer |
|---|---|
| Language and size | Python 3.11 backend (the package `auditiq/`, 35 modules), React 18 + TypeScript web application with 3D views, about 519 Python tests and 61 frontend tests |
| Core idea | **Controls first**: everything that can be decided by comparing field values is decided by twelve deterministic Python controls; language-model agents are used only for the four rules that need reading or judgement, and cannot remove or alter a control's finding. **The policy is data**: every threshold is read from the policy document, so changing the document changes the audit with no code change |
| Storage | SQLite (default, no server) or PostgreSQL 17, behind one interface |
| Models | Any OpenAI-compatible chat endpoint (measured with Qwen2.5-7B through a local Ollama) and an embedding model (`nomic-embed-text`) |
| Streaming | Apache Kafka: four topics (invoice, vendor, email, compliance), stateless workers, each message stored exactly once |
| Interfaces | Command line, REST API (FastAPI, 46 endpoints), web application (15 pages), a lighter Streamlit dashboard, and one launcher (`start.bat`) that runs the whole thing |
| Data | Synthetic only: eight generated ledgers (the largest used day to day has 25,000 invoices) with the **ground truth of every invoice written at the moment each error is injected**, plus a 500,000-invoice ledger generated on request |
| Origin | A college major project (phase 1) of the Department of Information Technology, CBIT Hyderabad, with a research paper. The project grew out of a hackathon prototype built in Flowise (a visual agent builder), which it replaced |

**The pipeline in one picture**

```
ledger (database) -> extraction -> twelve controls -> three specialist agents -> challenger
                  -> confidence -> risk score and route -> review queue -> audit pack and audit trail
policy PDFs       -> ingestion  -> clause registry (the thresholds) -> citations, policy search, Ask AI
Kafka topics      -> stream workers (invoice, vendor, email, compliance) -> the same store and audit
audit results     -> analytics, collusion rings, audit knowledge graph -> dashboards and Ask AI
```

Five **configurations** of the same pipeline exist (C1 to C5, plus C0, the classical baseline used only for comparison).
C1 is the controls alone (no model); C2 is one prompt to a model over the whole policy; C3 adds three specialist agents to
the controls; C4 adds the challenger; C5 adds a confidence score that depends on agreement over re-runs. Almost everything
shown in the application and everything measured on the large ledgers is **C1**, because it needs no model. The language
model configurations were run only on small samples (see sections 11 and 12).

## 2. The words you need

| Term | Meaning |
|---|---|
| Invoice, PO, GRN | The vendor's bill; the purchase order (what was ordered); the goods receipt note (what was received) |
| Three-way match | Checking that invoice, PO and GRN agree on amount and quantity |
| GSTIN, PAN | India's GST registration number (15 characters; first two are a state code, characters 3 to 12 are the vendor's PAN) and the permanent account number of the legal entity. One entity should have one PAN |
| Approval limit | The largest amount a role may approve: Manager 100,000; Senior Manager 500,000; Director 2,500,000; CFO 10,000,000 (INR, policy v2.5) |
| Policy, clause, rule | The written procurement SOP. A **clause** (rule) such as 5.1.1 defines exactly one kind of exception and has one severity. v2.5 has 16 clauses |
| Registry | The JSON file holding every clause's title, severity, kind and parameters; the only place a threshold is stored |
| Control | A deterministic Python function that decides one rule from field values (twelve of them) |
| Judgement rule, agent | The four rules that need reading or judgement (2.1.4 receipt remarks, 2.1.5 description match, 2.2.2 near duplicate, 4.1.2 structuring across days); a language-model agent handles them |
| Challenger | A model call that may remove an agent's finding (never a control's) |
| Finding, flag | One violated rule on one invoice, with evidence, severity and message |
| R0, Rc, route | Count-based score, confidence-weighted score, and the decision (approve, sample, escalate); section 7.5 and R13 |
| Risk level | LOW / MEDIUM / HIGH / CRITICAL band of the score, at least the level of the most severe held finding |
| Ledger | One generated dataset: five tables (vendor master, purchase orders, goods receipts, invoices, approval logs) |
| Labels, ground truth, answer key | `labels.csv`: for every invoice whether it is clean, a hard negative or anomalous, with the class and rules, written when the error was injected. The audit never reads it |
| Anomaly class | R1 to R10 (decidable from fields) and J1 to J4 (need judgement); section 7 |
| Hard negative | A clean invoice built to look like an anomaly, to catch detectors that learned the surface, not the rule |
| Compound fraud | An invoice that breaks several rules at once (only in the final ledger) |
| Policy in force | The policy version that governed on an invoice's date; an invoice is judged by it, not by whatever version is active when the audit runs |
| Ring | A connected group of vendors and approvers tied by a shared identity or by approvals that carry more findings than chance allows; a lead for investigation, not a finding |
| Run, store | A run of `start.bat` creates a **store** (a SQLite file) holding the ledger as it arrived through Kafka and every audit result |
| Knowledge graph | The policy as a graph (rules, parameters, checkers, versions) and the audit findings as a graph (vendors, invoices, rules, approvers, rings), both built by code |
| Ask AI | The question-answering page: policy questions, invoice questions, questions about the ledger, and data questions answered by a checked SQL query |

The complete glossary is section R32.

## 3. How the project got here: what changed between versions

### 3.1 Lineage

1. **The hackathon prototype (before October 2026).** A visual workflow in Flowise ("AuditIQ", the folder
   `pp1/AuditIQ-DeloitteHacksplosion-main/`, kept only as a reference export and excluded from git because its files
   hard-code a database password): LLM agents with tool calls, JavaScript tools for three-way match, duplicates, GST,
   approval limit, vendor policy and ledger pattern, an LLM "Risk Router" that decided review versus approval, an Appsmith
   interface and a hosted PostgreSQL. Its problem, verified in the export: thresholds lived in prompts and tool code,
   the policy text and the numbers the tools applied could disagree unnoticed, whether a rule check ran at all depended on
   the model choosing to call a tool, and nothing could show an auditor that the policy in force was applied
   (`docs/FEATURE_POLICY_AS_DATA.md` section 2).
2. **AuditIQ, the standalone system (11 to 14 October 2026).** Decision of 11 October: no Flowise; one Python project.
   Commit `59cd0aa` (13 October) "standalone system, datasets, evaluation and paper"; `53f3ec9` (14 October) "AuditIQ 0.4:
   REST API, React Three Fiber web app, measured results". This is where the package version 0.4.0 comes from.
3. **Measured and hardened (15 to 25 October).** Results for the paper, held-out policy documents, robustness of the
   policy reader, language-model samples, loading a ledger from Excel, the full report, browser tests, one-command
   reproduction, the 500,000-invoice ledger, a code review, the base papers' features, users and roles, a container image.
4. **The Review-1 deck and Kafka (27 October).** A project review deck ("AuditIQ 2.0") described an architecture with four
   Kafka topics, four specialised agents and an orchestrator; the team asked to match it. The Kafka layer was built; the
   other items of the deck were not (section 12).
5. **Forensic analytics, rings, graphs and consoles (1 to 4 November).**
6. **Live launcher, the collusion ledgers and the final ledger (11 to 14 November).**

### 3.2 Timeline of commits

All 36 commits are on branch `main` of the repository above.

| Date | Commit | What it added |
|---|---|---|
| 2026-10-13 | `59cd0aa` | The standalone system, the first datasets, the evaluation harness and the paper draft |
| 2026-10-14 | `53f3ec9` | AuditIQ 0.4: REST API, React + React Three Fiber web application, measured results |
| 2026-10-18 | `9d88543`, `2487dea`, `96e4d64` | RESULTS.md; held-out policies and reader robustness; the language-model stages on a benchmark sample |
| 2026-10-19 | `d909bd2`, `dd3403d`, `60b67d6`, `4f4bd69`..`00d22f8` | Loading a ledger from Excel or a zip; every result machine-readable; the full report REPORT.md; the 6-page conference paper |
| 2026-10-20 | `dc0316a`, `06dc5f0`, `07d6bcc` | Browser tests, `scripts/reproduce.py`, fixes found by reproducing from a fresh clone; the huge-ledger tooling |
| 2026-10-21 | `7965ac3`, `a949d02`, `356af24`, `88c18ec`, `0e3ca75` | The 500,000-invoice ledger and its results; the CLI closes every connection; room in the report for the 90-invoice sample |
| 2026-10-25 | `0638d75`, `98702dc`, `d7b6fc1`, `20350c4`, `caa389b`, `5a9fa02`, `4d2359b` | The five configurations on 90 invoices of ledger 202 on the integrated GPU; code review (eleven findings); vendor index (18.4 microseconds per invoice); the web application on 500,000 invoices; the base papers' revisions and policy simulation; users with roles, a CSP, a container image |
| 2026-11-13 | `d20a2f2` | Everything from 27 October onward that had not been committed: the Kafka layer, analytics, rings, the policy graph, the console pages, policy-in-force, the live launcher, the collusion ledgers, the **final 25,000-invoice ledger**, the verification, the **demonstration policies**, the **audit knowledge graph**, Ask AI fixes (174 files) |
| 2026-11-14 | (this commit) | This file and the corrections to the older documents listed in 3.5 |

### 3.3 What changed since the last committed snapshot (25 October) in detail

**Kafka ingestion (27 October; `auditiq/stream.py`, `emails.py`, `scripts/kafka_local.py`, `docs/STREAMING.md`).** Four
partitioned topics (`vendor`, `invoice`, `email`, `compliance`) read by stateless workers; each message is stored exactly once
because the offsets are kept in the database in the same transaction as the data; an invoice is audited against the invoices
that arrived before it, and a same-day split that a later invoice completes is audited again; vendor e-mails are parsed and
linked to invoices (`auditiq_bench/correspondence.py` generates synthetic ones); a local broker runs without Docker.

**Forensic analytics, coverage and rings (1 to 4 November; `analytics.py`, `rings.py`, `docs/ANALYTICS.md`).** The
Analytics page (Benford's law, amounts against approval limits, weekday, concentration, approvers), the Overview's coverage
panel (which configuration produced each result, what was not checked, the answer key under its own policy version), and
collusion rings (identity links, and approval links tested against the rate of the approver's role with a
Benjamini-Hochberg false-discovery-rate correction, plus a watch list).

**Knowledge graph of the policy and Ask AI (4 November; `policy_graph.py`, `docs/POLICY_GRAPH.md`).** The policy as a graph
built by code; its facts go to Ask AI; evaluated against passage retrieval (22 of 23 held-out questions with complete
evidence, against at most 13 for a passage ranker).

**Console pages (4 November).** Pages for Kafka streams, agents and pipeline, knowledge base, knowledge graph and RAG
retrieval, with `GET /api/system` and the stream endpoints.

**Each invoice under the policy in force on its date (4 November; code review finding 22).** A real bug: applying policy
v3.12 (effective 1 April 2026) to a ledger dated 1 April 2025 to 31 March 2026 sent 160,068 of 500,000 invoices (32.0%) to
review, 4.7% of them anomalous; with each invoice under the version in force on its date, 5,712 (1.1%) went to review, all
anomalous. The audit now keeps a **policy timeline** and judges every invoice by the version in force on its date.

**Risk level MEDIUM made reachable (4 November; finding 23).** A single medium finding scores 10, which is in the LOW band,
so MEDIUM needed three medium findings. The level is now at least that of the most severe finding held with confidence;
scores and routes did not change.

**Other findings 24 to 27** (a publish that could overwrite the store's invoices with another ledger's, a job that
reported sent counts as failures, the Kafka broker failing on Windows, a review queue that counted levels from a cut list)
are in `docs/CODE_REVIEW.md`; the review now lists 27 findings (earlier documents say 18).

**The live launcher (11 to 13 November; `start.bat`, `scripts/live.py`).** One batch file starts the Kafka broker, creates an
empty store with the policy versions, starts the workers and the web application, publishes the ledger (vendors, then
invoices with their orders, receipts and approvals, then vendor e-mails) and the policy documents through Kafka, and
reports the progress until every message is processed. Nothing is "displayed from a file": the web application shows what
arrived through Kafka and was audited. The stores live outside the project folder (`%LOCALAPPDATA%\auditiq\live`) because
SQLite's write-ahead log does not belong in a folder a sync client (OneDrive) rewrites.

**The collusion ledgers and the final ledger (11 to 14 November).** `collusion_seed_707` (5,000 invoices with planted rings;
`collusion_seed_808` is defined as the held-out twin and has not been generated) and **`final_seed_2025`**: 25,000 invoices,
1,250 vendors, 14 anomaly classes, 300 hard negatives, **compound frauds** (an invoice breaking several rules), four pairs
of shell vendors and six approver rings. It is the default of `start.bat`. Why it exists, and the "every score was 75"
problem that prompted it, are in sections 4 (D15) and 12.

**Verification against the ground truth (`evaluation/final_check.py`).** After a run, the audit is compared with the
ledger's labels: score spread, precision and recall per rule, results by number of violations, planted rings recovered. The
launcher loads the labels into the store after publishing, as an *answer key* shown on the Overview; the audit never
reads them.

**Demonstration policies (`auditiq/policy_demo.py`, `policy/demo/`, `docs/POLICY_DEMO.md`).** Five company policies as PDFs
(v5.01 to v5.05) and one deliberately incomplete draft (v5.99) that the system must refuse, with the measured effect of
each on the 25,000-invoice ledger (section 10).

**The audit knowledge graph (`auditiq/case_graph.py`, `docs/CASE_GRAPH.md`).** The audited ledger as a graph (vendors,
invoices with findings, rules, approvers, shared identities, rings), `GET /api/case-graph` and `/api/case-graph/ask`, a new
tab on the Knowledge graph page, and its facts (`[C1]`, `[C2]`, ...) given to Ask AI; evaluated on 78 questions
(section 9).

**Ask AI fixes.** Data questions guessed a value (`'approve'` for `'Approved'`) and described rows that did not exist; the
prompt now states the real values and the policy's rules, retries an empty result once and says plainly when nothing
matches. The answer prompt now names the ledger facts as a source.

**Counts.** The tests grew to 519 Python tests (collected; the PostgreSQL variants are skipped without a server) and 61
frontend tests; endpoints grew from 22 (October) to 38 (4 November) to 40.

### 3.4 Version numbers

| Thing | Version |
|---|---|
| Python package, REST API, frontend | 0.4.0 (`pyproject.toml`, `frontend/package.json`) |
| Dataset generator | 1.0 (`auditiq_bench.GENERATOR_VERSION`) |
| Policy v2.5 | the baseline (effective 2025-04-01); 16 clauses |
| Policy v2.6 | the policy-swap version (effective 2026-04-01): tolerance 5%, daily count 5, Manager limit 150,000 |
| Policies v3.01 to v3.14 | 14 evaluation variants (`policy/variants/`) |
| Policies v4.01 to v4.20 | 20 held-out random variants (`policy/variants_heldout/`) |
| Policies v5.01 to v5.05, v5.99 | the demonstration policies and the incomplete draft (`policy/demo/`) |
| Kafka | 4.3.2 (KRaft, one node, local) |

### 3.5 Statements of the older documents that the code has overtaken

Corrected in this commit where they are generated or short; listed here so nobody is misled by an old copy.

| Where | Old statement | Now |
|---|---|---|
| `docs/DATASETS.md` (generated prose) | "Each anomalous invoice carries exactly one injected anomaly" | true of the seven benchmark ledgers; the **final ledger has compound frauds** (558 invoices carry one to three further violations) |
| `docs/DATASETS.md` and datasheet of the final ledger | compound frauds make scores "run from 0 to 100" | they add combinations (scores up to 90 occur) but the scores still cluster at 50 and 70: section 12 |
| `docs/ANALYTICS.md` section 5 | "the generated benchmark ledgers ... model no collusion" | the collusion ledgers and the final ledger plant rings; the detector recovers them |
| `README.md` | "eighteen findings"; six datasets | 27 findings; eight datasets (nine counting the 500,000-invoice ledger) and the launcher `start.bat` |
| `ARCH.md` header | "as of 30 October 2026" | `ARCH.md` was last edited on 4 November and lacked `analytics.py`, `rings.py`, `case_graph.py`, `policy_demo.py`; this file supersedes it, and `ARCH.md` and `ARCH.pdf` were removed on 15 November (the 4 November snapshot is in git history, commit `bc12f8a`) |
| `PLAN.md` | "Last updated 2026-10-13" at the top | the header now says it was written on 13 October with items C27 to C37 added up to 14 November; C33 to C37 are the launcher, the final ledger, the demonstration policies, the audit graph and this file |
| Ask AI | answers could say "the documents do not answer" when ledger facts were present | the prompt names the ledger facts as a source; a test checks they are in the prompt |


---

# Part II. Why it is built this way

## 4. The decisions, the alternatives and the reasons

Each decision below has the same shape: **the question**, **what else was considered**, **what was chosen**, **why**,
**what it costs**, and **the evidence**. The sources are `PLAN.md` (sections 2, 5 and 6, written while building),
`docs/FEATURE_POLICY_AS_DATA.md`, `docs/POLICY_GRAPH.md`, `docs/CODE_REVIEW.md`, `docs/STREAMING.md`, `RESULTS.md`, and the
decisions taken with the project's owner between 5 and 14 November 2026. The standing rule behind all of them: **a number
goes into a document only if a script in the repository produced it** (the owner agreed: "do not create results").

### D1. No Flowise: one Python project (decided 11 October 2026)

- **Question.** The paper draft described a Flowise prototype with Appsmith and a hosted PostgreSQL. Keep building on it?
- **Alternatives.** Keep Flowise; port part of it.
- **Chosen.** A standalone Python project; the Flowise export stays as a reference only and is excluded from git.
- **Why.** In the prototype, thresholds were written into agent prompts and JavaScript tool code; the policy text and the
  numbers could disagree unnoticed; whether a rule ran depended on the model choosing to call a tool; an LLM chose
  between review and approval. None of it could be tested or shown to an auditor.
- **Cost.** Rebuilding everything; the first version of the controls was JavaScript so it could be pasted into Flowise, and
  the Python port had to be checked against it (3,900 transactions and 8,500 scoring cases, no difference).

### D2. Orchestration with LangGraph, not plain functions, CrewAI or AutoGen

- **Why.** The pipeline is a fixed graph with one parallel fan-out (three agents) and one human pause. LangGraph gives
  typed shared state, parallel branches, and `interrupt`/resume for the reviewer; the five configurations are the same
  nodes with some left out.
- **Rejected.** Plain functions (no pause/resume, no diagram); CrewAI and AutoGen (role-play conversation between agents,
  where this design needs fixed stages and exact control of every call). LangChain is *not* used (only `langchain-core` as
  a dependency of LangGraph): chains and templates add nothing here.

### D3. One structured call per agent, no tool loop; an own HTTP model client

- **Why.** With the controls running first, an agent has nothing to compute; a single call is cheaper, reproducible, and its
  cost is known in advance. The own client (`auditiq/llm.py`) works with a local Ollama, a hosted open-weight model or a
  LiteLLM gateway without code changes and controls temperature, seed, retries and token accounting.
- **Reproducibility.** Every reply is cached in SQLite keyed by the full request, so a repeated run costs nothing and returns
  the same text.
- **Rejected.** ReAct agents with tools (the prototype); `langchain-openai` or the LiteLLM SDK (a dependency for one POST).

### D4. Controls first, models second (the central design choice)

- **Question.** Who should decide an invoice: a language model reading everything, or code for what code can decide?
- **Chosen.** Twelve deterministic controls decide every rule that field comparison can decide. A model sees an invoice only
  for the four judgement rules, after the controls ran, and **can add findings but cannot remove or change a control's
  finding**. The audit pack is assembled by code from verified findings; no model writes it.
- **Why, with evidence.** (1) A model asked about the whole policy invents findings: in the 20-invoice pilot the single-prompt
  configuration (C2) flagged 18 of 20 invoices, raised five wrong findings on the one ordinary invoice and named a violated
  rule for only 0.091 of its citations; on the 90-invoice sample C2 flagged 9 of 10 ordinary invoices and 0.030 of its
  findings named a violated rule, while the agents (C3) found 34 of 60 judgement anomalies and 0.493 of their findings named
  a violated rule (Holm-adjusted p < 0.001 for C3 over C2). (2) The controls cost nothing per invoice: about 18 microseconds.
  (3) A control's decision is the same every time; an audit tool has to be reproducible.
- **Cost.** Rule-defined classes are circular as a measurement: the controls implement the same definitions by which the
  anomalies were injected, so "100% on R1 to R10" is a correctness check, not a detection result. The informative numbers are
  J1 to J4, hard negatives, citations and routing (`PLAN.md` section 7).

### D5. The policy is data: thresholds come from the document

- **Question.** Where does a threshold live?
- **Chosen.** Once, in a clause registry (`policy/policy_v<version>.json`). The policy text the agents read is *rendered from
  the registry*, the controls read the registry, and the generator reads it. A policy PDF is read by pattern (one regular
  expression per parameter against the text of its rule) into a registry; a document the system cannot execute is
  **refused with the reasons**.
- **Alternatives.** Thresholds in prompts and code (the prototype); an LLM extracting thresholds (rejected as the default: it
  can invent a number).
- **Evidence.** Policy-change experiment: 14 policy documents, 196 of 196 values read, 224 of 224 rules, **0 wrong decisions
  in 560,000 audits**, while the same controls with thresholds frozen at v2.5 decided up to 30.7% of 40,000 invoices against
  the policy in force. 20 held-out random documents: 280 of 280 values, 0 wrong in 800,000 audits (frozen: up to 19.9%).
  Reader robustness: 16 edited documents, 7 of 7 harmless edits read correctly, 9 of 9 defective or ambiguous documents
  refused (two ambiguous ones had been adopted before a fix on 18 October: a rule stated twice, an approval table without a
  role).
- **Cost.** The document must state its rules in the wording of the SOP template. A policy in free prose needs the model
  reading step (D6).

### D6. A model may read a free-worded policy, but code checks it and a person confirms it

- 6 free-form documents, 84 values: the model proposed 80 correctly; code verified 56, held back 24 correct values for the
  reviewer, caught 2 wrong values and passed 2 (one 7B model). So the reading is never adopted without verification and a
  named reviewer's confirmation (`policy_llm.py`, `POST /api/policy/propose` then `/confirm`).

### D7. SQLite or PostgreSQL behind one interface; no ORM

- **Why.** SQLite needs no server and is the default; PostgreSQL gives typed money and dates, concurrent readers and a database
  role that confines the copilot's queries. SQL is written once and loaders make both return the same values; the database
  tests run on both. An ORM would be a layer for seventeen tables and plain queries.
- **A review queue is a database state** (`PENDING_REVIEW`), so it survives a restart and is the same for the command line,
  the dashboard and the web application; LangGraph's `interrupt` remains for the interactive single audit. A LangGraph
  checkpointer was rejected (another package, and the paused graph would hold nothing the result row does not).
- **Results are added, never replaced**; a removed finding is kept with the reason; every result records configuration,
  policy version, model and prompt hash.

### D8. Policy search: lexical, dense and hybrid; no vector database; agents read the whole policy

- Retrieval serves Ask AI and citations, not the agents: an agent's clauses are fixed by its remit, so retrieving per invoice
  would add a failure mode and no information. The corpus is tens of passages, so a matrix product replaces a vector database.
- 48 fixed questions: lexical ranking finds every question asked in the policy's own wording (rank-1 accuracy 1.000); on
  paraphrases, rewriting the question with the chat model lifts hybrid ranking to rank-1 0.625 and top-3 0.938 (held-out, 16
  questions). Small: neighbouring cells differ by a question or two.

### D9. The challenger and the confidence terms, and what they do not mean

- The challenger rules on agent findings only (it sees the records those agents saw); it is not called when no agent raised a
  finding. Confidence for an agent finding is `c = (g + p + a) / 3`: **g** grounding (every quoted field value exists in the
  transaction), **p** clause validity (the cited clause exists), **a** agreement (share of three re-runs at temperature 0.7
  that cite the same clause). A control finding has confidence 1.
- **What it does not mean.** Confidence measures support and stability, not correctness. Observed twice with a real model:
  a wrong near-duplicate finding passed with g = p = a = 1 because the model was consistently wrong; the paper must say so.

### D10. Scoring: weights with floors, and the lumpy-score consequence (the "75" question)

- **The scheme** (`scoring.py`, equations (2) to (5) of the paper). Weights per finding: critical 30, high 20, medium 10, low
  5. Score `R0 = min(100, sum of weights)`, **raised to a floor** of 70 if any finding is critical and 50 if any is high.
  Route: escalate if the confidence-weighted score is at least 50 (`tau`); sample if only the count-based score reaches 50;
  else approve. Risk level: the band of the score (70 critical, 50 high, 30 medium, else low), **and at least the level of the
  most severe held finding** (added 4 November, finding 23, so a single medium finding is MEDIUM and not LOW).
- **Why floors.** A single critical finding (an approval above the limit, a blocked vendor, a duplicate) must escalate no
  matter how little else is wrong; a sum of weights alone would let a lone critical finding score 30 and be approved.
- **The consequence.** With one finding per invoice, a flagged invoice scores exactly 70 (critical), 50 (high), 10 or 5.
  This is what a teacher saw as "every error score is 75" (the exact number 75 arises when four rules fire together:
  2.1.2 + 3.1.3 + 4.3.1 + 5.1.1 = 20 + 20 + 5 + 30). No code sets 75. The older stores audited under the baseline policy held
  scores of 0, 5, 10, 50 and 70 (and a few 11), with 93 to 98.5 percent of invoices at 0; a store audited under a strict policy held
  mostly 0, 70 and 50.
- **Alternatives.** (a) Change the formula to a continuous score that reflects the size of the deviation (money, percentage
  difference). Rejected for now because the formula is the paper's equations (2) to (5) and every measured result depends on it.
  (b) Add a *separate* continuous, magnitude-aware risk index beside the paper's score, leaving routes and results intact.
  **Open decision** (section 12). (c) What was done: change the **data**, not the model, so the demonstration is diverse:
  compound frauds (D15). On the final ledger the scores still cluster: 23,165 invoices score 0, among 1,835 flagged invoices 852
  score 70 and 780 score 50, with a tail to 90 (13 invoices at 71 to 80, 3 at 81 to 90).

### D11. Evaluation design: baselines, hard negatives, weights, cross-fitting

- **Baselines (C0).** Isolation forest and one-class SVM on 21 generic features; thresholds **cross-fitted** (the ledger is
  split into five folds stratified by class; a fold is decided with the threshold chosen on the other four), so no invoice is
  decided with a threshold tuned on its own label. This replaced a single 20/80 split that left a fifth of the ledger out of
  every comparison.
- **Hard negatives** (five types) are reported separately: a detector that flags one learned the surface of a class, not the
  rule. Controls: 0.000 false positives on hard negatives; isolation forest 0.403 and one-class SVM 0.481 on the benchmark
  ledgers.
- **The evaluation subset.** The LLM configurations make several calls per invoice, so they audit a weighted subset (every
  anomalous invoice, every hard negative, every clean invoice a duplicate copies, a random sample of the rest) with weights that
  sum to the ledger's size, so rates computed on the subset estimate rates on the ledger. The agents still see the whole ledger
  as vendor history.
- **Result.** Controls F1 0.833 at precision 1.000 (recall 0.714: the four judgement classes are not theirs) against 0.536
  (isolation forest) and 0.498 (SVM) on the three benchmark ledgers; at a realistic 2.1% anomaly rate the detectors fall to 0.211
  and 0.429. The controls beat each detector on every ledger (McNemar, Holm-adjusted).

### D12. Vendor history is capped at 40 invoices per selection rule

- Chosen before looking at any label, and checked afterwards: on every dataset no labelled case loses an invoice it depends on
  (`results/history_cap.md`). It bounds prompt size (a vendor can have over a hundred invoices; one measured vendor on the final
  ledger has 125).

### D13. The data: synthetic, labelled at injection, validated independently, reproducible

- **Question.** Real procurement data was not available. What is the most honest substitute?
- **Chosen.** A seeded generator (`auditiq_bench/`) that builds clean transactions and injects errors into the same process,
  writing the label **at the moment of injection**; an **independent validator** that shares no code with the controls
  (a test fails if one imports the other) recomputes from the finished tables which rules each invoice violates and requires the
  result to equal the labels in both directions; a dataset that fails validation is not written. Datasets are a function of
  (seed, generator version, policy registry): the same command writes byte-identical files, and every file's SHA-256 is in its
  manifest.
- **Equal counts per class** (30 per class in a benchmark ledger, 141 in the final one) so every class can be measured; this is
  not the mix a real ledger has, and the documents say so.
- **Size choices.** Benchmark ledgers have **5,000 invoices, not 1,200**: around the 1,200 that now form the evaluation subset
  stand 3,800 further clean invoices so vendors have realistic histories and the anomaly rate is 8.4% and not 35%. The 20,000
  invoice ledger keeps the 420 anomalous invoices (2.1%, a realistic rate). The 500,000-invoice ledger (15,000 vendors) tests scale.
- **Alternatives.** LLM-generated data (labels would be unverifiable and unreproducible); real data (unavailable); a public
  dataset (none fits procure-to-pay three-way match with approval logs).
- **Costs and limits.** Everything is synthetic; amounts are plausible by design and not fitted to a real ledger; injected
  errors are clean cases; descriptions and remarks are templated; several columns are constant. A result on this data is a result
  about the system under controlled conditions, not an estimate of accuracy on a company's books.

### D14. The answer key stays outside the audit

- No stage of the audit reads `labels.csv`. For verification and display, the launcher loads the labels into a separate table
  (`benchmark_labels`) **after the ledger is published**, and only the analytics read it (to score the audit against the key).
  The labels hold for the policy version they were written for (`meta.labels_policy`); results under another version are left out
  and counted, so a changed threshold is never reported as a false alarm (code review finding 20). The copilot cannot read the
  labels either (finding 1).

### D15. The final ledger (`final_seed_2025`) and why it has compound frauds

- **The request.** "Create a database of 25k records ... the final database that we are going to use for the entire project ...
  real deviations and frauds ... every record had the same score and the teacher asked why." *"25k records"* was read as
  **25,000 invoices** (each with its PO, GRN and approvals: 103,741 ledger records in all).
- **The diagnosis.** The scoring floors (D10) and one violation per fraudulent invoice make flagged scores sit on a few values;
  the old stores held 0 / 5 / 10 / 50 / 70 only.
- **Alternatives considered.** (1) Change the scoring formula: rejected for now (it is the paper's model). (2) Generate more
  ledgers of the same kind: same lumpy scores. (3) **Compound frauds**: keep the model, change the data. Chosen.
- **How compound frauds are made** (`Builder.compound_frauds`, section 7.4). After the usual injections, about 40% of the
  *eligible* anomalous invoices receive one to three further violations (weights 0.5 / 0.3 / 0.2) from three add-ons that are
  independent of every other label: a **different GSTIN than the vendor master's** (3.1.3), **fewer units received than billed**
  (2.1.2), **approved by a role whose limit is below the amount** (5.1.1). Every added violation goes into the label
  (`clause_ids` and a new column `secondary_class_ids`), and the validator checks each.
- **Why 141 per class.** J2 (structuring) is built in groups of three, so the per-class count must be a multiple of 3; 141 gives
  14 x 141 = 1,974 injected invoices, plus 301 planted ring invoices (285 above-limit approvals in the six approver rings and 16
  invoices cross-registered under another vendor's GSTIN in the two shared-PAN shell pairs) = 2,275 anomalous invoices.
- **Why 9.1% anomalous and 1,250 vendors.** A visible but not absurd fraud rate (the 20,000 ledger is 2.1%, the benchmarks 8.4%),
  with the vendor-to-invoice ratio of the 20,000-invoice ledger (1,000 vendors for 20,000).
- **Planted collusion at company scale.** Four pairs of shell vendors (two sharing a PAN, two sharing a whole GST registration)
  and six approver rings (two in each of the three lower roles).
- **Result and honesty.** 558 compound frauds (395 with one added violation, 153 with two, 10 with three). The audit's findings
  equal the labels exactly on 100% of invoices with a rule violation, with 0 false alarms on 22,425 clean invoices and 0 of 300 hard
  negatives, and the detector recovers 10 of 10 planted rings. **But the scores remain lumpy** (section 12); the data change
  reduced, did not remove, the clustering.

### D16. Kafka: topics, exactly-once storage and what an invoice is audited against

- **Why Kafka.** The Review-1 deck described Kafka ingestion; the owner asked to match it.
- **Design.** Four topics (vendor, invoice, email, compliance), 4 partitions each; invoices keyed by vendor id so a vendor's
  invoices are processed in order by one worker; stateless workers per consumer group.
- **Exactly once.** Kafka delivers at least once, so a batch and the next offsets of its partitions go into **one database
  transaction** (`stream_offsets`), a worker starts from the database's offset, and a batch is stored only if no other worker has
  moved the partition ("fenced"). The publisher is idempotent.
- **Audited against arrivals.** In batch an invoice is compared with all the vendor's invoices (earlier and later); on a stream a
  later one has not arrived, so an invoice is audited against those before it in ledger order, and a same-day split completed by a
  later invoice makes the worker **audit the day's earlier invoices again**. Without that step a development run lost 21 findings
  of 5,000 invoices and F1 fell from 0.833 to 0.798; with it the stream ends with the batch audit's findings (F1 0.833, on SQLite
  and PostgreSQL, with 1, 2 or 4 workers).
- **Windows.** The local broker runs Java directly with a classpath wildcard (the release's `.bat` files overflow cmd's line
  length), clears read-only snapshot flags and disables the log cleaner (`log.cleaner.enable=false`) because Windows refuses to
  rename open segment files (finding 26). Every launcher run uses topics of its own (`live-<time>.invoice`, ...) because a topic
  cannot be emptied reliably on Windows; `reset` removes them.

### D17. An invoice is judged by the policy in force on its date

- A real bug (finding 22): v3.12 applied to a ledger dated before it took effect turned invoices approved within the limits of
  their day into breaches. **Chosen:** a policy timeline (`db.policy_timeline`, `service.audit_in_force`): the active version
  governs from its effective date; before that date each earlier version governs from its own; a stored version that takes effect on
  or after the active one without being active governs nothing. `--policy X` still audits everything under one version, for
  experiments. This is also why every demonstration policy takes effect on 2025-04-01 (D21).

### D18. Analytics, and collusion rings tested against the approver's role

- **The analytics** are read-only analyses of the store (section 8): Benford's law, amounts against approval limits, weekdays,
  concentration (Gini, HHI), approvers, findings by category and rule, a spend skyline in 3D.
- **Rings.** A first rule linked an approver to every vendor of one approval above their limit and joined an entire ledger into one
  ring; comparing approvers with the whole ledger made hundreds look unusual, because a role with a lower limit breaks the rules
  more often (finding 21). **Chosen:** an approval link needs a one-sided binomial test **against the rate of the approver's own
  role** to pass Benjamini-Hochberg at a false discovery rate of 1%; identity links (shared PAN, shared GSTIN, another vendor's
  GSTIN on an invoice) need no test; when nothing passes, a **watch list** ranks the strongest leads as "below significance".
  A ring is a lead, not a finding.
- **Verified against the planted rings** (section 7.5): the detector's tested links match the six planted approver rings exactly.

### D19. Knowledge graphs built by code, not extracted by a model

- **Question.** Plain passage retrieval cannot join facts (an amount and the limits table to know who may approve it; two versions
  of a rule to say what changed; an audit's findings across vendors and approvers). Add a graph?
- **Alternatives.** A graph extracted by a language model from the documents (the usual GraphRAG): rejected, because the corpus is
  tens of passages, each extraction takes minutes on the laptop's model, and a model can add relations the policy does not state,
  which an audit tool cannot afford. A graph database such as Neo4j: rejected as one more server for graphs of a few thousand
  nodes that are already stored exactly in tables.
- **Chosen.** Two graphs **derived from the store by code**, cached until the store changes, never stored separately:
  the **policy graph** (clauses, parameters, roles, checkers, pages, versions) and the **audit graph** (vendors, invoices with
  findings, rules, approvers, shared identities, rings). Each answers a question with **facts**: statements computed from the graph
  with the numbers they rest on. They are labelled `[F#]` (policy) and `[C#]` (ledger) in the prompt of Ask AI.
- **Choices inside the audit graph.** Only invoices with a finding are nodes (1,835 of 25,000); a ring fact lists, per approver,
  the vendors with a **tested** link and counts the rest as "through the hotspot link only" (the detector's ring joins an approver
  to every vendor of its flagged invoices, which widens a ring: 54 vendors named where 4.2 were planted before the change);
  identity questions get identity pairs and not the approver rings.
- **Evidence.** Policy graph: on 23 held-out questions the evidence was complete for 22 with graph + lexical (21 with the graph
  alone) against at most 13 for a passage ranker; derived answers stated for 17 of 19. Audit graph: 78 questions with answers
  computed from the ledger files, 78 right (policy-only retrieval 0 by construction); the ten ring-type questions are not held out
  (section 9.4).

### D20. Ask AI: guards, grounding and what it can and cannot do

- Three kinds of question: policy and invoice questions (passages + policy facts + the invoice's audit record + ledger facts, with
  citations), and **data questions** (the model writes one SELECT, which is checked, refused if it names a table outside an
  allow-list, and run on a read-only connection with a row limit and a time limit; on PostgreSQL as a role that holds SELECT on the
  allow-list only). A model that reads invoice text must be treated as written by someone who wants the labels: the review found
  and closed a path through `set_config('role', ...)` and `query_to_xml` (finding 1).
- **Two defects found on 13 and 14 November**, both by looking at what the model was given and not at the model: the data-question
  prompt did not give the real values (`action_taken` is `'Approved'`, not `'approve'`), so the SQL returned zero rows and the
  model described rows that did not exist; and the answer prompt did not name the ledger facts as a source (and, separately, a
  scripted edit had failed silently, so the facts were not in the prompt at all). Both are fixed and tested.
- **The model's limit.** With Qwen2.5-7B on a CPU (2 to 5 minutes per answer) the written answer cites the ledger facts but can garble
  a long multi-approver fact (it merged four approvers' vendors under all four names). The facts themselves are exact; the Ask page
  shows them under the answer.

### D21. The demonstration policies: change only the document

- To show that **the output follows the policy**, five company policies were written as PDFs with distinct stories and distinct
  levers: thresholds (tolerance, daily count, approval limits, working days, round-amount multiple) **and rule severities**
  (severity re-weighting is the lever that changes scores and review workload without changing which invoices are found).
  Each takes effect on 2025-04-01 so the chosen one governs the whole financial year (D17). A sixth, incomplete draft must be refused.
- **A calibration decision.** The first Strict policy halved every approval limit and held 38% of the ledger (9,624 of 25,000, with
  7,572 invoices that the baseline accepts), which is not a policy a company would issue; it was changed to a tenth off each limit
  and a 0.5% tolerance (3,263 held, about twice the baseline).
- Details and measured effects: section 10.

### D22. The web application, and why it is built like this

- React 18 + TypeScript + React Three Fiber (3D views), React Router 7, Vite 6; a single-page app that uses the REST API only; every
  page lazy-loaded; three.js in its own chunk. The owner asked for an "industry-grade" interface in the style of an earlier export
  (black sidebar, green accent, dashboard cards) with 3D views. A Streamlit dashboard remains as the lighter alternative (it needs no
  build). The 3D scenes fall back to a notice without WebGL.

### D23. Security decisions

- Users with roles (viewer, reviewer, admin; tokens stored as SHA-256 only, decisions carry the signed-in name), a Content-Security-Policy,
  security headers, upload checks (size, type, magic bytes, a hashed id for an upload), archive-bomb refusal (300 MB unpacked), the copilot's
  SQL guards, `pip-audit` and `npm audit` in CI, no credential in the repository. The reference export's database password (in 43 files of
  the excluded folder) must be rotated by the team in the old provider's console: the project must not touch that account.

### D24. Operational decisions that came from the machine (Windows, OneDrive, a laptop)

- **Stores outside OneDrive.** The launcher keeps the store and logs under `%LOCALAPPDATA%\auditiq\live`, because the store uses a
  SQLite write-ahead log and a sync client rewriting its folder would corrupt or lock it. The 500,000-invoice files are likewise kept
  outside the project folder.
- **Connections wait up to 60 seconds** (`db.LOCK_WAIT`) because a long read of a SQLite store made a batch audit fail with "database is
  locked" after the default 5 seconds.
- **Models on a laptop.** Qwen2.5-7B takes 3 to 5 minutes per call on the CPU (i5-1235U, 16 GB, no GPU), 6 to 8 times faster prompt
  processing on the integrated GPU through a second Ollama server (`OLLAMA_HOST=127.0.0.1:11435 OLLAMA_IGPU_ENABLE=1`, Vulkan). The full
  protocol would still take about 200 hours, so the measured step is a 90-invoice sample.

### D25. Decisions that were open and how they were settled (20 October 2026)

1. **Which model runs C2 to C5.** The same open-weight model, Qwen2.5-7B with frozen prompts, on the integrated GPU; the measured
   step is a 90-invoice sample of ledger 202; the full run waits for a GPU or hosted endpoint, with one command ready.
2. **J1 (near-duplicate).** Kept as a judgement rule; the limitation is stated: as generated, an invoice that is not the first on
   its PO is always a duplicate (R3 or J1), so a rule on the PO reference finds every J1 and both classical detectors report all
   of them. A control for 2.2.2 is the natural next step and would change every table.
3. **The reference export's password** is for the team to rotate.

### D26. Smaller decisions that matter when reading the code

| Decision | Reason |
|---|---|
| Policy v2.5 renumbers 2.2.2 (a routing instruction in v2.4; in v2.5 every numbered rule defines one exception) | One rule, one exception, one severity |
| R4 and R5 are disjoint by policy: 3.1.3 applies only to a well-formed GSTIN | A malformed GSTIN is reported under 3.1.1 or 3.1.2 only |
| Duplicates label the *later* invoice | The earlier one is the original and stays clean |
| "Amount exactly at an approval limit" is not a clean hard negative | Limits are round amounts, so it violates 4.3.1; the hard negative is "just inside" |
| The approval limit comes from the role's limit in the policy, not the log's `amount_limit` column | Otherwise a policy swap could not change the outcome |
| An empty evidence set gives g = 0 | A finding without evidence is not grounded |
| A valid clause fixes the severity | The scorer takes the cited clause's severity; an agent is not asked for one |
| Evidence is a list of record fields (`invoice.amount`, `history.<id>.invoice_number`) | Grounding can only be checked against stored fields |
| Agent remits follow policy sections: Math and Approvals 2.1 and 5; Tax and Identity 2.2 and 3; Vendor Intelligence 4 | A flag outside the remit is discarded and counted |
| The challenger cannot remove a control flag; a flag it does not rule on is kept | Models can add, not subtract, a control's finding |
| A reply that is not valid JSON is sent back once for repair | A stage that fails twice contributes nothing; both are counted |
| Generator and controls share no code (a test enforces it) | The validator is an independent second implementation of the same rules |
| No GSTIN longer than 15 characters is generated | `VARCHAR(15)` in the schema |
| Policy v2.5 effective 2025-04-01, v2.6 2026-04-01 | The ledgers cover the financial year 2025-26; an earlier draft dated the policy after the invoices it was applied to |
| A review decision is the last entry of its result's audit trail, with the reviewer as actor | One trail per result |


---

# Part III. Running it

## 5. How to run it

### 5.1 What you need

| Need | For | Notes |
|---|---|---|
| Python 3.11 or later | everything | `pip install -e ".[dev]"` from `pp1/auditiq/` installs the package, the `auditiq` command and the test tools |
| Node.js 20 or later | the web application | `cd frontend && npm ci && npm run build` builds `frontend/dist`, which the API serves. Without Node the API runs and the pages do not. (The development machine has Node 22) |
| Java 17 or later and Apache Kafka 4.3.2 | `start.bat` (the live run through Kafka) | One-time install of a local broker without Docker: download `kafka_2.13-4.3.2.tgz` from https://kafka.apache.org/downloads and run `python scripts\kafka_local.py init kafka_2.13-4.3.2.tgz` (unpacks to `%LOCALAPPDATA%\auditiq\kafka`, formats the storage, writes `AUDITIQ_KAFKA_BOOTSTRAP` to `.env`) |
| A chat model (optional) | Ask AI answers, configurations C2 to C5, reading a free-worded policy | Ollama with `qwen2.5:7b-ctx12k` (`ollama create qwen2.5:7b-ctx12k -f deploy/ollama/Modelfile`) and `nomic-embed-text` for embeddings; settings in `.env` (section R26). Without a model, everything else works: the audit (C1), analytics, rings, both graphs (their facts are the answer) |
| PostgreSQL (optional) | the second backend | `python scripts/pg_local.py init` starts a local PostgreSQL 17 without installation (port 5544). SQLite is the default and needs nothing |

No model and no database server are needed to run the audit, the tests, the analytics or the web application.

### 5.2 The one-file way: `start.bat`

From `pp1/auditiq/`:

```
start.bat
```

It runs `scripts\live.py` (with `.venv\Scripts\python.exe` if there is one). A **run** does, in order:

1. **Checks what it needs**: the Python packages (`confluent_kafka`), Kafka installed (or a broker already listening), the ledger
   (`data\final_seed_2025\invoices.csv`), port 8000 free; builds the web application once if `frontend\dist` is missing and Node exists.
2. **Starts the local Kafka broker** unless one is listening on 9092; waits 6 seconds for it (it listens before its coordinators have
   loaded, so a client may log "coordinator load in progress" and retry: harmless).
3. **Creates an empty store** with the policy versions and documents (`python -m auditiq --db <store> setup`) and **four topics of
   its own** (`live-<time>.vendor`, `.invoice`, `.email`, `.compliance`). Old stores of earlier runs are removed.
4. **Starts the web application and the stream workers** as separate processes (by default two invoice workers and one worker each for
   vendor, email and compliance; port 8000), and opens the browser at `/kafka`.
5. **Publishes** the policy documents (the SOPs the controls can execute), the ledger (vendors first, then invoices each with its
   purchase order, goods receipt and approval entries) and the vendor e-mails written about it (synthetic, from
   `auditiq_bench/correspondence.py`; for `final_seed_2025` this is 10,700 e-mails) through Kafka, then **loads the ledger's
   labels as an answer key** into a separate table (the audit never reads them).
6. **Reports progress** (per topic: processed / published; invoices waiting for review) until every message is processed, prints a
   summary, and **keeps the pipeline live** until Ctrl+C. The Kafka broker keeps running afterwards.

Nothing reaches the store except through the topics; the web application shows what arrived and was audited.

**Measured on the development laptop** (SQLite, two invoice workers, configuration C1): `collusion_seed_707` (5,000 invoices, 2,104
e-mails) was processed 34 seconds after publishing; `final_seed_2025` (25,000 invoices, 10,700 e-mails) 209 seconds after publishing:
25,000 audited, 1,658 sent to a person (6.6%), 23,342 approved, risk levels critical 868, high 790, medium 143, low 23,199, and 7 rings.

**Options** (all pass through to `scripts/live.py`; `python scripts/live.py --help` lists them):

| Command | Does |
|---|---|
| `start.bat` | a fresh run: an empty store, new topics, everything streamed and audited |
| `start.bat --keep` | open the last run again; nothing is published |
| `start.bat --ledger bench_seed_202 --limit 1000` | another ledger under `data\` (or the path of a ledger folder), only its first 1000 invoices |
| `start.bat --no-emails` / `--no-answer-key` / `--no-browser` | skip the e-mails / the labels / opening the browser |
| `start.bat --workers 4 --batch 200` | more invoice workers; messages a worker stores per transaction |
| `start.bat --config C3` | audit with another configuration (C2 to C5 need a model) |
| `start.bat --bootstrap host:9092` | use a Kafka broker that already exists |
| `start.bat --exit-when-done` | stop when every message is processed (used for tests and scripted runs) |
| `start.bat stop` | stop the Kafka broker |
| `start.bat reset` | stop it and delete the topics and messages of every run, and the stores |

**Where things go.** The store and logs of a run are **outside the project**, in `%LOCALAPPDATA%\auditiq\live` (override with
`AUDITIQ_LIVE_HOME`): `live-<time>.db` (the store, a SQLite file with a write-ahead log), `run.json` (what the last run is),
`logs\server.log`, `logs\worker-<topic>.log`, `logs\setup.log`, `mail\<ledger>.mbox`. The Kafka broker's files are in
`%LOCALAPPDATA%\auditiq\kafka` (the release) and `kafka-data` (the log), its log in `kafka.log`.

**What you can open** (http://127.0.0.1:8000): `/` Overview, `/review` review queue, `/invoice` invoices and their audit packs,
`/policy` policy versions, upload and simulate a policy, `/analytics` forensic analytics, `/rings` collusion rings, `/kafka` the
streams, `/ai` agents and pipeline costs, `/knowledge` documents and passages, `/graph` the two knowledge graphs, `/rag` retrieval
trace, `/ask` Ask AI, `/pipeline` architecture, `/results` measured results; the API description is at `/api/docs`.

### 5.3 The command-line way (no Kafka, SQLite)

```
pip install -e ".[dev]"
python -m auditiq setup --dataset data/large_seed_505     # a 20,000-invoice ledger, both policy versions, the policy PDFs
python -m auditiq run --config C1                         # audit every invoice with the twelve controls
cd frontend && npm ci && npm run build && cd ..
python -m auditiq serve                                    # http://127.0.0.1:8000
```

Other commands (`python -m auditiq --help`): `run --config C5 --invoice INV40042` (full pipeline on one invoice, needs a model),
`audit --invoice ... --review`, `show --invoice ...` (stored audit pack and trail), `queue`, `decide --result 17 --decision approve
--reviewer "A. Auditor"`, `ask "Why is INV40042 high risk?"`, `ask-data "Which five vendors have the most escalated invoices?"`,
`policy {make-pdfs,ingest,adopt,simulate,embed,activate,apply,search}`, `ledger {check,import,export}` (a folder, an Excel workbook with one
sheet per table, or a zip of CSVs), `stream {topics,publish,work,status}`, `user {add,list,disable}`, `status`, `export --out exports`,
`graph --config C5`, `check-llm`. `--db` chooses the store (a path, or a PostgreSQL URL).

### 5.4 Verifying a run against the ground truth

After a run (stores are named `live-<time>.db` in the folder above):

```
python -m evaluation.final_check --db "%LOCALAPPDATA%\auditiq\live\live-<time>.db"
python -m evaluation.case_graph_eval --db "%LOCALAPPDATA%\auditiq\live\live-<time>.db"
```

`final_check` writes `results/<ledger>/verification.md` and `.json` (score spread, per-rule precision and recall, results by number of
violations, planted rings recovered). `case_graph_eval` writes `results/case_graph/case_graph_eval.md` and `.json`.

### 5.5 The demonstration policies

```
python -m auditiq.policy_demo          # write the five policy PDFs and the incomplete draft to policy/demo/
python -m evaluation.policy_demo       # audit the final ledger under each, write results/policy_demo/ and docs/POLICY_DEMO.md
```

To show it live: in the web application open **Policy**, upload a PDF from `policy/demo/`, read the preview (what differs from the
policy in force), **Simulate** (nothing stored), **Adopt and activate**, **Apply** (re-audit), and watch the Overview, the review queue and
the analytics follow. Activate version 2.5 and apply again between demonstrations if the numbers are to be read against the baseline.
Upload `Draft_Incomplete_v5.99.pdf` to see a document refused with the reasons.

### 5.6 Datasets

```
python -m auditiq_bench --list                       # the datasets and their profiles
python -m auditiq_bench                              # regenerate every dataset (byte-identical)
python -m auditiq_bench --only final_seed_2025       # one dataset
python -m auditiq_bench.overview --verify            # compare every file with the hash in its manifest
python -m auditiq_bench --only huge_seed_606         # the 500,000-invoice ledger (about 330 MB), on request
```

### 5.7 Tests, browser tests, reproduction, containers

| Command | Does |
|---|---|
| `python -m pytest` | the Python suite (519 tests are collected; those that need PostgreSQL are skipped unless `AUDITIQ_TEST_DATABASE_URL` is set; no test calls a model; Kafka tests need `AUDITIQ_TEST_KAFKA_BOOTSTRAP`) |
| `cd frontend && npm test` | 61 frontend tests (Vitest, including the 3D layout and every page against canned API responses) |
| `cd frontend && npm run lint` and `npm run typecheck` | ESLint; strict TypeScript |
| `cd frontend && npm run e2e` | 10 Playwright browser tests against the real server on a fresh store (`npx playwright install chromium` once) |
| `python scripts/reproduce.py` | regenerates every dataset and every result that needs no model in a temporary folder and compares every file with the committed one (54 of 54 dataset files and 32 of 32 result files identical on 20 October) |
| `python -m ruff check .` | lint of the Python code |
| `docker compose -f deploy/docker-compose.yml up` | the API, PostgreSQL, a Kafka broker and the stream workers in containers (requires `POSTGRES_PASSWORD` in the environment; the development machine has no Docker: the compose file and the `Dockerfile` are proven by the CI `compose` and `container` jobs) |
| `python -m streamlit run app/dashboard.py` | the lighter Streamlit dashboard |

### 5.8 Troubleshooting

| Symptom | Cause and what to do |
|---|---|
| "Kafka is not installed" | run the one-time `python scripts\kafka_local.py init <the .tgz>` (needs Java 17+) |
| "the ledger ... does not exist" | generate it: `python -m auditiq_bench --only final_seed_2025` |
| "port 8000 is in use" | another AuditIQ server runs; close it or use `--port` |
| `confluent_kafka` import error | `pip install -e ".[dev]"` |
| Pages do not load, API does | the frontend is not built: `cd frontend && npm ci && npm run build` |
| Ask AI takes minutes | the local 7B model runs on the CPU (2 to 5 minutes per answer on the development laptop); use the integrated GPU server or a hosted endpoint; the exact facts show without a model |
| "database is locked" | a very long read of a SQLite store while workers write; connections wait up to 60 s (`db.LOCK_WAIT`); keep the store outside OneDrive |
| Kafka broker stops on Windows | use `scripts\kafka_local.py start` (it clears read-only flags and disables the log cleaner) |
| A model run hangs the laptop | it sleeps at critical battery; keep the charger in; only about 0.5 to 1 GB of RAM is free while a 7B model is loaded |


---

# Part IV. The data

## 6. The datasets, how to find them and how to read them

### 6.1 The catalogue

AuditIQ-Bench is the family of synthetic procurement ledgers the project is built and evaluated on. **Eight are committed** under
`auditiq/data/<name>/` (75,000 invoices and 311,935 ledger records in all) and a ninth, 500,000 invoices, is generated on request.
Everything is synthetic: no vendor, person, GSTIN or invoice is real.

| Dataset | Seed | Vendors | POs | GRNs | Invoices | Approval entries | Ledger records | Anomalous | Hard negatives | Eval. subset | Used for |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `bench_seed_101` | 101 | 250 | 4,920 | 4,910 | 5,000 | 5,680 | 20,760 | 420 (8.4%) | 120 | 1,200 | reported results; the 34-invoice model sample |
| `bench_seed_202` | 202 | 250 | 4,920 | 4,910 | 5,000 | 5,688 | 20,768 | 420 (8.4%) | 120 | 1,200 | reported results; Kafka measurement; 90-invoice sample |
| `bench_seed_303` | 303 | 250 | 4,920 | 4,910 | 5,000 | 5,651 | 20,731 | 420 (8.4%) | 120 | 1,200 | reported results |
| `pilot_seed_909` | 909 | 250 | 4,920 | 4,910 | 5,000 | 5,675 | 20,755 | 420 (8.4%) | 120 | 1,200 | development: the **only** ledger prompts and settings may be tried on |
| `swap_seed_404` | 404 | 250 | 5,000 | 5,000 | 5,000 | 5,654 | 20,904 | 150 (3.0%) | 0 | 300 | the policy-swap experiment (v2.5 against v2.6) |
| `large_seed_505` | 505 | 1,000 | 19,920 | 19,910 | 20,000 | 22,665 | 83,495 | 420 (2.1%) | 240 | 1,200 | the application demonstrations and precision at a realistic rate |
| `collusion_seed_707` | 707 | 250 | 4,920 | 4,910 | 5,000 | 5,701 | 20,781 | 471 (9.4%) | 120 | 1,251 | planted collusion rings; the ring detector was designed on it |
| **`final_seed_2025`** | 2025 | 1,250 | 24,624 | 24,577 | 25,000 | 28,290 | 103,741 | 2,275 (9.1%) | 300 | 3,657 | **the final ledger: the default of `start.bat` and of every demonstration** |
| `huge_seed_606` (on request) | 606 | 15,000 | 498,096 | 497,858 | 500,000 | 567,123 | 2,078,077 | 9,996 (2.0%) | 720 | 12,744 | every measurement without a model at scale; not committed (about 330 MB), its file hashes are in `results/huge_seed_606/manifest.json` |

`collusion_seed_808`, the held-out twin of 707, is **defined** in `auditiq_bench/__main__.py` but has **not been generated**.
The datasheet of each committed dataset is `data/<name>/README.md`; the generated overview is `docs/DATASETS.md`.

### 6.2 Where the files are and how to read them

Each dataset is a folder of CSV files (UTF-8, header row, amounts with two decimals, dates `YYYY-MM-DD`, an empty field means no value):

| File | One row per | Rows in `final_seed_2025` |
|---|---|---|
| `vendor_master.csv` | vendor | 1,250 |
| `purchase_orders.csv` | purchase order | 24,624 |
| `goods_receipts.csv` | goods receipt | 24,577 |
| `invoices.csv` | invoice | 25,000 |
| `approval_logs.csv` | approval step (forwarding or approving) | 28,290 |
| `labels.csv` | invoice: the ground truth; **never read by the audit** | 25,000 |
| `eval_subset.csv` | invoice in the evaluation subset: `invoice_id`, `stratum`, `weight` | 3,657 |
| `manifest.json` | the dataset: seed, versions, period, counts, file hashes, and for ledgers with planted collusion `rings` | |
| `README.md` | the datasheet, written from the generated tables | |

Reading with pandas: `pd.read_csv("data/final_seed_2025/invoices.csv")`. Loading into a store: `python -m auditiq setup --dataset
data/final_seed_2025`, or letting `start.bat` stream it through Kafka. A ledger of your own loads the same way from a folder of these
files, a zip of them or an Excel workbook with one sheet per file (`python -m auditiq ledger import`); it is checked first (tables, columns,
unique ids, amounts, dates, the references the store enforces) and replaces nothing if any check fails. An invoice may name a PO or GRN that does not exist:
that is the exception of rule 2.1.3.

**Verifying and regenerating.** `python -m auditiq_bench.overview --verify` compares every file with the SHA-256 in its manifest;
`python -m auditiq_bench --only <name>` regenerates one dataset byte for byte (a dataset is a function of its seed, the generator version
and the policy registry).

### 6.3 The tables and columns (as the CSV files have them)

The relations: `invoices.vendor_id` -> `vendor_master`; `invoices.po_id` -> `purchase_orders` (may be empty or name no order);
`invoices.grn_id` -> `goods_receipts` (may be empty); `goods_receipts.po_id` -> `purchase_orders`; `approval_logs.transaction_id` ->
`invoices.invoice_id`; `labels.invoice_id` -> `invoices`. The documents are dated in order: PO, then receipt, then invoice, then the approval steps.

| Table | Columns |
|---|---|
| `vendor_master` | `vendor_id` (`VEND1001`...), `vendor_name`, `official_gstin` (15 characters: 2-digit state code + PAN + entity digit + `Z` + check character), `pan_number` (10 characters), `vendor_category` (Logistics, IT Services, Raw Materials, MRO, Professional Services, Utilities), `city`, `state`, `country` (India), `gstin_status` (`Active` or `Suspended`), `kyc_status` (`Verified`, constant), `is_active` (1, constant), `blacklisted` (True/False), `blacklist_status` (copy of the flag) |
| `purchase_orders` | `po_id` (`PO` + 5 digits), `vendor_id`, `po_date`, `amount` (quantity x unit price, before tax), `po_amount` (copy), `quantity`, `unit_price`, `tax_amount` (GST 18%), `total_amount`, `currency` (INR), `department`, `requester`, `status` (`Closed`), `description` |
| `goods_receipts` | `grn_id`, `po_id`, `vendor_id`, `receipt_date`, `received_quantity`, `ordered_quantity`, `unit_price`, `amount`, `received_amount`, `received_by`, `warehouse_location`, `quality_check`, `status`, `notes` (the receiver's free-text remark; the judgement rule 2.1.4 reads it) |
| `invoices` | `invoice_id` (`INV40001`...), `vendor_id`, `invoice_number` (the vendor's own numbering style, e.g. `EJI-000263`, `JSC00629`), `date` (the date the pipeline uses), `invoice_date`, `due_date`, `amount` and `invoice_amount` (before tax), `quantity`, `unit_price`, `currency`, `tax_amount`, `total_amount`, `gstin` (the GSTIN **printed on the invoice**, which may differ from the master's), `po_id`, `grn_id`, `department`, `payment_terms` (`Net 30`), `payment_status` (`Unpaid`), `approval_status` (`Approved`), `approved_by`, `description` (the vendor's own words) |
| `approval_logs` | `log_id`, `transaction_id` (= `invoice_id`), `approver_name`, `approver_role` (Manager, Senior Manager, Director, CFO), `timestamp`, `action_taken` (`Approved` or `Escalated`; the **approving entry** is the latest `Approved`; an `Escalated` entry is a lower role forwarding the invoice and is not an approval), `amount_limit` |
| `labels` | `invoice_id`, `label` (`clean`, `hard_negative`, `anomalous`), `class_id` (R1..R10, J1..J4), `clause_ids` (the violated rules, `|`-separated; for a compound fraud the union), `severity` (the highest of those clauses), `group_id` (invoices that form one case: a same-day group, a structuring group, a ring), `related_invoice_id` (the original that a duplicate copies), `hard_negative_type`, `note` (what was injected, in words), and in the final ledger `secondary_class_ids` (the classes added to a compound fraud) |
| `eval_subset` | `invoice_id`, `stratum` (`anomalous`, `hard_negative`, `duplicate_original`, `ordinary`), `weight` (1 for the full strata, N/n for the sampled `ordinary` ones; the weights sum to the number of invoices) |

Several columns are constant on purpose (currency, payment terms, status, quality check, KYC): the schema is complete, and nothing can be
learned from them. Free text (descriptions, receipt remarks) is templated from a fixed vocabulary with variations.

The full column list with types on both backends, and who reads each column, is `docs/DATA_DICTIONARY.md` (generated). The store adds the policy,
audit, access and ingestion tables (section R15).

### 6.4 The final ledger in numbers (`final_seed_2025`, all counts from its files)

| Fact | Value |
|---|---|
| Period | 2025-04-01 to 2026-03-31 (financial year 2025-26) |
| Vendors | 1,250: 6 categories (209, 209, 208, 208, 208, 208), 1,229 `Active` and 21 `Suspended`, 20 blacklisted |
| Invoices per vendor | min 1, median 16.5, mean 20.0, max 125 (vendors get business in log-normal proportion) |
| Invoice amount (INR, before tax) | min 2,516; quartiles 40,854 / 90,644 / 222,650; mean 215,995; max 4,499,245 (capped at 4.5 million so the CFO's 10 million limit is never the question) |
| Items | 36 (6 per category), amounts log-normal per category, 6 departments |
| Anomalous | 2,275 (9.1%) = 1,974 injected (14 classes x 141) + 301 planted ring invoices |
| Hard negatives | 300 (5 types x 60) |
| Clean | 22,425 |
| Compound frauds | 558: 395 with one added violation, 153 with two, 10 with three |
| Clauses violated per anomalous invoice | 1 clause: 1,717 invoices; 2: 395; 3: 153; 4: 10 |
| Severity of the labelled invoices | critical 1,009; high 1,006; medium 226; low 34 |
| Evaluation subset | 3,657: anomalous 2,275, hard negative 300, duplicate originals 282, ordinary 800 (weight 27.679) |
| Planted rings | 10 (below) |

Per-class counts (the labelled class of the *primary* injection): R1 141, R2 141, R3 141, R4 141, **R5 157** (141 + 16 cross-registered invoices of the shell
pairs), R6 141, **R7 426** (141 + 285 above-limit approvals of the six approver rings), R8 141, R9 141, R10 141, J1 141, J2 141, J3 141, J4 141.

Planted rings (`manifest.json`, never read by the detector):

| Ring | Kind | Approver (role) | Vendors | Invoices with a finding |
|---|---|---|---|---|
| RING-01 | shell vendors, shared PAN | | VEND1809, VEND1549 | 8 |
| RING-02 | shell vendors, shared GSTIN | | VEND1309, VEND1319 | 0 (an identical GSTIN produces no mismatch) |
| RING-03 | shell vendors, shared PAN | | VEND2055, VEND2104 | 8 |
| RING-04 | shell vendors, shared GSTIN | | VEND1376, VEND1798 | 0 |
| RING-05 | approver and vendors | Qasim Pandey (Manager) | VEND1849, VEND1530, VEND1021, VEND2139 | 48 |
| RING-06 | approver and vendors | Frado Deep (Manager) | VEND2222, VEND1940, VEND1725, VEND1506, VEND2038 | 70 |
| RING-07 | approver and vendors | Ubika Gour (Senior Manager) | VEND2109, VEND1469, VEND1850, VEND2110, VEND1539 | 45 |
| RING-08 | approver and vendors | Orinder Merchant (Senior Manager) | VEND2234, VEND1029, VEND1727, VEND1147 | 44 |
| RING-09 | approver and vendors | Lakshit Pau (Director) | VEND1163, VEND1194, VEND1573, VEND2128 | 36 |
| RING-10 | approver and vendors | Meera Kapoor (Director) | VEND1223, VEND2244, VEND1527 | 42 |

### 6.5 The store (an audited ledger) and how to look inside it

A run of `start.bat` (or `python -m auditiq setup` + `run`) produces a **store**: the five ledger tables plus the policy tables (`company_policies`,
`policy_clauses`, `policy_parameters`, `policy_documents`, `policy_chunks`), the audit tables (`audit_runs`, `audit_results`, `latest_results`,
`audit_flags`, `audit_trail`, `review_decisions`), the answer key (`benchmark_labels`, loaded only for verification), `meta`, users (`api_users`) and the
ingestion tables (`emails`, `email_mentions`, `stream_offsets`, `stream_log`). Two views are the ones to query: **`v_latest_results`** (one row per
audited invoice: route, risk level, `r0`, `rc`, `flag_count`, workflow status, configuration, policy version) and **`v_review_queue`** (invoices waiting for a
person, with the vendor name). `audit_flags` holds each finding (`clause`, `severity`, `source` D for a control or L for an agent, `confidence`, `message`,
`evidence`, `removal_reason`). Open a SQLite store with any SQLite client, or `python -m auditiq --db <store> status`; `python -m auditiq export --out
exports` writes every table as CSV (`exports/large_seed_505_C1/` is such a snapshot).

## 7. How the errors are designed

### 7.1 The idea

A real ledger's errors are never labelled, so a system's accuracy on it cannot be measured. AuditIQ-Bench builds a clean ledger from a generator and
**injects each error into a copy of the same process**, so that an anomalous invoice differs from a clean one only in what was injected, and the label is
written at the instant of injection. Then an **independent validator** (sharing no code with the controls) recomputes from the finished tables which rules
each invoice violates and requires the result to equal the labels, in both directions. The thresholds are never written in the generator: it reads the
tolerance, the daily limit, the approval limits and the rest from the same policy registry the audit uses.

### 7.2 The fourteen classes

Classes **R1 to R10** can be decided by comparing field values; the pipeline decides them with **controls**. Classes **J1 to J4** need reading or judgement;
the pipeline gives them to **agents**. "Score if alone" is the risk score the invoice gets when that is its only finding (section 7.5). Severities are those of
policy v2.5.

| Class | The fraud or error, in plain words | Rule | Severity | Score if alone | How it is injected |
|---|---|---|---|---|---|
| R1 | Billed more (or less) than ordered | 2.1.1 amount match | high | 50 HIGH | The invoice bills a unit price 2% to 30% above (80% of cases) or below the order's, so the invoice amount differs from the PO amount by more than the 1% tolerance; round amounts and amounts above 4.5 million are avoided |
| R2 | More goods billed than received | 2.1.2 quantity match | high | 50 HIGH | The receipt records 1 to 40% fewer units than billed (goods only, at least 4 units); the shortfall is in `received_quantity` itself, with a short-receipt remark |
| R3 | Same invoice number billed twice | 2.2.1 exact duplicate | critical | 70 CRITICAL | A later invoice repeats the number of an earlier invoice of the same vendor with the same PO, GRN and amount; only the later one is anomalous (the earlier is its `related_invoice_id`) |
| R4 | Malformed tax number | 3.1.1 format; 3.1.2 state code | medium | 10, level MEDIUM | The invoice GSTIN is too short by 1 or 2 characters, or has a character that is not alphanumeric (3.1.1); or it starts with a state code outside 01 to 37, such as 00, 99 or 38 to 98 (3.1.2). Half and half |
| R5 | Invoice carries another registration than the vendor master's | 3.1.3 vendor match | high | 50 HIGH | The invoice GSTIN is well formed but not the vendor's: another state code (half), or another PAN with the same state (half). Applies only to a well-formed GSTIN: a malformed one is reported under 3.1.1 or 3.1.2 only |
| R6 | One purchase split into many same-day invoices | 4.1.1 same-day splitting | high | 50 HIGH | A vendor has 4 or 5 invoices on one day (the daily limit is 3); every invoice of that vendor on that day is anomalous and they share a `group_id` |
| R7 | Approved above the approver's authority | 5.1.1 approval limit | critical | 70 CRITICAL | The invoice amount is 1.05 to 2.5 times the limit of the role that approved it (capped at 4.5 million), with no escalation to a role that could approve it. The role is a Manager 50%, Senior Manager 35%, Director 15% of the time |
| R8 | Missing PO or GRN | 2.1.3 missing reference | high | 50 HIGH | The invoice names no PO and no GRN, or a PO but no GRN, or a PO that is not on record (three variants in turn) |
| R9 | Blacklisted or suspended vendor | 4.4.1 blocked vendor | critical | 70 CRITICAL | An invoice from a vendor that is blacklisted or whose GST registration is `Suspended`; blocked vendors have no other invoices (a few vendors, about 1 in 30, are blocked) |
| R10 | Weekend-dated or round-sum invoice | 4.2.1 non-business day; 4.3.1 round amount | medium; low | 10 MEDIUM; 5 LOW | Half are dated on a Saturday or Sunday; half bill an amount that is an exact multiple of 10,000 |
| J1 | Near-duplicate: re-keyed number | 2.2.2 near duplicate | critical | (agent) | A second invoice repeats an earlier one (same vendor, PO, GRN, amount) under a re-keyed number: separators changed, leading zeros dropped, a suffix added, two digits swapped, a zero typed as the letter O, or lower case. The numbers differ as text, so the exact-duplicate control does not fire |
| J2 | Structuring: splitting across days to stay under a limit | 4.1.2 structuring | high | (agent) | Three invoices of one vendor for the same goods, on three different days within 7 days, each 1.5% to 13% below the approval limit of the role that approved it (Manager or Senior Manager) and together above that limit; all three share a `group_id` |
| J3 | Invoice describes something else than was ordered | 2.1.5 description match | medium | (agent) | The invoice describes goods or services of another category than the PO; amounts and quantities agree, so no field comparison shows it |
| J4 | The receiver's remark contradicts the bill | 2.1.4 receipt remarks | high | (agent) | The remark says some units were rejected, damaged or returned, while `received_quantity` and the invoice still show the full quantity; only the free text contradicts the bill |

Each anomalous invoice of a **benchmark** ledger carries exactly one injected anomaly; classes have equal counts by design (30 each in a benchmark ledger, 141 in the
final one) so every class can be measured; that is not the mix of a real ledger. The final ledger relaxes the "exactly one" rule (section 7.4).

### 7.3 Hard negatives (clean invoices that look like errors)

A hard negative is a clean invoice built to sit next to an anomaly class. A detector that flags it learned the surface of the class, not the rule. They are
reported separately from ordinary clean invoices.

| Type | What it is | Resembles |
|---|---|---|
| HN_TOLERANCE | Invoice-PO variance just inside the 1% tolerance | R1 |
| HN_DAILY_LIMIT | Exactly 3 invoices of a vendor on one day (the daily limit) | R6 |
| HN_NEAR_LIMIT | An amount just inside an approval limit | R7 and J2 |
| HN_SIMILAR_NUMBER | Consecutive invoice numbers and equal amounts for separate deliveries | J1 |
| HN_RECURRING | Identical recurring monthly amounts | R3 and J1 |

"An amount exactly at an approval limit" cannot be a clean hard negative: limits are round, so it would violate 4.3.1.

### 7.4 Compound frauds (the final ledger)

Real frauds overlap. After the usual injections, `Builder.compound_frauds` turns about **40%** of the *eligible* anomalous invoices into compound frauds by adding **one to
three** further violations (probabilities 0.5 / 0.3 / 0.2 for one, two, three), chosen among three add-ons that are independent of every other label:

| Add-on | Rule added | What is changed | Not applied when |
|---|---|---|---|
| R5 | 3.1.3 | the invoice GSTIN is replaced by another state code on the vendor's PAN | the primary is R4 or R5 |
| R2 | 2.1.2 | the receipt records fewer units than billed, with a short-receipt remark | the primary is R2, R8 or J4, or the invoice has no GRN, is not goods, or has fewer than 4 units |
| R7 | 5.1.1 | the approval is replaced by one from the role *below* the adequate role (so the amount exceeds its limit) | the primary is R7, the invoice is under the lowest limit or above the highest |

*Eligible primaries*: R1, R2, R4, R5, R7, R8, R9, R10, J3, J4, not part of a group (R6, J2, a ring) and not a duplicate or an original of a duplicate. Every added violation is
written into `clause_ids` and its class into `secondary_class_ids`; the validator checks that each secondary class is a rule class, that its clause is among the clauses, and that the
recomputed rule violations equal the labels. The reason for the construction (the "75" problem) is D10 and D15 of section 4.

### 7.5 What a flagged invoice scores (the arithmetic)

Weights: critical 30, high 20, medium 10, low 5. Score = sum of the findings' weights (at most 100), raised to **70 if any finding is critical** and **50 if any is
high**. Level: the band of the score (>= 70 CRITICAL, >= 50 HIGH, >= 30 MEDIUM, else LOW), and at least the level of the most severe finding. Route (C1): escalate if
score >= 50, else approve. Examples: one critical finding scores 70; one high 50; two highs 40 raised to 50; one medium 10 (level MEDIUM, route approve); one low 5;
2.1.1 + 2.1.2 + 3.1.3 + 5.1.1 = 20 + 20 + 20 + 30 = 90 (the highest score in the final ledger's top queue); 2.1.2 + 3.1.3 + 4.3.1 + 5.1.1 = 75. So medium or low findings alone
are approved with the finding recorded (177 invoices of the final ledger: "findings that did not hold payment").

### 7.6 A worked example: why an invoice was flagged

`INV53478` of Sachdeva-Taneja (VEND1099), 2025-10-14, scored **90, CRITICAL, escalate**. The audit pack states, with the field values, a computed revision and the policy
page for each finding:

| Rule | Severity | Why (from the pack) | Revision |
|---|---|---|---|
| 2.1.1 amount match | high | "Invoice amount 261301.28 differs from PO amount 236741.44 by 10.37% (tolerance 1%)." | Bill the PO amount: the invoice is 24,559.84 above it; obtain a credit note. At that amount it is above the Manager's limit: obtain approval from a Senior Manager |
| 2.1.2 quantity match | high | "Billed quantity 4 exceeds received quantity 3." | Bill only the 3 units received; 65,325.32 at the invoice's unit price: obtain a credit note |
| 3.1.3 GSTIN vendor match | high | "Invoice GSTIN 19MBDBM9598T1ZO differs from the vendor master GSTIN 24MBDBM9598T1ZO." | Obtain a corrected invoice with the registered GSTIN; input tax credit cannot be claimed as it stands |
| 5.1.1 approval limit | critical | "Invoice amount 261301.28 exceeds the Manager approval limit of 100000; approved by Vasana Gokhale." | Obtain approval from a Senior Manager (limit 500000) before payment |

Each finding cites `Procurement_Audit_SOP_v2.5.pdf` and its page (pages 1 and 2). This invoice is a compound fraud: a price variance, a short receipt, a wrong GSTIN and an
approval above authority at once.

### 7.7 How the controls and the labels are kept honest

The validator (`auditiq_bench/validate.py`) checks, from the tables alone: (1) rule-defined clauses equal the labels, invoice by invoice, both ways; (2) label fields are
coherent (class, clauses, secondary classes, hard-negative type); (3) duplicates (R3, J1) follow an original with the same vendor, PO, GRN and amount, and nothing else shares a
PO; (4) structuring groups (J2) have one vendor, one role, one approver, dates within the window, amounts in the band and a total above the limit, and **no unlabelled pair of
invoices of one vendor near a limit within 10 days** exists; (5) receipt remarks and descriptions match the J4 and J3 labels; (6) the composition counts. Because the generator and
the controls are separate implementations of the same written rules, the controls' 100% on R1 to R10 is a **correctness check** (they agree), not a detection result: the
informative numbers are J1 to J4, hard negatives, citations and routing.

### 7.8 The planted collusion

*Shell vendors* (`share_identity`): two vendor records of one legal entity. Kind `pan`: the second record gets the first's PAN with a registration of its own (the GSTIN is
rebuilt from the second's state and the shared PAN; if it equals the first's it is altered). Kind `gstin`: the second record takes the first's whole GST registration. For the PAN
pairs, `cross_registration` adds 6 to 12 invoices of the second vendor that carry the first's GSTIN (a 3.1.3 finding). *Approver rings* (`plant_approver_ring`): one approver and
3 to 5 vendors; for each vendor the approver passes 8 to 14 invoices **above the limit of the role** (1.05 to 2.5 times) and 3 to 8 ordinary invoices within it (0.10 to 0.75 of the limit),
with no forwarding step; the invoices above the limit are labelled R7 with the ring's `group_id`. In the final ledger: four shell pairs (two PAN, two GSTIN) and two approver rings in each of the
Manager, Senior Manager and Director roles. The detector never reads these labels.


---

# Part V. What the system finds and shows

## 8. Analytics, coverage and rings

Three read-only analyses of the store, shown on the Overview, Analytics and Collusion rings pages. Each is computed from the ledger, the latest audit result of each invoice
and the policy (amounts are measured against the limits of the version in force); none calls a model and none writes to the store. Their answers are cached per server process,
keyed by a fingerprint of the store (`StoreCache`: the ledger's name, the newest result, the newest review decision, the policy versions and parameters, the Kafka offsets, the
labels' policy), so an audit, a decision, a policy change or a streamed batch makes the next request recompute.

| Analysis | Module | Endpoint | Page |
|---|---|---|---|
| Coverage of the latest results | `auditiq/analytics.py` (`coverage`) | `GET /api/overview` | Overview |
| Forensic analytics | `auditiq/analytics.py` (`ledger_analytics`) | `GET /api/analytics` | Analytics |
| Collusion rings and the watch list | `auditiq/rings.py` (`find_rings`) | `GET /api/rings?limit=` | Collusion rings |

### 8.1 The Overview (what the audit decided)

On the final ledger after a run: 25,000 invoices from 1,250 vendors, all audited; 23,342 approved automatically (93.4%), 1,658 waiting for review (6.6%); 2,442 findings (9.8 per 100
invoices, 12 rules); cards for critical alerts (868, weighted risk of 70 or more), duplicates (141), three-way match (573), tax identity (704), splitting and timing (282), approval and vendor
(742), vendors with findings (765 of 1,250, 20 blacklisted) and findings that did not hold payment (177: a medium or low finding alone stays under 50). It shows the **composition of the audit**
(risk level, route, workflow), the vendor risk map (a 3D "constellation": every vendor, a sector per category, height = highest risk), a vendor risk matrix, the monthly trend, findings by rule,
the escalation queue (the riskiest first, with the rules each breaks), the vendors with the most invoices waiting, and the newest steps of the audit trail.

**Coverage** (so that an approval is never read as "clean"): which configuration produced the latest results (here C1 for all 25,000); that the four judgement rules (2.1.4, 2.1.5, 2.2.2,
4.1.2) were **not checked** by a controls-only run; the findings that did not hold payment; and, on a generated ledger, the **answer key**: against `labels.csv`, an anomaly is *found* when its
invoice has a kept finding; a missed anomaly is *not checked* when its rule is a judgement rule and no agent ran, *missed* otherwise; a flagged clean or hard-negative invoice is a *false alarm*. On the
final ledger: found 1,835, false alarms 0, missed 0, not checked 440, precision 1.000, recall 0.807 (the 440 are judgement-class anomalies that a controls-only run cannot see). The key is scored only
under the policy version it was written for.

### 8.2 Forensic analytics (the Analytics page)

| View | What it computes | On the final ledger (measured) |
|---|---|---|
| Benford's law | first-digit and first-two-digit tests on amounts of at least 10: observed against expected shares, the z-statistic of each digit (marked above 1.96), chi-square, and the mean absolute deviation with Nigrini's thresholds (first digit 0.006 / 0.012 / 0.015 for close, acceptable, marginally acceptable conformity) | first digit MAD 0.0048 "close conformity", chi-square 80.5 on 8 degrees of freedom, digits that differ: 1, 4, 8, 9 (digit 1: 28.2% observed against 30.1% expected, z 6.5); first two digits MAD 0.00084, close |
| Amounts against the approval limits | invoices per quarter-decade of amount (log scale); for each limit, invoices within 10% **under** it against within 10% **over** it: a ratio well above 1 is the signature of amounts kept under an approver's limit | 1,439 just under against 1,009 just over (1.43x); Manager 913 / 739 (1.24x), Senior Manager 477 / 250 (1.91x), Director 49 / 20 (2.45x), CFO 0 / 0 |
| Day of the week | invoices, amount and invoices with findings per weekday | 70 weekend invoices (0.3%) |
| Findings by category and rule | kept findings per vendor category and rule (a 3D cell view) | each category has 7.0% to 7.7% of its invoices with findings (300 to 311 of 4,006 to 4,380) |
| Approvers | per approver: role, own limit, invoices, vendors, amount, invoices with findings and their amount, approvals above the approver's own limit; the twelve with most money on invoices with findings | 98 approvers; the top: Meera Kapoor (Director) 291 invoices, 58 with findings (INR 17 crore), 45 above their own limit; Lakshit Pau 37; Ubika Gour 49; Orinder Merchant 46; Frado Deep (Manager) 86 invoices with findings, 75 above their own limit |
| Spend concentration | the Lorenz curve over vendors, the Gini coefficient, the share of the ten largest, the Herfindahl-Hirschman index | Gini 0.567; top 10 vendors 9.1% of spend; HHI 24 |
| Monthly volume and spend skyline | invoices, amount, findings and escalations per month; spend per category and month in 3D | flagged rate 6.7% to 8.2% per month |

Benford's law describes amounts that span orders of magnitude and arise naturally; amounts generated from a catalogue of prices and quantities can depart from it without any manipulation, so the test points at
where to look, not at what is wrong.

### 8.3 Collusion rings

The links an auditor follows when looking for collusion between vendors, or between a vendor and the people who approve its invoices:

| Link | Between | When |
|---|---|---|
| shared PAN | two vendors | two vendor records with the same PAN |
| shared GSTIN | two vendors | two vendor records with the same GST registration |
| another vendor's GSTIN | two vendors | an invoice of one vendor carries the registration of another |
| repeated findings | approver and vendor | the pair's invoices with high or critical findings are more than the approver's role makes likely (test below) |
| above own limit | approver and vendor | a repeated-findings link whose findings include approvals above the approver's own limit |
| approver hotspot | approver and each vendor of their flagged invoices | the approver's approvals as a whole carry more high or critical findings than the role's rate allows |
| concentrated approvals | approver and vendor | one approver approved at least 40% of the vendor's invoices, at least 10 of them |

**The tests.** The rate of a role is the share of the invoices its approvers approved that have a kept finding of high or critical severity. A pair is tested when the approver approved at
least two of the vendor's invoices: with *k* such invoices with findings out of *n*, the p-value is P(X >= *k*) for X ~ Binomial(*n*, rate of the role), and a candidate needs *k* >= 2. Each approver is tested the same
way over all their approvals. Each family (all pairs; all approvers) is corrected with the Benjamini-Hochberg procedure and a link needs a **q-value of 0.01 or less**. Comparing an approver with others of the
**same role** matters: a role with a lower limit breaks the rules more often, so against the whole ledger every approver of that role would look unusual and the ledger would form one ring (the failure of the first
version, code review finding 21). Identity links need no test.

**Rings and the watch list.** A ring is a connected group of links with at least two vendors; a group around one vendor is a *pair*; rings are ranked by the money on the invoices with findings on their links
(at most 1,500 members drawn). When nothing passes, the **watch list** shows the forty approver-vendor pairs with the smallest p-values, each with *k* of *n*, the expected number, p and q, as "leads below
significance". A ring is a lead for an investigation, not a finding.

**On the final ledger** (the page): 7 rings with 107 vendors and 6 approvers, INR 41 crore on ring links, 3,216 approver-vendor pairs tested (36 with two findings or more), 98 approvers tested, 6 hotspots, 4 shared-PAN
pairs, 2 shared-GSTIN pairs, 704 GSTIN mismatches (invoices whose GSTIN is not the vendor's). The detector recovered **10 of 10 planted rings**; the 7 rings it reports contain a planted vendor each; the approver-vendor links that
survive the correction ("tested links") **match the six planted approver rings exactly** (4 of 4, 5 of 5, 5 of 5, 4 of 4, 4 of 4, 3 of 3 vendors, no extra). The detector's rings are wider than the plant because of the hotspot link
(for example one ring joins four approvers and 75 vendors); the facts of the audit graph therefore name the tested links, and count the others (section 9).

### 8.4 Verification of the audit against the ground truth (`evaluation/final_check.py`, `results/final_seed_2025/verification.md`)

| Check | Result on `final_seed_2025` (measured) |
|---|---|
| Score spread | 8 different scores among the 1,835 flagged invoices; the most common (70) takes 46.4%; histogram: 0: 23,165; 1 to 10: 177; 41 to 50: 780; 51 to 60: 10; 61 to 70: 852; 71 to 80: 13; 81 to 90: 3. The check requires at least 8 different scores and none above 60%: **passed, narrowly** |
| Rules decided by the controls (12 clauses) | precision 100% and recall 100% on every clause; findings equal the labelled rules exactly on 100% of the 1,835 invoices with a violation |
| Hard negatives and clean invoices flagged | 0 of 300; 0 of 22,425 |
| Judgement clauses (2.1.4, 2.1.5, 2.2.2, 4.1.2) | 141 labelled each; flagged by the controls: 0 (they need a model: C2 to C5) |
| By number of labelled violations | 1: 1,717 invoices (mean score 39.9, highest 70, 5 distinct scores); 2: 395 (57.0; 50 to 70); 3: 153 (67.0; 50 to 80); 4: 10 (78.5; 70 to 90) |
| Planted rings | 10 of 10 recovered |

The 100% on the rule-decided clauses is a correctness check (the controls and the generator implement the same written rules), not a measure of detection on real data. The score spread is the honest weak
point (section 12).

### 8.5 Policy simulation and the routing evaluation

`auditiq/simulation.py`: before a policy document is adopted, every invoice of the stored ledger is audited **in memory** under the version in force and under the document, and the difference is reported (decisions
moved, newly flagged, cleared, routes, findings by rule, money newly held); nothing is stored. It is exact for the controls' rules and compares against the policy **in force at that moment**. `evaluation/routing.py`
measures what goes to a person: on the 5,000-invoice demonstration store, 281 (5.6%) were sent to a person, 97.2% of them anomalous, 0 clean; on the 500,000-invoice ledger with a later policy applied to every invoice, 160,068
(32.0%), 4.7% anomalous; with each invoice under the version in force on its date, 5,712 (1.1%), 100.0% anomalous.

## 9. The knowledge layer: two graphs, retrieval and Ask AI

### 9.1 The policy knowledge graph (`auditiq/policy_graph.py`, `docs/POLICY_GRAPH.md`)

Built by code from the clause registry of each version, the passages of the ingested documents with their pages, and the code that checks each rule (read from `controls.CONTROLS` and `agents.AGENTS`). No model
extracts anything, so it can be wrong only where the registry or the documents are (and 196 of 196 values read correctly). For v2.5 it has **58 nodes**: 16 clauses, 15 checkers, 11 parameters, 8 sections, 4 roles (with their
limits), 2 versions, 2 pages; **75 edges**: stated on 17, has rule 16, checked by 16, sets 11, has section 8, limit 4, changes 3.

`PolicyGraph.query(question)` recognises rule numbers, versions, amounts (INR 30 lakh, Rs 7,50,000, 1.2 crore), roles, agents, severities and words of change, and returns **facts**, each citing the rule, version and passage:
the lowest role whose limit covers an amount ("an amount equal to the limit is within authority"), an amount inside the structuring band of 4.1.2 (15% under a limit), a round amount (4.3.1), a role's limit, what changed between two
versions, the rules of a severity or kind, and what checks a rule. Evaluated against passage retrieval (`evaluation/graph_eval.py`, `results/graph_retrieval.md`, 32 questions written by the authors: 9 dev and 23 held-out test; the method
was frozen before the test run): the evidence was complete for **22 of 23** with graph + lexical (what Ask AI is given) and 21 with the graph alone, against at most 13 for a passage ranker; the graph stated the derived answer for 17
of 19. Known misses kept: "relaxed" is not a word of change; one question lists all changes; a six-passage cap drops an older limits table.

### 9.2 The audit knowledge graph (`auditiq/case_graph.py`, `docs/CASE_GRAPH.md`)

The audited ledger as a graph, derived on request from the store (built in about half a second for 25,000 invoices) and cached until the store changes; nothing is stored beside the audit.

| Node | Holds |
|---|---|
| vendor (1,250) | name, category, blacklisted, invoices, invoices with findings, money with findings |
| invoice (1,835: only those with a finding) | amount, date, score, level, route |
| rule (16) | a clause of the policy in force, with the invoices that break it |
| approver (98) | role, limit, approvals, approvals with findings, approvals above the limit |
| ring (7) | a connected group of vendors and approvers |

Edges: vendor *billed* invoice; invoice *violates* rule (with the finding's message); invoice *approved by* approver; vendor *shares PAN/GSTIN with* vendor; vendor or approver *member of* ring. The web page (**Knowledge graph**, tab *Audit findings
graph*) draws it in 3D (rules in the middle, approvers and vendors around them, invoices outside; vendors coloured by highest risk), answers questions, opens the neighbourhood of any invoice, vendor, approver, ring or rule (by id or name: `INV53478`,
`Frado Deep`, `g:3`, `5.1.1`), and lists every relation as a table. `GET /api/case-graph?focus=` returns nodes and edges; `GET /api/case-graph/ask?q=` returns facts and the nodes used.

**Retrieval.** `CaseGraph.query(question)` recognises invoice numbers, vendor ids and names, approver names, ring numbers, rule numbers and kinds of fraud in everyday words (mismatch, duplicate, GSTIN, split, weekend, round amount,
blacklisted, above the limit, collusion, shell vendors, registered twice), and returns up to 14 facts, each a statement computed from the graph with the numbers it rests on: an invoice (vendor, amount, score, approver with role and limit, every
finding with its message, rings), a vendor (invoices, findings, rules broken, blacklisted, shared identities, usual approvers, rings), an approver (approvals, findings, approvals above own limit, the vendors with a **tested** ring link),
a ring (per approver, its tested vendors; the rest counted), a rule (invoices, money, vendors and approvers most often), the blocked vendors, shared PAN/GSTIN pairs, the approvers with most over-limit approvals, an overview. Two choices follow from the detector: a ring fact lists, for each approver,
the vendors with a tested link and counts the hotspot-only vendors; an identity question gets identity pairs, not approver rings.

### 9.3 Ask AI and what it is given

`POST /api/copilot/ask` assembles, for a question: the policy facts `[F#]` (policy graph), **ledger facts `[C#]`** (audit graph), the **passages** of the policy (lexical, dense or hybrid search; a question may be restated by the chat model), and for a named invoice its **audit
record** (the passages of the rules its findings cite come first, and the record is the authority). The system prompt names each source, tells the model to answer ledger questions from the ledger facts, to cite each fact by label and each passage by number, never to state a name, count or
amount about the ledger that no ledger fact gives, and to say "the documents do not answer the question" only if none of the sources does. Without a model the facts and passages are returned as they are. `POST /api/copilot/data` answers a data question with one SELECT the model writes (sections D20
and R18): a single statement, an allow-list of tables, a read-only connection, a row and a time limit; the prompt lists the real values (`action_taken` is `'Approved'` or `'Escalated'`), the policy's rules, and the retrieved rows are retried once when empty.

**Retrieval stack.** `retrieval.PolicyIndex`: TF-IDF lexical ranking, dense ranking with `nomic-embed-text` (computed on request: `python -m auditiq policy embed`; in the live store used here 7 of 47 passages were embedded, so search there is mostly lexical), reciprocal-rank-fusion hybrid, and question
rewriting by the chat model. The store's knowledge base: 3 documents, 47 passages (the two SOP versions and the review procedure). Retrieval serves Ask AI and the citations, not the agents.

### 9.4 Evaluation of the audit graph (`evaluation/case_graph_eval.py`, `results/case_graph/`)

78 questions in eight types, every expected answer computed from the ledger's files (labels, vendor master, approval log, planted rings), never from the audit; a retrieval is judged on what it hands the reader; policy-only retrieval is the policy graph plus the ranker over the policy documents.

| Type (questions) | Audit graph right | Policy-only right |
|---|---|---|
| why was INV... flagged: the rules equal the labelled rules (20) | 20 | 0 |
| how many invoices of vendor X have findings (14) | 14 | 0 |
| how many approvals above own limit did approver X make (14) | 14 | 0 |
| how many invoices break rule R, 6 of them in everyday words (18) | 18 | 0 |
| which approvers are in collusion rings (2); which vendors are in the ring around X (6); which share a PAN (2); which blacklisted vendors billed most (2) | 12 | 0 |

Recall is 1.00 on the four set types; precision is 1.00 for rings, ring members and shared PAN and 0.56 for blocked vendors (nine names given where the five largest were asked for). **Read with care:** (1) it measures that retrieval returns what the audit stored, not
that the audit detects fraud (section 8.4); (2) policy-only retrieval scores 0 by construction; (3) the recognisers were built on six questions, and the 66 invoice, vendor, approver and rule questions (other entities drawn by `--seed`) were right on the first run; (4) **the ten ring-type questions are not held out**:
the first run was 78 of 78 but with precision 0.16 (54 vendors named where 4.2 were planted) for ring members and 0.07 (107 named where 8) for shared PAN, so the retrieval was changed (identity apart from collusion; tested links as a ring's core; each approver's vendors attributed to the approver) and the same questions rerun (first
run kept in `results/case_graph/first_run/`); (5) a hidden control character in a regular expression had silently disabled the ring path in intermediate runs: fixed, and the final run is on the corrected code.

### 9.5 Ask AI with the local model (checked, not an evaluation)

With Qwen2.5-7B on the CPU (2 to 5 minutes per answer): *"Why was this invoice flagged, and what should the reviewer do?"* (INV53478) gave a grounded answer with every number right (10.37% over the PO, 4 billed against 3 received, the two GSTINs, the Manager's limit of 100,000) and the right corrective actions.
*"Which vendors share the same PAN?"* named all four planted pairs with the right vendor ids. *"Which vendors are in collusion rings and who approves their invoices?"* named the ring of each approver with its vendors and marked the two shared-identity rings as having no approver, but merged the vendors of one ring's four approvers under all
four names and left two of seven rings out. Data questions through the checked SQL: blacklisted vendors 66 invoices (INR 8,534,745.19); the five approvers with most approvals above their own limit: Frado Deep 75, Qasim Pandey 50, Ubika Gour 49, Orinder Merchant 46, Meera Kapoor 45 (four of the five are planted-ring approvers);
vendors with most GSTIN mismatches: Saran Group 10. The exact facts are the reliable part; a 7B model can garble a long multi-approver fact.

## 10. The demonstration policies

**Purpose.** To show that **the audit follows the document**: the same ledger, the same code, a different policy uploaded, a different result. `auditiq/policy_demo.py` defines five company policies and renders each as a PDF in `policy/demo/` from the policy template with the scenario's thresholds **and
rule severities** (severity re-weighting changes scores and review workload without changing which invoices are found). Each takes effect on 2025-04-01, so the policy chosen governs the whole financial year of the ledger. `evaluation/policy_demo.py` reads each PDF back as the system does on upload, audits the 25,000
invoices with the controls under it, compares with the answer key and with the baseline, and writes `results/policy_demo/` and `docs/POLICY_DEMO.md`.

| Policy (file) | Story | What it changes from v2.5 |
|---|---|---|
| **Lean Growth** v5.01 (`Lean_Growth_v5.01.pdf`) | a fast-growing distributor takes the friction out | tolerance 1% to 3%; daily invoices per vendor 3 to 5; non-business days Saturday and Sunday to Sunday only; round-amount multiple 10,000 to 50,000; limits Manager 250,000, Senior Manager 1,000,000, Director 5,000,000, CFO 20,000,000; rule 4.2.1 severity medium to low |
| **Strict Controls** v5.02 | a company defrauded through invoices just under its limits tightens everything | tolerance 0.5%; daily count 2; round multiple 5,000; limits Manager 90,000, Senior Manager 450,000, Director 2,250,000, CFO 9,000,000; severities: 4.2.1 high, 4.3.1 medium, 3.1.1 and 3.1.2 high |
| **Tax Compliance First** v5.03 | ahead of a GST audit: a wrong GSTIN cannot support an input-tax-credit claim | thresholds unchanged; severities 3.1.1, 3.1.2, 3.1.3 and 2.1.1 critical |
| **Manufacturing Plant** v5.04 | a six-day plant with larger lots | tolerance 2%; daily count 4; Sunday only non-business; limits Manager 150,000, Senior Manager 750,000, Director 3,750,000, CFO 15,000,000 |
| **Fraud Prevention** v5.05 | Internal Audit re-ranks rules by how a fraud looks | thresholds unchanged; severities 2.1.1, 2.1.2, 2.1.3, 4.1.1 critical; 4.2.1 high; 4.3.1 medium; 3.1.1 and 3.1.2 low |
| **Draft_Incomplete** v5.99 | a half-finished document | leaves out Rule 4.4.1 and the table of approval limits: **refused** with "Rule 4.4.1 (blocked vendor) is not in the document; the system needs every rule it executes to be stated" and "Rule 5.1.1: no table of approval limits by role was found" |

**Measured effect on `final_seed_2025`** (controls, configuration C1; `results/policy_demo/policy_demo.md`):

| Policy | Invoices with findings | Held for review | Money held | Critical | High | Medium | Distinct scores |
|---|---|---|---|---|---|---|---|
| Baseline v2.5 | 1,835 | 1,658 | INR 76.2 crore | 868 | 790 | 143 | 8 |
| Lean Growth | 1,295 | 1,157 | 30.4 | 387 | 770 | 109 | 7 |
| Strict Controls | 3,297 | 3,263 | 117.9 | 2,096 | 1,167 | 34 | 6 |
| Tax Compliance First | 1,835 | 1,754 | 77.4 | 1,440 | 314 | 47 | 8 |
| Manufacturing Plant | 1,530 | 1,369 | 53.7 | 649 | 720 | 124 | 8 |
| Fraud Prevention | 1,835 | 1,705 | 77.1 | 1,455 | 250 | 34 | 7 |

Against the baseline, invoice by invoice: **Lean** moves 715 decisions (540 baseline frauds fall inside the wider limits and are no longer raised; 501 invoices go from escalate to approve; no invoice newly flagged). **Strict** moves 1,524 (1,462 newly flagged; 1,605 go from approve to
escalate; 1,348 invoices the baseline accepts are now raised and held). **Tax Compliance First** moves no decision but 663 scores rise and 96 invoices go from approve to escalate (the medium-severity GSTIN-format findings become critical). **Manufacturing** moves 395 (305 cleared, 289 escalate to approve; the Saturday
invoices stop being exceptions). **Fraud Prevention** moves no decision but 744 scores rise, 96 fall, and 47 invoices go from approve to escalate. Findings of rule 5.1.1: 601 (baseline), 111 (Lean), 1,835 (Strict), 377 (Manufacturing); of 4.1.1: 141, 0, 414, 5.

**One invoice, five verdicts.** `INV43977` (INR 640,000) breaks 2.1.2, 3.1.3, 4.3.1 and 5.1.1 under the baseline and scores 75 (CRITICAL); under Lean it breaks only 2.1.2 and 3.1.3 and scores 50 (HIGH); Strict 80; Tax Compliance First 85; Manufacturing breaks 2.1.2, 3.1.3, 4.3.1 and scores 50;
Fraud Prevention 90. All route to escalate.

**The real flow reproduced the offline numbers.** On a copy of the 25,000-invoice store, uploading each PDF, previewing, simulating, adopting with activation and applying (re-audit) through the REST API gave held-for-review counts of 1,705 (Fraud Prevention), 1,157 (Lean), 1,369 (Manufacturing), 3,263 (Strict)
and 1,754 (Tax Compliance First), with identical risk-level counts, and refused the incomplete draft with the two reasons. The simulate step compares against the policy in force at that moment; activate the baseline (v2.5) and apply it between demonstrations to read numbers against it.

**Caution.** The answer key is written for the baseline: under another policy, a baseline fraud inside the new limits is not an exception of that company, and an invoice the baseline accepts may break the new rules; the tables say what a policy hides or adds, not which policy is right. The judgement rules need a model and are not in these figures.


---

# Part VI. Evidence and honesty

## 11. What has been measured

Every result below was produced by a script of the repository on the data stated (labels: **Measured**, **Pilot** or **sample**). The full list with commands and source files is `RESULTS.md` (and, machine-readable, `auditiq/results/results.json`);
`REPORT.md` is the generated full report (methodology, every result, threats to validity).

### 11.1 The results at a glance

| # | Question | Result | Kind |
|---|---|---|---|
| 1 | Are thresholds read correctly from a policy document? | 14 hand-written documents: 196 of 196 values and 224 of 224 rules. 20 held-out random documents: 280 of 280 values, 320 of 320 rules | Measured |
| 2 | Does the audit follow the policy in force? | 0 wrong decisions in 560,000 audits (14 documents) and in 800,000 (20 held-out) | Measured |
| 3 | How wrong is a system whose thresholds are not updated? | up to 30.7% of 40,000 invoices decided against the policy in force (strict policy); up to 19.9% on the held-out documents | Measured |
| 4 | Does the reader refuse what it cannot execute? | 16 edited documents: 7 of 7 harmless edits read correctly, 9 of 9 defective or ambiguous documents refused with the reason | Measured |
| 5 | What does a policy change do in the application? | strict policy on 20,000 invoices: findings 300 to 6,546; invoices waiting for review 240 to 6,353; no code edited | Measured |
| 6 | Controls against anomaly detectors | F1 0.833 at precision 1.000 against 0.536 (isolation forest) and 0.498 (one-class SVM); false positives on hard negatives 0.000 against 0.403 and 0.481 | Measured |
| 7 | And at a realistic anomaly rate (2.1%)? | F1 0.833 against 0.211 and 0.429 | Measured |
| 8 | How fast is the control stage? | about 18 microseconds per invoice on 5,000 to 40,000 invoices; 18.4 microseconds on 500,000 with the vendor index (31.7 before it); 172,226 invoices per second with 8 processes (speed-up 3.04) | Measured |
| 9 | Can a model read a policy in its own words? | 6 documents, 84 values: 80 proposed correctly; code verified 56, held back 24 right ones, caught 2 wrong ones, passed 2 | Measured (one 7B model) |
| 10 | How do the language-model stages do? | 90-invoice sample of ledger 202: the agents (C3) found 34 of 60 judgement anomalies (0.567); 0.493 of their findings name a violated rule (0.600 with the challenger); the single prompt (C2) flagged 9 of 10 ordinary invoices and 0.030 of its findings name a violated rule. C3 is better than C2 (37 invoices right only under C3, 1 only under C2; Holm-adjusted p < 0.001); the challenger's gain is not significant; 3 to 5 model calls per invoice | Sample |
| 11 | Does policy search find the right passage? | hybrid ranking after question rewriting: rank-1 0.625 and top-3 0.938 on held-out paraphrases (16 questions) | Measured (small) |
| 12 | What does the deployed system produce on each ledger? | each benchmark ledger loaded from an Excel workbook and audited through the store: 300 findings, every rule-defined anomaly found, 240 invoices escalated, no finding on any hard negative or ordinary invoice | Measured |
| 13 | Do the results hold at 500,000 invoices? | controls F1 0.833 at precision 1.000 against 0.192 and 0.431; 0 wrong decisions in 7,000,000 audits under 14 policy documents (a frozen system: up to 31.2% against the policy in force); the deployed path loads the ledger in 36 s and audits and stores every invoice in 708 s; every web page answers within 5.5 s | Measured |
| 14 | Does the system make the revisions the findings require? (AuditBench) | 1,200 control findings on four ledgers, every one with a computed revision; 600 of 600 amendments and re-approvals resolve their finding | Measured |
| 15 | Can a policy be evaluated before adoption? (Liu et al.) | the dry run of the strict policy predicts 6,353 invoices for review, the number its adoption produces | Measured |
| 16 | Does a ledger streamed through Kafka give the batch audit's findings? | 5,000 invoices, 250 vendors, 2,105 e-mails through four topics: every invoice has the batch audit's findings (F1 0.833) on SQLite and PostgreSQL with 1, 2 or 4 workers; on PostgreSQL 4 workers finish in 18.04 s against 27.2 s for one | Measured |
| 17 | Does a policy knowledge graph give a model what questions that join facts need? | 23 held-out questions: evidence complete for 22 with graph + lexical, 21 with the graph alone, at most 13 for a passage ranker; derived answer stated for 17 of 19 | Measured (small; authors' questions) |
| 18 | Does the audit send the right invoices to a person? | 5,000-invoice demonstration store: 281 (5.6%) sent to a person, 97.2% anomalous, 0 clean; 500,000-invoice ledger: 160,068 (32.0%, 4.7% anomalous) under a later policy applied to everything, 5,712 (1.1%, 100.0% anomalous) with each invoice under the version in force on its date | Measured |
| 19 | The final ledger audited through Kafka | 25,000 invoices in 209 s after publishing: 1,658 sent to a person, 868 critical, 790 high, 143 medium; rule-decided clauses precision and recall 100%, 0 false alarms on 22,425 clean and 300 hard negatives, 10 of 10 planted rings recovered; **scores cluster** (section 8.4) | Measured |
| 20 | Do the demonstration policies change the output? | held for review 1,658 (baseline), 1,157, 3,263, 1,754, 1,369, 1,705 under the five policies; the real upload-adopt-apply flow reproduced the offline numbers | Measured |
| 21 | Does the audit graph return what the audit stored? | 78 of 78 questions right (policy-only retrieval 0); ten ring questions not held out | Measured (small; computed answers) |

### 11.2 The language-model pilots (20 invoices, `results/pilot_seed_909/pilot20.md`; Pilot)

Qwen2.5-7B at a 12,288-token context on the laptop's CPU (about 5.5 minutes per call). Twenty invoices (one of each of the 14 classes, the five hard-negative types, one ordinary invoice) are a pilot: intervals are wide and no McNemar comparison is
significant (C3 against C2: 9 invoices right only under C3, 2 only under C2, Holm-adjusted p = 0.196).

| | C1 | C2 | C3 | C4 | C5 |
|---|---|---|---|---|---|
| Invoice-level recall | 0.714 | 0.929 | 0.929 | 0.857 | 0.857 |
| Invoice-level precision | 1.000 | 0.722 | 0.812 | 0.800 | 0.800 |
| Judgement classes found (of 4) | 0 | 1 | 2 | 1 | 1 |
| Hard negatives flagged (of 5) | 0 | 4 | 3 | 3 | 3 |
| Ordinary invoice flagged (of 1) | 0 | 1 | 0 | 0 | 0 |
| Citation correctness | 1.000 | 0.091 | 0.500 | 0.688 | 0.688 |
| Model calls per invoice | 0 | 1.15 | 3.00 | 3.60 | 4.95 |
| Tokens per invoice | 0 | 5,835 | 9,557 | 12,005 | 16,779 |

What it shows: the controls decided every rule-defined class right and nothing else; the agents found J4 and J1, missed J2, cited the wrong rule on J3, and raised wrong near-duplicate findings on hard negatives; the challenger removed most extra findings but also one right one;
confidence demoted one wrong finding and not the others ("it measures support and stability, not correctness"); the single prompt flagged 18 of 20 invoices. The 34-invoice sample of ledger 101 (5 of each judgement class, 2 of each hard-negative type, 4 ordinary) agrees: C3 found 12 of 20 judgement anomalies and
0.375 of its findings named a violated rule, C2 4 and 0.031; nothing significant.

### 11.3 What has not been measured

- **The language-model configurations (C2 to C5) on whole benchmark ledgers.** Only samples of 20, 34 and 90 invoices exist; the full protocol (about 1,200 invoices per ledger, several calls each, three seeds, a second model, a consistency subset) needs a GPU or a hosted endpoint, and the exact commands are ready (`python -m evaluation.run_full`; `RESULTS.md` section 10.1). Expected values for it are in
  the paper, labelled expected.
- **Detection on real data.** Everything is synthetic.
- **The judgement rules on the final ledger.** The controls-only audit does not check them (440 anomalies "not checked").
- **A second model**, and the audit graph's Ask AI answers beyond the checked questions of section 9.5.
- **The held-out collusion ledger** (`collusion_seed_808`) has not been generated.

## 12. Limits, open decisions and the questions people ask

### 12.1 Limits (what a reader must not over-claim)

1. **The data is synthetic and the rule-defined results are circular.** The controls and the generator implement the same written rules by separate code; 100% on R1 to R10 shows they agree. Informative numbers are J1 to J4, hard negatives, citations, routing and the comparison with detectors.
2. **Scores are lumpy.** The policy score is a sum of weights with floors, so a flagged invoice with one finding scores 70, 50, 10 or 5. On the final ledger 23,165 invoices score 0 and, of the 1,835 flagged, 852 score 70 and 780 score 50. A histogram shows spikes. This is the model of the paper, not a bug, but it is what a viewer sees first.
3. **Fraud is spread evenly.** In the final ledger the flagged rate is 6.7% to 8.2% per month and 7.0% to 7.7% per category, and 765 of 1,250 vendors have a flagged invoice (the top 10% of vendors hold 44.3% of the flagged invoices; 74 vendors have five or more). Real fraud concentrates in repeat offenders and seasons, so the analytics board looks flatter than a real one would; the planted rings and
   the planted over-limit approvers are the visible concentration.
4. **A controls-only audit cannot see four rules** (2.1.4, 2.1.5, 2.2.2, 4.1.2); the application says so ("not checked") instead of reading an approval as clean.
5. **Confidence measures support and stability, not correctness.** A model that is consistently wrong passes (observed twice).
6. **One model measured, on samples.** Qwen2.5-7B; findings from samples must be written as sample results. A 7B model on a CPU is slow (2 to 5 minutes per answer) and can garble a long fact.
7. **Policy reading is by pattern.** A document must state its rules in the SOP template's wording; free prose needs the model reading step with a person's confirmation.
8. **J1 is decidable from fields as generated** (an invoice that is not the first on its PO is a duplicate), so it does not test judgement; reclassifying it as a control would change every table.
9. **Rings are leads.** The detector's rings are widened by the hotspot link; the audit graph names the tested links.
10. **Kafka is one local node on Windows**; the compose file and the container image are proven only by CI (the development machine has no Docker).
11. **No rate limit or body limit in the server** (the reverse proxy's job); type checking is not in CI (the checker reports optional values and loosely typed dictionaries that the code checks before use: 49 reports in the October review, none reachable as a crash; the development machine also lacks the pandas stubs).
12. **Local browser tests time out on battery** (CPU throttled); CI is the authority for the end-to-end tests.
13. **The Review-1 deck's other items are not built**: an e-mail triage agent (e-mails are stored and linked, not judged), a FinBERT invoice classifier, a gradient-boosted vendor risk scorer, a compliance agent with retrieval, an orchestrator that fuses agent outputs with agreement-based routing, ISA 230 predicates, a hash-chained audit log, OCR of scanned invoices, and audit-cycle-time
    measurement (`PLAN.md` C28).
14. **The base papers were described from abstracts**; their full texts are behind a publisher paywall and have to be read through a library. The two papers of the project: a 13-page IEEE-format paper (`paper/auditiq_paper.tex`, three authors listed) and a 6-page conference version (`paper/conference/main.tex`, four authors).

### 12.2 Open decisions (not taken; each changes something)

| Decision | Options | Consequence |
|---|---|---|
| A **continuous, magnitude-aware risk index** beside the paper's score | add it (a separate field shown next to the score, leaving routes and results untouched) or keep the paper's score only | would give the dashboard a spread of values that reflect the money and the size of a deviation; changes the user interface and adds a model element that the paper does not describe |
| Route medium and low findings to sampled review | change equation (5) or keep | today a medium or low finding alone is approved with the finding recorded (177 on the final ledger); changing it changes the paper's routing |
| Make the final ledger's fraud concentrated | add repeat offenders, seasonal peaks, category skew | the analytics board would look like a real one; changes the dataset and its hashes |
| A control for 2.2.2 (J1) | reclassify J1 as rule-defined | changes every result table |
| Which model runs C2 to C5 at scale | GPU or hosted endpoint | the full benchmark runs; command ready |
| Generate `collusion_seed_808` | yes or no | a held-out ledger for the ring detector's reported results |
| Rotate the hackathon prototype's database password | the team does it in the old provider's console | removes the only known credential exposure (not in the repository) |

### 12.3 The questions people ask, with the answers

**Why did every record show the same score (75), and is it fixed?** No code sets 75. Old demonstration data had one violation per fraudulent invoice, and the scoring floors turn one critical finding into 70, one high into 50, so flagged scores sat on 70/50/10/5 (75 arises when 2.1.2, 3.1.3, 4.3.1 and 5.1.1 fire together). The final ledger adds compound frauds, so scores up to 90 occur
and the review queue's top shows 90, 80, 70. It is **not fixed**: the scores still cluster at 50 and 70 (section 8.4). The decision on a continuous index is open (section 12.2).

**Is 100% precision and recall real?** On the twelve rule-decided clauses of this synthetic ledger, yes, and it is expected: the controls and the generator are separate implementations of the same written rules (a correctness check). It says nothing about real data or about the four judgement rules (0 found by controls alone; 440 anomalies "not checked").

**What is a collusion ring, and how sure is it?** A connected group of vendors and approvers tied by a shared PAN or GSTIN, or by approvals with more high or critical findings than the approver's role makes likely (a binomial test per role, Benjamini-Hochberg at a 1% false discovery rate). It is a lead for an
investigation, not a finding. On the final ledger the detector recovered 10 of 10 planted rings and its tested links matched the six approver rings exactly.

**Why a knowledge graph built by code and not a graph database or a model-extracted graph?** The facts are already stored exactly in tables; a model-extracted graph could add relations the policy does not state; a graph database would be one more server for a few thousand nodes. The graphs are derived on request and cached until the store changes.

**Why Kafka for a 25,000-invoice ledger?** A ledger loaded in one go does not need it. Kafka was added to match the Review-1 architecture and to show the streaming path: each message stored exactly once (offsets in the same database transaction), an invoice audited against the invoices that arrived before it, same-day splits audited again when completed. Measured: the stream ends with the batch
audit's findings.

**Why is the data synthetic, and can I use my own ledger?** Real labelled procurement data was not available, and accuracy cannot be measured without labels. You can load your own ledger (a folder, a zip or an Excel workbook with one sheet per table); it is checked first and the audit runs on it; there is no answer key for it.

**How do I change a threshold?** Change the policy document (or the registry) and upload it: the system reads it, shows what changed, can simulate the effect without storing anything, and applies it from its effective date. No code changes. To add a control, an endpoint, a page or a table, see `docs/DEVELOPER.md` and sections R9, R20, R21, R15.

**What do the five policies demonstrate?** That the same ledger gives a different audit when only the document changes (section 10), and that an incomplete policy is refused.

**Is it production-ready?** No. It is a research system with a complete audit pipeline, tests and measured results on synthetic data. Gaps to an industry-grade system include: results on real data, the language-model configurations measured at scale, concentrated and seasonal fraud in the demonstration data, a continuous risk index, monitoring and alerting, a rate limit and request limits in front of the server, a
multi-node Kafka and PostgreSQL deployment proven outside CI, single sign-on, a type-checked codebase in CI, and the Review-1 deck's remaining agents.

## 13. The repository and its documents

### 13.1 Layout (`pp1/` is the git root)

```
pp1/
  README.md             overview of the repository
  ARCHITECTURE.md       this file
  RESULTS.md            every measured result, with source file and command (the paper's source document)
  REPORT.md             full methodology and results report, generated by evaluation/full_report.py
  paper/                LaTeX papers (13-page IEEE version; 6-page conference version)
  AuditIQ-DeloitteHacksplosion-main/   the Flowise export of the hackathon prototype (reference only; excluded from git)
  .github/workflows/ci.yml             five CI jobs
  auditiq/              the project (commands run from here)
    start.bat           the one-file launcher (calls scripts/live.py)
    auditiq/            the application package (41 files); imports nothing from auditiq_bench
    auditiq_bench/      the dataset generator and validator; imports nothing from auditiq
    evaluation/         baselines, runners, metrics, statistics, reports, verification, graph evaluations
    frontend/           React + TypeScript + React Three Fiber web application (src/pages: 15 pages)
    app/dashboard.py    the Streamlit dashboard
    policy/             clause registry JSON, SOP templates, SOP text, sample PDFs, variants, held-out variants, demo/ (the five policies)
    data/               eight committed datasets (CSV, labels, manifests, datasheets)
    results/            measured results (json + md per experiment), results.json, final_seed_2025/, policy_demo/, case_graph/
    scripts/            live.py, kafka_local.py, pg_local.py, e2e_server.py, reproduce.py
    deploy/             docker-compose.yml, postgres/, ollama/Modelfile
    tests/              the Python tests (27 files)
    docs/               the documents below
    exports/            a CSV snapshot of every table of an audited store
    Dockerfile, pyproject.toml, .env.example, README.md, PLAN.md
    .auditiq/           local state, not versioned
```

### 13.2 The documents (`auditiq/docs/`, plus the root files)

| Document | Content | Kept current by |
|---|---|---|
| `ARCHITECTURE.md` (root, this file) | context, decisions, data, errors, analytics, graphs, demo policies, evidence, and the technical reference | hand |
| `docs/ARCHITECTURE.md` | the earlier, shorter design document (principles, pipeline, agents, scoring, storage) | hand |
| `docs/DEVELOPER.md` | for changing the code: the map of every module, contracts, how to add a control, endpoint, page, table | hand |
| `docs/API.md` | every endpoint: parameters, body, role, answers | generated (`python -m auditiq.apidoc`); a test checks it |
| `docs/DATA_DICTIONARY.md` | every table and column with types on both backends and who reads it | generated (`auditiq/datadict.py`); a test checks it |
| `docs/DATASETS.md` | the eight datasets, how a ledger is built, how each anomaly is injected, limits | generated (`python -m auditiq_bench.overview`) |
| `docs/ANALYTICS.md` | coverage, forensic analytics, collusion rings and their tests | hand |
| `docs/POLICY_GRAPH.md`, `docs/CASE_GRAPH.md` | the two knowledge graphs, retrieval, evaluations | hand |
| `docs/POLICY_DEMO.md` | the demonstration policies, the steps, the measured numbers | generated (`python -m evaluation.policy_demo`) |
| `docs/STREAMING.md` | Kafka ingestion: topics, workers, exactly-once, e-mails, running, measurements | hand |
| `docs/WEB.md` | the REST API and web application: running, security, pages, 3D views, tests | hand |
| `docs/OPERATIONS.md` | install, configure, run, reproduce the evaluation, troubleshoot | hand |
| `docs/SECURITY.md` | what is protected and how, the copilot's SQL guards, a deployment checklist | hand |
| `docs/CODE_REVIEW.md` | the code review and the 27 findings with their fixes | hand |
| `docs/BASE_PAPERS.md` | each element of the two base papers and where the code implements it | hand |
| `docs/FEATURE_POLICY_AS_DATA.md` | the measured feature written up for the paper | hand |
| `PLAN.md` | what is built, decisions taken while building, what is open | hand |
| `../RESULTS.md`, `../REPORT.md`, `results/results.json` | every result; the full report; the machine-readable results | scripts (`evaluation.full_report`, `evaluation.collect_results`); tests check they are current |

### 13.3 CI (`.github/workflows/ci.yml`, on every push)

Five jobs: `test` (ruff, pytest on SQLite and PostgreSQL 17, a Kafka service container, `pip-audit`), `frontend` (lint, typecheck, test, build, `npm audit --omit=dev`), `e2e` (Playwright in Chromium against the real server), `compose` (PostgreSQL from the compose file, every test against it,
a ledger audited in it) and `container` (the image built and run). The CI database password `ci-only` is a placeholder for the throwaway service container.

---

# Part VII. The technical reference (sections R1 to R33)

This part is the complete engineering description: every module, formula, threshold, prompt, table, endpoint and test, written for a person or a model that has to **rebuild
the system** (section R33 gives the order of work, with a check for each step). It was written between 30 October and 4 November 2026 from the code, and on 14 November it was
checked against the code, with these differences patched in (each patch is marked "updated 14 November" or "since 14 November" where it is not obvious):

- the repository layout (`analytics.py`, `rings.py`, `policy_graph.py`, `case_graph.py`, `policy_demo.py`, `scripts/live.py`, `start.bat`);
- the copilot's prompt and its data-question handling (R18.2), now with the ledger facts as a named source and a retry of an empty result;
- the endpoints (40, with the two audit-graph endpoints) and the cache sentence (R20.5);
- the web pages (the five console pages and the two tabs of `/graph`; R21.2);
- the benchmark: the two collusion profiles and the final profile, the evaluation-subset sizes, compound frauds (R24);
- the test count and the test files added since (R28).

Section numbers in this part carry the prefix **R** so that they do not clash with sections 1 to 13 above; a reference such as "Section 24" in the text below means R24. The reference
describes the system **as built**; the reasons for the design are in section 4, the data in sections 6 and 7, and what was measured in section 11. Where this part and the code disagree, the code is right.

**Contents of the reference**

- [R1. What AuditIQ is](#r1-what-auditiq-is)
- [R2. Design principles](#r2-design-principles)
- [R3. The system at a glance](#r3-the-system-at-a-glance)
- [R4. Technology stack](#r4-technology-stack)
- [R5. Repository layout](#r5-repository-layout)
- [R6. The data: the ledger and the transaction](#r6-the-data-the-ledger-and-the-transaction)
- [R7. The policy: clause registry, text and versions](#r7-the-policy-clause-registry-text-and-versions)
- [R8. Evidence extraction and the vendor history](#r8-evidence-extraction-and-the-vendor-history)
- [R9. The twelve deterministic controls](#r9-the-twelve-deterministic-controls)
- [R10. The model client](#r10-the-model-client)
- [R11. The agents, the single auditor and the challenger](#r11-the-agents-the-single-auditor-and-the-challenger)
- [R12. The pipeline graph and the five configurations](#r12-the-pipeline-graph-and-the-five-configurations)
- [R13. Confidence, risk scores and routing](#r13-confidence-risk-scores-and-routing)
- [R14. The audit pack and the revisions](#r14-the-audit-pack-and-the-revisions)
- [R15. Storage: the database layer and the schema](#r15-storage-the-database-layer-and-the-schema)
- [R16. The batch audit service](#r16-the-batch-audit-service)
- [R17. Policy documents](#r17-policy-documents)
- [R18. Policy search and the copilot](#r18-policy-search-and-the-copilot)
- [R19. Kafka ingestion](#r19-kafka-ingestion)
- [R20. The REST API](#r20-the-rest-api)
- [R21. The web application](#r21-the-web-application)
- [R22. The Streamlit dashboard](#r22-the-streamlit-dashboard)
- [R23. The command line](#r23-the-command-line)
- [R24. The benchmark: AuditIQ-Bench](#r24-the-benchmark-auditiq-bench)
- [R25. The evaluation harness](#r25-the-evaluation-harness)
- [R26. Configuration: every environment variable](#r26-configuration-every-environment-variable)
- [R27. Deployment and local servers](#r27-deployment-and-local-servers)
- [R28. Tests and continuous integration](#r28-tests-and-continuous-integration)
- [R29. Security model](#r29-security-model)
- [R30. What has been measured](#r30-what-has-been-measured)
- [R31. Limits and open items](#r31-limits-and-open-items)
- [R32. Glossary](#r32-glossary)
- [R33. Rebuilding it: the order of work](#r33-rebuilding-it-the-order-of-work)

## R1. What AuditIQ is

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

## R2. Design principles

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

## R3. The system at a glance

### R3.1 Components

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

### R3.2 What happens to one invoice

1. **Extraction** gathers the invoice, its PO, its GRN, its vendor, its approval log entries and the vendor's other
   invoices into one *transaction* (Section R6.3).
2. **Controls** run twelve deterministic checks against the active policy's registry (Section R9).
3. **Agents** (if the configuration has them) each make one model call about the judgement clauses of their
   remit (Section R11).
4. The **challenger** (if configured) makes one model call that tests each agent finding and keeps or removes it.
5. **Confidence** (if configured): each kept agent finding gets grounding *g*, clause validity *p* and agreement *a*
   from 3 re-runs; confidence *c* = (*g* + *p* + *a*)/3 (Section R13).
6. **Scoring**: two risk scores, R0 (count-based) and Rc (confidence-weighted), and a route.
7. **Human review**: an escalated invoice waits in the review queue (or pauses the graph in interactive use).
8. **Audit pack**: code assembles the record of the result; no model writes it.
9. **Storage**: one row in `audit_results`, its findings in `audit_flags`, its steps in `audit_trail`.

### R3.3 Data flows

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

## R4. Technology stack

### R4.1 Backend (Python)

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

### R4.2 Frontend (TypeScript)

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

### R4.3 Services and infrastructure

| Service | Version | Role |
|---|---|---|
| SQLite | bundled with Python | default store (one file, `.auditiq/auditiq.db`) |
| PostgreSQL | 17 | production store; parallel stream workers |
| Apache Kafka | 4.3.2, KRaft mode, one node | ingestion topics |
| Ollama | any recent | serves the local models over an OpenAI-compatible API |
| Chat model | `qwen2.5:7b-ctx12k` (Qwen 2.5 7B with a 12,288-token context, from `deploy/ollama/Modelfile`) | agents, challenger, copilot, policy reading |
| Embedding model | `nomic-embed-text` (with prefixes `search_query: ` / `search_document: `) | dense policy search |
| Docker / Compose | | container image; app + PostgreSQL + Kafka + workers |
| GitHub Actions | | CI: five jobs (Section R28) |

The development machine is a laptop (Intel Core i5-1235U, 12 logical CPUs, 16 GB RAM, no discrete GPU). A 7B model
on its CPU takes minutes per call; a second Ollama server on the integrated GPU
(`OLLAMA_HOST=127.0.0.1:11435 OLLAMA_IGPU_ENABLE=1`, Vulkan) is about 6 to 8 times faster at prompt processing.

---

## R5. Repository layout

The git repository root is `pp1/`. The project is `pp1/auditiq/`; commands run from there.

```
pp1/
  RESULTS.md            every measured result, with source file and command (the paper's source)
  REPORT.md             full methodology and results report, generated by evaluation/full_report.py
  ARCHITECTURE.md       the architecture document of 14 November (the file that contains this reference)
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
      analytics.py      coverage of the results, answer key, forensic analytics (Benford, limits, concentration, approvers)
      rings.py          collusion rings: identity links, role-relative binomial tests with Benjamini-Hochberg, watch list
      policy_graph.py   the policy as a knowledge graph built by code; facts for Ask AI ([F#])
      case_graph.py     the audited ledger as a knowledge graph (vendors, invoices, rules, approvers, rings); facts ([C#])
      policy_demo.py    the five demonstration policies as PDFs and the incomplete draft
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
    evaluation/         baselines, runners, metrics, statistics, reports (Section R25)
    app/dashboard.py    Streamlit dashboard
    frontend/           React application (Section R21)
    policy/             policy_v2.5.json, policy_v2.6.json, SOP_template.md, SOP_v2.x.md, build_policy.py,
                        pdf/ (rendered PDFs), variants/ and variants_heldout/ (evaluation policies), freeform/,
                        robustness/
    data/               eight datasets (Section R24)
    results/            measured results (json + md per experiment), results.json
    scripts/            live.py (the launcher behind start.bat), pg_local.py, kafka_local.py, e2e_server.py, reproduce.py
    start.bat           one file: broker, store, workers, web application, publish through Kafka (see section 5.2 above)
    deploy/             docker-compose.yml, postgres/ (compose + init.sql), ollama/Modelfile
    tests/              Python tests (Section R28)
    docs/               ARCHITECTURE, DEVELOPER, API (generated), DATA_DICTIONARY (generated), DATASETS
                        (generated), OPERATIONS, SECURITY, WEB, STREAMING, CODE_REVIEW, BASE_PAPERS,
                        FEATURE_POLICY_AS_DATA
    Dockerfile, pyproject.toml, .env.example, README.md, PLAN.md
    .auditiq/           local state, not versioned: auditiq.db, llm_cache.sqlite, uploads/
```

---

## R6. The data: the ledger and the transaction

### R6.1 The five ledger tables

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

### R6.2 Field lists the pipeline reads (`extraction.py`)

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

### R6.3 The transaction

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
and name of its last `Approved` entry. It is a `History` object (Section R8.2).

---

## R7. The policy: clause registry, text and versions

### R7.1 The clause registry

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

### R7.2 The policy text

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

The rule lines of the template (the compiler in Section R17.3 reads thresholds back out of these sentences):

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

### R7.3 The `Policy` object

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

## R8. Evidence extraction and the vendor history

### R8.1 Three ways to build transactions

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

### R8.2 `History` and `VendorIndex` (`history.py`)

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

## R9. The twelve deterministic controls

`controls.py`. Each control is a pure function `control(txn, clauses) -> list[flag]`, where `clauses` is the
registry's `clauses` map. A control whose clause is not in the policy returns nothing (so removing a clause from
the registry switches the control off). No threshold is written in the file.

### R9.1 The flag

```python
{"clause": "2.1.1", "control": "amount_match", "severity": clauses["2.1.1"]["severity"],
 "source": "D", "confidence": 1.0,
 "evidence": [{"field": "invoice.amount", "value": 101500.0}, {"field": "po.amount", "value": 100000.0}],
 "message": "Invoice amount 101500.00 differs from PO amount 100000.00 by 1.50% (tolerance 1%)."}
```

`source` is `D` (deterministic) for a control and `L` for a model. Amounts are compared in **paise** (integer
hundredths: `paise(x) = int(round(float(x) * 100))`) so the arithmetic is exact.

### R9.2 The controls, in the order they run

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

## R10. The model client

`llm.py`. One client for any server that implements `POST {base_url}/chat/completions` in the OpenAI format: a
local Ollama (`http://localhost:11434/v1`), vLLM, a LiteLLM gateway, or a hosted provider. Nothing else in the
system knows which.

### R10.1 Settings (`LLMSettings.from_env`)

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

### R10.2 A request

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

### R10.3 Reading JSON from a reply

`extract_json(text)` removes `<think>...</think>` blocks, then tries `json.JSONDecoder().raw_decode` at every `{`
until one decodes to a dict. So code fences and prose around the object are tolerated. No object raises
`ValueError`.

### R10.4 Determinism

Decisions are requested at temperature 0 with `seed` = sample number 0. The agreement re-runs use temperature 0.7
and samples 1, 2, 3, so each has a different cache key.

`ScriptedClient(responder)` is a test double that returns scripted text; it is never used to produce a result.

---

## R11. The agents, the single auditor and the challenger

`agents.py` and `prompts.py`.

### R11.1 The specialist agents

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

### R11.2 Records as text (`render_records`)

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

### R11.3 Bounded vendor history (`select_history`, cap 40)

Below 41 invoices, an agent sees all of them. Above, it sees the 40 that a fixed rule ranks first, re-sorted oldest
first, and the heading says "the 40 most relevant of N":

- **duplicates**: rank key `(not same_document, amount != invoice.amount, -similarity, day_gap, invoice_id)` where
  `same_document` = same `po_id` or `grn_id` as the invoice, `similarity` = `difflib.SequenceMatcher` ratio of the
  invoice numbers reduced to upper-case alphanumerics, `day_gap` = absolute days between the dates.
- **time**: rank key `(day_gap, invoice_id)`.
- Both rules: the union of the two selections.

The rule reads only the records, so a re-run sees the same invoices. `evaluation/history_cap.py` checks on every
dataset that no labelled case loses an invoice it depends on.

### R11.4 The prompts (exact text)

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

### R11.5 One JSON call (`call_json`)

1. Call the model. 2. `extract_json` and check that `data[required_key]` is a list. 3. If not, append the bad reply
and the repair message and call once more. 4. After two failures return `None` (the stage *fails*: it contributes
nothing, counts in `failed_stages`, and the other stages go on). One cost record per call:
`{stage, agent, sample, attempt, ok, prompt_tokens, completion_tokens, latency_ms, cached}`.

### R11.6 From reply to flags (`parse_flags`)

For each item of `data["flags"]`:

- not a dict, or no clause -> dropped as `malformed`;
- `clause_id(item["clause"])` extracts the first `\d+(\.\d+)+` ("Rule 2.1.1", "SOP 2.1.1." -> "2.1.1");
- a clause that **exists** in the policy but is **outside the remit** -> dropped as `out_of_remit`;
- the same clause twice -> dropped as `repeated`;
- a clause that does **not** exist in the policy is **kept** (so clause validity *p* can see it);
- the flag becomes `{"clause", "source": "L", "agent", "evidence" (list or []), "message": explanation}` and is
  normalized: a valid clause takes the clause's severity from the registry; an unknown clause keeps the stated
  severity if valid, else `medium`.

### R11.7 The challenger (`run_challenger`)

- Not called when no agent raised a finding.
- It sees the records that the authors of the proposed findings saw (the union of their `records`, history columns
  and history rules), so a finding is tested against its author's evidence.
- A finding with a `remove` verdict (by integer id) goes to `removed` with `removed_by: "challenger"` and
  `removal_reason`. A finding without a valid verdict is **kept**; an unusable reply keeps **every** finding (the
  stage counts as failed).
- It can never touch a control finding.

---

## R12. The pipeline graph and the five configurations

`graph.py`.

**Direct path for a graph without a model (16 November 2026).** For a configuration with `agents="none"`, no
reviewer's pause and no checkpointer (C1, so every batch and stream audit by the controls), `build_graph`
returns a `DirectPipeline`: its `invoke({"txn": ...})` calls the node functions controls, confidence, risk
score and audit pack in the graph's order and returns the same state as the LangGraph runtime, without the
runtime's scheduling and checkpoint bookkeeping per step. Measured on the 25,000-invoice ledger
`final_seed_2025` on one laptop: the audit without storage takes 1.4 s directly (57 µs per invoice, on battery,
18 November); under the profiler the graph stage took 85 s through the runtime and 8 s directly. A whole run is
bound by storing the results in SQLite (8 to 30 s on the same laptop, depending on the disk and the journal mode),
so the measured run times vary with the machine's state far more than with the pipeline. The ground-truth check
(`evaluation.final_check`) gives the same `verification.json` after the change as before it.
`tests/test_pipeline.py` compares the two states on every flagged invoice of `pilot_seed_909` and on its first 300 invoices.
The compiled graph stays reachable as `.compiled` and is used for anything else (`get_graph`, an invocation
with a run configuration). Timings recorded in this file before that date were measured through the runtime.
Responses of the API of 1 kB or more are gzip-compressed since the same date (`GZipMiddleware`).

### R12.1 Configuration

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

C0 (the classical baselines) is not a pipeline (Section R25.2).

### R12.2 State

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

### R12.3 Nodes and edges

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

### R12.4 The prediction record (`to_result`)

```python
{"invoice_id", "config", "policy_version", "model", "anomalous": bool(flags), "flags", "removed_flags",
 "r0", "rc", "route",
 "cost": {"llm_calls", "prompt_tokens", "completion_tokens", "latency_ms", "cache_hits"},
 "issues": {"failed_stages", "repaired_replies", "out_of_remit_flags", "malformed_flags"}}
```

This is the format the evaluation reads (one JSON line per invoice) and what `db.save_result` stores.

---

## R13. Confidence, risk scores and routing

`scoring.py`.

### R13.1 Evidence paths (`resolve(txn, path)`)

| Path | Resolves to |
|---|---|
| `invoice.amount`, `po.description`, `grn.notes`, `vendor.official_gstin` | that field of that record |
| `approval.approver_role` | that field of the approving entry |
| `approvals[0].action_taken` | that field of the n-th log entry |
| `history.INV40012.invoice_number` (or `vendor_history.`) | a field of another invoice of the vendor |

A whole record, a list, or a missing key is `MISSING`.

### R13.2 Comparing a quoted value (`same_value(stated, actual)`)

- `MISSING` -> false. Empty stated -> true only if the actual is empty or null. Null actual -> false.
- Booleans: compared as lower-case strings.
- If the record holds a **number**: the stated value is parsed as a number (removing commas, spaces, `₹`, `INR`,
  `Rs.`) and must be within `0.005 + 1e-9 * |actual|`. (An identifier like `"00123"` is never compared as a number,
  because the record holds a string.)
- Otherwise: case-insensitive string equality after stripping.

### R13.3 The three confidence terms

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

### R13.4 Scores and route

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

### R13.5 Workflow states

| Route | State |
|---|---|
| `approve` | `AUTO_APPROVED` |
| `escalate` | `PENDING_REVIEW` |
| `sample` | `PENDING_REVIEW` if `in_sample(invoice_id, sample_rate)`, else `NOT_SAMPLED` |

`in_sample(id, rate)`: `int(sha256(id)[:8 hex], 16) / 2**32 < rate`. The draw is reproducible.

A reviewer's decision sets `REVIEW_APPROVED`, `REVIEW_REJECTED` or `REVIEW_OVERRIDDEN`. An override needs a written
justification.

---

## R14. The audit pack and the revisions

### R14.1 The pack (`audit_pack.build_pack`)

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

### R14.2 Revisions (`corrections.correct`)

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

## R15. Storage: the database layer and the schema

`db.py`.

### R15.1 One interface, two backends

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

### R15.2 Schema creation

`SCHEMA_ID` = first 16 hex digits of the SHA-256 of the schema text. `meta(key='schema')` records the stamp
(`SCHEMA_ID`, plus `+auditiq_reader` on PostgreSQL when the copilot's role exists). `ensure_schema`: if the recorded
stamp differs, take `pg_advisory_xact_lock(4702315001)` on PostgreSQL, read again, then `create_schema` (drop and
re-create the views on SQLite, run every statement, back-fill `latest_results` from `MAX(result_id)` per invoice,
grant SELECT on the copilot's tables to `auditiq_reader` if it exists, write the stamp). An up-to-date database is
only read, so connections take no exclusive lock (re-creating views on every connection once deadlocked two web
requests).

### R15.3 Tables

The five ledger tables are in Section R6.1. The rest:

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

### R15.4 Views

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

### R15.5 Writing results (`save_result`)

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

### R15.6 Loading a ledger

`load_dataset(conn, folder)` / `load_frames(conn, frames, name, replace=True)`: with `replace`, delete (in order)
`email_mentions, emails, review_decisions, audit_trail, audit_flags, latest_results, audit_results, audit_runs,
benchmark_labels, approval_logs, invoices, goods_receipts, purchase_orders, vendor_master`; then insert each table
(and `labels.csv` into `benchmark_labels`), converting text values with `typed(kind, column, value)`
(`BOOLEAN_COLUMNS` = is_active, blacklisted, blacklist_status -> 0/1; po_id/grn_id "" -> NULL; number/integer
parsed; empty date -> NULL); record `meta.dataset = name`.

`upsert_records(conn, table, key, records)` inserts text records or updates the row with the same key
(`ON CONFLICT (key) DO UPDATE`), used by the stream workers.

### R15.7 Users

`ROLES = ("viewer", "reviewer", "admin")`, each including the ones before it. `add_user(name, role)` creates a token
with `secrets.token_urlsafe(32)`, stores only `sha256(token)`, and returns the token once. `user_for_token`,
`has_users`, `list_users`, `disable_user`.

---

## R16. The batch audit service

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

## R17. Policy documents

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

### R17.1 Rendering PDFs (`policy_pdf.py`)

Markdown -> reportlab flowables (headings, paragraphs, bullet rules, tables; body font size 10) -> PDF with a title
and a footer `"<name> | version <v> | page N"`. `make_sample_pdfs()` writes `Procurement_Audit_SOP_v2.5.pdf`,
`Procurement_Audit_SOP_v2.6.pdf` and `Audit_Review_Procedure_v1.0.pdf` (a non-policy procedure document) into
`policy/pdf/`.

### R17.2 Ingestion: PDF to chunks (`policy_ingest.py`)

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

### R17.3 Compiling a template-worded policy (`policy_extract.py`)

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

### R17.4 Reading a free-worded policy with a model (`policy_llm.py`)

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

### R17.5 Simulating a policy before adoption (`simulation.py`)

`simulate(conn, registry, examples=20)`: extract every invoice of the stored ledger once; run the twelve controls and
C1 scoring under the **active** registry and under the **new** one, in memory; nothing is stored. Returns
`{active_version, new_version, invoices, decisions_moved (set of violated rules changed), newly_flagged, cleared,
routes {before, after}, route_changes {"approve -> escalate": n}, findings_by_rule [{rule, before, after}],
amount_newly_held (sum of amounts newly escalated), examples}`. Judgement rules are not simulated (they need a
model). For control rules the prediction is exact: it equals what adopting the document and re-auditing produces.

---

## R18. Policy search and the copilot

### R18.1 The index (`retrieval.PolicyIndex`)

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

### R18.2 The copilot (`copilot.py`)

**Policy and invoice questions** (`answer(question, conn, index, client, k=4, invoice_id=None)`):

1. Retrieve `k` passages (restating the question when a model is available).
2. If an invoice id is given or found in the question (`\bINV\d{3,}\b`), load its latest audit pack. The passages
   of the clauses its findings cite are put **first** (a question such as "why was it flagged" names no rule, so
   retrieval by wording alone finds the wrong rules).
3. Without a model, return the passages and the facts only. With one, the system message names four sources and says how to use
   them (updated 14 November): the FACTS `[F#]` read by code from the policy's registry (exact; prefer them for limits, thresholds,
   which role may approve an amount, what changed between versions); the LEDGER FACTS `[C#]` computed by code from the audited
   ledger (exact; answer questions about vendors, invoices, approvers, rings, counts and amounts from them, and never state a
   name, count or amount about the ledger that no ledger fact gives); the PASSAGES; and the AUDIT RECORD (the authority on what
   was found for an invoice: name only the rules its findings cite). Cite each fact by its label and each passage by its number;
   say that the documents do not answer the question **only if none of the four sources does**. The user message is
   `QUESTION`, then `FACTS`, then `LEDGER FACTS`, then `PASSAGES`, then `AUDIT RECORD`. Reply `{"answer", "passages_used": [n]}`
   (an empty list is accepted when the answer rests on facts only); sources = the passages used (valid numbers only).
   The call is `answer(question, conn, index, client, k=4, invoice_id=None, graph=None, cases=None)`; `graph` is the policy graph
   (`policy_graph.py`) and `cases` the audit graph (`case_graph.py`); the API passes both.

**Data questions** (`data_question(question, target, client)`): the model writes **one SELECT** (dialect named),
given the schema of the readable tables and guidance (outcome is in `v_latest_results`; `v_review_queue` lists what
waits; `approval_status` is not the audit outcome; at most 200 rows). Reply `{"sql": ["..."], "explanation"}`. Up to
two attempts: a rejected statement goes back to the model once with the error, and (since 14 November) a statement that runs and returns no rows goes back
once with a note that a condition may not match the listed values; if the second statement is also empty the explanation says "The statement ran and
returned no rows" instead of the model's description. The schema text now states the real values (`approval_logs.action_taken` is exactly `'Approved'`
or `'Escalated'`; `amount_limit` is the role's limit; `transaction_id` is the invoice id) and lists the active policy's rules (`audit_flags.clause`). Four guards:

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

## R19. Kafka ingestion

`stream.py`, `emails.py`, `auditiq_bench/correspondence.py`, `scripts/kafka_local.py`. Full write-up:
`docs/STREAMING.md`.

### R19.1 Topics

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

### R19.2 Publisher

`Publisher(settings)`: confluent-kafka `Producer` with `enable.idempotence=True`, `acks=all`, `linger.ms=20`,
`compression.type=lz4`. A full local queue (`BufferError`) waits on `poll(0.5)`; `close()` flushes and raises if
any message was not delivered. `publish_ledger(publisher, dataset, limit)` sends the vendor feed, then the invoices
sorted by `(date, invoice_id)` with their PO, GRN and approval entries. `publish_mailbox(publisher, mbox)` sends
every message of an mbox file. `publish_policy(publisher, pdf, activate)`.

### R19.3 Workers

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

### R19.4 Vendor e-mails (`emails.py`)

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

### R19.5 Synthetic correspondence (`auditiq_bench/correspondence.py`)

`python -m auditiq_bench.correspondence --dataset <ledger> --out <file.mbox> [--seed 7]` writes an mbox and
`<file>.labels.csv` (`message_id, category, suspicious, invoice_id, vendor_id`). Per invoice (in date order):
`invoice_submission` with probability 0.35; `payment_reminder` for unpaid invoices with probability 0.06; a
`quantity_query` when the GRN's received quantity is below the billed quantity. Per vendor (its latest unpaid
invoice): a legitimate `bank_change` (probability 0.08) from the vendor's domain, or a **suspicious** one
(probability 0.03) from a look-alike domain (`<name>-accounts`, `<name>s`, `pay-<name>`, or an `i` changed to `l`),
urgent, asking to pay to a new account. Every address is under `.example` (RFC 2606). Same ledger and seed, same
file.

### R19.6 Running

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

## R20. The REST API

`api.py`, FastAPI. `python -m auditiq serve [--host 127.0.0.1] [--port 8000]` runs it with uvicorn and also serves
the built web application (`frontend/dist`) with client-side routes (any non-API path returns `index.html`).

### R20.1 The app factory

`create_app(target=None, token=None, frontend=..., cors_origins=None)`. State: the database target, the shared token
(`AUDITIQ_API_TOKEN`), the jobs, the pending policy proposals. CORS origins from `AUDITIQ_CORS_ORIGINS` (default the
Vite dev server `http://localhost:5173,http://127.0.0.1:5173`). Every request opens its own database connection
(so the API holds no state between requests and works on both backends). Interactive docs at `/api/docs`.

### R20.2 Who is asking (authentication and roles)

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

### R20.3 Security headers

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

### R20.4 Background jobs

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

### R20.5 The 46 endpoints

| Method | Path | Role | What it does |
|---|---|---|---|
| GET | `/api/health` | open | status, version, backend, ledger name, active policy version, model name (503 when the database is down) |
| GET | `/api/me` | viewer | who is calling: `{name, role, via}` |
| GET | `/api/overview` | viewer | counts by state, route and risk level; findings by rule (rule, title, severity, source, count); 10 recent runs; 10 vendors with most invoices waiting; the 14 newest steps of the audit trail; invoices, vendors, audited, findings, reviewed; `coverage`: latest results per configuration, invoices checked by the controls and by the agents, findings approved without review, and on a benchmark ledger the answer key per configuration, scored only under the labels' policy version (docs/ANALYTICS.md) |
| GET | `/api/risk-map` | viewer | one point per vendor: category, invoices, amount, invoices waiting, findings, max risk (Rc) of its latest results, blacklisted |
| GET | `/api/leads` | viewer | the judgement-rule leads (Section R34): near duplicates (2.2.2) and structuring groups (4.1.2) with the policy's guide values, what the latest results did with them, and on a benchmark ledger the answer key; cached until the store changes |
| GET | `/api/sampling` | viewer | a monetary-unit sample (ISA 530) of the invoices approved without a person: `confidence` (0.9, 0.95, 0.99), `tolerable_pct`, `expected_pct`, `seed`; the plan, the random start, the invoices to examine, and on a benchmark ledger the Stringer upper limit with the answer key as the examination (Section R34) |
| GET | `/api/trail/verify` | viewer | recompute the seals of results, trail entries and finished runs (`auditiq/seal.py`, Section R34) and re-perform the evidence of the latest results (Section R35); `intact`, counts, the ids of altered items, `evidence`, the digest of the run seals; `?run=` for one run; not cached |
| GET | `/api/reliability` | viewer | the data-reliability checks of the ledger (ISA 500, Section R35): references, approvals, arithmetic, date logic, goods received not invoiced, gaps in the numbered series, vendor master data, audit coverage; control totals; the ledger fingerprint; not cached |
| GET | `/api/program` | viewer | the audit program (Section R35): every test with the assertions and fraud schemes it addresses and what it found, what no test covers, and on a benchmark ledger each scheme against the answer key; cached until the store changes |
| GET | `/api/workpapers` | viewer | the working papers as an Excel workbook (Section R35), with the report digest in `X-Report-Digest`; `seed` overrides the sample's seed |
| GET | `/api/analytics` | viewer | monthly volume, spend by category and month, Benford first-digit and first-two-digits tests (MAD with Nigrini's thresholds, z per digit, chi-square), invoices by quarter-decade of amount and just under / just over each approval limit, weekdays, findings by category and rule, top approvers, spend concentration (Lorenz, Gini, HHI, top ten) |
| GET | `/api/policy/graph?version=` | viewer | the policy knowledge graph of a version (default: active): nodes (version, sections, rules, parameters, roles, control functions and agents, pages, other versions) and edges (has section, has rule, sets, limit, checked by, stated on, changes); 404 for an unknown version |
| GET | `/api/policy/graph/ask?q=&version=` | viewer | what the question names, the facts the graph derives (routing an amount, the structuring band, round amounts, limits, changes, sets, checkers) with their citations, their passages, and the nodes used; 400 when empty |
| GET | `/api/case-graph?focus=&limit=` | viewer | the audited ledger as a knowledge graph (docs/CASE_GRAPH.md): without `focus` the rings with their vendors and approvers; with it the neighbourhood of a vendor, invoice, approver, ring or rule by id or name (`INV53478`, `Frado Deep`, `g:3`, `5.1.1`, or a node id such as `v:VEND1001`): nodes (vendor, invoice, rule, approver, ring) and edges (billed, violates, approved by, shares PAN/GSTIN, member of, breaks), counts, the policy version, `truncated`; 404 for a name that is in no graph |
| GET | `/api/case-graph/ask?q=` | viewer | what the question names (invoices, vendors, approvers, rings, rules, kinds of fraud), the facts the graph computes with the numbers they rest on, and the nodes used; no model; 400 when empty |
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

The answers of `/api/overview`, `/api/risk-map`, `/api/analytics`, `/api/rings` and the audit graph (`/api/case-graph*`) are kept per server process by
`StoreCache` with a fingerprint of the store (ledger name, newest result, newest review decision, policy versions
and parameters, Kafka offsets, the labels' policy): an audit, a decision, a ledger load, a policy change or a
streamed batch makes the next request compute afresh.

**The policy knowledge graph** (`auditiq/policy_graph.py`, docs/POLICY_GRAPH.md) is built per request from the
clause registry, the documents and the code that checks each rule, with no model. Ask AI passes it to
`copilot.answer`: its facts go to the model as a FACTS block labelled [F1], [F2], and the passages they cite come
before the retrieved ones (`merge_passages`). Evaluated against the passage rankers by `evaluation/graph_eval.py`.

## R21. The web application

`frontend/`. A single-page app that uses the API only.

### R21.1 Build and runtime

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

### R21.2 Routes and pages

| Route | Page | Content |
|---|---|---|
| `/` | Overview | six KPI cards (invoices + vendors, audited, approved automatically, waiting, findings, reviewed) and eight forensic signals; **audit coverage and quality** (configurations, controls and agents coverage, notices, the answer key per configuration); the composition of the audit (risk level, route, workflow as stacked bars); the **risk constellation** (3D) with legend; the vendor risk matrix and the monthly trend; findings by rule (table with severity and share); the escalation queue; vendors with most invoices waiting; the audit trail's newest steps; high-risk vendors; recent runs with durations; **load a ledger** (file, confirm replacement, job progress, problems, then "audit it with the controls") |
| `/review` | Review queue | the **queue constellation** (3D) of the waiting invoices with legend; filters (text, risk level); table (invoice link, vendor, date, amount, route badge, risk meter, findings, configuration) |
| `/invoice`, `/invoice/:id` | Invoices | search; for one invoice: route and both risk meters, recommended action, every finding (rule, title, severity, source, confidence, evidence, citation, revision), findings removed by the challenger, records in tabs (Invoice, PO, GRN, Vendor, Approvals, Vendor history), the decision form (approve/reject/override; justification required for override; reviewer from the account), "audit again" with a configuration (C2..C5 only with a model), the audit trail (tokens and seconds per model call), the vendor e-mails that name the invoice (collapsible), and the benchmark answer key on request |
| `/policy` | Policy | versions with activate; the **policy knowledge graph** (3D, version chooser, "Ask the graph" with examples, facts with citations, the relations of a node, every relation as a table); the active rules and parameters; **adopt a document** (upload PDF -> preview with changes and problems -> simulate the impact (decisions that would move, route changes, findings by rule now and under the document) -> adopt and activate; for a free-worded document with a model: the model's proposal with verified / needs-attention values, quotes and pages, passages and values supplied by the reviewer, confirm); ingested documents; **policy search** with the model's restatement shown |
| `/analytics` | Analytics | eight KPIs; monthly volume; the **spend skyline** (3D, category by month); Benford (first digit / first two digits, with the MAD, chi-square and the digits that differ); amounts against the approval limits (log histogram with the limits and the 10 % bands) and just under / just over each limit; weekdays; the Lorenz curve with the ten largest vendors; findings by category and rule (heat table); approvers |
| `/rings` | Collusion rings | eight KPIs (rings, pairs and approvers tested, most unusual pair, identity checks); the **collusion network** (3D) of the rings, or of the leads below significance when none passes, with the list and the detail of the one chosen; the watch list; the tests and the rate of each role; single-vendor groups; how rings are found |
| `/ask` | Ask AI | ask about the policy or an invoice (examples taken from the queue); answer with numbered citations, the facts of the policy graph ([F1]...), the facts of the audit graph ([C1]...) and the passages; ask about the data (the SQL, explanation and rows). `/copilot` redirects here |
| `/pipeline` | Pipeline | eight KPIs; the **architecture diagram** (SVG from `lib/architecture.ts`: 10 subsystems, 51 components with files and live figures, 43 connections drawn as rounded orthogonal runs with animated flow; hover traces a component's connections, click shows its description, files and connections; a configuration chooser dims the stages it does not run); the configurations compared stage by stage; tabs C1..C5 with the **pipeline** in 3D (stages lit for the configuration, flowing dots on the edges) and the stage list; the **Kafka ingestion** panel (four topic cards: processed of messages, partitions, lag, outcomes) |
| `/results` | Results | KPIs; detection table on every benchmark ledger with 95% intervals; per-class detection heat table; the **policy-change** bars (3D) with the table; scalability line chart (throughput vs workers) and table by ledger size; policies read in their own wording; real-model pilots and samples |
| `/kafka` | Kafka streams | ingestion from the browser: whether the broker answers, the live topology (sources, producer, every topic and partition filled as workers process it, consumer groups, what they write), publishing a ledger, a mailbox or a policy document, running the workers, throughput, outcomes per topic, the worker log, the newest messages inside a topic |
| `/ai` | Agents and pipeline | the audit graph with what each stage has cost (steps, tokens, latency), a step-by-step replay of an invoice's audit from its trail, auditing an invoice now under any configuration, the agents with their remits |
| `/knowledge` | Knowledge base | the knowledge pipeline (documents, passages, verification against the registry, embeddings), the embedding map of every passage in 3D, the registry across versions, every passage with its page |
| `/graph` | Knowledge graph | two tabs: the **policy knowledge graph** and "Ask the graph", and the **audit findings graph** (vendors, invoices with findings, rules, approvers, rings) in 3D with questions, the neighbourhood of any node (`CaseGraphPanel`, `three/CaseGraph3D.tsx`, layout in `three/caseLayout.ts`: rules in the middle, approvers and vendors around them, invoices outside) and every relation as a table |
| `/rag` | RAG retrieval | a question traced through every step: what the graph recognises, the lexical, dense and fused rankings with scores, the graph's facts, the context Ask AI would send, the question in the embedding space |

### R21.3 The 3D views

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

### R21.4 Look

A light theme for the pages (background `#f3f5f9`, white cards with a soft shadow, ink `#0f172a`, brand indigo
`#4f46e5`, teal `#0d9488`, a white sidebar with an indigo active item) and the 3D views on their own dark canvas, as
dark cards inside the light pages. Fonts: Inter / Segoe UI / system. All colours are CSS custom properties in
`styles.css`.

### R21.5 Tests

36 Vitest tests: the client (token, errors, uploads, job polling), formatting helpers, the 3D layout geometry, the
scenes in `@react-three/test-renderer` (one instance per point, stems only where asked, a clicked point handed to
the page, stages per configuration, bars per policy), and every page against a mocked fetch. 10 Playwright tests in
Chromium against the real server on a fresh store (`scripts/e2e_server.py`): upload and audit a ledger, a review
decision, a re-audit, adopt and apply a policy, search, results, pipeline, copilot, routes; an error in the browser
console fails a test.

---

## R22. The Streamlit dashboard

`app/dashboard.py` (`streamlit run app/dashboard.py`), the lighter alternative to the web app, reading the same
database through the same modules. Pages: **Overview** (counts by status, findings by rule, loading a ledger),
**Review queue** (waiting results and the decision form), **Invoice** (audit pack and trail, audit again),
**Policy** (versions, clauses and parameters, adopting a document, policy search), **Copilot**.

---

## R23. The command line

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
| `stream topics\|publish\|work\|status` | Kafka (Section R19) |
| `graph --config C` | the pipeline as a Mermaid diagram |
| `check-llm` | one request to the configured model |

`python -m auditiq_bench` generates the datasets; `python -m evaluation.<script>` runs an experiment.

---

## R24. The benchmark: AuditIQ-Bench

`auditiq_bench/`. Synthetic procurement ledgers with a labelled answer key. It shares **no code** with the pipeline
(it reads only the policy registry, which is data), and a dataset that fails its own validation is not written.

### R24.1 The datasets

| Dataset | Seed | Vendors | Invoices | Anomalous | Hard negatives | Purpose |
|---|---|---|---|---|---|---|
| `bench_seed_101`, `_202`, `_303` | 101, 202, 303 | 250 | 5,000 | 420 (8.4%) | 120 | results are reported as mean and spread over these three |
| `pilot_seed_909` | 909 | 250 | 5,000 | 420 | 120 | development: the only ledger on which prompts and settings may be tried |
| `swap_seed_404` | 404 | 250 | 5,000 | 150 (3.0%) | 0 | policy swap: 150 boundary invoices anomalous under v2.5, clean under v2.6 |
| `large_seed_505` | 505 | 1,000 | 20,000 | 420 (2.1%) | 240 | demonstration ledger; precision at a realistic anomaly rate |
| `collusion_seed_707` | 707 | 250 | 5,000 | 471 (9.4%) | 120 | planted collusion rings (two shell pairs, two approver rings); the ring detector was designed on it. `collusion_seed_808` (held out) is defined and not generated |
| `final_seed_2025` | 2025 | 1,250 | 25,000 | 2,275 (9.1%) | 300 | the final ledger: 141 invoices per class, compound frauds, four shell pairs, six approver rings; the default of `start.bat` (Part IV, sections 6 and 7) |
| `huge_seed_606` (on request) | 606 | 15,000 | 500,000 | 2% | | scale; files kept outside the repository, hashes committed |

Files of a dataset: the five ledger CSVs, `labels.csv` (`invoice_id, label, class_id, clause_ids, severity, group_id,
related_invoice_id, hard_negative_type, note`), `eval_subset.csv` (`invoice_id, stratum, weight`), `manifest.json`
(seed, versions, period, counts, SHA-256 of every file) and a generated `README.md` datasheet. The same seed gives
byte-identical files.

### R24.2 How a ledger is built (`generator.Builder`)

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
ordinary clean (Profile defaults `PER_CLASS = 30`, `PER_HARD_NEGATIVE_TYPE = 24`). The collusion profiles add planted rings (`build_collusion`); the final profile uses `per_class = 141` (a multiple of 3: J2 is built in groups of three), `per_hard_negative = 60`, `build_final` (rings at company scale, then `build_main`, then `compound_frauds`), and labels with a `secondary_class_ids` column (written only for a ledger that has compound frauds, so the benchmark ledgers' files did not change).

### R24.3 Anomaly classes

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

### R24.4 The evaluation subset

Model configurations are expensive per invoice, so `eval_subset.csv` lists what they audit: every anomalous
invoice, every hard negative, every clean invoice a duplicate copies, and a random sample of ordinary clean
invoices (600 by default; 150 in the policy-swap ledger, 480 in the 20,000-invoice ledger, 800 in the final ledger). Weights: 1 for the complete strata, N/n for the sampled ordinary invoices (N ordinary in the ledger, n
sampled), so the weights sum to the ledger size and a weighted rate on the subset estimates the rate on the whole
ledger. The agents still see the whole ledger as vendor history.

---

## R25. The evaluation harness

`evaluation/`.

### R25.1 Scripts

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

### R25.2 C0: the classical baselines (`run_c0.py`)

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

### R25.3 Metrics (`metrics.py`)

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

## R26. Configuration: every environment variable

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

## R27. Deployment and local servers

### R27.1 Local, without containers

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
- **Kafka without Docker**: `python scripts/kafka_local.py ...` (Section R19.6).
- **Model**: Ollama; `ollama create qwen2.5:7b-ctx12k -f deploy/ollama/Modelfile` (Qwen 2.5 7B with
  `num_ctx 12288`), `ollama pull nomic-embed-text`; `.env`: `AUDITIQ_LLM_BASE_URL=http://localhost:11434/v1`,
  `AUDITIQ_LLM_MODEL=qwen2.5:7b-ctx12k`, `AUDITIQ_LLM_CONTEXT=12288`, `AUDITIQ_LLM_TIMEOUT=3600`,
  `AUDITIQ_EMBED_MODEL=nomic-embed-text` with the two prefixes; then `python -m auditiq policy embed`.

### R27.2 The container image (`Dockerfile`)

Two stages: `node:20-slim` runs `npm ci` and `npm run build`; `python:3.11-slim` copies the project (code, policy,
data, results), `pip install -e .`, creates the unprivileged user `auditiq` (uid 1000) that may write only
`/app/.auditiq` and `/app/policy/pdf`, copies `frontend/dist`, sets `AUDITIQ_NO_DOTENV=1`, exposes 8000, has a health
check on `/api/health`, and runs `python -m auditiq serve --host 0.0.0.0 --port 8000`.

### R27.3 Compose (`deploy/docker-compose.yml`)

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

## R28. Tests and continuous integration

### R28.1 Python tests (`tests/`, pytest)

The tests generate their own small datasets (a 1,200-invoice ledger of 60 vendors, a 150-invoice swap ledger) and
never read `data/`. Every test that needs a store gets a new one; tests marked with the `backend` fixture run once
on SQLite and once on PostgreSQL (each in its own schema of the test database, dropped afterwards). No test calls a
model (a `ScriptedClient` stands in). 519 tests are collected on 14 November (those that need PostgreSQL are skipped without a server); 61 frontend tests sit beside the code.

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
| `test_analytics.py` | coverage, the answer key under its own policy, Benford, limits, concentration, rings and their tests, on both backends |
| `test_policy_graph.py` | the policy graph and its facts; Ask AI is given the facts and their passages first |
| `test_case_graph.py` | the audit graph: facts for an invoice, vendor, approver, ring, rule, identity; neighbourhoods; the cut limit |
| `test_policy_demo.py` | the five demonstration policies read exactly as stated, deterministic PDFs, the incomplete draft refused, effects in the intended direction (uses `data/bench_seed_101` when present) |
| `test_generator.py` | the generator and its validator; no import between pipeline and generator |
| `test_eval.py`, `test_run_full.py`, `test_huge.py`, `test_reproduce.py` | the evaluation harness |
| `test_docs.py`, `test_results.py`, `test_packaging.py` | generated documents current; results.json matches its sources; every import is a declared dependency |

### R28.2 CI (`.github/workflows/ci.yml`, five jobs on every push)

| Job | Steps |
|---|---|
| `test` | services PostgreSQL 17 and Kafka 4.3.2; `pip install -e ".[dev]"`; `ruff check`; `pip-audit` (8 Pillow advisories ignored by name: Pillow is held below 13 by Streamlit and no uploaded image is decoded); create `auditiq_reader`; wait for the broker; `pytest` (with `AUDITIQ_REQUIRE_KAFKA=1`) |
| `frontend` | `npm ci`, lint, typecheck, test, build, `npm audit --omit=dev --audit-level=high` |
| `e2e` | install, build, Playwright in Chromium against the real server |
| `compose` | PostgreSQL from `deploy/postgres/docker-compose.yml`; the whole test suite against it (with timeouts and failure annotations); a ledger set up and audited |
| `container` | build the image and start app + PostgreSQL + Kafka + workers from the compose file; set up and audit a ledger inside; check `/api/health`, 401 without token, overview counts with the token (5,000 audited, 300 findings, postgres), the SPA and its CSP header; send vendor e-mails through the e-mail topic and wait until the workers have stored them all |

---

## R29. Security model

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

## R30. What has been measured

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

## R31. Limits and open items

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

## R32. Glossary

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

## R33. Rebuilding it: the order of work

Each step lists what to build and the check that proves it before moving on. Python 3.11, a fresh virtual
environment, the dependencies of Section R4.

1. **Policy data.** Write `policy_v2.5.json` (Section R7.1) and `policy_v2.6.json` (three parameters changed). Write
   `SOP_template.md` with the rule sentences of Section R7.2 and `render_policy_text`. *Check:* rendering both versions
   succeeds, and the rule/severity cross-check fails when you change a severity in the text only.
2. **Benchmark generator** (Section R24) reading only the registry; vendors, purchases, documents, approvals; the 14
   injections and 5 hard negatives; an independent validator; manifests with SHA-256. *Check:* two runs with the same
   seed give identical files; the validator's recomputed rule violations equal the labels exactly.
3. **Extraction** (Section R6.2, R8): transactions from the CSV files, `History` with `VendorIndex`. *Check:* every
   invoice's history excludes itself and is sorted by (date, id).
4. **Controls** (Section R9). *Check:* on a benchmark ledger, the set of clauses flagged per invoice equals the labels'
   `clause_ids` for every R-class invoice; no flag on any hard negative or ordinary invoice; F1 = 0.833 with
   precision 1.000 (recall 0.714 = 300 of 420, because J1 to J4 are not control classes).
5. **Scoring** (Section R13). *Check:* Rc <= R0 on random flag sets; one critical control flag escalates; a weekend
   date alone (medium, 10) approves.
6. **Audit pack and revisions** (Section R14). *Check:* applying every `amend`/`reapprove` revision makes the invoice
   pass the failed rule with no new finding.
7. **Database layer** (Section R15) for SQLite first, then PostgreSQL with the type map and loaders. *Check:* load a
   ledger, `extract_one` and `extract_many` give the same transactions; schema creation is idempotent and stamped.
8. **Batch service and CLI** `setup`, `run`, `show`, `queue`, `decide` (Sections R16, R23). *Check:* `run --config C1`
   on a benchmark ledger stores 5,000 results with 300 findings and 240 escalated.
9. **Model client** (Section R10) with cache, retries, context guard, `extract_json`. *Check:* a repeated request makes
   no HTTP call; a 429 with `Retry-After` is retried; a 400 fails at once.
10. **Prompts and agents** (Section R11), with remit enforcement, repair, challenger rules. *Check with a scripted
    client:* an out-of-remit flag is dropped; an unknown clause is kept; a challenger without a verdict keeps the
    finding; an unusable reply keeps all.
11. **The graph** (Section R12) and the five presets; human review with `interrupt` and a checkpointer. *Check:* C1
    makes 0 calls, C3 three, C4 four when an agent finds something; C5 adds 3 re-runs per agent with a kept finding.
12. **Policy documents** (Section R17): PDF rendering, ingestion with chunking and verification, citations, the
    pattern compiler with every refusal, adoption, the model reader with verification and confirmation, the
    simulation. *Check:* the rendered v2.6 PDF compiles back to exactly the v2.6 registry; deleting a rule or a
    threshold sentence makes adoption refuse with that reason; the simulation of v2.6 equals what adopting it and
    re-auditing produces.
13. **Retrieval and copilot** (Section R18) with all four SQL guards. *Check:* a query naming `benchmark_labels`, using
    `set_config`, or with two statements is refused; on SQLite the authorizer denies reading a forbidden table at
    execution even if a name slipped past the check.
14. **REST API** (Section R20): auth and roles, headers and CSP, jobs and conflicts, every endpoint, the generated API
    reference. *Check:* each endpoint on both backends; 401/403 by role; 409 for conflicting jobs.
15. **Web application** (Section R21): client, pages, the 3D views with fallbacks. *Check:* page tests against a
    mocked API; Playwright against the real server.
16. **Kafka layer** (Section R19): topics, publisher, workers with stored offsets, fencing, vendor wait, re-audit of
    completed same-day groups, e-mails with deferred linking and the advisory lock, compliance documents, status,
    the local broker script. *Check:* a ledger streamed into an empty store ends with exactly the batch audit's
    findings on SQLite and PostgreSQL; a second worker run processes nothing; two workers process each invoice once.
17. **Evaluation** (Section R25): C0 with cross-fitting, weighted metrics, bootstrap, McNemar with Holm, the experiment
    scripts, `results.json` and the generated report. *Check:* `scripts/reproduce.py` regenerates every no-model result
    file identical to the committed one (apart from dates and timings).
18. **Deployment and CI** (Sections R27, R28). *Check:* all five CI jobs green.

Throughout: keep principle 2 (no threshold in code) and principle 6 (pipeline and generator share no code), and let
no number into a document that a script did not produce.

---

## R34. Assurance: the sealed record, judgement-rule leads and statistical sampling (18 November 2026)

Three additions for an auditor who has to rely on the audit, all on the web application's Assurance page
(`/assurance`) and measured on `final_seed_2025` by `python -m evaluation.industry`
(`results/final_seed_2025/industry.md`) and `python -m evaluation.leads_eval` (`results/leads/leads.md`).

**The sealed record (`auditiq/seal.py`).** Each stored result carries `audit_results.seal`, a SHA-256 over a canonical
JSON of its columns (with the workflow state it was stored with), its audit pack without the `review` entry, and its
`audit_flags` rows in order. Each `audit_trail.entry_hash` is a SHA-256 over the entry and the hash before it, the first
over the result's seal; the reviewer's decision is such an entry (`record_decision`), so a review extends the chain.
`finish_run` seals the run (`audit_runs.seal`) over its columns and its results' seals in result order. `seal.verify`
recomputes everything in chunks of 5,000 results (bounded memory on any store) and reports altered results, results
whose state is not the decision their chained review entry records, broken entries (the first broken entry is where
a change was made; every later entry of that result breaks too), and altered runs. A result changed and re-sealed by
someone still breaks its trail and its run's seal. Rows stored before sealing are counted as unsealed, not altered;
an older store gets the three columns when it is opened (`db.ADDED_COLUMNS`; the views are dropped and made again on
both backends because PostgreSQL refuses a view whose columns move). Not covered: someone who recomputes every hash,
and a run deleted whole; `seal.run_digest` (printed by `python -m auditiq verify`) is one value to keep outside the
store against both. Measured: the 25,000 sealed results of a C1 run and the 50,000 unsealed older ones verify in
3.1 s; `tests/test_seal.py` changes a finding, the route, the score, the pack, a trail entry, a review state, and takes a
result out of a finished run, and each change is found. Commands and endpoints: `python -m auditiq verify [--run N]
[--json]` (exit status 1 when altered), `GET /api/trail/verify`, and `integrity` in `GET /api/invoices/{id}`.

**Judgement-rule leads (`auditiq/leads.py`).** Rules 2.2.2 and 4.1.2 are judgement rules, but the policy words them
closely enough for code to list the invoices that fit, with the policy's guide values: near duplicates (the same
vendor, PO, GRN and amount as an earlier invoice under a re-keyed number; the number is normalised group by group:
case, separators, leading zeros of each digit group, a suffix of up to four letters after the last digit, and one
substituted, added, removed or transposed character compared with and without the zeros) and structuring (invoices
of one vendor approved by one role on different days within `guide_window_days`, each within `guide_band_pct` below
the role's limit, together above it; the descriptions are shown, not compared, because the rule's "same goods" may
be worded differently). A lead changes no result. Developed on `final_seed_2025`: the first version listed 136 of
141 J1 and 35 of 141 J2 invoices (two number-reading defects, and descriptions compared as text); after one change
it lists 141 of 141 of each with nothing else, and on the five held-out benchmark ledgers 30 of 30 of each with
nothing else, hard negatives included. The generator plants J1 and J2 in the policy's pattern, so this shows the code
follows the policy's wording; it bears on the open question whether J1 (and J2) should count as rule-defined.

**Monetary-unit sampling (`auditiq/sampling.py`).** ISA 530 on the invoices whose latest result is `approve`: sample
size n = BV x R(0, c) / (TM - E x EF(c)), R the Poisson reliability factor `chi2.ppf(c, 2(k+1)) / 2`, EF the AICPA
expansion factor (0.90: 1.5, 0.95: 1.6, 0.99: 1.9); systematic selection by monetary unit from a seeded random start
(an invoice of at least the interval is drawn with certainty); the Stringer upper limit from the taintings, largest
first. On a benchmark ledger the answer key stands in for the examination (an anomalous invoice misstated in full).
On `final_seed_2025` (C1): 23,342 approved invoices worth Rs 4,637,836,464 hold Rs 116,605,530 of anomalous invoices
(2.5 %); at 95 % and a tolerable 2 % the sample is 150; over 1,000 random starts the upper limit covers the true
amount in 97.4 % of draws and supports reliance in 2.6 %; with the anomalous invoices removed it supports reliance in
100 %.

**Optimisations made with these.** A batch run commits about once a second (`service.COMMIT_SECONDS`) instead of every
200 invoices: 10 commits instead of 128 for 25,000 invoices, 10.0 and 10.2 s against 10.9 and 12.0 s in alternating
rounds on one laptop. The GSTIN regular expressions are compiled once; `db.now()` formats the time once a second.
scikit-learn (2.5 s to import) is imported by the retrieval index when it is built, SciPy by the sampling factors and
ReportLab by the PDF maker: importing the command line went from 6.0 s to 2.3 s (`python -X importtime`), which every
`python -m auditiq` command saves. Runs 2 and 3 of the 25,000-invoice store, audited before and after these changes,
agree on every invoice (route, score, risk level, findings).

---

## R35. Evidence, data reliability, the audit program and the working papers (18 November 2026)

Four additions for an auditor, on the Assurance page and measured on `final_seed_2025` by `python -m evaluation.industry`
(`results/final_seed_2025/industry.md`).

**Evidence fingerprints and re-performance (`seal.evidence`, `seal.evidence_drift`).** The seals of R34 protect the
results, not the ledger they were based on: an invoice edited after its audit left its result intact and wrong. Each
result now stores `audit_results.evidence`, a JSON object with the first 128 bits of the SHA-256 of each record the
audit read (invoice, PO, GRN, vendor, approval entries; the vendor's other invoices are left out, as they grow with
the ledger), and the result's seal covers it (results sealed before it existed still verify: the field is sealed
only when present, and setting it to NULL afterwards is a change). `evidence_drift` re-extracts the latest results'
records (`db.extract_many(..., history=False)`) and names the invoices whose records changed and which record moved;
`python -m auditiq verify` prints it (`STALE`), `GET /api/trail/verify` returns it as `evidence`, and an invoice whose
result is intact but whose records changed shows `integrity: "stale"`. Measured on the 25k store: 25,000 latest
results re-performed in 1.6 s, all matching; the runs audited before and after the change agree on every invoice.

**Data reliability (`auditiq/reliability.py`, ISA 500).** Nineteen checks of the ledger as data: invoices whose
vendor, PO or GRN is not on file (the last two decided by rule 2.1.3), invoices billed by another vendor than their
PO's, GRNs without their PO, invoices without an approval, approval entries without an invoice, recorded approver
against the log, amount plus tax against total, quantity times unit price against amount, date logic, goods received
but never invoiced (unrecorded liabilities), gaps in the company's four numbered series, vendor GSTIN and PAN, and
audit coverage (never audited, or not under the version in force). Control totals and a SHA-256 over every row of
every ledger table. The ledger is reliable when no check has exceptions that no rule decides. On the 25k ledger: 18 of
19 checks clean, the 47 invoices naming a PO not on file decided by rule 2.1.3, 1.2 s. One query had to be a set
difference: `NOT EXISTS` against the unindexed `invoices.grn_id` took 64 s.

**The audit program (`auditiq/audit_program.py`).** Every test (the 16 rules, the two leads, the rings, Benford, the
limit analysis, the sample, the reliability checks, the seals) mapped to the assertions (ISA 315 plus authorization)
and fraud schemes (ACFE: shell company, overbilling, duplicate billing, not received, personal purchases, limit
evasion, override, kickbacks, conflicts of interest, bid rigging, tax misuse) it addresses; the mapping is a written
judgement in the module, the counts come from the store. Untested on this platform: bid rigging (no tender data);
scope limits are stated for cut-off, completeness, conflicts of interest and personal purchases. On a benchmark
ledger every scheme is scored against the answer key; a finding counts for a scheme only if its rule addresses that
scheme. On the 25k ledger with C1 and the leads: shell company, duplicate billing, limit evasion, override, conflicts
of interest and tax misuse 100 %, overbilling 90.5 %, goods not received 75.4 % and personal purchases 0 %: the last two
are the description and receipt-remark rules that need the agents.

**Working papers (`auditiq/workpapers.py`, ISA 230).** One workbook: summary, findings, review queue, leads, sample,
reliability, program, integrity. The report digest is a SHA-256 over all its values except the time it was written:
built again from an unchanged store it repeats, and `python -m auditiq workpapers --check <file>` says whether a
workbook still matches the store (a review decision or a ledger edit makes it differ). The sample's seed is taken from
the digest of the sealed runs, so nobody chose it and anyone with the store draws the same sample.
`GET /api/workpapers` serves it with the digest in `X-Report-Digest`. On the 25k store: 7.1 s, 334,930 bytes, the
digest repeats.
