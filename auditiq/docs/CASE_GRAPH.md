# The audit knowledge graph

The policy graph ([POLICY_GRAPH.md](POLICY_GRAPH.md)) holds what the rules say. The audit graph holds **what the audit found**: which vendor billed which invoice, which rule the invoice breaks and why, who approved it, which vendors share an identity, and which rings the vendors and approvers form. Ask AI uses both, so a question about the ledger ("which vendors are in a collusion ring and who approves their invoices?") is answered from the ledger and not from the policy text alone.

Code: `auditiq/case_graph.py`. Endpoints: `GET /api/case-graph`, `GET /api/case-graph/ask`. Web: **Knowledge graph**, tab *Audit findings graph*. Evaluation: `python -m evaluation.case_graph_eval`.

## What it is

Built by code from the store, on request, and kept until the store changes (the same fingerprint as the analytics and the rings). No model reads or writes it, so it can be wrong only where the audit is. Nothing is stored beside the audit: the graph is a view of the results, the findings with their messages, the approval log, the vendor master and the ring detector, so it cannot drift from them.

| Node | Holds |
|---|---|
| vendor | name, category, blacklisted, invoices, invoices with findings, money with findings |
| invoice | only invoices with at least one finding: amount, date, score, level, route |
| rule | a clause of the policy in force, with the invoices that break it |
| approver | role, limit, approvals, approvals with findings, approvals above the limit |
| ring | a connected group of vendors and approvers (`rings.py`) |

| Edge | Meaning |
|---|---|
| vendor billed invoice | |
| invoice violates rule | with the message of the finding |
| invoice approved by approver | the latest approving entry of the log |
| vendor shares PAN / GSTIN with vendor | one legal entity registered twice |
| vendor, approver member of ring | |

Invoices without a finding are not nodes: they are in the totals of their vendor and approver, so the graph stays small (on this ledger, 1,835 invoice nodes of 25,000).

## Retrieval

`CaseGraph.query(question)` recognises what a question names and follows the edges:

- invoice numbers, vendor ids and names, approver names, ring numbers, rule numbers;
- kinds of fraud in everyday words (mismatch, duplicate, GSTIN, split, weekend, round amount, blacklisted, above the limit, collusion, shell vendors, "registered twice").

It returns **facts**: statements computed from the graph with the numbers they rest on, each with the nodes to light up. Ask AI gives them to the model labelled `[C1]`, `[C2]`, ... beside the policy facts (`[F#]`) and the passages (`[#]`), and the model must cite them; the prompt forbids stating any name, count or amount about the ledger that no ledger fact gives. Without a model, the facts are the answer.

Two choices follow from what the ring detector does. It joins an approver to **every vendor of the approver's flagged invoices** (the hotspot link), which widens a ring; and it **tests** each approver-vendor pair against the approver's role at a false discovery rate of 1%. A ring fact therefore names, for each approver, the vendors with a tested link, and counts the rest. An identity question (same PAN, registered twice) gets the identity pairs and not the approver rings.

## Measured

`python -m evaluation.case_graph_eval --db <store>` on `final_seed_2025` (25,000 invoices; the store a run of `start.bat` made, audited by the controls, configuration C1). 78 questions in eight types; every expected answer is computed from the ledger's files (labels, vendor master, approval log, the planted rings in `manifest.json`), never from the audit. A retrieval is judged on what it hands the reader. Policy-only retrieval is the policy graph and the ranker over the policy documents.

| Type | Questions | Audit graph right | Policy-only right |
|---|---|---|---|
| why was INV... flagged (the rules equal the labelled rules) | 20 | 20 | 0 |
| how many invoices of vendor X have findings | 14 | 14 | 0 |
| how many approvals above own limit did approver X make | 14 | 14 | 0 |
| how many invoices break rule R (6 in everyday words) | 18 | 18 | 0 |
| which approvers are in collusion rings (planted: 6) | 2 | 2 | 0 |
| which vendors are in the ring around approver X | 6 | 6 | 0 |
| which vendors share the same PAN (planted: 8) | 2 | 2 | 0 |
| which blacklisted vendors billed the most | 2 | 2 | 0 |

For the four set questions the share of the planted names the facts give (recall) is 1.00, and the share of the names given that were planted (precision) is 1.00 for rings, ring members and shared PAN, and 0.56 for the blocked vendors (nine names where the five largest were asked for: the rule fact adds the vendors with the most blocked invoices).

**How to read this.**

- It measures that retrieval returns, faithfully and completely, what the audit stored. It is not a measure of detection: whether the audit finds the frauds is in `results/<ledger>/verification.md` (12 of 12 rule-decided clauses at precision and recall 1.00 on this ledger, the rings recovered 10 of 10).
- Policy-only retrieval scores 0 by construction: policy documents contain no vendor, invoice or count. The table shows the gap the audit graph closes, not a contest between equals.
- The recognisers were built looking at six questions. The invoice, vendor, approver and rule questions name other entities, drawn at random (`--seed`), in wordings written before the run; they were right on the first run (66 of 66) and nothing was tuned on them.
- **The ten ring-type questions are not held out.** The first run was 78 of 78 right but gave poor precision on two of them: for "which vendors are in the ring around X" the facts named 54 vendors on average where 4.2 were planted (precision 0.16), and for "same PAN" 107 where 8 (0.07), because identity questions also returned every ring and a ring listed all its hotspot vendors (`results/case_graph/first_run/`). The retrieval was then changed (identity apart from collusion; the tested links as the core of a ring; each approver's vendors attributed to the approver) and the same questions rerun. There are only six planted rings, so there were no others to draw. A second defect was found on the way: a pattern in the source held a stray control character (`\b` written through a shell heredoc became a backspace), so the ring path had not been running in the intermediate runs; it is fixed and the final run is on the corrected code.
- Ring facts are a lead for investigation, not a finding, as everywhere in the application.

## Ask AI with a model

With the local model (`qwen2.5:7b-ctx12k`, CPU) the written answer cites the ledger facts, and it is the facts that are exact. Two questions were put through the application:

- *Which vendors share the same PAN?* The answer named all four planted pairs with the right vendor ids, and said that the facts do not tell whether the vendors bill the company.
- *Which vendors are in collusion rings and who approves their invoices?* The answer named the ring of each approver with its vendors and marked the two shared-identity rings as having no approver. It still joins the vendors of the four approvers of one merged ring under all four names, and it leaves two of the seven rings out. The facts, listed under the answer on the Ask page, attribute every vendor to its approver.

Two defects were found by looking at the prompt and not at the model. The system prompt told the model to refuse unless the passages or the audit record held the answer, and did not name the ledger facts, so the first answers were "the documents do not answer"; and the ledger facts were not in the prompt at all, because the edit that added them had failed without an error. Both are fixed, and `tests/test_policy_docs.py` checks that the facts are in what the model receives. A rewording of the ring fact (one sentence per approver) improved the answer. A larger model would read a long fact better; the facts do not depend on it.

## Use

```bash
python -m evaluation.case_graph_eval --db "%LOCALAPPDATA%\auditiq\live\<the run's store>.db"
```

In the web application: **Knowledge graph**, tab *Audit findings graph*. Ask a question, or open a vendor, invoice, approver, ring or rule by id or name (`INV53478`, `Frado Deep`, `g:3`, `5.1.1`); click a node for its relations.
