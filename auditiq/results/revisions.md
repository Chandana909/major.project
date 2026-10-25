# Revisions of the control findings

Produced by `python -m evaluation.revisions` on 2026-10-25 23:32. Policy v2.5. For every finding of the controls, `auditiq/corrections.py` computes the revision; an invoice amended or re-approved as the revision says is audited again with all twelve controls.

| Ledger | Findings | Revisions that change the invoice | Resolved, no new finding |
|---|---|---|---|
| `bench_seed_101` | 300 | 150 | 150 |
| `bench_seed_202` | 300 | 150 | 150 |
| `bench_seed_303` | 300 | 150 | 150 |
| `large_seed_505` | 300 | 150 | 150 |
| all | 1,200 | 600 | 600 |

By rule, all ledgers together:

| Rule | Findings | Kind of revision | Checked | Resolved | New finding | With an action |
|---|---|---|---|---|---|---|
| 2.1.1 | 120 | amend 120 | 120 | 120 | 0 | 120 |
| 2.1.2 | 120 | amend 120 | 120 | 120 | 0 | 120 |
| 2.1.3 | 120 | obtain 120 | 0 | 0 | 0 | 120 |
| 2.2.1 | 120 | reject 120 | 0 | 0 | 0 | 120 |
| 3.1.1 | 60 | amend 60 | 60 | 60 | 0 | 60 |
| 3.1.2 | 60 | amend 60 | 60 | 60 | 0 | 60 |
| 3.1.3 | 120 | amend 120 | 120 | 120 | 0 | 120 |
| 4.1.1 | 120 | consolidate 120 | 0 | 0 | 0 | 120 |
| 4.2.1 | 60 | verify 60 | 0 | 0 | 0 | 60 |
| 4.3.1 | 60 | verify 60 | 0 | 0 | 0 | 60 |
| 4.4.1 | 120 | hold 120 | 0 | 0 | 0 | 120 |
| 5.1.1 | 120 | reapprove 120 | 120 | 120 | 0 | 120 |

Kinds: amend (the invoice is corrected), reapprove (approved again by the role named), consolidate (the day's invoices are one purchase), reject (a duplicate), hold (blocked vendor), obtain (a missing document), verify (supporting evidence). Only amend and reapprove change the invoice, so only they are audited again; a consolidation names the approver the total needs but leaves the invoices as they are, so rule 4.1.1 still counts them.
