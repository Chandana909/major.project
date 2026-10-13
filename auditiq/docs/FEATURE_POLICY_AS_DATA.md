# Feature: policy-driven controls

*From the organisation's policy document to audit decisions, with no threshold in code.*

This is the feature of AuditIQ that is implemented, tested and measured end to
end. This document has everything needed to write it up: what it is, how it
works logically and technically, the libraries, the data in and out of every
step, the experiment, the measured results, and what may and may not be
claimed. Every number below was produced by `python -m evaluation.policy_change`
(`results/policy_change.md`, `.json`, `_table.tex`, `.pdf`) or by the commands
shown next to it.

In the paper this is extra features **E1 (controls-first stage)** and **E4
(clause-level policy parameters)** taken together, and the experiment replaces
the planned "policy-swap experiment".

---

## 1. In one paragraph

A procurement audit applies thresholds: how far an invoice may differ from its
purchase order, how many invoices a vendor may send in a day, how much each
role may approve. In the prototype these thresholds were written into agent
prompts and tool code, so a change of policy meant editing the system, and
nothing guaranteed that the edit matched the document. In AuditIQ the policy
*document* is the input. The system reads the PDF, takes each threshold out of
the wording of the rule that states it, builds a clause registry, and twelve
deterministic controls execute that registry. Given 14 different policy
documents, the system read 196 of 196 threshold values correctly and decided
all 40,000 invoices of five ledgers as each policy requires (0 wrong decisions
in 560,000 invoice audits), while the same controls with thresholds fixed at
the original policy decided between 0% and 30.7% of the invoices against the
policy in force.

## 2. The problem in the base project

Verified in the Flowise export (`AuditIQ-DeloitteHacksplosion-main/`):

| Where the base keeps a threshold | Example |
|---|---|
| Agent prompt | The Math & Approvals agent is told to flag "any transaction above 100,000 that is not marked 'Approved'". |
| Policy text | SOP v2.4 states "tolerance of up to 1%" and "more than 3 invoices on a single day" in prose only; an agent has to read the number out of the prose and apply it itself. |
| Tool code | Six JavaScript tools exist (three-way match, duplicate, GST, approval limit, vendor policy, ledger pattern) and an agent decides whether to call them. The ledger-pattern tool carries constants of its own (amounts from 1,000 to 25,000, a ratio of 0.3) that appear in no policy; the approval-limit tool compares against whatever limit the model passes to it. |
| Routing | An LLM ("Risk Router") reads the risk JSON and chooses between review and approval. |

Consequences: (1) a policy change requires editing prompts and code in several
places; (2) the text the model reads and the numbers the tools apply can
disagree without anyone noticing; (3) whether a rule check runs at all depends
on the model choosing to call a tool; (4) there is no way to show an auditor
that the system applies the policy that is in force.

## 3. What was built

| Part | Module | Library | Role |
|---|---|---|---|
| Clause registry | `policy/policy_v2.5.json`, `auditiq/policy.py` | Python `json` | The one place a threshold is stored: for each rule its number, title, severity, kind (control or judgement) and parameters. |
| Policy text from the registry | `auditiq/policy.py` (`render_policy_text`), `policy/SOP_template.md` | Python `re` | Fills the template with the registry's parameters, so the text and the parameters cannot differ. |
| Policy PDF | `auditiq/policy_pdf.py` | ReportLab 5.0 | Writes the policy as a PDF, as an organisation would issue it. Deterministic output. |
| Reading a PDF | `auditiq/policy_ingest.py` | PyMuPDF 1.27 (`fitz`) | Extracts lines with font size, position and page; finds headings, numbered rules and paragraphs. |
| Thresholds from the wording | `auditiq/policy_extract.py` | Python `re` | One pattern per parameter, matched against the text of its rule; builds the registry; refuses a document it cannot execute. |
| Adoption | `auditiq/policy_extract.py` (`adopt`), `auditiq/cli.py` | `sqlite3` / psycopg 3 | Stores the document's policy as a version, ingests the document for page citations, optionally activates it. |
| Controls | `auditiq/controls.py` | none (pure Python) | Twelve functions; each takes a transaction and the registry and returns findings with evidence. |
| Pipeline | `auditiq/graph.py`, `auditiq/service.py` | LangGraph 1.2 | Runs the controls as the first stage; configuration C1 is the controls alone. |
| Store | `auditiq/db.py` | SQLite / PostgreSQL 17 | `company_policies`, `policy_clauses`, `policy_parameters`, `policy_documents`, `policy_chunks`, and the audit tables. |
| Independent ground truth | `auditiq_bench/validate.py` | pandas 2.2 | Recomputes from the ledger tables which rules each invoice violates. Shares no code with the controls (a test enforces it). |
| Experiment | `evaluation/policy_change.py` | pandas, matplotlib 3.9 | Generates the policy variants, runs everything, writes the report, the LaTeX table and the figure. |
| Tests | `tests/test_policy_change.py`, `tests/test_controls.py`, `tests/test_policy_docs.py` | pytest 9 | Run on SQLite and PostgreSQL. |

