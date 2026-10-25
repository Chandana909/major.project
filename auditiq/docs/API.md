# REST API reference

All 22 endpoints of the AuditIQ API (`auditiq/api.py`, served by `python -m auditiq serve`). **This file is generated** from the application by `python -m auditiq.apidoc`; a test checks that it is current. How to use the API (jobs, errors, the token, how the web application calls it) is in [`WEB.md`](WEB.md), Section 4; the interactive version of this reference is at `/api/docs` on a running server.

**Common to every endpoint.** Requests and answers are JSON, except the two uploads (multipart). An error answer carries `detail`: a message, or `{"message", "problems"}`. When the server has a token (`AUDITIQ_API_TOKEN`), every endpoint marked *token* needs the header `Authorization: Bearer <token>`. Every answer carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` and `Referrer-Policy: no-referrer`.

**Background jobs.** An endpoint that answers 202 has started a job; `GET /api/jobs/{id}` reports it. Jobs that would change the ledger under one another are refused with 409 while the other runs: `load-ledger` waits for `apply-policy`, `audit`, `load-ledger`; `apply-policy` waits for `apply-policy`, `load-ledger`; `audit` waits for `load-ledger`.

| Method | Path | Token | Answers |
|---|---|---|---|
| GET | [`/api/health`](#get-apihealth) | open | 200, 503 |
| GET | [`/api/overview`](#get-apioverview) | token | 200, 401, 503 |
| GET | [`/api/risk-map`](#get-apirisk-map) | token | 200, 401, 503 |
| GET | [`/api/pipeline`](#get-apipipeline) | open | 200 |
| GET | [`/api/queue`](#get-apiqueue) | token | 200, 401, 422, 503 |
| GET | [`/api/invoices`](#get-apiinvoices) | token | 200, 401, 422, 503 |
| GET | [`/api/invoices/{invoice_id}`](#get-apiinvoicesinvoice_id) | token | 200, 400, 401, 404, 422, 503 |
| POST | [`/api/results/{result_id}/decision`](#post-apiresultsresult_iddecision) | token | 200, 400, 401, 404, 422, 503 |
| POST | [`/api/invoices/{invoice_id}/audit`](#post-apiinvoicesinvoice_idaudit) | token | 202, 400, 401, 409, 422 |
| GET | [`/api/policy`](#get-apipolicy) | token | 200, 401, 503 |
| POST | [`/api/policy/activate`](#post-apipolicyactivate) | token | 200, 401, 404, 422, 503 |
| POST | [`/api/policy/preview`](#post-apipolicypreview) | token | 200, 401, 413, 415, 422, 503 |
| POST | [`/api/policy/adopt`](#post-apipolicyadopt) | token | 200, 401, 422, 503 |
| POST | [`/api/policy/propose`](#post-apipolicypropose) | token | 202, 400, 401, 422 |
| POST | [`/api/policy/confirm`](#post-apipolicyconfirm) | token | 200, 400, 401, 404, 422, 503 |
| POST | [`/api/policy/apply`](#post-apipolicyapply) | token | 202, 401, 409 |
| POST | [`/api/ledger`](#post-apiledger) | token | 202, 400, 401, 409, 413, 415, 422 |
| GET | [`/api/search`](#get-apisearch) | token | 200, 400, 401, 409, 422, 503 |
| POST | [`/api/copilot/ask`](#post-apicopilotask) | token | 202, 401, 422 |
| POST | [`/api/copilot/data`](#post-apicopilotdata) | token | 202, 400, 401, 422 |
| GET | [`/api/jobs/{job_id}`](#get-apijobsjob_id) | token | 200, 401, 404, 422 |
| GET | [`/api/results`](#get-apiresults) | token | 200, 401 |

## Status

### GET `/api/health`

Version, backend, ledger, active policy and model; open without a token, for monitoring.

Token: not needed.

Answers:

- **200**: the answer, as JSON
- **503**: the database cannot be reached

### GET `/api/overview`

Counts by state, route and risk level; findings by rule; recent runs; the vendors with most invoices waiting.

Token: required when the server has one.

Answers:

- **200**: the answer, as JSON
- **401**: the server requires the token, and the request has none or a wrong one
- **503**: the database cannot be reached

### GET `/api/risk-map`

One point per vendor: its invoices, amount, findings and the highest risk among its latest results.

Token: required when the server has one.

Answers:

- **200**: the answer, as JSON
- **401**: the server requires the token, and the request has none or a wrong one
- **503**: the database cannot be reached

### GET `/api/pipeline`

The stages of the pipeline and which configuration runs which: for the diagram of the frontend.

Token: not needed.

Answers:

- **200**: the answer, as JSON

### GET `/api/jobs/{job_id}`

The state of a background job: queued, running, done (with its result) or failed (with the reason).

Token: required when the server has one.

| Parameter | In | Type | Default |
|---|---|---|---|
| `job_id` | path | string | required |

Answers:

- **200**: the answer, as JSON
- **401**: the server requires the token, and the request has none or a wrong one
- **404**: no such record
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why

## Review

### GET `/api/queue`

Invoices waiting for review, highest weighted risk first (at most 2,000).

Token: required when the server has one.

| Parameter | In | Type | Default |
|---|---|---|---|
| `limit` | query | integer | `200` |

Answers:

- **200**: the answer, as JSON
- **401**: the server requires the token, and the request has none or a wrong one
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### GET `/api/invoices`

Search invoices by id or vendor name, with their latest audit outcome.

Token: required when the server has one.

| Parameter | In | Type | Default |
|---|---|---|---|
| `q` | query | string | empty |
| `limit` | query | integer | `50` |

Answers:

- **200**: the answer, as JSON
- **401**: the server requires the token, and the request has none or a wrong one
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### GET `/api/invoices/{invoice_id}`

The records of an invoice, its vendor's last 40 other invoices, and its latest result with the audit pack and trail; with_label adds the benchmark label.

Token: required when the server has one.

| Parameter | In | Type | Default |
|---|---|---|---|
| `invoice_id` | path | string | required |
| `with_label` | query | boolean | `false` |

Answers:

- **200**: the answer, as JSON
- **400**: the request was refused; `detail` says why
- **401**: the server requires the token, and the request has none or a wrong one
- **404**: no such record
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### POST `/api/results/{result_id}/decision`

Record a reviewer's decision on a result: approve, reject or override (an override needs a justification).

Token: required when the server has one.

| Parameter | In | Type | Default |
|---|---|---|---|
| `result_id` | path | integer | required |

JSON body (`DecisionIn`):

| Field | Type | Default | Limits |
|---|---|---|---|
| `decision` | `approve` or `reject` or `override` | required |  |
| `reviewer` | string | required | at least 1 characters; at most 120 characters |
| `justification` | string | empty | at most 4000 characters |

Answers:

- **200**: the answer, as JSON
- **400**: the request was refused; `detail` says why
- **401**: the server requires the token, and the request has none or a wrong one
- **404**: no such record
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### POST `/api/invoices/{invoice_id}/audit`

Audit one invoice again under a configuration (a background job); C2 to C5 need a model.

Token: required when the server has one. Starts a background job of kind `audit`.

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
- **401**: the server requires the token, and the request has none or a wrong one
- **409**: the request conflicts with the state of the server; `detail` says with what
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why

## Policy

### GET `/api/policy`

The stored policy versions and how each was adopted, the rules of the active one, the ingested documents.

Token: required when the server has one.

Answers:

- **200**: the answer, as JSON
- **401**: the server requires the token, and the request has none or a wrong one
- **503**: the database cannot be reached

### POST `/api/policy/activate`

Make a stored policy version the active one; later audits use it.

Token: required when the server has one.

JSON body (`VersionIn`):

| Field | Type | Default | Limits |
|---|---|---|---|
| `version` | string | required | at least 1 characters; at most 40 characters |

Answers:

- **200**: the answer, as JSON
- **401**: the server requires the token, and the request has none or a wrong one
- **404**: no such record
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### POST `/api/policy/preview`

Read a policy PDF without storing anything: what it states and how it differs from the active version.

Token: required when the server has one.

Multipart form:

| Field | Type | Default |
|---|---|---|
| `file` | file | `PydanticUndefined` |

Answers:

- **200**: the answer, as JSON
- **401**: the server requires the token, and the request has none or a wrong one
- **413**: the upload is too large
- **415**: the upload is not of the expected type
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### POST `/api/policy/adopt`

Adopt a previewed policy document as a new version; refused with the problems if it cannot be executed.

Token: required when the server has one.

JSON body (`AdoptIn`):

| Field | Type | Default | Limits |
|---|---|---|---|
| `upload_id` | string | required |  |
| `activate` | boolean | `true` |  |
| `replace` | boolean | `false` |  |

Answers:

- **200**: the answer, as JSON
- **401**: the server requires the token, and the request has none or a wrong one
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### POST `/api/policy/propose`

Let the model read a policy in its own wording (a background job); the result waits for confirmation.

Token: required when the server has one. Starts a background job of kind `policy-reading`.

JSON body (`AdoptIn`):

| Field | Type | Default | Limits |
|---|---|---|---|
| `upload_id` | string | required |  |
| `activate` | boolean | `true` |  |
| `replace` | boolean | `false` |  |

Answers:

- **202**: a background job was started: poll `GET /api/jobs/{id}` until `status` is `done` or `failed`
- **400**: the request was refused; `detail` says why
- **401**: the server requires the token, and the request has none or a wrong one
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why

### POST `/api/policy/confirm`

Adopt a model's proposal after the reviewer's confirmation, corrections and quoted passages.

Token: required when the server has one.

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
- **401**: the server requires the token, and the request has none or a wrong one
- **404**: no such record
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

### POST `/api/policy/apply`

Audit every invoice again with the controls under the active policy (a background job).

Token: required when the server has one. Starts a background job of kind `apply-policy`.

Answers:

- **202**: a background job was started: poll `GET /api/jobs/{id}` until `status` is `done` or `failed`
- **401**: the server requires the token, and the request has none or a wrong one
- **409**: the request conflicts with the state of the server; `detail` says with what

### GET `/api/search`

Search the policy documents: hybrid when an embedding model is configured, lexical otherwise.

Token: required when the server has one.

| Parameter | In | Type | Default |
|---|---|---|---|
| `q` | query | string | required |
| `k` | query | integer | `4` |

Answers:

- **200**: the answer, as JSON
- **400**: the request was refused; `detail` says why
- **401**: the server requires the token, and the request has none or a wrong one
- **409**: the request conflicts with the state of the server; `detail` says with what
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why
- **503**: the database cannot be reached

## Ledger

### POST `/api/ledger`

Replace the ledger with an uploaded one: an .xlsx workbook with one sheet per table, or a .zip archive of the CSV files (a background job). The ledger is checked first; with any problem nothing is replaced. Loading removes the previous ledger with every audit result and review decision, so the request must say replace=true.

Token: required when the server has one. Starts a background job of kind `load-ledger`.

Multipart form:

| Field | Type | Default |
|---|---|---|
| `file` | file | `PydanticUndefined` |
| `replace` | boolean | `false` |

Answers:

- **202**: a background job was started: poll `GET /api/jobs/{id}` until `status` is `done` or `failed`
- **400**: the request was refused; `detail` says why
- **401**: the server requires the token, and the request has none or a wrong one
- **409**: the request conflicts with the state of the server; `detail` says with what
- **413**: the upload is too large
- **415**: the upload is not of the expected type
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why

## Copilot

### POST `/api/copilot/ask`

A question about the policy or an audited invoice, answered from the passages with citations (a job).

Token: required when the server has one. Starts a background job of kind `copilot`.

JSON body (`AskIn`):

| Field | Type | Default | Limits |
|---|---|---|---|
| `question` | string | required | at least 1 characters; at most 2000 characters |
| `invoice_id` | string or null | null |  |

Answers:

- **202**: a background job was started: poll `GET /api/jobs/{id}` until `status` is `done` or `failed`
- **401**: the server requires the token, and the request has none or a wrong one
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why

### POST `/api/copilot/data`

A question about the data, answered by one checked, read-only SELECT the model writes (a job).

Token: required when the server has one. Starts a background job of kind `data-question`.

JSON body (`DataQuestionIn`):

| Field | Type | Default | Limits |
|---|---|---|---|
| `question` | string | required | at least 1 characters; at most 2000 characters |

Answers:

- **202**: a background job was started: poll `GET /api/jobs/{id}` until `status` is `done` or `failed`
- **400**: the request was refused; `detail` says why
- **401**: the server requires the token, and the request has none or a wrong one
- **422**: the parameters or the body are not valid, or the document cannot be executed; `detail` lists why

## Results

### GET `/api/results`

The measured results of the evaluation, as the scripts wrote them.

Token: required when the server has one.

Answers:

- **200**: the answer, as JSON
- **401**: the server requires the token, and the request has none or a wrong one
