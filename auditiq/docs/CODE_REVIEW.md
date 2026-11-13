# Code review, 21 October 2026

A review of the whole project for correctness, security, performance and
documentation: about 21,000 lines of Python (the application, the benchmark
generator, the evaluation, the dashboard, the scripts and the tests) and 4,000
of TypeScript (the web application and its tests). Each finding below says
what was wrong, what it could cause, what was changed and which test now
checks it. Findings 12 to 14 were added on 25 October, when the application
was served from the 500,000-invoice ledger, 15 to 17 later the same day, and 18 on 27 October, with the Kafka layer. Section 3 lists what was examined
and found sound, and Section 4 what is left.

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

**12. The latest result of an invoice was found again for every row**
(performance, found on 25 October by serving the 500,000-invoice ledger). The
view `v_latest_results` kept a result when its id was the largest of its
invoice's, a subquery for every one of a million results; joined to the
invoices, SQLite built the whole view first. The overview took 19.3 s, the risk
map 12.8 s, an invoice search 4.1 s. *Changed:* a table `latest_results` (one row
per invoice, with a unique index on the result) is updated as each result is
stored, the view joins through it, an older store fills it once when it is
opened, and loading a ledger clears it (`auditiq/db.py`). *Tests:* a re-audited
invoice's latest result is the newer one; an older store gets the table filled
(`tests/test_db.py`); every test of the queue, the API and the copilot passes on
both backends.

**13. Pages read more than they show** (performance). The overview counted
states, routes and risk levels in three passes, and the risk map joined every
invoice with its result before grouping by vendor. *Changed:* one pass for the
three counts; the risk map counts invoices and latest results per vendor apart
and joins the two; the invoice search finds its 50 invoices before it reads their
results (`auditiq/api.py`). The risk map's rows are the same as before for all
14,998 vendors with invoices. *Measured* on 500,000 invoices: overview 4.6 s,
risk map 5.5 s, search 1.0 s (RESULTS.md, Section 5.1). An index tried on the
results' vendor made the queue slower (19 s: SQLite read the results in vendor
order) and was removed; a store that had it loses it on upgrade.

**14. The 3D view of a large ledger was one surface** (presentation). Points
were sized for a few hundred vendors; 15,000 merged into a single shape. *Changed:*
above 250 vendors points and stems shrink with the square root of the number of
vendors (`frontend/src/three/layout.ts`, `RiskConstellation.tsx`). *Test:*
`scenes.test.tsx`.