Python 3.11. No language model is used anywhere in this feature.

## 4. How it works, logically

Notation for the paper. A policy version is $P_v = (K, s, \kappa, \theta)$:
a set of clause identifiers $K$, a severity $s(k)$ for each, a kind
$\kappa(k) \in \{\text{control}, \text{judgement}\}$, and parameters
$\theta_k$. A transaction $x$ is an invoice with its purchase order, goods
receipt, vendor record, approval log and the vendor's other invoices. A control
is a function $c_k(x;\theta_k)$ that returns a finding or nothing; it contains
no constant of its own.

1. **Document in.** The organisation supplies its policy as a PDF $D$.
2. **Structure.** The PDF is cut into numbered rules and other paragraphs,
   each with its section heading and page.
3. **Extraction.** For every parameter the system knows, one pattern is
   matched against the text of the rule that states it:
   $\hat\theta = E(D)$. The severity of each rule is read from the rule
   itself ("Rule 5.1.1 (CRITICAL), ...").
4. **Check.** The document is refused, with reasons, if a rule the system
   executes is absent, if a threshold is not found in the wording, if the
   document has a rule the system has no check for, or if a value is not
   meaningful (for example a day that is not a weekday name).
5. **Registry.** $\hat P = (K, \hat s, \kappa, \hat\theta)$ is stored as a
   new policy version, with the policy text in the document's own words. The
   document itself is stored passage by passage so that findings can cite
   "document, page".
6. **Audit.** For every invoice the controls run:
   $F(x) = \{\,c_k(x;\hat\theta_k) : \kappa(k)=\text{control}\,\}$. Each finding
   cites its rule, its severity and the field values it rests on.
7. **Score and route.** $R_0(x) = \min(100, \sum_{f} w_{s(f)})$ with weights
   30, 20, 10, 5 and floors 70 (critical) and 50 (high); the invoice is
   escalated to a reviewer when $R_0 \ge 50$. The rule is code, not a model.

**Policy adherence** under a policy $P$ is the share of invoices for which
the set of cited rules equals the ground truth of $P$:
$A(P) = \frac{1}{N}\sum_x \mathbb{1}[\,\{k(f): f\in F(x)\} = Y_P(x)\,]$.

## 5. How it works, technically

### 5.1 The registry (data)

```json
"2.1.1": {"title": "Amount match", "severity": "high", "kind": "control",
          "params": {"amount_tolerance_pct": 1.0}},
"5.1.1": {"title": "Approval limit", "severity": "critical", "kind": "control",
          "params": {"approval_limits": {"Manager": 100000, "Senior Manager": 500000,
                                         "Director": 2500000, "CFO": 10000000}}}
```

Sixteen rules: twelve of kind `control`, four of kind `judgement`. Fourteen
parameter values in all (the limit of each of four roles counted once).

### 5.2 The parameters and where each is read from

| Rule | Parameter | Sentence of the rule it is read from | Control that uses it |
|---|---|---|---|
| 2.1.1 | `amount_tolerance_pct` | "A difference of up to **1%** of the PO amount is tolerated." | `amount_match` |
| 3.1.1 | `gstin_length` | "exactly **15** alphanumeric characters" | `gstin_format` |
| 3.1.2 | `state_code_min`, `state_code_max` | "a state code from **01** to **37**" | `gstin_state_code` |
| 4.1.1 | `max_invoices_per_vendor_per_day` | "at most **3** invoices dated on the same day" | `same_day_splitting` |
| 4.1.2 | `guide_window_days`, `guide_band_pct` | "as a guide, **7** days", "within **15%** of the limit" | read by the Vendor Intelligence agent |
| 4.2.1 | `non_business_days` | "dated on a **Saturday or Sunday** is an exception" | `non_business_day` |
| 4.3.1 | `round_amount_multiple` | "an exact multiple of INR **10,000**" | `round_amount` |
| 4.4.1 | `blocked_gstin_statuses` | "registration status is **Suspended**, is an exception" | `blocked_vendor` |
| 5.1.1 | `approval_limits` (4 values) | the table "Approver role / Approval limit (INR)" | `approval_limit` |

