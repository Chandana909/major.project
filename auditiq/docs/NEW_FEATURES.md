# The intelligence layer (21 November 2026): ideas, what was built, what it measures

This round asked for features that make AuditIQ stronger for the final-year review and for interviews: better agents
for audit questions, SHAP or other explanations, an agent that checks the audit trail and reports what happened
where, and automatic classification. Below is the brainstormed list, then the five features built, how to run them
and what they measured. Every number here comes from a script in the repository; see "Limits" before quoting one.

## 1. Brainstormed ideas

| # | Idea | Why it is a selling point | Status |
|---|---|---|---|
| 1 | **Explainable risk screen**: gradient-boosted trees per judgement rule + exact TreeSHAP | ML with exact, verified explanations; a cheap screen in front of the slow LLM agents (a cascade) | **Built** |
| 2 | **Counterfactual explanations** of control findings ("what would clear it", margin past the rule, policy what-if with blast radius) | Explainability for rule-based decisions; ties into policy-as-data | **Built** |
| 3 | **Trail investigator agent**: audits the audit (seals, coverage, review quality, segregation of duties, rubber-stamping, overrides, opinion shopping, unexplained flips), invoice stories, a Markdown report | "Who audits the auditor": ISA 230/220/240, COSO, SOX in code | **Built** |
| 4 | **E-mail triage and payment-redirection (BEC) detection**, hold list, prompt-injection quarantine | Closes the Review-1 deck's "e-mail triage agent"; real AP fraud pattern | **Built** |
| 5 | **Tool-using audit agent**: 15 tools, rules planner (no model) or ReAct model planner, citations, number verification | Answers audit questions without a GPU; shows agent design (planning, tools, grounding) | **Built** |
| 6 | P2P process mining (event log, directly-follows graph, conformance) | Celonis-style view of the procure-to-pay flow | **Built** (second round, see below) |
| 7 | LLM-polished engagement report with a number-preservation guard | Narrative audit-committee report | Not built: needs a model at every use; the investigator's report is already written by code |
| 8 | Vendor behaviour drift (change points in monthly spend) | Continuous monitoring | Not built: the generator plants no change in a vendor's spending, so it could only report noise |
| 9 | OCR of scanned invoices (PyMuPDF + Tesseract) | Deck item C28 | Not built: there are no scanned invoices to read or to measure it on |
| 10 | Red-team suite of prompt injections against the agents (needs model runs) | LLM security (OWASP LLM01) | Not built: needs model runs; the detector exists in triage and the agent withholds such text |

## 2. What was built

| Feature | Code | Command line | API | Web page |
|---|---|---|---|---|
| Risk screen + SHAP | `auditiq/screen.py`, `auditiq/treeshap.py`, model `models/risk_screen.json` | `python -m auditiq model train`, `model explain --invoice INV…` | `GET /api/model`, `GET /api/invoices/{id}/explain` | `/explain`; invoice page "Why the risk screen scores this invoice" |
| Counterfactuals | `auditiq/counterfactual.py` | `model explain --invoice INV…` | in `/api/invoices/{id}/explain` | invoice page "What would clear each finding" |
| Trail investigator | `auditiq/investigator.py` | `python -m auditiq investigate [--out report.md] [--invoice INV…]` | `GET /api/investigation`, `GET /api/invoices/{id}/story` | `/investigator`; invoice page "The story of this invoice" |
| E-mail triage | `auditiq/triage.py` | `python -m auditiq mail load file.mbox`, `mail triage` | `GET /api/mail`; `email_triage` in the invoice | `/mail`; risk badges on the invoice's e-mails |
| Audit agent | `auditiq/audit_agent.py` | `python -m auditiq agent "question" [--mode rules|model]` | `POST /api/agent/ask` (job) | `/agent` |
| Process mining | `auditiq/process_mining.py` | (the API and the page) | `GET /api/process` | `/process` |

The API now has 53 endpoints (`docs/API.md`, regenerated). Nothing here changes a result, score or route of the audit:
equations 2 to 5 of the paper are untouched.

