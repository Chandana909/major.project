# The policy knowledge graph

The policy as a graph, built by code, and retrieval over it for Ask AI.
Module `auditiq/policy_graph.py`; endpoints `GET /api/policy/graph` and
`GET /api/policy/graph/ask`; the graph view on the Policy page; the evaluation
`evaluation/graph_eval.py` with its questions in `evaluation/graph_queries.json`;
tests in `tests/test_policy_graph.py`.

## 1. Why a graph, and why built by code

Passage retrieval finds the passage that best matches a question. Many of an
auditor's questions need several facts joined: an amount and the table of
approval limits to know who may approve it; two versions of a rule to say what
changed; a rule and the code or agent that checks it. Retrieval returns the
passages, when it finds them all, and leaves the joining to the reader.

Everything such a question joins is already stored exactly: the clause registry
of each version (title, severity, kind, parameters, the limit of each role), the
passages of the ingested documents with their pages, and the code that checks
each rule. The graph is built from these alone. No model extracts anything, so
the graph can be wrong only where the registry or the documents are, and the
registry's values are the ones the controls apply (196 of 196 values read
correctly from the policy documents, RESULTS.md 3.1).

A graph extracted by a language model from the documents (the usual GraphRAG)
was not chosen: the corpus is a few dozen passages per version, each extraction
would take minutes on the laptop's model, and a model can add relations the
policy does not state, which an audit tool cannot afford.

## 2. The graph

Built for one version (by default the active one), with what every other stored
version changes.

| Node | From | Count for v2.5 |
|---|---|---|
| version | `company_policies` (the one drawn and the others) | 2 |
| section | the clause ids and the documents' section headings | 8 |
| clause | `policy_clauses`: title, severity, kind, findings in the latest results | 16 |
| parameter | `policy_parameters` | 11 |
| role | the `approval_limits` parameter: each role and its limit | 4 |
| checker | the control function that names the rule (read from `controls.CONTROLS`), or the agent whose sections cover a judgement rule (`agents.AGENTS`) | 15 |
| page | the document page that states a rule | 2 |

| Edge | Between |
|---|---|
| has section, has rule | version to section, section to clause |
| sets | clause to parameter |
| limit | the approval limits to each role, labelled with the limit |
| checked by | clause to its control function or agent |
| stated on | clause (and the limits table) to its document page |
| changes | another version to each parameter or rule it changes, labelled with the old and new value |

## 3. Asking the graph

`PolicyGraph.query(question)` first recognises what the question names:

- rule numbers (5.1.1) and stored versions (2.6, v2.6), kept apart from each other;
- amounts of money: ₹30 lakh, Rs 7,50,000, 1.2 crore, 95,000 rupees, INR 60,000.
  A bare number counts as money only with four digits or more, and not when it
  looks like a year;
- roles (Senior Manager before Manager), agents (Math and Approvals, Tax and
  Identity, Vendor Intelligence), severities and kinds named with "rules", and
  words of change (changed, differ, between, new, old, increased);
- the rules a question is about, from the words of their titles (with a small
  stemmer; words common to many titles, such as "amount" or "vendor", do not
  count alone). When the question names nothing at all, the two best passages of
  the lexical ranker give the topic.

It then follows the edges and states facts, each citing the rule and version it
rests on and the passage that states it:

| Fact | Derived from |
|---|---|
| routing | an amount and the limits: the lowest role whose limit covers it ("an amount equal to the limit is within authority"), the roles that may not, or that it is above every limit; and whether a named role may approve it |
| band | an amount within the band rule 4.1.2 names as a guide to structuring (15 % under a limit in v2.5) |
| round | an amount that is an exact multiple of the round-amount parameter (4.3.1) |
| limit | a role named without an amount: its limit |
| change | what changed between two versions, per parameter and per role; or that a rule did not change |
| set | the rules of a severity or kind; the rules an agent judges |
| rule, parameter | for every rule in question: its severity, kind and checker, and its parameters |

The passages come with the facts that cite them, at most six.

