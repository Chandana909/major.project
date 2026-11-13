# Audit graph retrieval on `final_seed_2025`

78 questions in eight types; expected answers computed from the ledger's files (seed 2026). Audit graph right on 78 of 78, policy-only retrieval on 0.

| Type | Questions | Audit graph right | Policy-only right | Audit graph recall | Audit graph precision | Names given (planted) | Policy-only recall |
|---|---|---|---|---|---|---|---|
| invoice | 20 | 20 | 0 | | | | |
| vendor | 14 | 14 | 0 | | | | |
| approver | 14 | 14 | 0 | | | | |
| rule | 18 | 18 | 0 | | | | |
| rings | 2 | 2 | 0 | 1.00 | 1.00 | 6.0 (6.0) | 0.00 |
| members | 6 | 6 | 0 | 1.00 | 0.16 | 54.2 (4.2) | 0.00 |
| identity | 2 | 2 | 0 | 1.00 | 0.07 | 107.0 (8.0) | 0.00 |
| blocked | 2 | 2 | 0 | 1.00 | 0.56 | 9.0 (5.0) | 0.00 |

## Questions the audit graph got wrong (0)

None.
