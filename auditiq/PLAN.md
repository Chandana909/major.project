# AuditIQ: implementation plan

Last updated 2026-10-13. This plan turns the paper draft
(`../paper/auditiq_paper.tex`) into a working standalone system and measured
results. The folder `../AuditIQ-DeloitteHacksplosion-main` holds the Flowise
export of the hackathon prototype and is kept for reference only; nothing here
reads it.

## 1. Goal

The paper states five extra features (E1 to E5), six configurations (C0 to C5)
and six hypotheses (H1 to H6), and reports no measurements. The work is:

1. build the system as a standalone project,
2. generate AuditIQ-Bench,
3. run C0 to C5 on it,
4. replace Section VII ("Expected Results") with measured results.

Rule for the whole plan: a number goes into the paper only if a script in this
repository produced it from a dataset in this repository.

## 2. Architecture

Decided on 2026-10-11: the system does not depend on Flowise. It is one Python
project.

| Concern | Choice | Why | Considered and not chosen |
|---|---|---|---|
| Orchestration | LangGraph `StateGraph` | The pipeline is a fixed graph with one parallel fan-out and one human pause. LangGraph gives typed shared state, parallel branches, `interrupt` and resume for the reviewer, and a diagram of the graph for the paper. Each configuration C1 to C5 is the same nodes with some left out. | Plain functions: no pause and resume, no diagram. CrewAI or AutoGen: role-play conversation between agents, where this design needs fixed stages and exact control of every call. |
| Agents | One structured LLM call per agent, no tool loop | With the controls running first, an agent has nothing to compute. A single call per agent is cheaper and easier to reproduce, and its cost is known in advance. | ReAct agents with tools, as in the prototype. |
| LangChain | Not used | Chains, prompt templates and model wrappers add nothing here. `langchain-core` is present only as a dependency of LangGraph. | |
| Model access | Own client over HTTP for any OpenAI-compatible endpoint (`auditiq/llm.py`) | Works with local Ollama, hosted open-weight models and a LiteLLM gateway without code changes. Full control of temperature, seed, retries, token accounting. | `langchain-openai`, LiteLLM SDK: another dependency for one POST request. |
| Reproducibility | SQLite cache of every reply, keyed by the full request | A repeated run costs nothing and returns the same text. C3, C4 and C5 share their agent calls. | |
| Controls and scorer | Python modules | One language for the whole project. The first version was JavaScript so that it could be pasted into Flowise nodes; that reason is gone. The port was checked against the JavaScript on 3,900 transactions and 8,500 scoring cases with no difference. | |
| Audit pack | Assembled by code from the verified flags | It cannot state anything the pipeline did not establish. The prototype had an LLM write it. | |
| Database | SQLite or PostgreSQL behind one interface (`auditiq/db.py`), tables named as in `schema_v3.sql` | SQLite needs no server and is the default. PostgreSQL gives typed money and dates, concurrent readers and a role that confines the copilot's queries. SQL is written once; loaders make both return the same values, and the database tests run on both. | An ORM: one more layer for seventeen tables and plain queries. |
| Review queue | A state in the database | An escalated result waits as `PENDING_REVIEW` until a decision is recorded, so the queue survives a restart and is the same for the command line and the dashboard. LangGraph's `interrupt` remains for the interactive single audit. | LangGraph SQLite checkpointer: another package, and the paused graph would hold nothing the result row does not. |
| Policy documents | PDFs are ingested into clause chunks with page numbers and checked against the clause registry | A finding can cite "document, page", and a PDF that disagrees with the parameters the controls use is reported instead of silently shown. | |
| Policy search | Lexical ranking, question rewriting by the chat model, and embeddings behind one interface | Retrieval serves the copilot and the citations. The agents still read the whole policy: their clauses are fixed by their remit, so retrieving per invoice would add a failure mode and no information. | A vector database: the corpus is tens of passages; a matrix product is enough. |
| Interface | Command line and a Streamlit dashboard | Streamlit was already installed and needs no separate front-end build. | Appsmith. |

## 3. Layout

