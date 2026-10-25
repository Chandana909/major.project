# Security

What AuditIQ protects, against whom, with which guard, and what it does not
protect. Each guard below names the code that implements it and the test that
checks it. The review that added the last of them is
[CODE_REVIEW.md](CODE_REVIEW.md).

## 1. What there is to protect

| Asset | Why it matters |
|---|---|
| The ledger (invoices, vendors, approvals) | An organisation's financial records: confidential |
| Audit results, findings, the trail and review decisions | The audit's evidence: must not be altered or lost |
| The policy store | A forged or misread policy changes every decision the controls take |
| The benchmark labels (`benchmark_labels`) | The ground truth of the evaluation: a model that could read them would score itself |
| Credentials | The database URL, the API token and a hosted model's key, in `.env` |

## 2. Who and what is not trusted

- **A client of the API** without the token, or with it.
- **The content of the ledger and of the documents.** An invoice description,
  a goods-receipt remark or a policy document is written by someone outside
  the audit, and it reaches the model. It may contain instructions
  ("prompt injection").
- **Uploaded files**: policy PDFs, workbooks, zip archives.
- **The model's replies.** Everything a model returns is parsed, checked and
  bounded before it has any effect.

## 3. The guards

**The API** (`auditiq/api.py`; tests in `tests/test_api.py`)