The other controls (`quantity_match`, `missing_reference`, `exact_duplicate`,
`gstin_vendor_match`) have no parameter.

### 5.3 Reading the PDF

`policy_ingest.read_lines` opens the PDF with PyMuPDF
(`page.get_text("dict")`) and returns every text line with its font size, its
left edge and its page. `chunk_lines` then works from layout, not from
keywords: the most common font size is the body size; a line at least one point
larger is a heading; a line that starts with `Rule <number> (<SEVERITY>),` opens
a rule, and indented lines continue it. The page footer is dropped.

Output, one passage per rule or paragraph:

```json
{"kind": "clause", "clause_id": "2.1.1", "section": "2.1 Three-Way Match", "page": 1,
 "text": "Rule 2.1.1 (HIGH), amount match. The invoice amount must equal the PO amount. A difference of up to 1% of the PO amount is tolerated. A larger difference, in either direction, is an exception."}
```

### 5.4 Extracting the thresholds

`policy_extract.PATTERNS` holds one regular expression per parameter, for
example `difference of up to (\d[\d,]*(?:\.\d+)?)\s*% of the PO amount`. The
approval limits are read from the table by a row pattern (role, amount).
Numbers are parsed with thousands separators removed; lists such as "Saturday
or Sunday" are split on commas and "or". Each value is converted to the type
the registry uses for that parameter.

`build(path, reference)` returns:

```json
{"file": "Company_Policy_v3.12.pdf", "version": "3.12", "pages": 3, "problems": [],
 "changes": [{"clause": "2.1.1", "parameter": "amount_tolerance_pct", "from": 1.0, "to": 0.5},
             {"clause": "4.1.1", "parameter": "max_invoices_per_vendor_per_day", "from": 3, "to": 2},
             {"clause": "4.3.1", "parameter": "round_amount_multiple", "from": 10000, "to": 5000},
             {"clause": "5.1.1", "parameter": "approval_limits", "from": {"Manager": 100000, "...": "..."},
              "to": {"Manager": 50000, "Senior Manager": 250000, "...": "..."}}]}
```

The *reference* is the registry of a version the system already executes. It
supplies what a document cannot: which rules the system has a control or an
agent for, and which parameters each needs. Rule numbers, severities and every
value come from the document.

A document is **refused** (nothing is stored) when:

| Condition | Message |
|---|---|
| A rule the system executes is missing | "Rule 4.3.1 (round amount) is not in the document" |
| A threshold is not in the wording | "Rule 2.1.1: the value of amount_tolerance_pct was not found in the wording of the rule" |
| The document has a rule the system cannot check | "Rule 4.3.2 is in the document, and the system has no control or agent for it" |
| A value is not meaningful | "Rule 4.2.1: 'Caturday' is not a day of the week" |
| No table of limits | "Rule 5.1.1: no table of approval limits by role was found" |
| No version | "the document states no version" |
| The version exists with other values | "version 4.2 is already stored with other parameters" (unless `--replace`) |

Each of these is a test in `tests/test_policy_change.py`.

### 5.5 A control (code)

Every control has the same shape: transaction and registry in, findings out.

```python
def amount_match(txn: dict, clauses: dict) -> list[dict]:
    clause = clauses.get("2.1.1")
    if clause is None or not txn.get("po"):
        return []
    inv, po = paise(txn["invoice"]["amount"]), paise(txn["po"]["amount"])
    if po <= 0:
        return []
    tolerance = clause["params"]["amount_tolerance_pct"]
    if abs(inv - po) * 100 <= tolerance * po:
        return []
    pct = (inv - po) / po * 100
    return [make_flag(clauses, "2.1.1", "amount_match",
                      [ev("invoice.amount", txn["invoice"]["amount"]), ev("po.amount", txn["po"]["amount"])],
                      f"Invoice amount ... differs from PO amount ... by {pct:.2f}% (tolerance ...%).")]
```

(From `auditiq/controls.py`, message shortened.) Amounts are compared in integer paise, so no rounding error can move a decision at the boundary.
The approval-limit control takes the limit of the approver's role from the
registry and ignores the `amount_limit` column of the approval log, because
that column records what the approval system believed at the time, not what
the policy in force says.

A finding:

```json
{"clause": "5.1.1", "severity": "critical", "source": "D", "control": "approval_limit", "confidence": 1.0,
 "message": "Invoice amount 694181.12 exceeds the Senior Manager approval limit of 500000; approved by ...",
 "evidence": [{"field": "invoice.amount", "value": 694181.12},
              {"field": "approval.approver_role", "value": "Senior Manager"}],
 "citation": {"document": "Procurement_Audit_SOP_v2.5.pdf", "page": 2}}
```