```
auditiq/         the pipeline, the database, policy documents and search, copilot, command line
auditiq_bench/   AuditIQ-Bench generator and validator; shares no code with the pipeline
evaluation/      configuration runners, metrics, statistics, reports, retrieval evaluation
app/             the Streamlit dashboard
policy/          clause registry with parameters, text templates, SOP v2.5 and v2.6, sample PDFs
data/            generated datasets: bench_seed_101/202/303, pilot_seed_909, swap_seed_404, large_seed_505
results/         predictions, metrics, summary.md, retrieval.md, history_cap.md, pilot reports
docs/            ARCHITECTURE, DATA_DICTIONARY (generated), DATASETS (generated), OPERATIONS
deploy/          Ollama Modelfile, PostgreSQL compose file
scripts/         pg_local.py: a local PostgreSQL server without installation
tests/           the test suite; no test calls a model
```

## 4. Phases

### Phase A: everything that needs no LLM (done)

| # | Deliverable | Status |
|---|---|---|
| A1 | SOP v2.5: one numbered rule per exception, one severity each, clauses for all fourteen classes | Done: 16 clauses |
| A2 | Clause registry with parameters; v2.6 for the policy swap | Done |
| A3 | SQL for the clause and parameter tables | Generated; not applied to any database |
| A4 | Generator: benchmark ledgers of 5,000 invoices from 250 vendors (420 anomalous, 120 hard negatives, 4,460 ordinary clean), labels written at injection | Done: seeds 101, 202, 303, and the pilot ledger, seed 909; byte-identical on re-run; about 20,750 ledger records each |
| A5 | Policy-swap ledger: 150 boundary invoices, labelled under v2.5 and v2.6, among 4,850 invoices that are clean under both | Done: seed 404 |
| A6 | Controls for R1 to R10 | Done: 12 controls |
| A7 | Scorer: equations (2) to (5) | Done; 20,000 random flag sets confirm Rc <= R0 and an unchanged approved set |
| A8 | C0, C1, metrics of Sec. VI-C as ratios of weighted sums, stratified bootstrap intervals, McNemar, Holm | Done; `results/summary.md` |
| A9 | Construction checks of Sec. VII-A | Pass on seeds 101, 202, 303, on the large ledger and on an unseen seed in the test suite |
| A10 | A ledger at a realistic anomaly rate: 20,000 invoices, 1,000 vendors, 420 anomalous (2.1%), 240 hard negatives | Done: seed 505; 83,495 records in the five tables; C0 and C1 evaluated on it |
| A11 | Evaluation subset of each ledger with weights, so that the LLM configurations audit 1,200 invoices and their rates estimate the ledger | Done; the weighted subset reproduces the whole-ledger metrics of C0 and C1 (`results/summary.md`, section 5) |
| A12 | Documentation of every dataset and every column | Done: `docs/DATASETS.md`, `docs/DATA_DICTIONARY.md` and a datasheet per dataset, all generated and checked by tests |

What phase A showed (`results/summary.md`, run of 2026-10-13):

1. **The construction checks hold** on the three benchmark ledgers and the
   large ledger. The controls report every R1 to R10 invoice under the labelled
   clause, no J1 to J4 invoice, and nothing on the clean and hard-negative
   invoices. Under v2.6 they raise no flag on the 150 boundary invoices, all of
   which they flag under v2.5, and none on the other 4,850 invoices under
   either version.
2. **Classical detectors, measured on whole ledgers with cross-fitted
   thresholds.** Mean over the three seeds (8.4% anomalous): isolation forest
   recall 0.577, precision 0.501, F1 0.536; one-class SVM 0.464, 0.543, 0.498;
   controls 0.714, 1.000, 0.833. The detectors flag 4.4% and 2.5% of ordinary
   clean invoices and 40% and 48% of hard negatives. These are untuned
   baselines.
3. **J1 is decidable from field values as generated.** Both detectors report
   every J1 invoice on the benchmark ledgers: an invoice that is not the first
   on its PO is either an R3 or a J1. See open decision 2.
