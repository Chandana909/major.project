# REST API reference

All 53 endpoints of the AuditIQ API (`auditiq/api.py`, served by `python -m auditiq serve`). **This file is generated** from the application by `python -m auditiq.apidoc`; a test checks that it is current. How to use the API (jobs, errors, the token, how the web application calls it) is in [`WEB.md`](WEB.md), Section 4; the interactive version of this reference is at `/api/docs` on a running server.

**Common to every endpoint.** Requests and answers are JSON, except the two uploads (multipart). An error answer carries `detail`: a message, or `{"message", "problems"}`. When the server has users (`python -m auditiq user add`) or a shared token (`AUDITIQ_API_TOKEN`), every endpoint but the open ones needs the header `Authorization: Bearer <token>`, and the token's role must be at least the one listed: a `viewer` reads, a `reviewer` also records decisions and audits invoices again, an `admin` also changes the policy and the ledger. The shared token acts as an admin; a server with neither is open. Every answer carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` and `Referrer-Policy: no-referrer`.

**Background jobs.** An endpoint that answers 202 has started a job; `GET /api/jobs/{id}` reports it. Jobs that would change the ledger under one another are refused with 409 while the other runs: `load-ledger` waits for `apply-policy`, `audit`, `load-ledger`, `simulate`, `stream-work`; `apply-policy` waits for `apply-policy`, `load-ledger`, `stream-work`; `stream-work` waits for `apply-policy`, `load-ledger`, `stream-work`; `audit` waits for `load-ledger`; `simulate` waits for `load-ledger`.