### 5.6 Data in, data out

| Step | In | Out |
|---|---|---|
| Read PDF | a PDF file | lines with font size, position, page |
| Structure | lines | passages: 16 rules and the other paragraphs, each with section and page |
| Extract | passages, reference registry | registry (16 rules, 14 values), list of changes, list of problems |
| Adopt | registry, PDF | rows in `company_policies` (text, registry JSON), `policy_clauses`, `policy_parameters`, `policy_documents`, `policy_chunks` |
| Audit | invoice id, active registry | row in `audit_results`, findings in `audit_flags`, steps in `audit_trail` |
| Review | result waiting for review | row in `review_decisions`; status of the result |

### 5.7 Commands

```bash
python -m auditiq policy adopt policy/variants/Company_Policy_v3.12.pdf --activate
```

```bash
python -m auditiq run --config C1
```

```bash
python -m evaluation.policy_change
```

## 6. The experiment

**Question.** When an organisation changes its policy and supplies only the new
document, does the system decide every invoice as the new policy requires, and
how wrong is a system that is not updated?

**Policies.** Fourteen variants of the reference policy (version 2.5): eleven
change one threshold, three change several (a strict policy, a lenient policy,
and version 2.6 of the original policy-swap design). Each is rendered to a
three-page PDF (`policy/variants/`).

**Ledgers.** `bench_seed_101`, `_202`, `_303`, `swap_seed_404` (5,000 invoices
each) and `large_seed_505` (20,000 invoices): 40,000 invoices with their
purchase orders, goods receipts, vendors and approval logs
([DATASETS.md](DATASETS.md)).

**Systems compared.**

- *Policy-driven*: the controls under the registry the system extracted from
  the variant's PDF.
- *Frozen*: the same controls with the thresholds of version 2.5. This is the
  behaviour of a system whose thresholds are written into prompts and code, as
  in the prototype, until someone edits it.

**Ground truth.** For each variant, which rules each invoice violates is
recomputed from the ledger tables by `auditiq_bench/validate.py`
(`rule_clauses`), the validator of the dataset generator. It is a second
implementation of the written rules and shares no code with the controls.

**Measures.** Parameters read correctly; rules read word for word; policy
adherence (section 4); for the frozen system, the findings the policy in force
does not support, the exceptions it does not raise, and the invoices it routes
wrongly (escalated needlessly, or approved although the policy requires
review).

### 6.1 Reading the documents

All 14 documents were read without a reported problem: **196 of 196** parameter
values and **224 of 224** rules (word for word). Reading a document took 0.02
to 0.04 seconds.

### 6.2 Adherence

Pooled over the five ledgers (N = 40,000 invoices per policy).

| Policy | Decisions the change moves | Policy-driven adherence | Frozen adherence | Frozen: unsupported findings | Frozen: exceptions not raised | Frozen: needless escalations | Frozen: missed escalations |
|---|---|---|---|---|---|---|---|
| Tolerance 0.5% | 62 (0.2%) | 1.000 | 0.998 | 0 | 62 | 0 | 62 |
| Tolerance 2% | 7 (0.0%) | 1.000 | 1.000 | 7 | 0 | 7 | 0 |
| Tolerance 5% | 63 (0.2%) | 1.000 | 0.998 | 63 | 0 | 63 | 0 |
| Daily count 2 | 429 (1.1%) | 1.000 | 0.989 | 0 | 429 | 0 | 428 |
| Daily count 5 | 170 (0.4%) | 1.000 | 0.996 | 170 | 0 | 170 | 0 |
| Manager limit 50,000 | 7,677 (19.2%) | 1.000 | 0.808 | 0 | 7,677 | 0 | 7,514 |
| Manager limit 150,000 | 69 (0.2%) | 1.000 | 0.998 | 69 | 0 | 69 | 0 |
| Senior Manager limit 250,000 | 4,259 (10.6%) | 1.000 | 0.894 | 0 | 4,259 | 0 | 4,161 |
| Round multiple 5,000 | 0 (0.0%) | 1.000 | 1.000 | 0 | 0 | 0 | 0 |
| Round multiple 50,000 | 43 (0.1%) | 1.000 | 0.999 | 43 | 0 | 0 | 0 |
| Six-day week | 35 (0.1%) | 1.000 | 0.999 | 35 | 0 | 0 | 0 |
| Strict policy | 12,274 (30.7%) | 1.000 | 0.693 | 0 | 12,427 | 0 | 12,012 |
| Lenient policy | 380 (0.9%) | 1.000 | 0.991 | 380 | 0 | 302 | 0 |
| Version 2.6 | 302 (0.8%) | 1.000 | 0.992 | 302 | 0 | 302 | 0 |