4. **J3 and J4 are the classes no field comparison finds** (detectors: 0% to
   2%). J2 is found 22% and 7% of the time.
5. **At a realistic anomaly rate the detectors do worse.** On the 20,000-invoice
   ledger (2.1% anomalous): isolation forest recall 0.162 and precision 0.301;
   one-class SVM 0.402 and 0.460; controls 0.714 and 1.000. The paper should
   report these measured values instead of the precision computed from the
   formula of Sec. VI-C, and say that the threshold was chosen again on that
   ledger.
6. **The weighted evaluation subset reproduces the whole ledger.** For C0 and
   C1, recall and the hard-negative false-positive rate are identical on the
   subset and the ledger; precision and the ordinary false-positive rate agree
   within sampling error.

### Phase B: the LLM pipeline (built; real runs pending)

| # | Deliverable | Status |
|---|---|---|
| B1 | Model client with cache, retries and token accounting | Done; tested against a fake endpoint and used for the real calls of B8 |
| B2 | Prompts without thresholds or rule numbers; the policy text is inserted at run time and is a shared prefix of every call | Done; first wording, to be fixed on the pilot |
| B3 | Three specialists with remits derived from the policy sections; flags outside the remit discarded by code | Done |
| B4 | Challenger that can remove agent flags only | Done |
| B5 | Agreement term: m = 3 re-runs at temperature 0.7 of each agent that raised a flag | Done |
| B6 | LangGraph graphs for C1 to C5; human review by `interrupt` and resume | Done |
| B7 | Runner for any configuration over a dataset, resumable; comparison report | Done |
| B8 | Smoke test on a real model | Done on one invoice, all stages; see section 6 |
| B9 | Pilot on stratified invoices of the pilot ledger to fix the prompts and measure cost | Done with the local 7B model on 20 invoices (one of each of the 14 classes, the five hard-negative types, one ordinary invoice) under C1 to C5, and on six invoices before that; both are recorded in section 6. A pilot of 50 or more needs a faster endpoint (open decision 1) |
| B12 | The configurations on a sample of a benchmark ledger, with frozen prompts | 34 invoices of `bench_seed_101` (5 of each judgement class, 2 of each hard-negative type, 4 ordinary; `evaluation/bench101_sample_ids.txt`, drawn by `evaluation.sample_ids`), C1 then C3, C4, C5 and C2, with the local 7B model; started 2026-10-18 (`results/bench_seed_101/sample34.*`) |
| B11 | Bounded prompts: at most 40 of a vendor's other invoices per selection rule | Done; no labelled case loses an invoice it depends on (`results/history_cap.md`) |
| B10 | Full run: 3 seeds x C2 to C5; second model on the main comparison; consistency subset of 300; policy swap under v2.5 and v2.6 | Pending |

Everything in B1 to B7 is verified with a scripted stand-in for the model. That
shows that the pipeline asks, parses, scores and routes as designed. It shows
nothing about how well a model audits.

### Phase C: the application (built)

