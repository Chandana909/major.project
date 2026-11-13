# Routing of `bench_seed_202` (demo)

Source: `python -m evaluation.routing` on the store, latest results.

5,000 invoices audited; **281 (5.6%) sent to a person** (escalated or sampled); 60 approved automatically with a finding recorded.

| Route | Invoices |
|---|---|
| escalate | 277 |
| sample | 4 |
| approve | 4,719 |

| Risk level | Invoices |
|---|---|
| CRITICAL | 105 |
| HIGH | 172 |
| MEDIUM | 45 |
| LOW | 4,678 |

| Answer key | Escalated | Sampled | Approved |
|---|---|---|---|
| anomalous | 270 | 3 | 147 |
| clean | 0 | 0 | 4,460 |
| hard_negative | 7 | 1 | 112 |

Of the invoices sent to a person, 97.2% are anomalous in the answer key; 0 clean invoices were sent to a person.

| Result made under | Version in force on the invoice's date | Invoices |
|---|---|---|
| v2.5 | v2.5 | 5,000 |

Results not under the version in force on the invoice's date: 0.
