# Code review, 21 October 2026

A review of the whole project for correctness, security, performance and
documentation: about 21,000 lines of Python (the application, the benchmark
generator, the evaluation, the dashboard, the scripts and the tests) and 4,000
of TypeScript (the web application and its tests). Each finding below says
what was wrong, what it could cause, what was changed and which test now
checks it. Section 3 lists what was examined and found sound, and Section 4
what is left.

## 1. How the code was examined

| Method | Tool | Scope |
|---|---|---|
| Lint, the project's rules | `ruff check .` (E, F, W, I, B, UP) | everything; clean before and after |
| Lint, a wide set of rules for bugs and security | `ruff --select B,SIM,PERF,S,ARG,PL,RUF,TRY,BLE,DTZ,...` | 1,391 reports, mostly style; the 44 that can hide a bug or a hole were read one by one |
| Types | `mypy auditiq --ignore-missing-imports` | 49 reports, each read |
| Dead code | `vulture --min-confidence 60` | the application, generator, evaluation, dashboard, scripts |
| Known vulnerabilities | `pip-audit` on the installed dependencies; `npm audit` on every frontend package, development tools included | |
| Probes | a script that sends hostile SQL to the copilot on PostgreSQL | Finding 1 |
| Reading | every SQL statement built from strings, every subprocess call, every upload path, every place a connection is opened, the model client, the batch service, the job runner, the frontend's client | |
| Measurement | the control stage before and after Finding 7, timed in turn | Finding 7 |

## 2. Findings and changes

**1. The copilot's SQL could read the labels on PostgreSQL** (security, high).
A data question is answered by one SELECT the model writes. On PostgreSQL the
statement ran as the restricted role `auditiq_reader`, but the session's own
user is the database owner, so `set_config('role', session_user, false)`
inside the SELECT gave the owner's rights back, and
`query_to_xml('select label from bench' || 'mark_labels ...')` ran a query
the name check could not see. A probe read the ground-truth labels this way;
as the owner, the same route reaches server files. The model reads invoice
descriptions, so a text in the ledger could steer it there. *Changed:* the
copilot refuses `set_config`, `current_setting`, the `*_to_xml` functions,
`ts_stat`, `dblink`, `lo_*` and Unicode-escaped names before running a
statement, and on PostgreSQL refuses data questions when the reader role does
not exist instead of running as the owner (`auditiq/copilot.py`). *Tests:*
eight hostile statements, among them the one that read the labels, are refused
on both backends; a server without the role is refused
(`tests/test_policy_docs.py`).

**2. The command line left its database connections open** (correctness,
high). Each command opened a connection and left it to the garbage collector.
On PostgreSQL a connection that is not closed stays "idle in transaction" and
keeps its locks: the CI job against the compose database waited forever in
`DROP SCHEMA` behind the `run` and `queue` commands. *Changed:* `main()`
closes every connection a command opened (`auditiq/cli.py`). *Test:* every
connection the commands open is closed when they end, on both backends
(`tests/test_cli.py`).

**3. The report depended on a model run in progress** (correctness, medium).
`REPORT.md` listed every result file on disk, so a run still writing its files
entered the report on the machine running it, and CI found the committed report
out of date. *Changed:* a run's files count once its report exists
(`evaluation/full_report.py`). *Test:* `tests/test_results.py`.

**4. A workbook could unpack without bound** (security, medium). A zip archive
was refused when its parts unpacked to more than 300 MB, but a workbook, which
is also a zip container, went to openpyxl unchecked: a 100 MB upload could
expand to many gigabytes. *Changed:* the same bound for workbooks
(`auditiq/ledger_import.py`). *Test:* a 40 KB file that unpacks past the
limit is refused in both formats (`tests/test_ledger_import.py`).

**5. Background jobs could collide** (correctness, medium). Any number of jobs
ran at once: a ledger load (which deletes every result) could run during an
audit of the ledger, and two whole-ledger audits could interleave. The job list
also dropped its oldest entries without looking, so a long job could vanish from
`GET /api/jobs/{id}` while it ran. *Changed:* `api.CONFLICTS` names the jobs
each kind may not run beside, a conflicting request is answered 409 with the job
it waits for, and only finished jobs are forgotten (`auditiq/api.py`).
*Tests:* `tests/test_api.py`.

**6. A reply that was not a completion crashed the stage** (robustness,
medium). A status-200 answer without a completion (a proxy's error page, a body
without `choices`) raised `KeyError` or `JSONDecodeError` out of the model
client. *Changed:* it is a failed attempt like a 503: retried with backoff, then
reported as `LLMError` (`auditiq/llm.py`). *Test:* `tests/test_llm.py`.