| # | Deliverable | Status |
|---|---|---|
| C1 | Database (SQLite and PostgreSQL): ledger, policy store, audit runs, results, flags, per-stage audit trail, review decisions | Done; extraction from the database returns the same transactions as extraction from the files, on both backends |
| C2 | Review queue that survives a restart; decisions with reviewer and justification | Done. Sending an analysis back for re-analysis is done by auditing the invoice again; the newer result takes its place in the queue |
| C3 | Batch audit of the ledger, storing every result | Done; 20,000 invoices under C1 in about one minute on SQLite and three on PostgreSQL (the ledger is read in bulk for a batch run) |
| C4 | Policy PDFs: three sample documents, ingestion with page numbers, check against the registry, citations in audit packs | Done; all 16 clauses of each version come back from the PDF word for word |
| C5 | Policy search: lexical, question rewriting, embeddings | Done and measured with `nomic-embed-text` (below) |
| C6 | Copilot: policy and invoice questions with cited passages; data questions as one checked, read-only SELECT | Done; tested with a scripted model, and once with the local model (section 6) |
| C7 | Streamlit dashboard: overview, review queue with decision form, invoice, policy, copilot | Done; headless tests and a visual check in the browser |
| C14 | REST API (FastAPI) with background jobs, optional token, safe uploads, OpenAPI description; web application in React and TypeScript with 3D views in React Three Fiber (risk constellation, pipeline graph, policy-change bars) | Done (`docs/WEB.md`); 10 API tests on both backends, 26 frontend tests including the 3D scenes; visual check of every page in the browser; no known vulnerability in the frontend's packages (`npm audit`) |
| C8 | Loading a new ledger from CSV | Done (`setup --dataset`). Excel upload and upload through the dashboard are not built |
| C9 | Packaging | `pip install -e .` with an `auditiq` command; `npm ci && npm run build` for the frontend. CI on GitHub runs ruff and the tests on SQLite and PostgreSQL, and lint, typecheck, tests, build and audit of the frontend, on every push. The PostgreSQL compose file has not been run (no Docker on the development machine) |
| C11 | Policy adoption from a document: thresholds read from the PDF by pattern; command line and dashboard; re-audit of the ledger under the adopted version | Done and measured (`results/policy_change.md`, `docs/FEATURE_POLICY_AS_DATA.md`) |
| C12 | Policies in their own wording: a model proposes rules and thresholds, code verifies them against the document, a named reviewer confirms | Done and measured on six free-form documents: 80 of 84 values proposed correctly; the code check verified 56, held back 24 correct ones for the reviewer, caught 2 wrong ones and passed 2 (`results/policy_llm.md`) |
| C15 | Held-out policy documents: 20 variants drawn at random from values never used to build or check the reader | Measured (`results/policy_heldout.md`): 280 of 280 values, 320 of 320 rules, no wrong decision in 800,000 audits; this measures what the paper listed as expected value X1 |
| C16 | Robustness of the reader: 16 edited documents that must be read correctly or refused | Measured (`results/policy_robustness.md`). The first run (2026-10-18, `policy_robustness-before-fix.md`) found that a rule stated twice and an approval table without a role were adopted; both are now refused, with tests; 16 of 16 as required |
| C17 | The application run of a policy change as a script | Done (`evaluation/application_demo.py`, `results/application_demo.md`); the counts equal the ones recorded by hand on 2026-10-13 |
| C18 | One results document for the paper | Done: `../RESULTS.md`, with figures from `python -m evaluation.figures` |
| C13 | Throughput of the control stage against worker processes and ledger size | Measured (`results/scalability.md`) |
| C10 | Logging and failure messages | Done: one log format for the command line and the dashboard; an unreachable database and a failing model endpoint end with a message, not a traceback |

Policy retrieval on 48 fixed questions (`results/retrieval.md`; the questions
are in `evaluation/retrieval_queries.json`). Sixteen are in the policy's
wording; thirty-two are paraphrases, half used to choose the default ranking
(dev) and half never used for a choice (test). Embeddings: `nomic-embed-text`;
rewriting: `qwen2.5-coder:7b`.

| Ranking | Paraphrases, dev: R@1 / R@3 | Paraphrases, test: R@1 / R@3 |
|---|---|---|
| lexical | 0.062 / 0.250 | 0.250 / 0.312 |
| dense | 0.625 / 0.812 | 0.438 / 0.812 |
| hybrid | 0.250 / 0.688 | 0.312 / 0.312 |
| lexical after rewriting | 0.625 / 0.938 | 0.625 / 0.812 |
| dense after rewriting | 0.625 / 0.875 | 0.562 / 0.938 |
| hybrid after rewriting | 0.750 / 0.938 | 0.625 / 0.938 |

Lexical ranking finds every question asked in the policy's wording (R@1
1.000). The default is dense for a question as asked and hybrid for a restated
one, chosen on the dev half. Sixteen questions per cell: the differences
between neighbouring cells are a question or two. This is one retriever on
questions written by its author, on 27 passages of two documents (the active
policy version and the review procedure). The lexical, dense and hybrid rows
were measured again after the correction of the policy dates and did not change.

### Phase D: the paper