**15. One shared token, no user accounts** (security; done 25 October).
Anyone with the token could do everything, and a reviewer's name was typed.
*Changed:* users with roles (`api_users`, `python -m auditiq user add`), each
endpoint requiring viewer, reviewer or admin (403 below it), a decision recording
the signed-in user's name, `GET /api/me`, and the web application showing who
is signed in and filling in the reviewer. The shared token remains, as an admin.
*Tests:* `tests/test_api.py` (each role allowed and refused, disabled user,
the decision's name, the shared token beside users), `tests/test_docs.py`.

**16. No Content-Security-Policy** (security; done 25 October). *Changed:* the
web application's pages carry a policy that allows scripts, connections and
fonts from the server only; checked in a browser on every page, with the 3D
views, without a violation. *Test:* `tests/test_api.py`.

**17. No container image of the application** (deployment; done 25 October).
*Changed:* `Dockerfile` (the frontend built with Node, served by the Python
API, run as an unprivileged user, with a health check) and
`deploy/docker-compose.yml` (the application with PostgreSQL). CI builds the
image, starts both, sets up and audits a ledger inside it and reads the result
through the API with a token (the `container` job).

**18. Storing the active version again left no version active** (correctness;
found 27 October, while building the compliance topic). `db.store_policy`
replaced a version with `is_active = 0`, so adopting the active version's own
document again without "activate" (on the policy page, with `policy adopt`, or
from the Kafka compliance topic) left the store with no active policy, and the
next audit failed. *Changed:* a version that was active stays active when it is
stored again; which version is active changes only when asked. *Test:*
`tests/test_stream.py` (the compliance topic).

**19. The overview read an unchecked invoice as an approved one** (honesty of
the results; found 1 November, checking the scores on the overview against the
answer key). The overview counted every approval together, but most latest
results came from the controls-only configuration, which never evaluates the
four judgement rules: anomalies of those rules were approved without any check,
invoices whose one finding was medium or low were approved with it, and the
model's findings on the sampled invoices (which can be false) were mixed with
the controls'. *Changed:* the overview reports the coverage of the latest
results: the configurations behind them, how many invoices the controls and the
agents checked, the findings that did not hold payment, and, on a benchmark
ledger, the results against the answer key per configuration
(`analytics.coverage`, docs/ANALYTICS.md). *Tests:* `tests/test_analytics.py`.

**20. The answer key would have scored results under another policy**
(correctness; found 1 November, on the 500,000-invoice ledger). The labels of
a benchmark ledger hold for the policy they were generated for (v2.5); results
audited under another version (v3.12 there) differ from them because the
thresholds changed, not because the audit erred, and would have shown as false
alarms. *Changed:* loading a dataset records the labels' policy version from
its manifest (`meta.labels_policy`); only results under that version are
scored, and the others are counted apart. *Test:*
`test_the_answer_key_scores_only_results_under_its_own_policy`.

**21. A first rule for collusion rings joined a whole ledger into one ring**
(correctness; found 1 November, while building the rings). Linking an approver
to every vendor of one approval above their own limit made one ring of almost
every vendor and approver of the 500,000-invoice ledger, whose policy v3.12
makes such approvals common; comparing approvers with the whole ledger instead
of their own role made hundreds of them look unusual, because a role with a
lower limit breaks the rules more often. *Changed:* an approval link needs a
one-sided binomial test against the rate of the approver's role to pass the
Benjamini-Hochberg procedure at a false discovery rate of 1 %; identity links
need no test; a watch list ranks the strongest leads when nothing passes
(`auditiq/rings.py`, docs/ANALYTICS.md). *Tests:* `tests/test_analytics.py`.

**22. A new policy version judged invoices dated before it took effect**
(correctness; found 4 November, from a question about why the 500,000-invoice
ledger sent a third of its invoices to review). Applying a policy, the CLI's
`run`, the audit of one invoice, the stream worker and the dashboard all
audited every invoice under the version active at the time of the audit. Version
3.12 (effective 1 April 2026) had been applied to a ledger dated 1 April 2025 to
31 March 2026: 149,514 invoices approved within the limits of their day became
critical breaches of the halved approval limits, 160,068 invoices (32.0 %) went
to a person and 4.7 % of them were anomalous in the answer key (RESULTS.md
3.9). The Policy page's notice, "results do not yet follow the active policy",
invited exactly that re-audit. *Changed:* `db.policy_timeline` and
`service.audit_in_force`: every invoice under the version in force on its date,
in the API, the CLI, the worker and the dashboard; the analytics measure amounts
against the limits in force; the Policy page shows which version governs which
dates. `--policy` still audits every invoice under one version, for experiments.
*Tests:* `test_each_invoice_is_governed_by_the_policy_in_force_on_its_date`,
`test_an_adopted_version_does_not_judge_the_invoices_before_its_date`, and the
policy tests of the API, the CLI, the dashboard and the stream.

**23. The risk level MEDIUM could not occur** (design; found 4 November). A
medium finding scores 10, in the lowest band, so an invoice breaking a medium
rule had the level of a clean invoice, and MEDIUM needed three medium findings.
*Changed:* the level is at least that of the most severe finding held with
confidence; scores and routes are unchanged. *Test:*
`test_the_risk_level_is_at_least_that_of_the_most_severe_finding_held`.

**24. The Kafka page could overwrite the store's invoices with another
ledger's** (data integrity; found 4 November). Every generated ledger numbers
its invoices from INV40001, and the page offered the first ledger in the
folder. *Changed:* publishing a ledger that would replace invoices of the store
with different ones is refused with 409 (`stream.ledger_clash`); the page
offers the store's own ledger first. *Tests:*
`test_another_ledger_with_the_same_invoice_numbers_would_replace_the_stores`
and the console test of `tests/test_stream.py`.

**25. A publish job reported its sent counts as failures** (correctness; found
4 November). `Publisher.close()` returns the messages sent per topic and raises
when one is not delivered; the endpoint stored its return value as the number
failed. *Changed:* the job reports the topics that received messages; a
delivery failure fails the job with its reason.

**26. The local Kafka broker stopped on Windows and would not start again**
(operations; found 4 November). Kafka marks a finished metadata snapshot
read-only and then cannot delete it on Windows; its log cleaner renames open
segment files, which Windows refuses, and the broker took its only log
directory offline. *Changed:* `scripts/kafka_local.py start` clears the
read-only flag on the broker's files and writes `log.cleaner.enable=false`. A
long read of a SQLite store could also make a batch audit fail ("database is
locked") after the default 5 s wait; connections now wait up to 60 s
(`db.LOCK_WAIT`).

**27. The review queue counted its levels from a cut list** (correctness of a
display; found 4 November). The page loads at most 2,000 invoices, riskiest
first, and counted the cards from them: on the 500,000-invoice ledger it showed
2,000 waiting, all critical, while 5,712 were waiting, 3,570 of them high.
*Changed:* `GET /api/queue` returns the count and amount of the whole queue per
level (`levels`) and takes a `level`, so a level chosen on the page is read from
the server; the page says when the list holds only the riskiest. *Tests:*
`test_the_queue_counts_every_level_and_lists_one_level` and the review-queue
tests of `pages.test.tsx`.

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
| No rate limit or body limit in the server | The job of the reverse proxy in front of it (SECURITY.md, Section 5) |
| Type checking is not in CI | The 49 reports are not bugs; making the checker pass needs annotations through the dictionaries the stages pass, without changing behaviour |
| The model stages are not faster | Their time is the model's; on this laptop's integrated GPU a 7B model's prompt is processed 6 to 8 times faster than on its CPU (OPERATIONS.md, Section 5) |