**7. The control stage grew faster than the ledger** (performance). Controls
2.2.1 and 4.1.1 read every other invoice of the vendor, so an invoice's cost
grew with its vendor's history: 1.96 times as much per invoice on 500,000
invoices as on 20,000 (RESULTS.md, Section 5.1). *Changed:* the vendor history
is a list that carries an index of the vendor's invoices by number and by date,
built once per vendor (`auditiq/history.py`); the two controls look up the
invoices they need, and read the list when there is no index. Nothing else
sees a difference: JSON writes the history as a list and the prompts are
unchanged. *Tests:* on every invoice of a ledger, under the policy and under a
one-invoice-a-day limit that makes 4.1.1 fire on every shared day, the findings
with the index equal the findings from the plain list
(`tests/test_controls.py`); the reproduction compares every result file with
the committed one. *Measured:* on the 20,000-invoice ledger, timed in turn
three times, 21.0, 24.1 and 20.9 µs per invoice before and 13.4, 15.8 and 12.7
after (about 37% less), with the same 300 findings. On the 500,000-invoice ledger,
31.7 µs per invoice before and 18.4 after, with the same 7,140 findings; the
cost an earlier invoice of the vendor adds fell from 0.431 µs to 0.006, so the
cost of an invoice no longer depends on its vendor's history (RESULTS.md,
Section 5.1).

**8. No security headers** (security, low). *Changed:* every answer carries
`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` and
`Referrer-Policy: no-referrer`. *Test:* `tests/test_api.py`.

**9. Dependencies with published vulnerabilities** (security). `pip-audit`
found 36 advisories in four installed packages: `starlette` (under FastAPI),
`python-multipart` (the upload parser), `python-dotenv` and `pillow`.
*Changed:* the lower bounds in `pyproject.toml` exclude the affected releases of
the first three, and CI runs `pip-audit` on every push. Pillow cannot follow:
Streamlit requires `pillow<13`, and the fixes are in 13; AuditIQ decodes no
uploaded image with it, so its advisories are recorded and ignored by name
(SECURITY.md, Section 4). `npm audit` found nothing in the frontend, development
tools included.

**10. The documentation said more than the code allowed** (documentation). The
data dictionary said the copilot's SQL "may read ... the policy tables"; it may
read one of them, `policy_clauses`. *Changed:* the sentence is generated from
the copilot's allow-list (`auditiq/datadict.py`).

**11. Endpoints without a description** (documentation). Fourteen of the 22
endpoints had no docstring, so `/api/docs` showed them bare. *Changed:* every
endpoint has one, and `docs/API.md`, the reference of every endpoint with its
parameters, body, token and answers, is generated from the application
(`auditiq/apidoc.py`). *Test:* the reference is current and documents every
endpoint (`tests/test_docs.py`).

## 3. Examined and found sound

- **SQL built from strings.** The eight places `ruff` flags (S608) put
  integers clamped by FastAPI (`LIMIT`) or names from the schema into the
  statement; every value from a request is a bound parameter, and an uploaded
  ledger's column names are filtered against the schema before an insert.
- **Subprocesses.** Every call has a fixed argument list and no shell.
- **The token** is compared in constant time; uploads are checked for size,
  type and magic bytes; an upload id is matched against a fixed pattern before
  it becomes a path; the built web application is served only from inside its
  folder.
- **Connections.** Apart from Finding 2, every connection is closed: by the
  request's dependency, the job's `finally`, or the script.
- **The model client** retries 408, 409, 429 and server errors with capped
  exponential backoff, honours a numeric `Retry-After` and treats a date as
  none, and refuses a prompt that would not fit the context.
- **The batch service** touches the database from one thread, runs the model
  calls in a bounded pool, and commits every 200 results; a run that fails
  stays visible as unfinished, with what it stored.
- **The frontend** uses no `innerHTML` or `eval`, no `any`, strict TypeScript,
  keeps the token in `sessionStorage`, and shows the server's error message.
- **Type checker.** The 49 reports are optional values and loosely typed
  dictionaries that the code checks before use (for example a registry read
  only after `found.usable`); none is reachable as a crash.
- **Dead code.** The route handlers `vulture` reports are registered by their
  decorators; `extraction.read_jsonl` reads the files `python -m
  auditiq.extraction` writes; `stats.consistency` and `stats.non_inferior` are
  tested parts of the evaluation protocol that the full model run (plan item
  B10) uses.
- **Naive datetimes** (DTZ) appear in the generator's synthetic timestamps and
  the "produced" stamps of reports, where local time is meant.

## 4. Not changed, and why

| Item | Why it stays |
|---|---|
| One shared token, no user accounts or roles | A larger change across the API and the web application; stated in SECURITY.md and RESULTS.md |
| No Content-Security-Policy header | The 3D views' needs (workers, inline styles) must be checked in a browser first |
| No rate limit or body limit in the server | The job of the reverse proxy in front of it (SECURITY.md, Section 5) |
| Type checking is not in CI | The 49 reports are not bugs; making the checker pass needs annotations through the dictionaries the stages pass, without changing behaviour |
| The model stages are not faster | Their time is the model's; on this laptop's integrated GPU a 7B model's prompt is processed 6 to 8 times faster than on its CPU (OPERATIONS.md, Section 5) |