| Method | Path | Role | Answers |
|---|---|---|---|
| GET | [`/api/health`](#get-apihealth) | open | 200, 503 |
| GET | [`/api/me`](#get-apime) | viewer | 200, 401, 503 |
| GET | [`/api/overview`](#get-apioverview) | viewer | 200, 401, 503 |
| GET | [`/api/analytics`](#get-apianalytics) | viewer | 200, 401, 503 |
| GET | [`/api/rings`](#get-apirings) | viewer | 200, 401, 422, 503 |
| GET | [`/api/leads`](#get-apileads) | viewer | 200, 401, 503 |
| GET | [`/api/sampling`](#get-apisampling) | viewer | 200, 400, 401, 422, 503 |
| GET | [`/api/reliability`](#get-apireliability) | viewer | 200, 401, 503 |
| GET | [`/api/program`](#get-apiprogram) | viewer | 200, 401, 503 |
| GET | [`/api/workpapers`](#get-apiworkpapers) | viewer | 200, 401, 422, 503 |
| GET | [`/api/trail/verify`](#get-apitrailverify) | viewer | 200, 401, 422, 503 |
| GET | [`/api/risk-map`](#get-apirisk-map) | viewer | 200, 401, 503 |
| GET | [`/api/stream`](#get-apistream) | viewer | 200, 401, 503 |
| GET | [`/api/stream/sources`](#get-apistreamsources) | viewer | 200, 401, 503 |
| POST | [`/api/stream/publish`](#post-apistreampublish) | admin | 202, 401, 403, 404, 409, 422, 503 |
| POST | [`/api/stream/work`](#post-apistreamwork) | admin | 202, 401, 403, 409, 422, 503 |
| GET | [`/api/stream/log`](#get-apistreamlog) | viewer | 200, 401, 422, 503 |
| GET | [`/api/stream/peek`](#get-apistreampeek) | viewer | 200, 401, 422, 503 |
| GET | [`/api/system`](#get-apisystem) | viewer | 200, 401, 503 |
| GET | [`/api/rag/trace`](#get-apiragtrace) | viewer | 200, 400, 401, 409, 422, 503 |
| GET | [`/api/knowledge`](#get-apiknowledge) | viewer | 200, 401, 503 |
| GET | [`/api/ai`](#get-apiai) | viewer | 200, 401, 503 |
| GET | [`/api/pipeline`](#get-apipipeline) | open | 200 |
| GET | [`/api/queue`](#get-apiqueue) | viewer | 200, 401, 422, 503 |
| GET | [`/api/invoices`](#get-apiinvoices) | viewer | 200, 401, 422, 503 |
| GET | [`/api/invoices/{invoice_id}`](#get-apiinvoicesinvoice_id) | viewer | 200, 400, 401, 404, 422, 503 |
| POST | [`/api/results/{result_id}/decision`](#post-apiresultsresult_iddecision) | reviewer | 200, 400, 401, 403, 404, 422, 503 |
| POST | [`/api/invoices/{invoice_id}/audit`](#post-apiinvoicesinvoice_idaudit) | reviewer | 202, 400, 401, 403, 409, 422, 503 |
| GET | [`/api/policy`](#get-apipolicy) | viewer | 200, 401, 503 |
| POST | [`/api/policy/activate`](#post-apipolicyactivate) | admin | 200, 401, 403, 404, 422, 503 |
| POST | [`/api/policy/preview`](#post-apipolicypreview) | admin | 200, 401, 403, 413, 415, 422, 503 |
| POST | [`/api/policy/adopt`](#post-apipolicyadopt) | admin | 200, 401, 403, 422, 503 |
| POST | [`/api/policy/simulate`](#post-apipolicysimulate) | admin | 202, 401, 403, 409, 422, 503 |
| POST | [`/api/policy/propose`](#post-apipolicypropose) | admin | 202, 400, 401, 403, 422, 503 |
| POST | [`/api/policy/confirm`](#post-apipolicyconfirm) | admin | 200, 400, 401, 403, 404, 422, 503 |
| POST | [`/api/policy/apply`](#post-apipolicyapply) | admin | 202, 401, 403, 409, 503 |
| POST | [`/api/ledger`](#post-apiledger) | admin | 202, 400, 401, 403, 409, 413, 415, 422, 503 |
| GET | [`/api/search`](#get-apisearch) | viewer | 200, 400, 401, 409, 422, 503 |
| GET | [`/api/policy/graph`](#get-apipolicygraph) | viewer | 200, 401, 404, 422, 503 |
| GET | [`/api/policy/graph/ask`](#get-apipolicygraphask) | viewer | 200, 400, 401, 404, 422, 503 |
| GET | [`/api/case-graph`](#get-apicase-graph) | viewer | 200, 401, 404, 422, 503 |
| GET | [`/api/case-graph/ask`](#get-apicase-graphask) | viewer | 200, 400, 401, 422, 503 |
| GET | [`/api/model`](#get-apimodel) | viewer | 200, 401, 503 |
| GET | [`/api/invoices/{invoice_id}/explain`](#get-apiinvoicesinvoice_idexplain) | viewer | 200, 400, 401, 404, 422, 503 |
| GET | [`/api/invoices/{invoice_id}/story`](#get-apiinvoicesinvoice_idstory) | viewer | 200, 400, 401, 404, 422, 503 |
| GET | [`/api/investigation`](#get-apiinvestigation) | viewer | 200, 401, 422, 503 |
| GET | [`/api/mail`](#get-apimail) | viewer | 200, 401, 503 |
| GET | [`/api/process`](#get-apiprocess) | viewer | 200, 401, 503 |
| POST | [`/api/agent/ask`](#post-apiagentask) | viewer | 202, 400, 401, 422, 503 |
| POST | [`/api/copilot/ask`](#post-apicopilotask) | viewer | 202, 401, 422, 503 |
| POST | [`/api/copilot/data`](#post-apicopilotdata) | viewer | 202, 400, 401, 422, 503 |
| GET | [`/api/jobs/{job_id}`](#get-apijobsjob_id) | viewer | 200, 401, 404, 422, 503 |
| GET | [`/api/results`](#get-apiresults) | viewer | 200, 401, 503 |

## Status

### GET `/api/health`

Version, backend, ledger, active policy and model; open without a token, for monitoring.

Role: none; open to everyone.

Answers:

- **200**: the answer, as JSON
- **503**: the database cannot be reached

### GET `/api/me`

Who the request is from: the user's name and role, or the shared token, or an open server.

Role: at least `viewer` when the server has users or a token.

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **503**: the database cannot be reached

### GET `/api/overview`

Counts by state, route and risk level; findings by rule; recent runs; the vendors with most invoices waiting; the newest steps of the audit trail; and the coverage of the latest results: which configurations produced them, what they did not check, and, on a benchmark ledger, how they compare with its answer key. Kept until the store changes.

Role: at least `viewer` when the server has users or a token.

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **503**: the database cannot be reached

### GET `/api/trail/verify`

Whether the audit record is as it was stored: the seal of every result (its decision, findings and audit pack), the hash chain of every audit-trail entry, including the reviewers' decisions, and the seal of every finished run are computed again and compared (auditiq/seal.py). `digest` is one value over the seals of all finished runs, to keep outside the store. Not cached: a change made directly in the database must show at once. `evidence` re-performs the extraction: whether the ledger still holds the records each latest result was based on, and which invoices' records changed after their audit.

Role: at least `viewer` when the server has users or a token.

| Parameter | In | Type | Default |
|---|---|---|---|
| `run` | query | integer or null | null |

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### GET `/api/risk-map`

One point per vendor: its invoices, amount, findings and the highest risk among its latest results. Kept until the store changes.

Role: at least `viewer` when the server has users or a token.

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **503**: the database cannot be reached

### GET `/api/stream`

The Kafka ingestion layer: per topic, the messages in it, those the workers have processed, the lag and the outcomes. `configured` is false without AUDITIQ_KAFKA_BOOTSTRAP; `error` says why a broker that is configured does not answer.

Role: at least `viewer` when the server has users or a token.

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **503**: the database cannot be reached

### GET `/api/system`

What is running: the store, the Kafka broker, the chat model (asked whether it answers), the embedding model and the active policy.

Role: at least `viewer` when the server has users or a token.

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **503**: the database cannot be reached

### GET `/api/ai`

The AI layer: the agents and their remits under the active policy, the configurations, what every stage of the audit trail has cost (calls, tokens, time), and the invoices whose latest result was audited by the agents, to replay.

Role: at least `viewer` when the server has users or a token.

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **503**: the database cannot be reached

### GET `/api/pipeline`

The stages of the pipeline and which configuration runs which: for the diagram of the frontend.

Role: none; open to everyone.

Answers:

- **200**: the answer, as JSON

### GET `/api/jobs/{job_id}`

The state of a background job: queued, running, done (with its result) or failed (with the reason).

Role: at least `viewer` when the server has users or a token.

| Parameter | In | Type | Default |
|---|---|---|---|
| `job_id` | path | string | required |

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **404**: no such record
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

## Analytics

### GET `/api/analytics`

Forensic views of the ledger: monthly volume and findings, spend by category and month, Benford's first-digit and first-two-digits tests, amounts against the approval limits of the active policy, weekdays, findings by vendor category and rule, approvers and spend concentration. Computed from the store, and kept until the store changes.

Role: at least `viewer` when the server has users or a token.

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **503**: the database cannot be reached

### GET `/api/rings`

Vendor collusion rings: vendors and approvers linked by a shared PAN or GSTIN, by invoices that carry another vendor's GSTIN, by concentrated approvals, or by approvals that carry more high or critical findings than the approver's role makes likely (one-sided binomial tests, Benjamini-Hochberg at a false discovery rate of 1 %). The `limit` strongest rings (1 to 200) come with their members and links, with the watch list of the most unusual approver-vendor pairs and the tests behind them. Kept until the store changes.

Role: at least `viewer` when the server has users or a token.

| Parameter | In | Type | Default |
|---|---|---|---|
| `limit` | query | integer | `40` |

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### GET `/api/leads`

Invoices for a reviewer under the two judgement rules the policy words most precisely, with its guide values: near duplicates (2.2.2: the same vendor, PO, GRN and amount as an earlier invoice under a re-keyed number) and structuring across days (4.1.2: invoices of one vendor and approving role within the guide window, each within the guide band below the role's limit, together above it). A lead is not a finding and changes no result. On a benchmark ledger, compared with its answer key. Kept until the store changes.

Role: at least `viewer` when the server has users or a token.

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **503**: the database cannot be reached

### GET `/api/sampling`

A monetary-unit sample (ISA 530) of the invoices approved without a person: the plan (sample size and sampling interval from the confidence, the tolerable and the expected misstatement, as a percentage of the approved amount), the random start and its seed (give the seed to draw the same sample again), and the invoices to examine. On a benchmark ledger, the answer key stands in for the examination: the misstatements the sample would find, the Stringer upper limit and whether it holds against the truth.

Role: at least `viewer` when the server has users or a token.

| Parameter | In | Type | Default |
|---|---|---|---|
| `confidence` | query | number | `annotation=float required=False default=0.95 alias='confidence' description='0.9, 0.95 or 0.99'` |
| `tolerable_pct` | query | number | `annotation=float required=False default=2.0 alias='tolerable_pct' metadata=[Gt(gt=0), Le(le=20)]` |
| `expected_pct` | query | number | `annotation=float required=False default=0.0 alias='expected_pct' metadata=[Ge(ge=0), Le(le=10)]` |
| `seed` | query | integer or null | `annotation=Union[int, NoneType] required=False default=None alias='seed' metadata=[Ge(ge=1)]` |

Answers:

- **200**: the answer, as JSON
- **400**: the request was refused; `detail` says why
- **401**: the server requires a token, and the request has none or a wrong one
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### GET `/api/reliability`

Whether the ledger can be relied on (ISA 500): references to documents not on file, approvals, the arithmetic of every invoice, date logic, goods received but not invoiced, gaps in the company's numbered series, vendor master data and audit coverage, each with its exceptions and the rule that decides them if one does; control totals; a SHA-256 fingerprint of every ledger table. Not cached: a change to the ledger must show at once.

Role: at least `viewer` when the server has users or a token.

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **503**: the database cannot be reached

### GET `/api/program`

The audit program: every test (the policy's rules, the leads, the analytics, the sample, the integrity checks) with the assertions (ISA 315) and fraud schemes (ACFE) it addresses and what it found; the assertions and schemes no test covers, with the scope limits; and on a benchmark ledger each scheme against the answer key. Kept until the store changes.

Role: at least `viewer` when the server has users or a token.

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **503**: the database cannot be reached

### GET `/api/workpapers`

The working papers as an Excel workbook (auditiq/workpapers.py): summary, findings, review queue, leads, sample, reliability, audit program and integrity. The report digest, in the workbook and in the header X-Report-Digest, is the same whenever the store is unchanged; `python -m auditiq workpapers --check` tells whether a workbook still matches the store. The sample's seed comes from the digest of the sealed runs unless one is given.

Role: at least `viewer` when the server has users or a token.

| Parameter | In | Type | Default |
|---|---|---|---|
| `seed` | query | integer or null | `annotation=Union[int, NoneType] required=False default=None alias='seed' metadata=[Ge(ge=1)]` |

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### GET `/api/case-graph`

The audited ledger as a knowledge graph (docs/CASE_GRAPH.md): vendors, invoices with findings, the rules they break, approvers and rings. Without `focus` the rings of the ledger; with it the neighbourhood of a vendor, an invoice, an approver, a ring or a rule, by id or name. Built by code from the audit; nothing is stored.

Role: at least `viewer` when the server has users or a token.

| Parameter | In | Type | Default |
|---|---|---|---|
| `focus` | query | string or null | null |
| `limit` | query | integer | `250` |

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **404**: no such record
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### GET `/api/case-graph/ask`

Ask the ledger graph: what the question names (invoices, vendors, approvers, rules, kinds of fraud), the facts that follow from the graph with the numbers they rest on, and the nodes used. No model is involved.

Role: at least `viewer` when the server has users or a token.

| Parameter | In | Type | Default |
|---|---|---|---|
| `q` | query | string | required |

Answers:

- **200**: the answer, as JSON
- **400**: the request was refused; `detail` says why
- **401**: the server requires a token, and the request has none or a wrong one
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### GET `/api/process`

Process mining of procure-to-pay (auditiq/process_mining.py): the event log of every invoice (PO raised, goods received, invoice dated, escalations, approval, due date), the process map (how often one step directly follows another and the median days between them), the variants, conformance to the reference path with how many deviating invoices the audit already flagged, cycle times by stage and approval time by role. Kept until the store changes.

Role: at least `viewer` when the server has users or a token.

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **503**: the database cannot be reached

## Stream (Kafka)

### GET `/api/stream/sources`

What can be published from the server: the generated ledgers, the mailboxes and the policy documents.

Role: at least `viewer` when the server has users or a token.

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **503**: the database cannot be reached

### POST `/api/stream/publish`

Publish a source to the Kafka topics (a job): a ledger's vendors and invoices (each with its PO, receipt and approvals), a mailbox's e-mails, or a policy document. The topics are created when missing. A ledger that would replace invoices of the store with different ones (another ledger with the same invoice numbers) is refused with 409; the store's own ledger can be published again.

Role: at least `admin` when the server has users or a token. Starts a background job of kind `stream-publish`.

JSON body (`PublishIn`):

| Field | Type | Default | Limits |
|---|---|---|---|
| `source` | `ledger` or `mailbox` or `policy` | required |  |
| `name` | string | required | at least 1 characters; at most 200 characters |
| `limit` | integer or null | null | at least 1; at most 1000000; ledger: publish only the first invoices |
| `activate` | boolean | `false` | policy: make the version active when it is stored |

Answers:

- **202**: a background job was started: poll `GET /api/jobs/{id}` until `status` is `done` or `failed`
- **401**: the server requires a token, and the request has none or a wrong one
- **403**: the token's user does not have the role the endpoint needs
- **404**: no such record
- **409**: the request conflicts with the state of the server; `detail` says with what
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### POST `/api/stream/work`

Run the stream workers until each topic has been idle for `idle_exit` seconds (a job): vendors, then invoices (audited with the controls as they arrive), e-mails (linked to their invoices) and policies.

Role: at least `admin` when the server has users or a token. Starts a background job of kind `stream-work`.

JSON body (`WorkIn`):

| Field | Type | Default | Limits |
|---|---|---|---|
| `kinds` | list of `vendor` or `invoice` or `email` or `compliance` | `['vendor', 'invoice', 'email', 'compliance']` |  |
| `idle_exit` | number | `4.0` | at least 1.0; at most 120.0; stop a topic after this many idle seconds |

Answers:

- **202**: a background job was started: poll `GET /api/jobs/{id}` until `status` is `done` or `failed`
- **401**: the server requires a token, and the request has none or a wrong one
- **403**: the token's user does not have the role the endpoint needs
- **409**: the request conflicts with the state of the server; `detail` says with what
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### GET `/api/stream/log`

The newest messages the workers processed: topic, partition, offset, key, outcome, detail, the result it produced and how long after it was produced it was processed.

Role: at least `viewer` when the server has users or a token.

| Parameter | In | Type | Default |
|---|---|---|---|
| `limit` | query | integer | `60` |
| `topic` | query | string or null | null |

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### GET `/api/stream/peek`

The newest messages of a topic as they sit in Kafka, with the fields that identify each.

Role: at least `viewer` when the server has users or a token.

| Parameter | In | Type | Default |
|---|---|---|---|
| `kind` | query | `vendor` or `invoice` or `email` or `compliance` | required |
| `n` | query | integer | `10` |

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

## Policy

### GET `/api/rag/trace`

Every step retrieval takes for a question, laid open: what the policy graph recognises and the facts it derives, each passage's lexical and dense score and rank, their reciprocal-rank fusion, the context Ask AI would give the model, and the passages and the question in the embedding space (three principal components).

Role: at least `viewer` when the server has users or a token.

| Parameter | In | Type | Default |
|---|---|---|---|
| `q` | query | string | required |
| `k` | query | integer | `5` |

Answers:

- **200**: the answer, as JSON
- **400**: the request was refused; `detail` says why
- **401**: the server requires a token, and the request has none or a wrong one
- **409**: the request conflicts with the state of the server; `detail` says with what
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### GET `/api/knowledge`

The knowledge layer: the ingested documents, every passage with its page, kind, rule and whether it matches the registry, the registry of every version, and the passages in the embedding space.

Role: at least `viewer` when the server has users or a token.

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **503**: the database cannot be reached

### GET `/api/policy`

The stored policy versions and how each was adopted, the rules of the active one, the ingested documents, and the timeline: which version governs the invoices of which dates (each invoice is judged by the version in force on its date), how many invoices of the ledger each governs and how many of those were last audited under another version.

Role: at least `viewer` when the server has users or a token.

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **503**: the database cannot be reached

### POST `/api/policy/activate`

Make a stored policy version the active one. It governs the invoices dated from its effective date on; the invoices before that date stay under the versions in force then.

Role: at least `admin` when the server has users or a token.

JSON body (`VersionIn`):

| Field | Type | Default | Limits |
|---|---|---|---|
| `version` | string | required | at least 1 characters; at most 40 characters |

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **403**: the token's user does not have the role the endpoint needs
- **404**: no such record
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### POST `/api/policy/preview`

Read a policy PDF without storing anything: what it states and how it differs from the active version.

Role: at least `admin` when the server has users or a token.

Multipart form:

| Field | Type | Default |
|---|---|---|
| `file` | file | `PydanticUndefined` |

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **403**: the token's user does not have the role the endpoint needs
- **413**: the upload is too large
- **415**: the upload is not of the expected type
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### POST `/api/policy/adopt`

Adopt a previewed policy document as a new version; refused with the problems if it cannot be executed.

Role: at least `admin` when the server has users or a token.

JSON body (`AdoptIn`):

| Field | Type | Default | Limits |
|---|---|---|---|
| `upload_id` | string | required |  |
| `activate` | boolean | `true` |  |
| `replace` | boolean | `false` |  |

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **403**: the token's user does not have the role the endpoint needs
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### POST `/api/policy/simulate`

What a previewed policy document would do to the ledger before it is adopted: every invoice audited by the controls under the active policy and under the document, in memory (a job); nothing is stored.

Role: at least `admin` when the server has users or a token. Starts a background job of kind `simulate`.

JSON body (`AdoptIn`):

| Field | Type | Default | Limits |
|---|---|---|---|
| `upload_id` | string | required |  |
| `activate` | boolean | `true` |  |
| `replace` | boolean | `false` |  |

Answers:

- **202**: a background job was started: poll `GET /api/jobs/{id}` until `status` is `done` or `failed`
- **401**: the server requires a token, and the request has none or a wrong one
- **403**: the token's user does not have the role the endpoint needs
- **409**: the request conflicts with the state of the server; `detail` says with what
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### POST `/api/policy/propose`

Let the model read a policy in its own wording (a background job); the result waits for confirmation.

Role: at least `admin` when the server has users or a token. Starts a background job of kind `policy-reading`.

JSON body (`AdoptIn`):

| Field | Type | Default | Limits |
|---|---|---|---|
| `upload_id` | string | required |  |
| `activate` | boolean | `true` |  |
| `replace` | boolean | `false` |  |

Answers:

- **202**: a background job was started: poll `GET /api/jobs/{id}` until `status` is `done` or `failed`
- **400**: the request was refused; `detail` says why
- **401**: the server requires a token, and the request has none or a wrong one
- **403**: the token's user does not have the role the endpoint needs
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### POST `/api/policy/confirm`

Adopt a model's proposal after the reviewer's confirmation, corrections and quoted passages.

Role: at least `admin` when the server has users or a token.

JSON body (`ConfirmIn`):

| Field | Type | Default | Limits |
|---|---|---|---|
| `upload_id` | string | required |  |
| `reviewer` | string | empty | at most 120 characters |
| `accept_verified` | boolean | `false` |  |
| `values` | object | empty | `{"<rule>.<parameter>": <value>}` |
| `passages` | object | empty | `{"<rule>": "<passage of the document>"}` |
| `version` | string or null | null |  |
| `activate` | boolean | `true` |  |
| `replace` | boolean | `false` |  |

Answers:

- **200**: the answer, as JSON
- **400**: the request was refused; `detail` says why
- **401**: the server requires a token, and the request has none or a wrong one
- **403**: the token's user does not have the role the endpoint needs
- **404**: no such record
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### POST `/api/policy/apply`

Bring the audit results in line with the policy timeline (a background job): every invoice the active version governs, and every invoice last audited under a version that does not govern it, is audited again with the controls under the version in force on its date. An invoice approved under the rules of its day is not judged by a version that took effect after it; the other invoices keep their results.

Role: at least `admin` when the server has users or a token. Starts a background job of kind `apply-policy`.

Answers:

- **202**: a background job was started: poll `GET /api/jobs/{id}` until `status` is `done` or `failed`
- **401**: the server requires a token, and the request has none or a wrong one
- **403**: the token's user does not have the role the endpoint needs
- **409**: the request conflicts with the state of the server; `detail` says with what
- **503**: the database cannot be reached

### GET `/api/search`

Search the policy documents. With a chat model the question is first restated in the documents' vocabulary and ranked by the hybrid ranker, the best measured setting (RESULTS.md, Section 8); without one, by meaning (embeddings) or by wording.

Role: at least `viewer` when the server has users or a token.

| Parameter | In | Type | Default |
|---|---|---|---|
| `q` | query | string | required |
| `k` | query | integer | `4` |

Answers:

- **200**: the answer, as JSON
- **400**: the request was refused; `detail` says why
- **401**: the server requires a token, and the request has none or a wrong one
- **409**: the request conflicts with the state of the server; `detail` says with what
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### GET `/api/policy/graph`

The policy as a knowledge graph, built by code from the clause registry, the ingested documents and the code that checks each rule: the version (default: the active one), its sections, rules, parameters, the roles of the approval limits, the control functions and agents that check the rules, the pages that state them, and what the other stored versions change (docs/POLICY_GRAPH.md).

Role: at least `viewer` when the server has users or a token.

| Parameter | In | Type | Default |
|---|---|---|---|
| `version` | query | string or null | null |

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **404**: no such record
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### GET `/api/policy/graph/ask`

Ask the policy graph: what the question names (rules, versions, roles, amounts, agents, severities), the facts that follow from the graph with the passage each cites, the passages, and the nodes used.

Role: at least `viewer` when the server has users or a token.

| Parameter | In | Type | Default |
|---|---|---|---|
| `q` | query | string | required |
| `version` | query | string or null | null |

Answers:

- **200**: the answer, as JSON
- **400**: the request was refused; `detail` says why
- **401**: the server requires a token, and the request has none or a wrong one
- **404**: no such record
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

## Review

### GET `/api/queue`

Invoices waiting for review, highest weighted risk first (at most 2,000), of one risk level or of every level. Each item lists the rules its kept findings break, the most severe first; `rules` gives the title of each rule in the active policy; `total` counts the invoices waiting at the level asked; `levels` counts the whole queue per risk level, with the amount at stake, whatever the list holds. Kept until the store changes (a decision changes it).

Role: at least `viewer` when the server has users or a token.

| Parameter | In | Type | Default |
|---|---|---|---|
| `limit` | query | integer | `200` |
| `level` | query | `CRITICAL` or `HIGH` or `MEDIUM` or `LOW` or null | null |

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### GET `/api/invoices`

Search invoices by id or vendor name, with their latest audit outcome.

Role: at least `viewer` when the server has users or a token.

| Parameter | In | Type | Default |
|---|---|---|---|
| `q` | query | string | empty |
| `limit` | query | integer | `50` |

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### GET `/api/invoices/{invoice_id}`

The records of an invoice, its vendor's last 40 other invoices, the vendor e-mails that name it, and its latest result with the audit pack and trail; with_label adds the benchmark label.

Role: at least `viewer` when the server has users or a token.

| Parameter | In | Type | Default |
|---|---|---|---|
| `invoice_id` | path | string | required |
| `with_label` | query | boolean | `false` |

Answers:

- **200**: the answer, as JSON
- **400**: the request was refused; `detail` says why
- **401**: the server requires a token, and the request has none or a wrong one
- **404**: no such record
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### POST `/api/results/{result_id}/decision`

Record a reviewer's decision on a result: approve, reject or override (an override needs a justification). Signed in with a user's token, the decision carries that user's name.

Role: at least `reviewer` when the server has users or a token.

| Parameter | In | Type | Default |
|---|---|---|---|
| `result_id` | path | integer | required |

JSON body (`DecisionIn`):

| Field | Type | Default | Limits |
|---|---|---|---|
| `decision` | `approve` or `reject` or `override` | required |  |
| `reviewer` | string | empty | at most 120 characters; taken from the account when signed in as a user |
| `justification` | string | empty | at most 4000 characters |

Answers:

- **200**: the answer, as JSON
- **400**: the request was refused; `detail` says why
- **401**: the server requires a token, and the request has none or a wrong one
- **403**: the token's user does not have the role the endpoint needs
- **404**: no such record
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### POST `/api/invoices/{invoice_id}/audit`

Audit one invoice again under a configuration (a background job), with the policy version in force on the invoice's date; C2 to C5 need a model.

Role: at least `reviewer` when the server has users or a token. Starts a background job of kind `audit`.

| Parameter | In | Type | Default |
|---|---|---|---|
| `invoice_id` | path | string | required |

JSON body (`AuditIn`):

| Field | Type | Default | Limits |
|---|---|---|---|
| `config` | `C1` or `C2` or `C3` or `C4` or `C5` | `C1` |  |

Answers:

- **202**: a background job was started: poll `GET /api/jobs/{id}` until `status` is `done` or `failed`
- **400**: the request was refused; `detail` says why
- **401**: the server requires a token, and the request has none or a wrong one
- **403**: the token's user does not have the role the endpoint needs
- **409**: the request conflicts with the state of the server; `detail` says with what
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

## Ledger

### POST `/api/ledger`

Replace the ledger with an uploaded one: an .xlsx workbook with one sheet per table, or a .zip archive of the CSV files (a background job). The ledger is checked first; with any problem nothing is replaced. Loading removes the previous ledger with every audit result and review decision, so the request must say replace=true.

Role: at least `admin` when the server has users or a token. Starts a background job of kind `load-ledger`.

Multipart form:

| Field | Type | Default |
|---|---|---|
| `file` | file | `PydanticUndefined` |
| `replace` | boolean | `false` |

Answers:

- **202**: a background job was started: poll `GET /api/jobs/{id}` until `status` is `done` or `failed`
- **400**: the request was refused; `detail` says why
- **401**: the server requires a token, and the request has none or a wrong one
- **403**: the token's user does not have the role the endpoint needs
- **409**: the request conflicts with the state of the server; `detail` says with what
- **413**: the upload is too large
- **415**: the upload is not of the expected type
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

## Explainable AI, investigation and e-mail triage

### GET `/api/model`

The risk screen (auditiq/screen.py): how it was trained, its five heads (any anomaly and one per judgement rule), each feature's importance over the store's invoices (mean absolute SHAP value, exact TreeSHAP) with a dot plot of a sample, the distribution of its probability by route next to the paper's score, the invoices the audit passed that the screen rates highest for a judgement rule (a second opinion, not a finding), and its measured accuracy on ledgers it was not trained on. Kept until the store changes.

Role: at least `viewer` when the server has users or a token.

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **503**: the database cannot be reached

### GET `/api/invoices/{invoice_id}/explain`

Why an invoice scores as it does: each head of the risk screen with its probability and the SHAP value of every feature (they add up to the model's output exactly), and for each finding of a control its margin beyond the rule and the changes of the records or of the policy that would clear it, each verified by running the controls again, with how many other findings a policy change would also clear.

Role: at least `viewer` when the server has users or a token.

| Parameter | In | Type | Default |
|---|---|---|---|
| `invoice_id` | path | string | required |

Answers:

- **200**: the answer, as JSON
- **400**: the request was refused; `detail` says why
- **401**: the server requires a token, and the request has none or a wrong one
- **404**: no such record
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### GET `/api/invoices/{invoice_id}/story`

The life of an invoice in order: its purchase order, goods receipt, approvals, the vendor e-mails that name it, every audit of it with its findings and trail, every review decision, and where it stands now.

Role: at least `viewer` when the server has users or a token.

| Parameter | In | Type | Default |
|---|---|---|---|
| `invoice_id` | path | string | required |

Answers:

- **200**: the answer, as JSON
- **400**: the request was refused; `detail` says why
- **401**: the server requires a token, and the request has none or a wrong one
- **404**: no such record
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### GET `/api/investigation`

The trail investigator (auditiq/investigator.py) audits the audit: the seals, the evidence, the stages of every trail, coverage under the policy in force, failed model stages, the review backlog, reasons given, the pace of decisions, segregation of duties, critical findings cleared, rejections undone by a later audit and outcomes that changed between audits; each check with what it found and where, the timeline, the reviewers, and the report as Markdown. Not cached: a change made directly in the store must show at once.

Role: at least `viewer` when the server has users or a token.

| Parameter | In | Type | Default |
|---|---|---|---|
| `sla_days` | query | number | `annotation=float required=False default=5.0 alias='sla_days' metadata=[Gt(gt=0), Le(le=365)]` |

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### GET `/api/mail`

Every stored vendor e-mail triaged by code (auditiq/triage.py): its category, the signals of payment redirection (a look-alike or new domain, urgency, secrecy, an account change, an unpaid invoice) and text addressed to a model, its risk and the action; the alerts, and the invoices whose payment to hold. Kept until the store changes.

Role: at least `viewer` when the server has users or a token.

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **503**: the database cannot be reached

## Ask AI (copilot) and the audit agent

### POST `/api/agent/ask`

The audit agent (auditiq/audit_agent.py), a job: the question is turned into calls to tools that read the audit (results, records, the screen's SHAP values, counterfactuals, stories, leads, rings, e-mail triage, the trail investigation), planned by rules or, in the model mode, by the model in a ReAct loop; the answer cites each observation, and numbers no tool returned are listed.

Role: at least `viewer` when the server has users or a token. Starts a background job of kind `agent`.

JSON body (`AgentIn`):

| Field | Type | Default | Limits |
|---|---|---|---|
| `question` | string | required | at least 1 characters; at most 2000 characters |
| `mode` | `auto` or `rules` or `model` | `auto` | rules: tools chosen by the question's words, no model; model: the model plans (ReAct); auto: rules when they recognise the question, else the model |

Answers:

- **202**: a background job was started: poll `GET /api/jobs/{id}` until `status` is `done` or `failed`
- **400**: the request was refused; `detail` says why
- **401**: the server requires a token, and the request has none or a wrong one
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### POST `/api/copilot/ask`

A question about the policy or an audited invoice, answered from the passages and the facts of the policy graph, with citations (a job).

Role: at least `viewer` when the server has users or a token. Starts a background job of kind `copilot`.

JSON body (`AskIn`):

| Field | Type | Default | Limits |
|---|---|---|---|
| `question` | string | required | at least 1 characters; at most 2000 characters |
| `invoice_id` | string or null | null |  |

Answers:

- **202**: a background job was started: poll `GET /api/jobs/{id}` until `status` is `done` or `failed`
- **401**: the server requires a token, and the request has none or a wrong one
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### POST `/api/copilot/data`

A question about the data, answered by one checked, read-only SELECT the model writes (a job).

Role: at least `viewer` when the server has users or a token. Starts a background job of kind `data-question`.

JSON body (`DataQuestionIn`):

| Field | Type | Default | Limits |
|---|---|---|---|
| `question` | string | required | at least 1 characters; at most 2000 characters |

Answers:

- **202**: a background job was started: poll `GET /api/jobs/{id}` until `status` is `done` or `failed`
- **400**: the request was refused; `detail` says why
- **401**: the server requires a token, and the request has none or a wrong one
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

## Results

### GET `/api/results`

The measured results of the evaluation, as the scripts wrote them.

Role: at least `viewer` when the server has users or a token.

Answers:

- **200**: the answer, as JSON
- **401**: the server requires a token, and the request has none or a wrong one
- **503**: the database cannot be reached
