# Reading policies in their own wording

Produced by `python -m evaluation.policy_llm_eval` on 2026-10-14 09:42. Model: `qwen2.5:7b-ctx12k`, temperature 0, one call per document. Six documents in two styles (a memorandum in prose; a handbook with lettered clauses, number words and Indian digit grouping), each stating three policies. None uses the wording or the rule numbers of the SOP template.

The model proposes passages and values; code checks that each quote is in the document and that each value is written in a quote of its rule; a person then confirms. The table compares the proposals with the policy each document was written from.

| Document | Values | Right and verified | Right, held back | Wrong, caught | Wrong, passed | Missing | Rules located | At the right passage | Seconds |
|---|---|---|---|---|---|---|---|---|---|
| `memo_reference_v5.1.pdf` | 14 | 9 | 4 | 1 | 0 | 0 | 16 of 16 | 16 of 16 | 393.4 |
| `memo_strict_v5.2.pdf` | 14 | 9 | 4 | 1 | 0 | 0 | 16 of 16 | 16 of 16 | 301.0 |
| `memo_lenient_v5.3.pdf` | 14 | 10 | 4 | 0 | 0 | 0 | 15 of 16 | 15 of 16 | 297.3 |
| `handbook_reference_v5.4.pdf` | 14 | 9 | 4 | 0 | 1 | 0 | 15 of 16 | 15 of 16 | 288.9 |
| `handbook_strict_v5.5.pdf` | 14 | 9 | 4 | 0 | 1 | 0 | 15 of 16 | 15 of 16 | 281.6 |
| `handbook_lenient_v5.6.pdf` | 14 | 10 | 4 | 0 | 0 | 0 | 15 of 16 | 15 of 16 | 309.7 |
| **All** | 84 | 56 | 24 | 2 | 2 | 0 | 92 of 96 | 92 of 96 | |

Documents for which a reviewer who accepts the verified values, supplies the others and gives the passage of any rule that was not located ends with exactly the intended policy: 4 of 6.

"Wrong, passed" is the dangerous cell: a value that is not the document's, which the code check nevertheless accepted. Only the confirming person stands between it and the controls.

## Values that were not right and verified

| Document | Rule | Parameter | Proposed | Intended | Outcome | Reason given by the check |
|---|---|---|---|---|---|---|
| `memo_reference_v5.1.pdf` | 4.4.1 | blocked_gstin_statuses | ["Blacklisted", "Suspended"] | ["Suspended"] | wrong caught | the value is not written in the quoted text |
| `memo_reference_v5.1.pdf` | 5.1.1 | approval_limits: Manager | 100000 | 100000 | right held back | the value is not written in the quoted text |
| `memo_reference_v5.1.pdf` | 5.1.1 | approval_limits: Senior Manager | 500000 | 500000 | right held back | the value is not written in the quoted text |
| `memo_reference_v5.1.pdf` | 5.1.1 | approval_limits: Director | 2500000 | 2500000 | right held back | the value is not written in the quoted text |
| `memo_reference_v5.1.pdf` | 5.1.1 | approval_limits: CFO | 10000000 | 10000000 | right held back | the value is not written in the quoted text |
| `memo_strict_v5.2.pdf` | 4.4.1 | blocked_gstin_statuses | ["Blacklisted", "Suspended"] | ["Suspended"] | wrong caught | the value is not written in the quoted text |
| `memo_strict_v5.2.pdf` | 5.1.1 | approval_limits: Manager | 50000 | 50000 | right held back | the value is not written in the quoted text |
| `memo_strict_v5.2.pdf` | 5.1.1 | approval_limits: Senior Manager | 250000 | 250000 | right held back | the value is not written in the quoted text |
| `memo_strict_v5.2.pdf` | 5.1.1 | approval_limits: Director | 2500000 | 2500000 | right held back | the value is not written in the quoted text |
| `memo_strict_v5.2.pdf` | 5.1.1 | approval_limits: CFO | 10000000 | 10000000 | right held back | the value is not written in the quoted text |
| `memo_lenient_v5.3.pdf` | 5.1.1 | approval_limits: Manager | 150000 | 150000 | right held back | no quote of the rule was found in the document |
| `memo_lenient_v5.3.pdf` | 5.1.1 | approval_limits: Senior Manager | 500000 | 500000 | right held back | no quote of the rule was found in the document |
| `memo_lenient_v5.3.pdf` | 5.1.1 | approval_limits: Director | 2500000 | 2500000 | right held back | no quote of the rule was found in the document |
| `memo_lenient_v5.3.pdf` | 5.1.1 | approval_limits: CFO | 10000000 | 10000000 | right held back | no quote of the rule was found in the document |
| `handbook_reference_v5.4.pdf` | 4.4.1 | blocked_gstin_statuses | ["Blacklisted", "Suspended"] | ["Suspended"] | wrong passed |  |
| `handbook_reference_v5.4.pdf` | 5.1.1 | approval_limits: Manager | 100000 | 100000 | right held back | no quote of the rule was found in the document |
| `handbook_reference_v5.4.pdf` | 5.1.1 | approval_limits: Senior Manager | 500000 | 500000 | right held back | no quote of the rule was found in the document |
| `handbook_reference_v5.4.pdf` | 5.1.1 | approval_limits: Director | 2500000 | 2500000 | right held back | no quote of the rule was found in the document |
| `handbook_reference_v5.4.pdf` | 5.1.1 | approval_limits: CFO | 10000000 | 10000000 | right held back | no quote of the rule was found in the document |
| `handbook_strict_v5.5.pdf` | 4.4.1 | blocked_gstin_statuses | ["Blacklisted", "Suspended"] | ["Suspended"] | wrong passed |  |
| `handbook_strict_v5.5.pdf` | 5.1.1 | approval_limits: Manager | 50000 | 50000 | right held back | no quote of the rule was found in the document |
| `handbook_strict_v5.5.pdf` | 5.1.1 | approval_limits: Senior Manager | 250000 | 250000 | right held back | no quote of the rule was found in the document |
| `handbook_strict_v5.5.pdf` | 5.1.1 | approval_limits: Director | 2500000 | 2500000 | right held back | no quote of the rule was found in the document |
| `handbook_strict_v5.5.pdf` | 5.1.1 | approval_limits: CFO | 10000000 | 10000000 | right held back | no quote of the rule was found in the document |
| `handbook_lenient_v5.6.pdf` | 5.1.1 | approval_limits: Manager | 150000 | 150000 | right held back | no quote of the rule was found in the document |
| `handbook_lenient_v5.6.pdf` | 5.1.1 | approval_limits: Senior Manager | 500000 | 500000 | right held back | no quote of the rule was found in the document |
| `handbook_lenient_v5.6.pdf` | 5.1.1 | approval_limits: Director | 2500000 | 2500000 | right held back | no quote of the rule was found in the document |
| `handbook_lenient_v5.6.pdf` | 5.1.1 | approval_limits: CFO | 10000000 | 10000000 | right held back | no quote of the rule was found in the document |

The six documents were written by the authors of the system and are short. This measures one model on them; it is not an estimate for policies in general.
