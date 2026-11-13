# Routing of `huge_seed_606` (huge)

Source: `python -m evaluation.routing` on the store, latest results.

500,000 invoices audited; **5,712 (1.1%) sent to a person** (escalated or sampled); 1,428 approved automatically with a finding recorded.

| Route | Invoices |
|---|---|
| escalate | 5,712 |
| sample | 0 |
| approve | 494,288 |

| Risk level | Invoices |
|---|---|
| CRITICAL | 2,142 |
| HIGH | 3,570 |
| MEDIUM | 1,071 |
| LOW | 493,217 |

| Answer key | Escalated | Sampled | Approved |
|---|---|---|---|
| anomalous | 5,712 | 0 | 4,284 |
| clean | 0 | 0 | 489,284 |
| hard_negative | 0 | 0 | 720 |

Of the invoices sent to a person, 100.0% are anomalous in the answer key; 0 clean invoices were sent to a person.

| Result made under | Version in force on the invoice's date | Invoices |
|---|---|---|
| v2.5 | v2.5 | 500,000 |

Results not under the version in force on the invoice's date: 0.
