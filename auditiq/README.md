# AuditIQ

A controls-first, multi-agent audit of procure-to-pay transactions, with the
AuditIQ-Bench datasets and the evaluation harness of the paper
(`../paper/auditiq_paper.tex`).

AuditIQ examines vendor invoices that have been approved and not yet paid. For
each invoice it gathers the purchase order, the goods receipt, the vendor
record, the approval log and the vendor's other invoices, checks them against
a written policy, and decides whether the invoice can be paid without review,
should be reviewed, or must be reviewed. Every decision carries its findings,
the evidence each finding quotes, the policy clause it cites with document and
page, and a trail of every step.

It is a standalone Python project. The pipeline is a LangGraph state graph,
the store is SQLite or PostgreSQL, and the model is any OpenAI-compatible
endpoint, local or hosted. A REST API (FastAPI) and a web application (React,
with 3D views in React Three Fiber) put the audit, the review queue, the policy
and the measured results in the browser.

```
ledger (database) -> extraction -> controls -> three specialist agents -> challenger
                  -> confidence -> risk score and route -> review queue -> audit pack and audit trail
policy PDFs       -> ingestion  -> clause store -> citations, policy search, copilot
```

## Documentation

| Document | Content |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | The design: principles, pipeline, agents, scoring, storage, retrieval, copilot, evaluation |
| [docs/DEVELOPER.md](docs/DEVELOPER.md) | For changing the code: the map of every module, how an invoice, a policy and a request pass through it, the contracts between the parts, how to add a control, an endpoint, a page or a table, the conventions and the checks |
| [docs/API.md](docs/API.md) | Every endpoint of the REST API: parameters, body, role, answers (generated from the code) |
| [docs/BASE_PAPERS.md](docs/BASE_PAPERS.md) | Each element of the two base papers, where the code implements it and the measurement that shows it |
| [docs/SECURITY.md](docs/SECURITY.md) | What is protected and how, the copilot's SQL guards, what is not protected, a checklist before a deployment |
| [docs/CODE_REVIEW.md](docs/CODE_REVIEW.md) | The code review of 21 October 2026: how the code was examined, eleven findings and their fixes, what was found sound |
| [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) | Every table and column, with types on both backends and who reads it (generated) |
| [docs/DATASETS.md](docs/DATASETS.md) | The six datasets: sizes, how a ledger is built, how each anomaly is injected, limits (generated) |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Install, configure, run, reproduce the evaluation, troubleshoot |
| [docs/WEB.md](docs/WEB.md) | The REST API and the web application: running, settings, security, every endpoint, the pages and 3D views, tests |
| [docs/FEATURE_POLICY_AS_DATA.md](docs/FEATURE_POLICY_AS_DATA.md) | The measured feature, written up for the paper: thresholds read from the policy PDF, the policy-change experiment and its results |
| `data/<name>/README.md` | The datasheet of each dataset (generated with the data) |
| [PLAN.md](PLAN.md) | What is built, decisions taken while building, what is open |
| `results/` | What has been measured: `summary.md`, `retrieval.md`, `history_cap.md`, pilot reports |

## Quick start

Python 3.11 or later. Neither a model nor a database server is needed for this.

```bash
pip install -e ".[dev]"
```

```bash
python -m pytest
```

```bash
python -m auditiq setup --dataset data/large_seed_505
```

```bash
python -m auditiq run --config C1
```

```bash
cd frontend && npm ci && npm run build && cd ..
```

```bash
python -m auditiq serve
```

`setup` loads a ledger of 20,000 invoices (83,495 records in five tables), the
two policy versions and the policy PDFs. `run --config C1` audits every invoice
with the twelve controls and stores results, findings and the audit trail.
`serve` starts the web application at http://127.0.0.1:8000 (the API
description is at `/api/docs`): the overview with a 3D map of every vendor's
risk, the review queue and the decision form, single invoices with their audit
pack and trail, policy adoption from a PDF, the copilot, the pipeline as a 3D
graph, and the measured results. A ledger of your own is loaded on the
Overview page, or with `python -m auditiq ledger import ledger.xlsx`, from an
Excel workbook with one sheet per table or a .zip archive of the CSV files; it
is checked before it replaces the current one. Building the frontend needs Node 20 or later;
without it the API runs alone. The Streamlit dashboard
(`python -m streamlit run app/dashboard.py`) offers the same work in a simpler
form.

