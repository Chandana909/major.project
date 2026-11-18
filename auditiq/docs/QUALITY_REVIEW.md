# Quality review: the code, and the audit of the 25,000-invoice ledger

18 November 2026. How the code measures against the checks an engineering team would run, what the audit of
`final_seed_2025` means for an audit team, and what was added for them. Every number below comes from a command named
next to it; the audit numbers are in `results/final_seed_2025/industry.md` (`python -m evaluation.industry`),
`results/final_seed_2025/verification.md` (`python -m evaluation.final_check`) and `results/leads/leads.md`
(`python -m evaluation.leads_eval`).

## 1. Code

| Check | Command | Result |
|---|---|---|
| Lint, project rules (E, F, W, I, B, UP) | `ruff check .` | 0 findings (also in CI) |
| Frontend lint and types | `npm run lint`, `npm run typecheck` | 0 findings (also in CI) |
| Python tests | `pytest` | 588 cases with both backends; all pass on SQLite and PostgreSQL (the Kafka tests need a broker and were skipped here) |
| Frontend tests | `npm test` | 65 pass |
| Size | non-blank, non-comment lines, 18 November before the additions | package 9,187; bench 2,139; evaluation 5,500; tests 4,276 |
| Complexity above 10 | `ruff check --select C901` | 37 functions. `create_app` counts 138 because every endpoint is a closure inside it; the rest are 11 to 34 (`ledger_import.validate` 34, `policy_graph.query` 32, `build_graph` 32, `case_graph.public` 30) |
| Security patterns (Bandit rules) | `ruff check --select S auditiq app scripts` | 30 SQL strings built in code: each one reviewed, every value is a bound parameter and every table or column name comes from the code, not from a request. 1 tar extraction: uses Python's `data` filter, or checks every member by hand on older Pythons. 8 subprocess calls: fixed argument lists, no shell |
| Static types | `mypy auditiq --ignore-missing-imports` | 114 errors in 22 files; not in CI. Those read (Optional values, a reused variable name, Kafka message types) are guarded in the code or are stubs the checker lacks, not failures at run time |
| Dead code | `vulture auditiq auditiq_bench app --min-confidence 80` | 3 unused names (`case_graph.py:243`, `copilot.py:208` twice) |
| Start-up of the command line | `python -X importtime -c "import auditiq.cli"` | 6.0 s before, 2.3 s after (section 4) |
| Test coverage | not measured | `coverage` is not installed here |

What would raise the code to the next level, most useful first:

1. **Type checking in CI.** Add mypy to the CI job with a baseline and fix the 114 errors file by file; most are
   `Optional` narrowing and missing annotations.
2. **Coverage.** Run `pytest --cov` in CI so the share of lines the tests reach is known.
3. **Split `create_app`.** Moving the endpoints into `APIRouter` modules (status, review, policy, stream, graph,
   copilot, assurance) would make each testable and readable apart; behaviour would not change.
4. **The three unused names** can be removed.

## 2. The audit of `final_seed_2025` (C1, controls only)

| Measure | Value |
|---|---|
| Invoices | 25,000: 2,275 anomalous, 22,425 clean, 300 hard negatives |
| Sent to a person | 1,658 (6.6% of invoices, 14.1% of the spend) |
| Of those, anomalous | 100.0%: no clean invoice and no hard negative was sent |
| Anomalous invoices sent to a person | 72.9% |
| Anomalous spend sent to a person | 86.7% (₹762.0 M of ₹878.6 M) |
| Rule clauses (12) | precision and recall 100% each (`verification.md`) |
| Ranking, average precision | C1 risk score 0.824; isolation forest 0.553; one-class SVM 0.606 |
| Top 1,000 by score | 100% anomalous (isolation forest 70.2%, one-class SVM 74.8%) |
| Repeatability | two complete C1 runs, before and after this review's changes: 0 of 25,000 invoices differ |
| Benford, first digit | MAD 0.0048, close conformity |

**Where the 617 anomalous invoices that reach no person come from.** Two causes, both known and neither a bug:

- **440 judgement-class invoices** (J1 to J4: near-duplicates, structuring, a description that does not match the
  PO, a GRN remark that contradicts the quantity) carry no rule the controls can decide. C1 runs no model; C2 to C5
  are the configurations built for them, measured only on samples so far. The 124 J3 and J4 invoices that did reach
  a person were sent for a second, rule-defined violation on the same invoice. Section 3 lists the J1 and J2 ones
  for a reviewer without a model.
- **177 rule breaches are approved with the finding recorded**: 96 of class R4 (malformed GSTIN or invalid state
  code) and 81 of R10 (weekend-dated or round amount). Their clauses are medium or low severity, and the score of
  one such finding stays below the threshold for review (eq. 5 of the paper). An audit team would usually send them
  to sampled review instead. That is a policy decision, not a code change, and is still open: it changes eq. 5.

**What these numbers do not show.** The ledger is generated, and its violations are planted to match the policy's
wording, so the 100% precision and recall of the controls is what a correct implementation of the policy should
give on it, not an estimate for a real ledger, where records are messier and the policy's wording is not the
generator's. The Benford conformity is likewise a property of the generator. The model configurations' quality on
the judgement classes is measured only on the 20-, 34- and 90-invoice samples (RESULTS.md).

## 3. Added for the auditor: the Assurance page

**The sealed record (`auditiq/seal.py`, ISA 230).** Every stored result is sealed with a SHA-256 hash over its
decision, its findings and its audit pack; every audit-trail entry, the reviewer's decision included, is chained to
the hash before it; every finished run is sealed over its results' seals. `python -m auditiq verify`,
`GET /api/trail/verify` and the Assurance page recompute them all. On the 25k store: 25,000 sealed results intact,
50,000 older results counted as stored before sealing, verified in 3.1 s. The tests change a finding, the route, the
score, the pack, a trail entry and a review state, and take a result out of a finished run: each is found, and so is a
result changed and sealed again by whoever changed it (its trail and its run no longer match). Not covered: someone
who recomputes every hash, or a run deleted whole; the digest of the run seals, kept outside the store, covers both.

**Leads under two judgement rules (`auditiq/leads.py`).** Near duplicates (2.2.2) and structuring across days (4.1.2),
listed with the policy's own guide values; a lead is not a finding and changes no result.

| Ledger | Rule | Labelled | Listed | Recall | Precision | Listed otherwise |
|---|---|---|---|---|---|---|
| final_seed_2025 (developed on) | 2.2.2 / 4.1.2 | 141 / 141 | 141 / 141 | 100% / 100% | 100% / 100% | none |
| five held-out benchmark ledgers | 2.2.2 / 4.1.2 | 30 / 30 each | 30 / 30 each | 100% / 100% | 100% / 100% | none, hard negatives included |

The first version listed 136 of 141 near duplicates and 35 of 141 structuring invoices on `final_seed_2025`; the
misses showed two defects in reading invoice numbers and that a structuring group's descriptions differ by design.
The method was changed once, then run on the other ledgers. The generator plants J1 and J2 in the pattern the policy
describes, so this shows the code follows the policy's wording, not how often real duplicates look like this. It also
means these two classes can be listed from field values: the open question whether J1 should count as a rule-defined
class applies to J2 as well.

**Monetary-unit sampling of what the audit approved (`auditiq/sampling.py`, ISA 530).** The invoices approved without
a person are the population; the sample size follows from the confidence and the tolerable and expected misstatement,
selection is by monetary unit from a seeded random start, and the Stringer bound turns what the examination finds
into an upper limit. On the 25k ledger: 23,342 approved invoices worth ₹463.8 Cr, of which ₹11.7 Cr (2.5%) are
anomalous; at 95% and a tolerable 2% the sample is 150 invoices. Over 1,000 random starts, with the answer key as the
examination, the upper limit covers the true amount in 97.4% of draws and supports reliance in 2.6%, which is right,
since the true amount exceeds the tolerable one; with the anomalous invoices removed it supports reliance in 100%.

**Evidence, data reliability, the audit program and the working papers** (second round, also on the Assurance page;
`ARCHITECTURE.md` R35; numbers from `industry.md`):

