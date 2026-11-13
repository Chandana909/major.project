# The web application

AuditIQ has a REST API (`auditiq/api.py`, FastAPI) and a web frontend
(`frontend/`, React and TypeScript, with 3D views in React Three Fiber). The
frontend is a single-page application that talks only to the API; the API is a
thin layer over the same modules the command line uses (`service`, `db`,
`policy_extract`, `policy_llm`, `copilot`), so a decision taken in the browser
is the same decision the command line would take. The Streamlit dashboard
(`app/dashboard.py`) is kept as the lightweight alternative.

```
browser ──HTTP──> /            the built frontend (frontend/dist), client-side routes
                  /api/...     REST API ──> service, db, policy_extract, policy_llm, copilot
                                         ──> SQLite or PostgreSQL; optional chat and embedding models
                  /api/docs    OpenAPI description, interactive
```

## 1. Running it

Build the frontend once (Node 20 or later), then start the server:

```bash
cd frontend && npm ci && npm run build
```

```bash
python -m auditiq serve
```

The application is at http://127.0.0.1:8000 and the API description at
http://127.0.0.1:8000/api/docs. `serve` takes `--host` and `--port`; it serves
the database configured in `.env` (SQLite by default, PostgreSQL when
`AUDITIQ_DATABASE_URL` is set; see [OPERATIONS.md](OPERATIONS.md)). Without a
build, the API still runs and `/` answers 404.

For frontend development, run the API as above and the Vite development
server, which reloads on every change and forwards `/api` to port 8000:

```bash
cd frontend && npm run dev
```

The development server is at http://localhost:5173.

## 2. Settings