End to end, two more checks need no model either. The first runs the whole
application in a browser (Playwright, after `npx playwright install chromium`
once); the second reproduces every result that needs no model in a temporary
folder and compares it with the committed files:

```bash
cd frontend && npm run e2e && cd ..
```

```bash
python scripts/reproduce.py
```

For PostgreSQL, a chat model, and an embedding model, see
[docs/OPERATIONS.md](docs/OPERATIONS.md). In short:

```bash
python scripts/pg_local.py init
```

```bash
ollama create qwen2.5:7b-ctx12k -f deploy/ollama/Modelfile
```

```bash
python -m auditiq check-llm
```

```bash
python -m auditiq run --config C5 --invoice INV40042
```

```bash
python -m auditiq ask "Why is INV40042 high risk?"
```

## Configurations

| | Controls | Agents | Challenger | Confidence | Needs a model |
|---|---|---|---|---|---|
| C0 | classical detectors (isolation forest, one-class SVM); evaluation only | | | | no |
| C1 | yes | | | | no |
| C2 | | one prompt over the whole policy | | | yes |
| C3 | yes | three specialists | | | yes |
| C4 | yes | three specialists | yes | | yes |
| C5 | yes | three specialists | yes | yes | yes |

## Data

Six generated ledgers, 45,000 invoices and 187,413 ledger records in all, each
with vendors, purchase orders, goods receipts, invoices, approval logs and the
ground truth of every invoice.

| Dataset | Invoices | Ledger records | For |
|---|---|---|---|
| `bench_seed_101`, `_202`, `_303` | 5,000 each | about 20,750 each | reported results |
| `pilot_seed_909` | 5,000 | 20,755 | development; the only ledger prompts may be tried on |
| `swap_seed_404` | 5,000 | 20,904 | the policy-swap experiment |
| `large_seed_505` | 20,000 | 83,495 | the application; a realistic anomaly rate (2.1%) |
| `huge_seed_606` | 500,000 | 2,078,077 | every measurement without a model at scale, and the web application on half a million invoices; generated only on request (`python -m evaluation.huge`), not committed |

`python -m auditiq_bench` regenerates them byte-identically;
`python -m auditiq_bench.overview --verify` checks the files against their
recorded hashes. Everything is synthetic. `exports/large_seed_505_C1/` holds
every table of the loaded and audited database as CSV, including the policy
and audit tables that a dataset folder does not have.

## What has been measured, and what has not

Every result, with its table, its source file and the command that produced it, is collected in
[`../RESULTS.md`](../RESULTS.md): the one document to read while writing the paper. The same results in
one machine-readable file: [`results/results.json`](results/results.json)
(`python -m evaluation.collect_results`, checked against its sources by a test).

Measured, by scripts in this repository:

- **Controls (C1) and classical baselines (C0)** on every ledger, and the
  policy swap: `results/summary.md` (`python -m evaluation.run_all`).
- **Policy change**: 14 policy documents read and applied to 40,000 invoices,
  against a system with frozen thresholds: `results/policy_change.md`
  (`python -m evaluation.policy_change`).
- **Held-out policy documents**: 20 variants drawn at random, read and applied
  to the same 40,000 invoices: `results/policy_heldout.md`
  (`python -m evaluation.policy_heldout`).
- **Robustness of the policy reader**: 16 edited documents that must be read
  correctly or refused: `results/policy_robustness.md`
  (`python -m evaluation.policy_robustness`).
- **A policy change in the application**, with storage, on the 20,000-invoice
  ledger: `results/application_demo.md` (`python -m evaluation.application_demo`).
- **Every ledger through the deployed system**: each of the six ledgers loaded
  from an Excel workbook and audited through the store, with the review queue
  and the answer key: `results/ledger_runs.md` (`python -m evaluation.ledger_runs`).
- **Policy retrieval** on 48 fixed questions, lexical, dense and hybrid, with
  and without question rewriting: `results/retrieval.md`.
