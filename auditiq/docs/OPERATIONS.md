# Operations

How to install, configure, run and check AuditIQ. Run every command from the
project folder (the one that holds `pyproject.toml`).

## 1. Install

Python 3.11 or later.

```bash
pip install -e ".[dev]"
```

This installs the packages listed in `pyproject.toml` and the `auditiq`
command (the same as `python -m auditiq`).

The web application also needs Node 20 or later, once, to build the frontend:

```bash
cd frontend && npm ci && npm run build
```

`npm ci` installs the exact versions recorded in `package-lock.json`; the build
writes `frontend/dist`, which `python -m auditiq serve` serves.

## 2. First run, without a model or a server

Nothing needs configuring for this: the database is a SQLite file and
configuration C1 uses the controls only.

```bash
python -m auditiq setup --dataset data/large_seed_505
```

```bash
python -m auditiq run --config C1
```

```bash
python -m auditiq queue
```

```bash
python -m auditiq serve
```

`setup` loads the five ledger tables of the dataset, stores policy versions
2.5 and 2.6 (2.5 active), writes the sample policy PDFs to `policy/pdf/` and
ingests them. Loading a ledger replaces the ledger and clears earlier results.
`run --config C1` audits every invoice and stores results, findings and the
audit trail. `queue` lists what is waiting for a reviewer. `serve` starts the
web application at http://127.0.0.1:8000, with the API description at
`/api/docs` ([WEB.md](WEB.md)); `python -m streamlit run app/dashboard.py` starts
the simpler Streamlit dashboard instead.

## 3. Configuration

Every setting is an environment variable. `.env` in the project folder is read
at start-up; a variable already set in the environment wins. Copy
`.env.example` to `.env` to begin. `.env` is not versioned and must not be:
it holds the database password and any API key.

| Variable | Meaning | Default |
|---|---|---|
| `AUDITIQ_DATABASE_URL` | `postgresql://user:password@host:port/database` | not set: SQLite |
| `AUDITIQ_DB` | SQLite file, used when no URL is set | `.auditiq/auditiq.db` |
| `AUDITIQ_TEST_DATABASE_URL` | PostgreSQL database the tests may use | not set: PostgreSQL tests are skipped |
| `AUDITIQ_LLM_BASE_URL` | base URL of an OpenAI-compatible server | none; required for C2 to C5 and the copilot |
| `AUDITIQ_LLM_MODEL` | model identifier; stored with every result | none |
| `AUDITIQ_LLM_API_KEY` | key, when the server needs one | empty |
| `AUDITIQ_LLM_CONTEXT` | the server's context window in tokens; a longer prompt is refused | not set: no check |
| `AUDITIQ_LLM_TIMEOUT` | seconds to wait for one reply | 600 |
| `AUDITIQ_LLM_MAX_TOKENS` | longest reply requested | 700 |
| `AUDITIQ_LLM_JSON_MODE` | 0 if the server rejects `response_format` | 1 |
| `AUDITIQ_LLM_SEND_SEED` | 0 if the server rejects `seed` | 1 |
| `AUDITIQ_LLM_EXTRA_BODY` | extra JSON fields for the request body | `{}` |
| `AUDITIQ_EMBED_MODEL` | embedding model for dense policy search | not set: lexical search |
| `AUDITIQ_EMBED_BASE_URL`, `AUDITIQ_EMBED_API_KEY` | embedding server | the chat model's |
| `AUDITIQ_EMBED_QUERY_PREFIX`, `AUDITIQ_EMBED_DOCUMENT_PREFIX` | prefixes some embedding models expect | empty |
| `AUDITIQ_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING` | `INFO` |
| `AUDITIQ_API_TOKEN` | when set, every API request except `/api/health` needs `Authorization: Bearer <token>`; set it before the server is reachable from another machine | not set: no token |
| `AUDITIQ_CORS_ORIGINS` | comma-separated origins allowed to call the API from a browser | the Vite development server (`http://localhost:5173`) |
| `AUDITIQ_NO_DOTENV` | when set, `.env` is ignored (the tests set it) | not set |

`python -m auditiq status` shows which database is in use, the loaded ledger,
the active policy and the row count of every table. It never prints a password.

## 4. PostgreSQL