- Policy-driven controls: **0 wrong decisions in 560,000 invoice audits**.
- Under the reference version the controls agree with the independent
  recomputation on 40,000 of 40,000 invoices.
- The 560,000 audits took 13 seconds in one process on a laptop (Intel
  i5-1235U): about 44,000 invoices per second for the controls in memory.
- A tightening of policy is the dangerous direction for a frozen system: with
  the Manager limit lowered to 50,000 it would approve 7,514 invoices that the
  policy in force sends to review; under the strict policy, 12,012. A loosening
  costs reviewer time instead: 302 needless escalations under version 2.6.

Figure: `results/policy_change.pdf` (share of invoices a frozen system decides
against the policy in force, one bar per policy). LaTeX table:
`results/policy_change_table.tex`.

### 6.3 In the application

The same change through the deployed path, on the 20,000-invoice ledger in the
database (a copy of the SQLite store, `.auditiq/policy_demo.db`):

```bash
python -m auditiq policy adopt policy/variants/Company_Policy_v3.12.pdf --activate
python -m auditiq run --config C1
```

| | Version 2.5 | After adopting the strict policy (3.12) |
|---|---|---|
| Findings | 300 | 6,546 |
| Invoices waiting for review | 240 | 6,353 |
| Invoices approved automatically | 19,760 | 13,647 |
| Findings under Rule 5.1.1 (approval limit) | 30 | 6,060 |
| Findings under Rule 4.1.1 (same-day splitting) | 30 | 216 |
| Findings under Rule 2.1.1 (amount match) | 30 | 60 |

Adopting the document took 7 seconds and re-auditing 20,000 invoices with
storage of every result, finding and trail entry took one minute. No file of
the system was edited between the two runs.

## 7. What may be claimed, and what may not

**May be claimed**

- The system's thresholds come from the policy document: 196 of 196 values
  read correctly from 14 documents.
- Its decisions follow the policy in force on every invoice tested: adherence
  1.000 on 40,000 invoices under each of 14 policies, against an independent
  recomputation of the ground truth.
- A system with fixed thresholds decides up to 30.7% of invoices against the
  policy in force under the changes tested, and the errors of a tightening are
  missed escalations.
- A policy change takes effect in seconds and needs no change to code or
  prompts.

**Must be said with it**

- Full adherence is agreement between two implementations of the same written
  rules by the same authors. It shows that the document was read correctly and
  that no control keeps a threshold of its own. It is not evidence that the
  rules are the right rules, and it is not a detection result.
- The documents follow the wording of one template. A policy written in other
  words is refused with reasons, not interpreted. Reading free-form policies
  would need a language model with human confirmation in front of this step;
  that is future work, and its accuracy is not measured here.
- The system can execute only rules it has a control or an agent for. A new
  kind of rule needs a new control.
- The ledgers are synthetic. The counts describe how these ledgers react to
  these changes, not a real company's books.
- This covers the twelve rule-defined clauses. The four judgement clauses are
  handled by language-model agents, whose accuracy is not measured yet.

## 8. Reproducing everything

```bash
python policy/build_policy.py
python -m auditiq_bench
python -m evaluation.policy_change
python -m pytest tests/test_policy_change.py tests/test_controls.py tests/test_policy_docs.py
```

The experiment regenerates the 14 PDFs, re-reads them, re-audits the ledgers
and rewrites `results/policy_change.*`. `python -m evaluation.policy_change
--from-json` rebuilds the report, the table and the figure from the stored
results without auditing again.

## 9. For the paper

`../paper/policy_feature.tex` (in `pp1/paper/`) is a ready section with the
method, the experimental setup, the results table and figure, and the
limitations, written from this document. Suggested placement in
`auditiq_paper.tex`:

| Paper location | Change |
|---|---|
| Sec. IV-C, E1 and E4 | Replace with the method subsection of `policy_feature.tex`. |
| Sec. VI, "Policy-Swap Experiment" | Replace with the setup subsection (14 policies, 5 ledgers, frozen baseline). |
| Sec. VII | Add "Measured results" with the table and figure; H6 is then answered for the controls and remains open for the full pipeline. |
| Sec. V, Table III | Controls and policy store: status "implemented and measured"; technology Python, PyMuPDF, ReportLab, SQLite/PostgreSQL in place of SQL views and JavaScript. |
| Limitations | Add the four points of section 7 above. |
