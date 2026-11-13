# Routing of `huge_seed_606` (huge_v3.12_retroactive)

Source: `python -m evaluation.routing` on the store, run 2.

500,000 invoices audited; **160,068 (32.0%) sent to a person** (escalated or sampled); 1,025 approved automatically with a finding recorded.

| Route | Invoices |
|---|---|
| escalate | 160,068 |
| sample | 0 |
| approve | 339,932 |

| Risk level | Invoices |
|---|---|
| CRITICAL | 150,570 |
| HIGH | 9,498 |
| MEDIUM | 0 |
| LOW | 339,932 |

| Answer key | Escalated | Sampled | Approved |
|---|---|---|---|
| anomalous | 7,499 | 0 | 2,497 |
| clean | 152,117 | 0 | 337,167 |
| hard_negative | 452 | 0 | 268 |

Of the invoices sent to a person, 4.7% are anomalous in the answer key; 152,117 clean invoices were sent to a person.

| Result made under | Version in force on the invoice's date | Invoices |
|---|---|---|
| v3.12 | v2.5 | 500,000 |

Results not under the version in force on the invoice's date: 500,000.