SQLite is enough to run everything. PostgreSQL gives typed money and dates,
concurrent readers, and a database role that confines the copilot's queries.

### A local server without installing a service

```bash
python scripts/pg_local.py init
```

```bash
python scripts/pg_local.py start
```

`init` needs the PostgreSQL binaries unpacked at `%LOCALAPPDATA%/auditiq/pgsql`
(the Windows zip archive from EnterpriseDB unpacks to a `pgsql` folder; another
location can be given in `AUDITIQ_PG_HOME`). It creates a cluster that listens
on localhost port 5544 only, the user `auditiq` with a random password, the
databases `auditiq` and `auditiq_test`, the role `auditiq_reader`, and writes
the two URLs to `.env`. `stop` and `status` do what they say. The server does
not start with Windows: run `start` after a reboot.

### In a container

`deploy/postgres/docker-compose.yml` starts PostgreSQL 17 with the same
databases and role. It was not run on the machine this project was developed
on, which has no Docker.

### After switching backend

The two backends are separate stores. After pointing `.env` at PostgreSQL, load
it as in section 2 (`setup`, then `run`). To go back to SQLite, remove
`AUDITIQ_DATABASE_URL` from `.env`.

Measured on the development laptop (Intel i5-1235U, 16 GB) with PostgreSQL:
`setup` with the 20,000-invoice ledger takes under two minutes including
embedding the policy passages, and `run --config C1` over all 20,000 invoices
takes about three minutes (the ledger is read in bulk for a batch run).

## 5. The chat model

Configurations C2 to C5 and the copilot need a chat model behind an
OpenAI-compatible endpoint.

### Local, with Ollama

```bash
ollama pull qwen2.5:7b
```

```bash
ollama create qwen2.5:7b-ctx12k -f deploy/ollama/Modelfile
```

```bash
python -m auditiq check-llm
```

The second command matters. Ollama serves a context window of 4,096 tokens by
default and cuts a longer prompt without an error, so the model would answer a
question it only partly saw. The longest prompt of the pipeline is about 7,200
tokens with its reply; `deploy/ollama/Modelfile` sets the window to 12,288.
Set `AUDITIQ_LLM_CONTEXT` to the same number so that the client refuses a
prompt that would not fit.

**Speed.** On the development laptop, which has no GPU, the 7B model reads a
prompt at 7 to 12 tokens per second while other programs are open, so one
model call takes two to seven minutes and one invoice under C3 takes about ten.
That is enough to see the pipeline work on a handful of invoices and far too
slow for the benchmark (1,200 invoices per ledger, several calls each). The
benchmark needs a GPU or a hosted endpoint.

### Hosted

Set `AUDITIQ_LLM_BASE_URL`, `AUDITIQ_LLM_MODEL` and `AUDITIQ_LLM_API_KEY` to
the provider's values and run `check-llm`. If the provider rejects
`response_format` or `seed`, set `AUDITIQ_LLM_JSON_MODE=0` or
`AUDITIQ_LLM_SEND_SEED=0`.

### The response cache

Every reply is stored in `.auditiq/llm_cache.sqlite`, keyed by the whole
request. A repeated run makes no new calls; an interrupted run continues
without paying twice; C3, C4 and C5 share their agent calls. Delete the file
to force fresh calls, or pass `--no-cache` where a command offers it.

## 6. The embedding model

```bash
ollama pull nomic-embed-text
```

```bash
python -m auditiq policy embed
```

With `AUDITIQ_EMBED_MODEL` set, `setup` embeds the passages itself; `policy
embed` is for a database that was set up before. `policy search` then ranks by
meaning; `--mode lexical` forces the wording-based ranking.

## 7. Everyday commands

