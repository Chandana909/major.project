# Robustness of the policy reader

Produced by `python -m evaluation.policy_robustness` on 2026-10-18 14:06. The reference policy (version 2.5) is edited, written as a PDF and read by the system. Group A edits keep every rule and value and must be read correctly; group B edits make the document impossible to execute and must be refused; group C edits make it ambiguous, and refusal is the only safe outcome. No language model is used.

| Id | Group | Edit | Required | Outcome | Values read correctly | Reasons given by the system |
|---|---|---|---|---|---|---|
| A1 | A | extra prose and a revision table before the rules | read correctly | **read correctly** | 14 of 14 | – |
| A2 | A | rules and sections in another order | read correctly | **read correctly** | 14 of 14 | – |
| A3 | A | every rule followed by a long explanation | read correctly | **read correctly** | 14 of 14 | – |
| A4 | A | 45 notes before section 4, which push the later rules onto later pages | read correctly | **read correctly** | 14 of 14 | – |
| A5 | A | the approval table in another order | read correctly | **read correctly** | 14 of 14 | – |
| A6 | A | the severity of rule 2.1.1 changed from high to low | read correctly | **read correctly** | 14 of 14 | – |
| A7 | A | approval limits in Indian digit grouping | read correctly | **read correctly** | 14 of 14 | – |
| B1 | B | the threshold sentence of rule 2.1.1 removed | refused | **refused** | – | Rule 2.1.1: the value of amount_tolerance_pct was not found in the wording of the rule |
| B2 | B | rule 4.3.1 removed | refused | **refused** | – | Rule 4.3.1 (round amount) is not in the document; the system needs every rule it executes to be stated |
| B3 | B | a rule added that the system has no control for | refused | **refused** | – | Rule 4.4.2 is in the document, and the system has no control or agent for it |
| B4 | B | no version stated | refused | **refused** | – | the document states no version (expected 'Version: <number>' before the first section) |
| B5 | B | a non-business 'day' that is not a day of the week | refused | **refused** | – | Rule 4.2.1: 'public holiday' is not a day of the week |
| B6 | B | the approval table removed | refused | **refused** | – | Rule 5.1.1: no table of approval limits by role was found |
| B7 | B | the tolerance written in words | refused | **refused** | – | Rule 2.1.1: the value of amount_tolerance_pct was not found in the wording of the rule |
| C1 | C | rule 2.1.1 stated twice, with 1% and with 2% | refused | **refused** | – | Rule 2.1.1 is stated 2 times; a document must state each rule once |
| C2 | C | the approval table without the CFO | refused | **refused** | – | Rule 5.1.1: the table of approval limits has no limit for the role CFO |

16 of 16 documents were handled as required; 0 were adopted wrongly.