- *Evidence fingerprints* (`seal.evidence_drift`). The seals protect the results, not the ledger they were based on:
  an invoice edited after its audit left its result intact and wrong. Each result now seals a fingerprint of the
  records it read, and `verify` names the invoices whose records changed since (`stale`). On the 25k store: 25,000
  latest results re-performed in 1.6 s, all matching. Results sealed before this still verify.
- *Data reliability* (`auditiq/reliability.py`, ISA 500): 19 checks of the ledger as data, control totals and a
  fingerprint of every row. On the 25k ledger 18 of 19 are clean; the 47 invoices naming a purchase order not on file
  are what rule 2.1.3 decides. 1.2 s.
- *The audit program* (`auditiq/audit_program.py`): every test against the assertions (ISA 315) and fraud schemes
  (ACFE) it addresses, what each found, and what no test covers (bid rigging: no tender data). Scored against the
  answer key with C1 and the leads: shell company, duplicate billing, limit evasion, override, conflicts of interest
  and tax misuse 100 %; overbilling 90.5 %; goods not received 75.4 %; personal purchases 0 %. The last two are the
  rules only the agents check. Which test addresses which scheme is a written judgement in the module.
- *Working papers* (`auditiq/workpapers.py`, ISA 230): one workbook (summary, findings, queue, leads, sample,
  reliability, program, integrity) with a report digest that repeats for an unchanged store; `workpapers --check`
  says whether a workbook still matches the store. The sample's seed comes from the digest of the sealed runs. 7.1 s
  on the 25k store.

## 4. Speed

One laptop (i5-1235U), on battery, 18 November 2026. Times vary with the machine's state (a SQLite commit took 75 ms
at one time and 110 ms at another), so only changes measured in alternating rounds are attributed to the code:

| Step | Time |
|---|---|
| Read the 25,000 transactions from SQLite | 1.9 s |
| Audit them with the controls, no storage | 1.4 s (57 µs per invoice) |
| Audit and store, in-process: commit every 200 invoices / about once a second (alternating rounds) | 10.9 and 12.0 s, 128 commits / 10.0 and 10.2 s, 10 commits |
| Audit, seal and store, in-process (later, machine slower) | 16.0 to 16.4 s; under the profiler the 100,000 seal digests are 4.2 s of 31 s |
| Verify the seals of the 25k store (25,000 sealed, 50,000 older) | 3.1 s |
| Import the command line (`python -X importtime`) | 6.0 s before, 2.3 s after |

Storage, not the audit, sets a run's time; a SQLite commit took 75 to 110 ms on battery. The 16 November figure of
3.7 s for a whole run did not reproduce and is not used. API answer times are in `industry.md`: once an analysis is
cached, the endpoints answer in a median of 13 to 28 ms; the uncached ones are the sample (334 ms) and the seal
check (3.0 s), both run on request.

## 5. Changes made with this review

- C1 runs its four node functions directly instead of through the LangGraph runtime (`graph.DirectPipeline`); the
  state is identical (test in `tests/test_pipeline.py`) and `verification.json` is unchanged.
- A batch run commits about once a second; GSTIN patterns are compiled once; the stored time is formatted once a
  second; scikit-learn, SciPy and ReportLab are imported where they are used, not by every command.
- API answers of 1 kB or more are gzip-compressed (the risk map: 216 kB to 31 kB); the review queue is cached until
  the store changes (median 168 ms to 30 ms, then 16 ms); concurrent requests for the same analysis compute it once;
  one-invoice policy lookups read by key; PostgreSQL rows look columns up in a dictionary made once per statement;
  hidden browser tabs stop polling.
- Sealed results, chained trail entries and sealed runs, with `python -m auditiq verify`, `GET /api/trail/verify`
  and an integrity badge on each invoice; three columns added to older stores when they are opened.
- `GET /api/leads` and `GET /api/sampling`, and the Assurance page (`/assurance`) that shows all three.
- `evaluation/industry.py`, `evaluation/leads_eval.py` and the tests `test_industry.py`, `test_seal.py`,
  `test_leads.py`, with new API and page tests.
- Second round: evidence fingerprints (`audit_results.evidence`) with re-performance, `GET /api/reliability`,
  `GET /api/program`, `GET /api/workpapers`, `python -m auditiq workpapers`, the `stale` state on the invoice page, and
  `tests/test_workpapers.py`.