| Command | Does |
|---|---|
| `python -m auditiq status` | backend, ledger, active policy, row counts |
| `python -m auditiq ledger check ledger.xlsx` | check a ledger (an Excel workbook with one sheet per table, or a .zip archive of the five CSV files; every column of the store must be present) without loading it |
| `python -m auditiq ledger import ledger.xlsx` | replace the ledger, and its audit results, with a checked one; then `run --config C1` |
| `python -m auditiq ledger export data/large_seed_505 ledger.xlsx` | write a dataset as a workbook, one sheet per table |
| `python -m auditiq run --config C1` | audit every invoice with the controls |
| `python -m auditiq run --config C5 --invoice INV40042 INV40043` | audit chosen invoices with the full pipeline |
| `python -m auditiq audit --invoice INV40042 --config C5 --review` | audit one invoice and decide it at the prompt |
| `python -m auditiq show --invoice INV40042` | the stored audit pack and audit trail |
| `python -m auditiq queue` | results waiting for review |
| `python -m auditiq decide --result 17 --decision approve --reviewer "A. Auditor"` | record a decision; `override` needs `--justification` |
| `python -m auditiq policy search "bill raised on the weekend"` | passages with document and page |
| `python -m auditiq policy activate 2.6` | switch the policy the next audit applies |
| `python -m auditiq policy ingest my_policy.pdf` | add a policy PDF for search and citation |
| `python -m auditiq policy adopt company_policy.pdf --activate` | read the thresholds from a policy PDF in the template's wording and make it the policy the audit applies |
| `python -m auditiq policy adopt company_policy.pdf --llm` | a policy in its own wording: the model proposes rules and thresholds, code verifies them against the document, and the command shows what it found |
| `python -m auditiq policy adopt company_policy.pdf --llm --accept-verified --reviewer "A. Auditor"` | confirm the verified values and adopt; supply any other value with `--set 2.1.1.amount_tolerance_pct=0.5` |
| `python -m auditiq ask "Why is INV40042 high risk?"` | a cited answer |
| `python -m auditiq ask-data "Which five vendors have the most invoices waiting for review?"` | one read-only query |
| `python -m auditiq export --out exports` | every table as CSV |
| `python -m auditiq graph --config C5` | the pipeline as a Mermaid diagram |
| `python -m auditiq serve --port 8000` | the web application and the REST API (`--host 0.0.0.0` to listen on every interface; set `AUDITIQ_API_TOKEN` first) |
| `python -m streamlit run app/dashboard.py` | the Streamlit dashboard |

## 8. Reproducing the evaluation

In this order. Steps 1 to 3 need no model.

| Step | Command | Writes |
|---|---|---|
| 1. Policy text from the registry | `python policy/build_policy.py` | `policy/SOP_v*.md`, `policy_v2.6.json` |
| 2. Datasets | `python -m auditiq_bench` | `data/<name>/` |
| 3. Baselines, controls, policy swap | `python -m evaluation.run_all` | `results/summary.md`, `results/<name>/` |
| 4. History cap check | `python -m evaluation.history_cap` | `results/history_cap.md` |
| 5. Policy retrieval | `python -m evaluation.retrieval_eval --out results/retrieval.md` | `results/retrieval.md` |
| 5a. Policy change | `python -m evaluation.policy_change` | `results/policy_change.md`, the table and the figure |
| 5b. Held-out policy documents | `python -m evaluation.policy_heldout` | `results/policy_heldout.md` |
| 5c. Robustness of the policy reader | `python -m evaluation.policy_robustness` | `results/policy_robustness.md` |
| 5d. A policy change in the application | `python -m evaluation.application_demo` | `results/application_demo.md` |
| 5e. Scalability of the control stage | `python -m evaluation.scalability` | `results/scalability.md` |
| 5f. Policies in their own wording (needs a model) | `python -m evaluation.policy_llm_eval` | `results/policy_llm.md` |
| 6. Pilot of the LLM configurations | `python -m evaluation.run_pilot --dataset data/pilot_seed_909 --ids-file evaluation/pilot_ids.txt --tag pilot20` | `results/pilot_seed_909/pilot20.md` |
| 6a. The LLM configurations on a sample of a benchmark ledger | `python -m evaluation.sample_ids --dataset data/bench_seed_101 --out evaluation/bench101_sample_ids.txt`, then `python -m evaluation.run_pilot --dataset data/bench_seed_101 --ids-file evaluation/bench101_sample_ids.txt --tag sample34 --configs C1 C3 C4 C5 C2` | `results/bench_seed_101/sample34.md` |
| 6b. Figures of the results | `python -m evaluation.figures` | `results/figures/*.png` |
| 7. One LLM configuration on a benchmark ledger | `python -m evaluation.run_config --dataset data/bench_seed_101 --config C5` | `results/bench_seed_101/C5.jsonl` |
| 8. Comparison | `python -m evaluation.report --dataset data/bench_seed_101 results/bench_seed_101/C*.jsonl --compare C3:C2 C4:C3 C5:C4` | a table |