**In Ask AI** (`copilot.answer` with the graph, as the API calls it): the facts
are given to the model as a FACTS block, labelled [F1], [F2], and their passages
come before the retrieved ones (`merge_passages`: the graph's passages, then the
ranker's, at least two beyond the graph's). The prompt tells the model the facts
are exact and to prefer them for limits, approvals and changes. Without a model,
the facts and passages are shown as they are.

**On the Policy page**: the graph in 3D (rules around their version, coloured by
severity; parameters, roles, checkers and pages outside), the version to draw,
"Ask the graph" with examples (the part of the graph that answers lights up and
the facts are listed with their citations), the relations of a node clicked, and
every relation as a table.

## 4. Evaluation

`python -m evaluation.graph_eval --db <store> --out results/graph_retrieval.md`,
on a store with policy v2.5 active, v2.6 stored and the three sample documents
ingested and embedded (`python -m auditiq setup`, `python -m auditiq policy embed`).

**Questions.** 32, written by the authors (`evaluation/graph_queries.json`), in
six types: routing an amount to a role, changes between versions, what checks a
rule, sets of rules, amounts that need several rules, and single-step questions.
The 9 *dev* questions were used while the recognition of questions was built; the
23 *test* questions were written afterwards, and the method was not changed after
they were run. Each question lists its **evidence** (the passages a complete answer
rests on: a rule's passage, or the section text with the limits table, in the
version named) and, except the single-step ones, the **answer** the graph must
derive.

**Methods.** Five passages for each ranker: lexical over the active version (the
application's ranker), lexical over every version's passages, dense and hybrid
(`nomic-embed-text`); the graph alone (its facts and the passages they cite); and
graph + lexical, what Ask AI is given.

**Results** (`results/graph_retrieval.md`):

| Method | Dev: evidence complete | Test: evidence complete | Test: derived answer stated | Test: passages | Test: characters |
|---|---|---|---|---|---|
| lexical | 4/9 | 11/23 | – | 5.0 | 1,580 |
| lexical, all versions | 3/9 | 13/23 | – | 5.0 | 1,480 |
| dense | 4/9 | 12/23 | – | 5.0 | 1,525 |
| hybrid | 3/9 | 12/23 | – | 5.0 | 1,701 |
| graph | 8/9 | 21/23 | 17/19 | 2.8 | 1,164 |
| graph + lexical | 8/9 | 22/23 | 17/19 | 5.3 | 2,092 |

By type on the test questions, the rankers miss most where a question joins
facts: no ranker gathered the evidence of a version change confined to the
active version (0 of 5; 3 of 5 over all versions) or of an amount that needs
several rules (0 of 2), while the graph did for 4 of 5 and 2 of 2. On single-step
questions the rankers were already complete (4 of 4 for lexical); graph + lexical
keeps 4 of 4, the graph alone 3 of 4.

**What the graph missed on the test questions**, reported as found:

- T7, "Was the amount tolerance of the three-way match relaxed in version 2.6?":
  "relaxed" is not among the words of change, and one version alone does not ask
  for a comparison, so no change was stated (evidence and answer missed).
- T6, "How many invoices a day may one vendor have under 2.6 compared with 2.5?":
  the right change was stated, but the question names no rule title the graph
  knows ("invoices a day" is not "same-day splitting"), so it listed all three
  changes; the answer check requires exactly the change asked about.
- T23 (graph alone), the suspended-GSTIN question: the topic resolved to the
  three GSTIN rules instead of the blocked-vendor rule; graph + lexical answers it.

And on the dev questions: for "What changed between version 2.5 and 2.6?" the
older version's limits table falls past the six passages (the facts state both
values).

**Limits of the evaluation.** 32 questions by the authors, about one policy;
the evidence and the answers are checked by code, not by a model answering from
the context, so they measure what the model is given, not what it answers. The
recognition of questions is made of rules: words it does not know, like
"relaxed", it misses.

## 5. Size and speed

The graph of v2.5 has 58 nodes and 75 edges and is built from the store on each
request in milliseconds; a question is answered without a model.