| Variable | Default | Effect |
|---|---|---|
| `AUDITIQ_API_TOKEN` | unset | When set, every `/api` request except `/api/health` needs `Authorization: Bearer <token>`. The frontend asks for the token when the API answers 401 and keeps it for the browser tab only (`sessionStorage`). |
| `AUDITIQ_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Origins allowed to call the API from a browser. The built frontend is served from the API's own origin and needs no entry. |
| `AUDITIQ_DATABASE_URL`, `AUDITIQ_DB` | `.auditiq/auditiq.db` | The store, as for the command line: the PostgreSQL URL if set, else the SQLite file. |
| `AUDITIQ_LLM_*`, `AUDITIQ_EMBED_*` | unset | The chat and embedding models, as for the command line. Without a chat model the application runs C1 only, reads policies by pattern only, and the copilot answers with retrieved passages instead of a written answer. |

## 3. Security

- **Binding.** `serve` listens on 127.0.0.1 unless `--host` says otherwise.
  Before exposing it, set `AUDITIQ_API_TOKEN` and put the server behind a
  reverse proxy that terminates TLS.
- **Token.** A single shared bearer token, compared in constant time. There are
  no user accounts: the reviewer's name on a decision is the name typed in the
  form, recorded with the decision in the audit trail.
- **Uploads.** A policy upload is read up to 20 MB (413 above), must start with
  the PDF signature (415 otherwise), and is stored under `.auditiq/uploads/`
  under a random 16-hex-digit id; later requests refer to it by that id only, and
  an id that is not 16 hex digits is refused before any file is touched.
- **Input.** Every request body is a Pydantic model with types and length
  limits; invoice ids must match `[A-Z0-9_-]{1,40}`.
- **Data questions.** The copilot's data questions run as one checked query: a
  single `SELECT` that names only tables of an allow-list, run on a read-only
  connection with a row limit and a time limit, and on PostgreSQL as the role
  `auditiq_reader` when it exists ([ARCHITECTURE.md](ARCHITECTURE.md)).
- **Static files.** The frontend route resolves a path inside `frontend/dist`
  only; anything else gets `index.html`, and `/api/...` paths that do not exist
  get 404, never the page.
- **Errors.** A database that cannot be reached answers 503 with the reason;
  a failed background job reports its error type and message, and the full
  trace goes to the server log.

## 4. API

The reference of every endpoint, with its parameters, body and answers, is
[API.md](API.md) (generated from the code). Every response is JSON. Errors carry `detail`: a message, or for a refused
policy `{"message": ..., "problems": [...]}`. Requests that take long return
**202** with a job; poll `GET /api/jobs/{id}` until `status` is `done` (the
result is in `result`) or `failed` (the reason is in `error`). `done` and
`total` report progress where the work has steps.

| Method | Path | What it does | Answer |
|---|---|---|---|
| GET | `/api/health` | Version, backend, ledger, active policy, model; open without a token | 200 |
| GET | `/api/me` | Who the request is from: the user's name and role, the shared token, or an open server | 200, 401 |
| GET | `/api/overview` | Counts by state, route and risk level; findings by rule; recent runs; vendors with most invoices waiting | 200 |
| GET | `/api/risk-map` | Every vendor with category, invoices, amount, invoices waiting, highest risk, blacklisting | 200 |
| GET | `/api/pipeline` | The stages and the stages of each configuration C1 to C5; open without a token | 200 |
| GET | `/api/stream` | The Kafka ingestion layer: per topic, the messages in it, those processed, the lag and the outcomes; `configured: false` without a broker | 200 |
| GET | `/api/queue?limit=` | Invoices waiting for review, highest weighted risk first | 200 |
| GET | `/api/invoices?q=&limit=` | Invoices by id or vendor name, with their latest route and state | 200 |
| GET | `/api/invoices/{id}?with_label=` | The records of an invoice, its vendor history, the vendor e-mails that name it, its latest result with audit pack and trail; the benchmark label on request | 200, 400, 404 |
| POST | `/api/results/{id}/decision` | Record a reviewer's decision: `approve`, `reject` or `override` (an override needs a justification) | 200, 400, 404 |
| POST | `/api/invoices/{id}/audit` | Audit one invoice again under a configuration; C2 to C5 need a model | 202 job, 400 |
| GET | `/api/policy` | Stored versions and how each was adopted, the rules of the active version, ingested documents, results under another version | 200 |
| POST | `/api/policy/activate` | Make a stored version the active one | 200, 404 |
| POST | `/api/policy/preview` | Upload a policy PDF (multipart); answers its thresholds, the changes against the active version, and whether it can be adopted | 200, 413, 415 |
| POST | `/api/policy/adopt` | Adopt a previewed document as a new policy version | 200, 422 |
| POST | `/api/policy/simulate` | What a previewed document would do to the ledger before it is adopted: decisions moved, invoices newly flagged and cleared, route changes, findings by rule, money newly held (a dry run; nothing is stored) | 202 job, 400, 422 |
| POST | `/api/policy/propose` | Let the model read a document in its own wording; answers the proposal with every value, its quote and its verification status | 202 job, 400 |
| POST | `/api/policy/confirm` | Adopt a proposal after the reviewer's confirmation, corrections and passages | 200, 400, 404, 422 |
| POST | `/api/policy/apply` | Audit the whole ledger again under the active version, with progress | 202 job |
| POST | `/api/ledger` | Replace the ledger with an uploaded one (multipart: `file`, an .xlsx workbook with one sheet per table, or a .zip archive of the five CSV files; every column of the store must be present; and `replace=true`). The ledger is checked first; the job answers `loaded` and, if it was refused, the problems, with nothing replaced | 202 job, 400, 413, 415 |
| GET | `/api/search?q=&k=` | Search the policy documents: with a chat model the question is first restated in the policy's vocabulary and ranked by the hybrid ranker (the best measured setting), and the answer says what was searched; by meaning with embeddings alone; by wording otherwise | 200, 400, 409, 502 |
| POST | `/api/copilot/ask` | A question about the policy or an audited invoice, answered with citations | 202 job |
| POST | `/api/copilot/data` | A question about the data, answered by one checked read-only query; needs a model | 202 job, 400 |
| GET | `/api/jobs/{id}` | The state of a background job | 200, 404 |
| GET | `/api/results` | The measured results as the evaluation scripts wrote them under `results/` | 200 |

Background jobs run on threads of the server process, each with its own
database connection. They are kept in memory (the last 200 finished ones, and
every running one), so a restart forgets them; the work they did is in the
database. Jobs that would change the ledger under each other do not run
together: a ledger load is refused (409) while an audit or another load runs,
and so is a second audit of the whole ledger; the answer names the job that is
running.

## 5. The frontend

### Stack

| Part | Choice |
|---|---|
| Language, build | TypeScript 5.6 (strict), Vite 6 |
| UI | React 18, React Router 7 |
| 3D | three.js 0.170, React Three Fiber 8, drei 9 (orbit controls, HTML labels, rounded boxes) |
| Tests | Vitest 4 with jsdom, Testing Library, React Three Fiber's test renderer; Playwright 1.63 with Chromium for the end-to-end tests |
| Lint | ESLint 9 with typescript-eslint and the React hooks rules |

Every dependency is pinned to an exact version in `package.json`, and
`package-lock.json` fixes the whole tree; `npm ci` installs it as recorded.

### Pages

| Route | Page | Shows |
|---|---|---|
| `/` | Overview | Counts of the audit and the forensic signals (critical alerts, duplicates, three-way match, tax identity, splitting and timing, approval and vendor, vendors with findings, findings that did not hold payment); **audit coverage and quality**: the configurations behind the latest results, how many invoices the controls and the agents checked, and, on a benchmark ledger, the results against its answer key (docs/ANALYTICS.md); the composition of the audit (risk level, route, workflow); the **risk constellation**, a 3D view of every vendor (sector = spending category, height = highest risk, size = number of invoices, pulsing = invoices waiting, violet = blacklisted; click a vendor to see its invoices); the vendor risk matrix and the monthly trend; findings by rule; the escalation queue; vendors with most invoices waiting; the newest steps of the audit trail; high-risk vendors; recent runs; **loading a ledger** from a workbook or a zip archive, checked before it replaces the current one, and auditing it with the controls |
| `/review` | Review queue | Invoices waiting for a reviewer and what share of the audited invoices they are (the others approved automatically, with how many carry a medium or low finding), by risk level with the money each level puts at stake (counted over the whole queue; a level chosen is read from the server, as the list holds at most the 2,000 riskiest), filtered by text and risk level, each with the rules it breaks; the **queue constellation**, a 3D view of the same invoices (sector = the most severe rule each breaks, height = weighted risk, size = amount, pulsing = risk 70 and above; click an invoice to open it) |
| `/invoice`, `/invoice/:id` | Invoices | Search; for one invoice: route, both risk scores, every finding with its evidence, confidence terms and citation, findings removed by the challenger, the records, the audit trail with tokens and time per model call, the vendor e-mails that name the invoice, the decision form, a new audit under any configuration, and the benchmark label on request |
| `/policy` | Policy | **Which version governs which invoices** (each invoice is judged by the version in force on its date: the periods, the invoices in each and whether their results follow it, with an action to audit those that do not); versions and activation; the dry run of a document (how many invoices it would govern if adopted, and what would change as if it had always applied); the **policy knowledge graph** in 3D (rules around their version, with their parameters, the roles of the limits, the control functions and agents that check them and the pages that state them), "Ask the graph" with the facts it derives and the passages they cite, the relations of a node, every relation as a table (docs/POLICY_GRAPH.md); upload of a policy PDF with the changes it makes, adoption, reading by the model with the reviewer's confirmation; auditing again the invoices not under the version in force on their date, with progress; the rules; policy search |
| `/analytics` | Analytics | The forensic tests of the ledger: monthly volume, the **spend skyline** (3D, category by month), Benford's first-digit and first-two-digits tests, amounts against the approval limits and the invoices just under and just over each, weekdays, findings by category and rule, approvers, spend concentration (docs/ANALYTICS.md) |
| `/rings` | Vendor collusion | Vendors and approvers linked by shared identities and by approvals that carry more serious findings than the approver's role makes likely, tested with a false-discovery-rate correction; the **collusion network** in 3D, the rings or, when none passes, the leads below significance; the watch list, the tests and the rate of each role (docs/ANALYTICS.md) |
| `/kafka` | Kafka streams | Ingestion through Kafka from the browser: whether the broker answers, the **live topology** (sources, the producer, every topic and partition filled as the workers process it, the consumer groups and what they write; dots move while messages flow), publishing a ledger, a mailbox or a policy document, running the workers, the throughput, the outcomes per topic, the worker log, and the newest messages inside a topic (docs/STREAMING.md 6.1) |
| `/ai` | Agents & pipeline | The audit graph with what each stage has cost (steps, tokens, latency), a step-by-step **replay** of an invoice's audit from its trail with the stage lighting up, auditing an invoice now under any configuration, the agents with their remits and the configurations |
| `/knowledge` | Knowledge base | The knowledge pipeline (documents, passages, verification against the registry, embeddings), the **embedding map** of every passage in 3D (three principal components), the documents, the registry across versions with what each changes, and every passage with its page and whether it matches the registry |
| `/graph` | Knowledge graph | Two tabs: the policy knowledge graph and "Ask the graph" (docs/POLICY_GRAPH.md), and the audit findings graph (vendors, invoices with findings, rules, approvers, rings) in 3D with questions, the neighbourhood of any node and every relation as a table (docs/CASE_GRAPH.md) |
| `/rag` | RAG retrieval | A question traced through every step: what the graph recognises, the lexical, dense and fused rankings with their scores, the graph's facts, the context Ask AI would send with where each passage came from, the question in the embedding space, and the answer |
| `/ask` | Ask AI | Questions about the policy and invoices, with citations and the facts of the policy graph; questions about the data, with the query that answered them (`/copilot` leads here) |
| `/pipeline` | Pipeline | The **architecture diagram** of the whole platform: ten subsystems (sources, ingestion with the Kafka topics, the LangGraph audit engine and its agents, serving, policy as data, the store, the models, delivery), every component with its files and live figures, the data moving between them; choosing a configuration dims the stages it does not run; the configurations compared stage by stage; the stages as a **3D graph**; the **Kafka ingestion** panel: per topic, the messages processed, the lag and the outcomes (`GET /api/stream`) |
| `/results` | Results | The measured results: detection on the benchmark ledgers with intervals, detection per anomaly class, the policy-change experiment with a **3D bar view** of the share of invoices a frozen system decides wrongly under each policy, scalability, policy reading, and the real-model runs on small samples, marked as pilots (development ledger) or as the benchmark sample (34 invoices of ledger 101) |

### Structure

| Path | Content |
|---|---|
| `src/api/` | `types.ts` (the shapes of the API), `client.ts` (typed calls, the token, error messages, job polling) |
| `src/lib/` | Formatting (Indian digit grouping, risk colours, labels), the data hook, helpers for the policy and results pages |
| `src/components/` | The layout with navigation and server status, and the shared pieces: panels, figures, badges, risk meters, progress, errors |
| `src/three/` | The 3D views and their geometry (`layout.ts`, plain functions without rendering, tested on their own) and the frame every 3D view sits in |
| `src/pages/` | One file per page; each is loaded when first opened |
| `src/test/` | Test set-up, API fixtures, a fetch mock |
| `e2e/` | The end-to-end tests in a browser (Playwright); `playwright.config.ts` starts the server with `../scripts/e2e_server.py` |

### 3D views

Each 3D view sits in `SceneFrame`: a canvas with orbit controls (drag to turn,
scroll to zoom), a fallback message when the browser has no WebGL, and an
error boundary that shows the same message if the view fails. Every 3D view
has a table or list on the same page with the same data, so nothing is shown
only in 3D. The pages are light; the 3D views keep a dark canvas of their own.
The two constellations (vendors on the overview, invoices waiting on the review
queue) share one layout (`layoutVendors`, `layoutQueue` in `three/layout.ts`)
and one point field (`PointField`), which draws all points as one instanced
mesh with one colour per instance, so the number of points does not change the
number of draw calls. The spend skyline (`three/SpendSkyline.tsx`) raises one
bar per category and month; the collusion network (`three/RingNetwork.tsx`)
places each ring around its own centre on a golden-angle spiral and settles its
members with a few hundred steps of springs and repulsion
(`networkLayout` in `three/layout.ts`), drawing all links as one line segment
geometry. The architecture diagram of the Pipeline page is SVG drawn from a
description of the platform (`lib/architecture.ts`); a test checks that every
connection is drawn as horizontal and vertical runs and that no two components
overlap.

### Size

The production build splits the code so that three.js loads only with a page
that draws a 3D view (overview, review queue, pipeline, results):

| Chunk | Size | gzip | Loaded |
|---|---|---|---|
| application shell | 12 kB | 5 kB | always |
| React and the router | 183 kB | 61 kB | always |
| one page | 3 to 12 kB | 1 to 4 kB | when the page is opened |
| three.js, React Three Fiber, drei | 822 kB | 221 kB | with the overview, pipeline and results pages |

## 6. Tests

```bash
python -m pytest tests/test_api.py
```

```bash
cd frontend && npm test
```

```bash
cd frontend && npm run build && npm run e2e
```

- **API** (`tests/test_api.py`, 11 tests, on SQLite and on PostgreSQL): the
  status endpoints; the review flow from queue to recorded decision; an audit
  job; a policy previewed, adopted and applied to the ledger; a policy in its
  own wording proposed and confirmed (with a scripted model); search and the
  copilot without a model; the results; a ledger uploaded, refused with its
  problems or loaded; the token; 503 for an unreachable
  database; the built frontend with client-side routes.
- **Frontend** (36 tests): the API client (token, error messages, uploads, job
  polling); formatting and the policy and results helpers; the geometry of the
  3D views (vendors and the invoices waiting placed in sectors, stages, bars);
  the 3D scenes rendered with React Three Fiber's test renderer (instances per
  vendor, stems only where asked, a clicked point handed to the page, stages per
  configuration, bars per policy); and the pages against a mocked API (overview
  with the WebGL fallback and retry after an error, queue filters, invoice
  findings, records and vendor e-mails, decision validation and recording,
  policy preview and adoption, a document the patterns cannot read, the
  results, the Kafka topics with and without a broker, the token prompt, an
  unknown route).
- **End to end** (`e2e/app.spec.ts`, 10 tests in Chromium, about two minutes):
  the real server on a new SQLite store, the built application, no mock. The
  overview of the ledger set up from the command line; a workbook loaded
  through the page (nothing is replaced before the confirmation) and audited
  with the controls (300 findings, 240 waiting for review on ledger 909); an
  escalated invoice opened from the queue and approved, after which the queue
  has one invoice fewer; an invoice found by vendor and by number and audited
  again; a policy PDF previewed, adopted and the ledger audited under it; the
  policy search; the results, pipeline (every configuration) and copilot pages;
  a page reloaded at its address and an unknown address. An error in the
  browser's console fails a test. The first run installs the browser:
  `npx playwright install chromium`.

CI runs all three: the Python job (ruff, the tests on SQLite and PostgreSQL),
the frontend job (`npm ci`, lint, typecheck, tests, build, and `npm audit` of
the packages shipped to the browser) and the e2e job (the build and the
browser tests).

## 7. Limits

- One server process: background jobs live in its memory and are lost on a
  restart. A deployment for many users would put them in a queue (for example
  a database table polled by workers).
- Users have tokens and roles (viewer, reviewer, admin), not passwords or a
  single sign-on service; on an open server or with the shared token the
  reviewer's name is typed (SECURITY.md).
- The 3D views need WebGL; without it the pages show the tables only.