Rules that keep the results honest:

- Prompts and settings are tried on `pilot_seed_909` only and frozen before a
  benchmark ledger is audited. The prompt hash is stored with every run.
- A number is reported only if a script in this repository produced it.
- A pilot is reported as a pilot.

## 9. Backup and export

- **SQLite:** copy `.auditiq/auditiq.db` while nothing is writing.
- **PostgreSQL:** `pg_dump` with the URL in `.env`.
- **Either:** `python -m auditiq export --out <folder>` writes every table as
  CSV (the embedding vectors are left out), with a `README.md` that says what
  was exported. `exports/large_seed_505_C1/` is such a snapshot.

Datasets need no backup: `python -m auditiq_bench` regenerates them
byte-identically, and `python -m auditiq_bench.overview --verify` checks the
files against their recorded hashes.

## 10. Tests and lint

```bash
python -m pytest
```

```bash
ruff check .
```

The tests call no model: the model is replaced by a scripted stand-in, so they
check what the pipeline asks and how it handles replies, not how well a model
audits. Tests that use a database run on SQLite and, when
`AUDITIQ_TEST_DATABASE_URL` names a reachable database, on PostgreSQL too; each
PostgreSQL test works in its own schema and removes it. The tests never read
the application's settings from `.env`, so they cannot touch the working
database. `.github/workflows/ci.yml` (at the root of the repository) runs lint and
tests on both backends on every push.

The frontend has its own checks, run from `frontend/`:

```bash
npm run lint
```

```bash
npm run typecheck
```

```bash
npm test
```

```bash
npm audit --omit=dev
```

The tests run in Node with a simulated browser and a mocked API, so they need
neither the server nor a GPU; the 3D scenes are rendered with React Three
Fiber's test renderer. CI runs these checks and a production build in a second
job.

After changing the schema or a column's meaning, regenerate the data
dictionary; after regenerating datasets, the overview:

```bash
python -m auditiq.datadict
```

```bash
python -m auditiq_bench.overview
```

## 11. Troubleshooting

| Symptom | Cause and remedy |
|---|---|
| `error: cannot connect to PostgreSQL at localhost:5544/auditiq` | The local server is not running: `python scripts/pg_local.py start`. Or remove `AUDITIQ_DATABASE_URL` from `.env` to use SQLite. |
| `status` shows an empty ledger after switching backend | The backends are separate stores: run `setup` and `run` again. |
| `the prompt needs about N tokens ... more than the context` | The prompt does not fit `AUDITIQ_LLM_CONTEXT`. Raise the server's context (section 5) and the variable together. |
| A local model's replies ignore the instructions or lose the JSON format | The server cut the prompt. Create the model with the larger context and set `AUDITIQ_LLM_CONTEXT`. |
| A model call times out | Raise `AUDITIQ_LLM_TIMEOUT`; on a CPU-only machine one call can take several minutes. |
| `ask` or `ask-data` fails with HTTP 400 mentioning `response_format` or `seed` | Set `AUDITIQ_LLM_JSON_MODE=0` or `AUDITIQ_LLM_SEND_SEED=0`. |
| Policy search finds nothing for a paraphrased question | No embedding model is configured, so the ranking is lexical. Set `AUDITIQ_EMBED_MODEL` and run `policy embed`. |
| Ingestion reports an unverified clause | The PDF's text of that rule differs from the registry of the same version. Regenerate the PDF (`python -m auditiq policy make-pdfs`) or correct the registry. |
| A test of the data dictionary or the datasets overview fails | Regenerate the file with the command the failure message names. |
| `serve` answers 404 at `/` | The frontend has not been built: `cd frontend && npm ci && npm run build`. The API works without it. |
| The web application asks for an API token | `AUDITIQ_API_TOKEN` is set on the server; enter the same value. It is kept for the browser tab only. |
| A 3D view shows a message instead of the scene | The browser has no WebGL (or it is switched off). The tables on the same page show the same data. |
| The browser reports a CORS error during frontend development | Open the development server at `http://localhost:5173`, or add its origin to `AUDITIQ_CORS_ORIGINS`. |