| Guard | How |
|---|---|
| Users and roles | `python -m auditiq user add <name> --role viewer\|reviewer\|admin` creates a user and prints the user's token once; only its SHA-256 is stored (`api_users`). A viewer reads, a reviewer also records decisions and audits invoices again, an admin also changes the policy and the ledger; every endpoint states the role it needs (API.md) and answers 403 below it. A decision records the signed-in user's name, not a typed one. A user can be disabled |
| Shared token | `AUDITIQ_API_TOKEN` acts as an admin, compared in constant time (`hmac.compare_digest`). With users or a shared token, every endpoint but `/api/health` and `/api/pipeline` needs `Authorization: Bearer <token>`; with neither, the server is open (development) |
| Origins | CORS only for the origins in `AUDITIQ_CORS_ORIGINS` (default: the development server) |
| Headers | Every answer carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` and `Referrer-Policy: no-referrer`; the web application's pages also a Content-Security-Policy that allows scripts, connections and fonts from the server only (`api.CONTENT_SECURITY_POLICY`; style attributes are allowed for the 3D views' labels) |
| Uploads | A policy PDF at most 20 MB and starting with `%PDF`; a ledger at most 100 MB, `.xlsx` or `.zip`, starting with `PK`; file names reduced to `[A-Za-z0-9._-]`; an upload is referred to by a hash id that is matched against a fixed pattern before it becomes a path |
| Archives that expand | A zip archive and a workbook (which is a zip container) are refused when their parts would unpack to more than 300 MB, before anything is unpacked (`ledger_import.py`) |
| A ledger replaced by mistake | Loading a ledger needs `replace=true`, and the ledger is checked first; with any problem nothing is replaced |
| Jobs that would collide | A ledger load is refused while an audit or another load runs, and a whole-ledger audit while another runs (409) |
| Static files | The web application's files are served only from inside its build folder; any other path gets `index.html` |
| Errors | A database that cannot be reached answers 503 with a message, never a traceback; a URL with a password is never printed |

**The model's output** (`auditiq/agents.py`, `auditiq/graph.py`; tests in
`tests/test_pipeline.py`)

- Replies must be JSON of the expected shape; a malformed finding is dropped
  and counted (`malformed_flags`).
- An agent may only raise findings under the rules of its remit; others are
  dropped and counted (`out_of_remit_flags`).
- The challenger can only remove an agent's finding, never add one; without a
  usable reply every finding is kept.
- The deterministic controls run on every invoice whatever the model says, and
  no model output changes them. Every escalated invoice waits for a person.

**The copilot's SQL** (`auditiq/copilot.py`; tests in
`tests/test_policy_docs.py`). A data question is answered by one SELECT that
the model writes, and the model reads the ledger, so the statement is treated
as written by someone who wants what it should not see.

1. It must be a single `SELECT` (or `WITH ... SELECT`).
2. It may not name any table outside the allow-list: the ledger tables, the two
   views, `audit_flags`, `review_decisions` and `policy_clauses`. Not the
   labels, the trail, the policy documents or the store's own tables.
3. It may not call a function that changes the session's role or settings, or
   runs a query given as text: `set_config`, `current_setting`,
   `query_to_xml` and the other `*_to_xml` functions, `ts_stat`, `dblink`,
   `lo_*`; nor use Unicode-escaped names (`U&"..."`).
4. It runs read-only, with a 10-second limit and at most 200 rows. On SQLite an
   authorizer refuses every other table at execution. On PostgreSQL it runs as
   the role `auditiq_reader`, which holds SELECT on the allow-list only; a
   server without that role refuses data questions.

Guard 3 and the refusal without the role were added on 21 October 2026, after
a probe showed that on PostgreSQL a statement could reset its role with
`set_config('role', ...)` and then read the labels through
`query_to_xml('select ... from bench' || 'mark_labels', ...)`, a name the
check in guard 2 never saw (CODE_REVIEW.md, finding 1).

**Policies** (`auditiq/policy_extract.py`, `auditiq/policy_llm.py`)

- A document is adopted only when every rule's thresholds are read; a
  defective or ambiguous one is refused with the reason (16 edited documents
  measured, RESULTS.md, Section 3.4).
- A document in its own wording goes through the model, but every value must
  come with a quote that the code finds in the document, and a person confirms
  the values before anything is stored.
- A stored version is never replaced unless the request says so.

**Records** (`auditiq/db.py`). Results are added, never overwritten: a new
audit of an invoice is a new result. A review decision is stored beside the
result with the reviewer's name, and an override needs a written
justification. Each result keeps its trail of stages, with the model's tokens
and times.

**Secrets.** `.env` is ignored by git; tests never read the application's
settings from it (`AUDITIQ_NO_DOTENV`). `auditiq status` and the logs show a
database's host, never its password. The browser keeps the API token in
`sessionStorage`, which is cleared when the tab is closed.

**Dependencies.** CI audits the Python dependencies (`pip-audit`) and the
frontend's (`npm audit --omit=dev`). The lower bounds in `pyproject.toml`
exclude the releases of `python-multipart`, `starlette` and `python-dotenv`
with published vulnerabilities.

## 4. What is not protected

- **Tokens, not a sign-in service.** Users have tokens and roles, but there
  is no single sign-on, no expiry and no password: a token is a secret to keep
  like one, and a user who leaves must be disabled (`user disable`). With no
  users and no shared token the server is open, which is meant for development
  only. On an open server or with the shared token, a reviewer's name is typed.
- **No TLS, rate limit or body-size limit of its own.** Run the server behind
  a reverse proxy that terminates HTTPS, limits request rates and refuses
  bodies above the upload limits. The framework writes an upload to a
  temporary file before the size check sees it.
- **Prompt injection can still mislead a judgement.** It cannot change a
  control, the challenger can only remove, and a person reviews every escalated
  invoice; but a text in an invoice can still sway what an agent finds.
- **Data sent to the model.** The prompts carry invoice records. With a hosted
  endpoint those records leave the organisation; use a local model for
  confidential ledgers.
- **Pillow** is held below 13 by Streamlit, and its published fixes are in 13.
  AuditIQ decodes no uploaded image with it (PDFs are read by PyMuPDF; pandas
  opens workbooks read-only, which loads no embedded image), so the risk is
  low, but `pip-audit` reports it; CI ignores those advisories by name.
- **The policy allows inline styles** (`style-src 'unsafe-inline'`), which
  the 3D views' labels need; scripts are allowed from the server only. The
  interactive API documentation (`/api/docs`) loads its viewer from a CDN and
  is not under the policy.
- **Jobs live in memory.** A restart forgets running jobs (their stored work
  remains).
- **The SQLite file** is protected only by the file system's permissions.

## 5. Before a deployment

1. Create a user for every person (`python -m auditiq user add`), with the
   least role each needs, and set `AUDITIQ_CORS_ORIGINS` to the application's
   address. A shared token (`AUDITIQ_API_TOKEN`) is for automation only.
2. Put the server behind a reverse proxy with HTTPS, a request-rate limit and a
   body limit of 100 MB.
3. On PostgreSQL, create the role `auditiq_reader` (`deploy/postgres/init.sql`
   or `python scripts/pg_local.py init`), and give the application its own
   database user rather than a superuser.
4. Use a local model, or an endpoint whose terms allow the data.
5. Back up the store (OPERATIONS.md, Section 9), and keep the dependencies
   current (`pip-audit`, `npm audit`).