| # | Deliverable |
|---|---|
| D1 | Section VII rewritten with measured tables and intervals; each hypothesis marked supported or refuted |
| D2 | Section V (System Implementation) and Table III rewritten for the standalone stack of section 2 |
| D3 | Abstract, contributions, figure and conclusion updated to match |
| D4 | The items in the header comment of `auditiq_paper.tex` closed (model identifier, base papers read in full, Roumeliotis reference checked) |
| D5 | Every decision of section 5 reflected in the text |

## 5. Decisions made while implementing (differences from the draft)

1. **No Flowise.** The draft describes a Flowise prototype with Appsmith and a
   hosted PostgreSQL. The system is now the stack of section 2.
2. **Policy v2.5 renumbers 2.2.2.** In v2.4 it is a routing instruction; in v2.5
   every numbered rule defines one exception, and 2.2.2 is the near-duplicate
   rule. The illustration in Sec. IV-C cites 2.2.1 for a near-duplicate and
   calls a round amount "medium"; under v2.5 these are 2.2.2 and "low".
3. **R4 and R5 are disjoint by policy.** Clause 3.1.3 (mismatch with the vendor
   master) applies only to a well-formed GSTIN.
4. **Duplicates label the later invoice.** For R3 and J1 the earlier invoice is
   the original and stays clean.
5. **"Amount exactly at an approval limit" cannot be a clean hard negative.**
   Limits are round amounts, so such an invoice violates 4.3.1. The hard
   negative is an amount just inside the limit.
6. **Approval limits are policy parameters by role.** The control uses the limit
   of the approver's role in the active policy, not the `amount_limit` column of
   the approval log; otherwise the policy swap could not change the outcome.
7. **An empty evidence set gives g = 0.**
8. **C0 uses cross-fitted thresholds and 22 generic features.** The ledger is
   split into five folds stratified by class; the threshold applied to a fold
   is chosen on the other four, so every invoice is scored and none with a
   threshold tuned on its own label. This replaced a single 20/80 split, which
   left a fifth of the ledger out of every comparison.
9. **A valid clause fixes the severity.** The scorer takes the severity of the
   cited clause from the policy; an agent is not asked for a severity.
10. **No GSTIN longer than 15 characters is generated** (`VARCHAR(15)` in the
    schema).
11. **Evidence is a list of record fields** (`invoice.amount`,
    `history.<invoice_id>.invoice_number`). Derived values belong in the
    explanation, because grounding can only be checked against stored fields.
12. **Agent remits follow the policy sections.** Math and Approvals: sections
    2.1 and 5 (judgement clauses 2.1.4, 2.1.5). Tax and Identity: 2.2 and 3
    (2.2.2). Vendor Intelligence: 4 (4.1.2). A flag citing a clause outside the
    remit is discarded and counted.
13. **The challenger cannot remove a control flag.** It rules on agent flags
    only; a flag it gives no verdict on is kept. It sees the records that were
    shown to the agents whose findings it tests, not the whole transaction.
14. **The challenger is not called when no agent raised a flag,** and agreement
    re-runs are made only for agents that raised a flag that survived.
15. **The audit pack is assembled by code,** not written by an LLM.
16. **A reply that is not valid JSON is sent back once for repair.** A stage
    that fails twice contributes no flag; both are counted in the results.
17. **Authorship of generator and controls.** The draft says one author writes
    the generator and the other the controls from the policy text. Both were
    drafted in one session. They share no code (a test enforces it), but that
    sentence is not true until each author has reviewed one side.

18. **The large ledger keeps the benchmark's 420 anomalous invoices.** Thirty
    per class in 20,000 invoices gives 2.1%, the rate the draft assumes. It is
    used for the baselines and the application.
19. **Retrieval serves the copilot and the citations, not the agents.** See the
    architecture table.
20. **The copilot cannot write and cannot read the labels.** A data question
    becomes one SELECT that is checked, refused if it names a table outside an
    allow-list, and run on a read-only connection with a row and time limit.
21. **Each sample PDF is rendered from the text the pipeline applies,** and the
    review procedure from the scorer's own constants, so the documents cannot
    drift from the system.