## 3. What was measured

| Script | Result file | What it shows |
|---|---|---|
| `python -m evaluation.screen_eval` | `results/risk_screen/screen.md` | Trained only on `pilot_seed_909`, scored on six held-out ledgers: AUC 1.000 (2.1.4, 2.2.2, 4.1.2) and 0.993 (2.1.5) vs isolation forest 0.47 to 0.98; of 1,040 judgement anomalies the controls approve, 890 (85.6%) are in the top 2% of the invoices the controls approve; suggested rule right for 985 of 985 scored at least 0.5; the two SHAP implementations agree to 1.8e-15; the committed model is reproduced exactly |
| `python -m evaluation.investigator_eval` | `results/investigator/investigator.md` | 54 faults planted in an audited `bench_seed_101` store (11 kinds): all found at their place, 0 missed, 0 extra; 0 places reported on the store run properly |
| `python -m evaluation.triage_eval` | `results/triage/triage.md` | Four generated mailboxes, 17,011 e-mails: categories 100%, 54 of 54 redirection attempts caught, 0 false alarms, 152 of 152 genuine bank changes sent for confirmation |
| `python -m evaluation.agent_eval` | `results/agent/agent.md` | Rules mode, `collusion_seed_707`, 17 intents: dev wording 30 of 30; frozen test wording 27 of 30 (misses kept: "largest number of findings" ranked by amount; "altered the stored audit record" and "duplicate bills under a re-keyed number" matched no tool) |

## 4. Limits

- Every ledger and mailbox comes from the project's own generator. The screen's and the triage's numbers show that
  they work on this generator's data, not their accuracy on real invoices or real mail.
- The investigator's faults are planted exactly as its checks define them: it shows the checks work, not how often
  such faults happen; an insider who also recomputes every seal is not caught.
- The agent's questions were written by the planner's author; the model (ReAct) mode is built but was not measured
  (no fast model endpoint on the laptop).

## 4b. Process mining (built in the second round, 21 November 2026)

Of the five ideas left after the first round, process mining was the one the data supports and that adds something
without a model. `auditiq/process_mining.py` turns the ledger into an event log (PO raised, goods received, invoice
dated, each escalation, approval, due date: every step's time is already in the five ledger tables), and derives the
process map (how often one step directly follows another and the median days between them), the variants, the
conformance of each invoice to the reference path PO -> goods receipt -> invoice -> approval -> due date, cycle times
and approval time by role. `GET /api/process` (cached until the store changes), page `/process` with the map drawn
in SVG. On `collusion_seed_707` (5,000 invoices, 0.14 s): 99.4% follow the reference path; 701 invoices were
escalated before approval; the deviations are invoices without a PO or a goods receipt, and the audit already flags
every one of them (rule 2.1.3). On generated data it confirms the controls from another angle rather than finding
something new; on a real ledger the same code would show late approvals, invoices dated before the goods arrived,
and which roles slow the process. It is a description, not a measurement, so it adds no result file. Tests:
`tests/test_process_mining.py` (both backends), `test_api.py`, `frontend/src/pages/intel.test.tsx`.

## 5. Tests and documents

- Python: `tests/test_screen.py` (TreeSHAP against the Shapley formula and a brute-force enumeration, local
  accuracy, the features, training and reading back), `test_counterfactual.py` (every finding of every control has a
  verified way to clear it), `test_investigator.py` (each fault found where it was made, on SQLite and PostgreSQL),
  `test_triage.py`, `test_audit_agent.py` (the planner, the tools, the ReAct loop with a scripted stand-in, the
  number check), and the new endpoints in `test_api.py`.
- Frontend: `src/pages/intel.test.tsx` (the four pages and the invoice's explanations) and the invoice tests of
  `pages.test.tsx`.
- Results: `../RESULTS.md` Section 14, `../REPORT.md` Section 21 (generated), `results/results.json` (four entries),
  `../ARCHITECTURE.md` R36, `PLAN.md` C38 to C42, `docs/API.md` (regenerated).