- **The vendor-history cap** against the labels: `results/history_cap.md`.
- **Scalability of the control stage** against worker processes and ledger size:
  `results/scalability.md`.
- **The huge ledger**: detection, the fourteen policy documents, the deployed
  path and the control stage on 500,000 invoices from 15,000 vendors:
  `results/huge_seed_606/huge.md` (`python -m evaluation.huge`).
- **The pipeline against a real local model** (`qwen2.5:7b`, on a laptop CPU):
  a pilot of 20 invoices under all five configurations, and a six-invoice
  demonstration, in `results/pilot_seed_909/` (`pilot20.md`, `demo.md`). A
  pilot shows that every stage runs and what an invoice costs; 20 invoices are
  far too few to compare configurations, and the report says so.
- **The same configurations on a sample of a benchmark ledger**: 34 invoices of
  `bench_seed_101` (5 of each judgement class, 2 of each hard-negative type, 4
  ordinary), drawn by `python -m evaluation.sample_ids`:
  `results/bench_seed_101/sample34.md`. A sample, not the benchmark.
- **Policies in their own wording** read by the local model, verified by code
  and confirmed by a person: six documents, 84 values,
  `results/policy_llm.md` (`python -m evaluation.policy_llm_eval`).

Not measured:

- **The LLM configurations (C2 to C5) on whole benchmark ledgers.** The
  development laptop has no GPU and needs minutes per model call, so only
  samples are possible on it (20 and 34 invoices). The harness is ready
  (`evaluation.run_config`, `evaluation.report`); a full ledger needs a faster
  endpoint. Numbers from the samples must be written as sample results.

## Layout

| Path | Content |
|---|---|
| `auditiq/` | The pipeline, the database, the policy documents, the copilot, the command line, the REST API (`api.py`). Imports nothing from the benchmark. |
| `frontend/` | The web application: React, TypeScript, React Three Fiber; built into `frontend/dist`, which the API serves. |
| `auditiq_bench/` | The dataset generator and its validator. Imports nothing from the pipeline. |
| `evaluation/` | Baselines, runners, metrics, statistics, reports. |
| `app/` | The Streamlit dashboard, the lightweight alternative to the web application. |
| `policy/` | The clause registry (`policy_v2.5.json`), the text templates, the generated SOP text and PDFs. The registry is the only place a threshold is written. |
| `data/`, `results/` | Datasets; predictions, metrics and reports. |
| `exports/` | A CSV snapshot of every table of the database (`python -m auditiq export`): the ledger, the policy store and the audit results of the 20,000-invoice ledger under C1. |
| `docs/` | The documents listed above. |
| `deploy/` | The Ollama Modelfile; a PostgreSQL compose file. |
| `scripts/` | `pg_local.py`, a local PostgreSQL server without installation. |
| `tests/` | The Python test suite. No test calls a model. The frontend's tests sit next to its code (`frontend/src/**/*.test.ts(x)`). |
| `.auditiq/` | Local state, not versioned: the SQLite database and the model-reply cache. |

## Prediction format

Every configuration writes one JSON object per invoice;
`evaluation/metrics.py` needs nothing else.

```json
{"invoice_id": "INV40015", "config": "C5", "model": "<model identifier>", "anomalous": true,
 "flags": [{"clause": "2.1.4", "severity": "high", "source": "L", "agent": "math_approvals",
            "g": 1, "p": 1, "a": 0.67, "confidence": 0.89,
            "evidence": [{"field": "grn.notes", "value": "..."}], "message": "..."}],
 "removed_flags": [], "r0": 50, "rc": 50, "route": "escalate",
 "cost": {"llm_calls": 7, "prompt_tokens": 15100, "completion_tokens": 240, "latency_ms": 9100, "cache_hits": 0},
 "issues": {"failed_stages": 0, "repaired_replies": 0, "out_of_remit_flags": 0, "malformed_flags": 0}}
```

`source` is `D` for a control and `L` for an agent. An evidence `field` is a
path into the transaction (`invoice.amount`, `po.description`, `grn.notes`,
`vendor.official_gstin`, `approval.approver_role`,
`history.<invoice_id>.invoice_number`); the grounding term checks it against
the extracted values.