22. **Benchmark ledgers have 5,000 invoices, not 1,200.** The draft's dataset is
    the 1,200 invoices that now form the evaluation subset. Around them stand
    3,800 further clean invoices, so that vendors have realistic histories and
    the anomaly rate is 8.4% instead of 35%. The LLM configurations audit the
    subset with the whole ledger as history; the weights make their rates
    estimates for the ledger. Sec. VI-A of the paper must be rewritten for this.
23. **Vendor history is capped at 40 invoices per selection rule.** Chosen
    before looking at any label; checked afterwards against the labels on every
    dataset with no loss.
24. **Policy v2.5 is effective 2025-04-01 and v2.6 2026-04-01.** The ledgers
    cover the financial year 2025-26; an earlier draft dated the policy after
    the invoices it was applied to.
25. **A review decision is the last entry of the audit trail** of its result,
    with the reviewer as the actor.

## 6. Open decisions

1. **Which model runs C2 to C5.** See the measurements below. The client needs
   a base URL, a model identifier and a key (`.env.example`). The paper says
   "an open-weight LLM"; a hosted open-weight model satisfies that.
2. **What to do about J1.** (a) Reclassify it as rule-defined: add a control for
   2.2.2 and report eleven rule-defined and three judgement classes.
   (b) Change the generator so that legitimate invoices can share a PO.
   (c) Leave it and state the limitation. Recommended: (a).
3. **Rotate the database password** of the hackathon prototype: it is written
   in 43 files of the reference folder.

### Smoke test on a real model (2026-10-12)

One pilot invoice (seed 909, `INV40029`, class J4) was audited under C3 and C5
with `qwen2.5-coder:7b` served by the local Ollama, on the laptop's CPU. This
checks that every LLM stage works against a real model. It is one invoice and a
small coding model: it is not a result and says nothing about H1 to H6.

- All 7 replies were JSON of the required form; none needed the repair request.
- The Math and Approvals agent cited clause 2.1.4 with the GRN remark as
  evidence; the evidence matched the record (g = 1).
- The Vendor Intelligence agent raised a wrong flag (clause 4.1.2, claiming a
  Wednesday was a Saturday). Its cited field existed, so g = 1 for a wrong
  flag, which is the limitation stated in the paper. The challenger removed it.
- Two of the three re-runs reproduced the 2.1.4 flag (a = 0.67, confidence
  0.89). Route: escalate.
- Size: 2,300 to 2,800 prompt tokens per call; 16,898 prompt and 556 completion
  tokens for this invoice under C5 (7 calls). An invoice on which no agent
  raises a flag needs 3 calls.
- Speed on this laptop (i5-1235U, no GPU): 20 to 245 seconds per call.

### Real-model check through the database (2026-10-13)

The same local model, on the 15,000-invoice ledger that was in the database
that day (since replaced by the 20,000-invoice ledger, so these ids differ): one
invoice (`INV48779`, class J4) under C5, then two copilot questions. Again one
invoice and a small coding model: a check that the parts work together, not a
result.

- The run was stored with its 10 model calls in the audit trail, and the
  invoice entered the review queue.
- The correct finding (2.1.4) was raised with matching evidence and
  reproduced by two of three re-runs.
- **A wrong finding passed with confidence 1.00.** The Tax and Identity agent
  called `GUL00715` a re-keyed form of `GUL00714`: consecutive numbers, which
  the policy says are not duplicates. The challenger kept it and all three
  re-runs repeated it. Its cited field exists, so g = 1, p = 1, a = 1. The
  confidence terms measure support and stability, not correctness; a model that
  is consistently wrong scores high. The pilot must report how often this
  happens before H4 is read as anything.
- The challenger removed a third proposed finding (2.1.5) with a correct reason.
- **The local server cut a prompt without saying so.** In a first attempt the
  challenger prompt exceeded Ollama's default context of 4,096 tokens; the
  server dropped part of it, the reply lost its format, and the stage failed.
  Two changes followed: the challenger now sees only the records of the agents
  whose findings it tests, and `AUDITIQ_LLM_CONTEXT` makes the client refuse a
  prompt that would not fit. A hosted model with a larger context does not
  have this problem; a local run on a vendor with many invoices does.
