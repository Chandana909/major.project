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

Every response is JSON. Errors carry `detail`: a message, or for a refused
policy `{"message": ..., "problems": [...]}`. Requests that take long return
**202** with a job; poll `GET /api/jobs/{id}` until `status` is `done` (the
result is in `result`) or `failed` (the reason is in `error`). `done` and
`total` report progress where the work has steps.

| Method | Path | What it does | Answer |
|---|---|---|---|
| GET | `/api/health` | Version, backend, ledger, active policy, model; open without a token | 200 |
| GET | `/api/overview` | Counts by state, route and risk level; findings by rule; recent runs; vendors with most invoices waiting | 200 |
| GET | `/api/risk-map` | Every vendor with category, invoices, amount, invoices waiting, highest risk, blacklisting | 200 |
| GET | `/api/pipeline` | The stages and the stages of each configuration C1 to C5; open without a token | 200 |
| GET | `/api/queue?limit=` | Invoices waiting for review, highest weighted risk first | 200 |
| GET | `/api/invoices?q=&limit=` | Invoices by id or vendor name, with their latest route and state | 200 |
| GET | `/api/invoices/{id}?with_label=` | The records of an invoice, its vendor history, its latest result with audit pack and trail; the benchmark label on request | 200, 400, 404 |
| POST | `/api/results/{id}/decision` | Record a reviewer's decision: `approve`, `reject` or `override` (an override needs a justification) | 200, 400, 404 |
| POST | `/api/invoices/{id}/audit` | Audit one invoice again under a configuration; C2 to C5 need a model | 202 job, 400 |
| GET | `/api/policy` | Stored versions and how each was adopted, the rules of the active version, ingested documents, results under another version | 200 |
| POST | `/api/policy/activate` | Make a stored version the active one | 200, 404 |
| POST | `/api/policy/preview` | Upload a policy PDF (multipart); answers its thresholds, the changes against the active version, and whether it can be adopted | 200, 413, 415 |
| POST | `/api/policy/adopt` | Adopt a previewed document as a new policy version | 200, 422 |
| POST | `/api/policy/propose` | Let the model read a document in its own wording; answers the proposal with every value, its quote and its verification status | 202 job, 400 |
| POST | `/api/policy/confirm` | Adopt a proposal after the reviewer's confirmation, corrections and passages | 200, 400, 404, 422 |
| POST | `/api/policy/apply` | Audit the whole ledger again under the active version, with progress | 202 job |
| GET | `/api/search?q=&k=` | Search the policy documents (hybrid when an embedding model is configured, lexical otherwise) | 200, 400, 409 |
| POST | `/api/copilot/ask` | A question about the policy or an audited invoice, answered with citations | 202 job |
| POST | `/api/copilot/data` | A question about the data, answered by one checked read-only query; needs a model | 202 job, 400 |
| GET | `/api/jobs/{id}` | The state of a background job | 200, 404 |
| GET | `/api/results` | The measured results as the evaluation scripts wrote them under `results/` | 200 |

Background jobs run on threads of the server process, each with its own
database connection. They are kept in memory (the last 200), so a restart
forgets them; the work they did is in the database.

## 5. The frontend

### Stack

| Part | Choice |
|---|---|
| Language, build | TypeScript 5.6 (strict), Vite 6 |
| UI | React 18, React Router 7 |
| 3D | three.js 0.170, React Three Fiber 8, drei 9 (orbit controls, HTML labels, rounded boxes) |
| Tests | Vitest 4 with jsdom, Testing Library, React Three Fiber's test renderer |
| Lint | ESLint 9 with typescript-eslint and the React hooks rules |

Every dependency is pinned to an exact version in `package.json`, and
`package-lock.json` fixes the whole tree; `npm ci` installs it as recorded.

### Pages

| Route | Page | Shows |
|---|---|---|
| `/` | Overview | Counts of the audit; the **risk constellation**, a 3D view of every vendor (sector = spending category, height = highest risk, size = number of invoices, pulsing = invoices waiting, violet = blacklisted; click a vendor to see its invoices); findings by rule; vendors with most invoices waiting; recent runs |
| `/review` | Review queue | Invoices waiting for a reviewer, filtered by text and risk level |
| `/invoice`, `/invoice/:id` | Invoices | Search; for one invoice: route, both risk scores, every finding with its evidence, confidence terms and citation, findings removed by the challenger, the records, the audit trail with tokens and time per model call, the decision form, a new audit under any configuration, and the benchmark label on request |
| `/policy` | Policy | Versions and activation; upload of a policy PDF with the changes it makes, adoption, reading by the model with the reviewer's confirmation; re-auditing the ledger under the active version with progress; the rules; policy search |
| `/copilot` | Copilot | Questions about the policy and invoices, with citations; questions about the data, with the query that answered them |
| `/pipeline` | Pipeline | The stages of the audit as a **3D graph**; choosing a configuration lights the stages it runs |
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

### 3D views

Each 3D view sits in `SceneFrame`: a canvas with orbit controls (drag to turn,
scroll to zoom), a fallback message when the browser has no WebGL, and an
error boundary that shows the same message if the view fails. Every 3D view
has a table or list on the same page with the same data, so nothing is shown
only in 3D. The constellation draws all vendors as one instanced mesh, with one
colour per instance, so the number of vendors does not change the number of
draw calls.

### Size

The production build splits the code so that three.js loads only with a page
that draws a 3D view (overview, pipeline, results):

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

- **API** (`tests/test_api.py`, 10 tests, on SQLite and on PostgreSQL): the
  status endpoints; the review flow from queue to recorded decision; an audit
  job; a policy previewed, adopted and applied to the ledger; a policy in its
  own wording proposed and confirmed (with a scripted model); search and the
  copilot without a model; the results; the token; 503 for an unreachable
  database; the built frontend with client-side routes.
- **Frontend** (26 tests): the API client (token, error messages, uploads, job
  polling); formatting and the policy and results helpers; the geometry of the
  3D views; the three 3D scenes rendered with React Three Fiber's test renderer
  (instances per vendor, stages per configuration, bars per policy); and the
  pages against a mocked API (overview with the WebGL fallback and retry after
  an error, queue filters, invoice findings and records, decision validation
  and recording, policy preview and adoption, a document the patterns cannot
  read, the results, the token prompt, an unknown route).

CI runs both: the Python job (ruff, the tests on SQLite and PostgreSQL) and the
frontend job (`npm ci`, lint, typecheck, tests, build, and `npm audit` of the
packages shipped to the browser).

## 7. Limits

- One server process: background jobs live in its memory and are lost on a
  restart. A deployment for many users would put them in a queue (for example
  a database table polled by workers).
- One shared token and no user accounts or roles; the reviewer's name is not
  an authenticated identity.
- The 3D views need WebGL; without it the pages show the tables only.