- Copilot, policy question: the right passage was retrieved and cited, and the
  answer explained the finding, then ended with a sentence that contradicted
  it. That is the model, not the retrieval.
- Copilot, data question: the first query used the ledger's payment-approval
  column and returned nothing. After the schema notes were made explicit and
  the review-queue view was exposed, the model wrote a correct query.

What this means for open decision 1:

- **The full protocol cannot run on this laptop.** One dataset needs 1,200
  single-prompt calls and 3,600 specialist calls before any challenger call or
  re-run: at these speeds, days of continuous computing per dataset.
- **A pilot of 50 invoices is a day's computing here**, not a few hours as first
  estimated: see the run of 2026-10-13 below. The laptop must be kept awake (it
  went to sleep once during the test).
- **Estimated volume of the full run** (from the prompt sizes above, not
  measured): about 12 million prompt tokens per dataset for C2 to C4, so about
  36 million for the three seeds, plus the re-runs of C5, the second model and
  the consistency subset. Output is small, around 100 tokens per call.
- The paper should use a general-purpose open-weight model, not a coding model.

### Real-model run on the pilot ledger (2026-10-13 and 14)

`python -m evaluation.run_pilot --dataset data/pilot_seed_909 --ids-file evaluation/demo_ids.txt --tag demo`
audits six invoices (one of each judgement class J1 to J4, one hard negative
with a similar invoice number, one ordinary invoice) under C1 to C5 with
`qwen2.5:7b` at a 12,288-token context. The report is
`results/pilot_seed_909/demo.md`. Six invoices are a check that every stage
works against a real model, and a first look at cost; they are not a result,
and no difference between configurations can be claimed from them.

- All five configurations completed. No stage failed; one reply of C2 needed
  the repair request.
- C3 raised the right rule on the J4 invoice (2.1.4, evidence found in the
  records) and on the J1 invoice (2.2.2, but with evidence that is not in the
  records). It missed J2 and J3, raised a wrong 2.2.2 on the J3 invoice, and
  raised two findings on the hard negative.
- C4: the challenger removed the right J1 finding and the wrong 4.1.2 on the
  hard negative, and kept the two wrong 2.2.2 findings.
- C5: the wrong 2.2.2 on the J3 invoice was repeated by one of three re-runs
  (confidence 0.44), so the invoice moved from escalation to sampled review.
  The wrong 2.2.2 on the hard negative was repeated by all three re-runs
  (confidence 0.67, at the threshold) and stayed escalated. The right J4
  finding had confidence 1.00. Confidence demoted one wrong finding and not the
  other: it measures support and stability, not correctness.
- C2, one prompt over the whole policy, raised five rule-defined findings on
  the ordinary invoice, none of them true, and flagged all six invoices.
- Cost per invoice: C3 3 calls and 9,744 tokens; C4 3.67 and 12,422; C5 5.17
  and 18,137; C2 1.17 and 5,978. On this laptop one call took about four to six
  minutes on average, waiting included.

The benchmark (1,200 invoices per ledger, several calls each) is out of reach
on this laptop; it needs a GPU or a hosted endpoint.

### Real-model pilot of 20 invoices (2026-10-14)

`python -m evaluation.run_pilot --dataset data/pilot_seed_909 --ids-file evaluation/pilot_ids.txt --tag pilot20`
audits 20 invoices of the pilot ledger (one of each of the 14 anomaly classes,
one of each of the five hard-negative types, one ordinary invoice) under C1 to
C5 with `qwen2.5:7b` at a 12,288-token context, on the laptop's CPU (about five
and a half minutes per model call). The report is
`results/pilot_seed_909/pilot20.md`. Twenty invoices are a pilot: the intervals
are wide, and no McNemar comparison is significant (C3 against C2: 9 invoices
right only under C3, 2 only under C2, Holm-adjusted p = 0.196).

| | C1 | C2 | C3 | C4 | C5 |
|---|---|---|---|---|---|
| Invoice-level recall | 0.714 | 0.929 | 0.929 | 0.857 | 0.857 |
| Invoice-level precision | 1.000 | 0.722 | 0.812 | 0.800 | 0.800 |
| Judgement classes found (of 4) | 0 | 1 | 2 | 1 | 1 |
| Hard negatives flagged (of 5) | 0 | 4 | 3 | 3 | 3 |
| Ordinary invoice flagged (of 1) | 0 | 1 | 0 | 0 | 0 |
| Citation correctness | 1.000 | 0.091 | 0.500 | 0.688 | 0.688 |
| Model calls per invoice | 0 | 1.15 | 3.00 | 3.60 | 4.95 |
| Prompt and completion tokens per invoice | 0 | 5,835 | 9,557 | 12,005 | 16,779 |

- C1 decided every rule-defined class right and flagged nothing else; it
  cannot see the judgement classes, by design.
- C3's agents found J4 (Rule 2.1.4, with the goods-receipt remark as evidence)
  and J1 (Rule 2.2.2), missed J2 (the weekend bill) and cited the wrong rule
  on J3. They also raised a wrong 2.2.2 on three hard negatives and extra
  findings on six invoices the controls had already flagged.
- C4's challenger removed most of the extra findings and the wrong 4.1.2 on
  the similar-number hard negative, but also the right J1 finding, and kept the
  wrong 2.2.2 on the three hard negatives.
- C5's confidence sent two invoices to sampled review instead of escalation
  (the J3 invoice, whose wrong-rule finding had confidence 0.44, and an R10
  invoice); both are true anomalies. The wrong findings on the hard negatives
  had confidence 0.67, 0.67 and 1.00 and stayed escalated: once more,
  confidence measures support and stability, not correctness.
- C2, one prompt over the whole policy, flagged 18 of the 20 invoices: five
  wrong findings on the ordinary invoice, wrong rule-defined findings on most
  invoices (macro-F1 on the rule-defined classes 0.095), and two failed stages.
  The controls-first design avoids exactly this.

### Real-model check through PostgreSQL (2026-10-14)

`results/llm_checks.log`. One invoice of the 20,000-invoice ledger
(`INV51287`, class J4: a goods-receipt remark says 28 rolls were returned)
audited under C5 in PostgreSQL, then the copilot.

- C5 made 7 model calls (16,020 prompt tokens), no stage failed. The Math and
  Approvals agent raised Rule 2.1.4, all three re-runs repeated it (confidence
  1.00), the invoice was escalated and entered the review queue, and the
  finding cites the SOP, page 1.
- **The copilot first answered wrongly.** Asked "Why was INV51287 flagged, and
  which rule applies?", it said Rule 2.2.1 (exact duplicate): retrieval by the
  question's wording had found the duplicate rules, and the model followed the
  passages instead of the audit record it was also given. Fix: for an audited
  invoice the passages of the rules its findings cite come first, and the
  instructions say the audit record is the authority. Asked again, it answered
  Rule 2.1.4 with the remark and the accepted quantity, citing page 1.
- Data question "Which five vendors have the most invoices waiting for review?":
  the model wrote a correct query over `v_review_queue`, which ran as the
  read-only role.

## 7. Risks

- **Rule-defined classes are circular.** The controls implement the definitions
  used to inject R1 to R10, so C1 scoring 100% there is a correctness check.
  The informative numbers are J1 to J4, hard negatives, citation and routing.
- **Cost of the agreement term.** C5 adds three calls per agent that raised a
  flag. The pilot measures this before the full run.
- **Judgement labels must be unambiguous.** A borderline case found by an LLM
  run is fixed in the generator and the dataset regenerated; it is not
  relabelled by hand.
- **Prompt tuning on the test data.** Prompts are fixed on the pilot dataset
  (seed 909), which is not one of the three reported seeds. The prompt hash is
  stored with every run.
- **A small model may fail the output format.** The runner counts failed stages
  and repaired replies; a configuration with many failures measures the format,
  not the method.

## 8. How to run

See `README.md`.
