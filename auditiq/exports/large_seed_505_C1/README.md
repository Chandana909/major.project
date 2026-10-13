# Export of the AuditIQ database

Written by `python -m auditiq export` on 2026-10-13 09:13:51 from the postgres database. Ledger: `large_seed_505`. Active policy: version 2.5.

One CSV file per table, UTF-8 with a header row; an empty field is NULL. The embedding vectors of `policy_chunks` are left out. Every table and column is described in `docs/DATA_DICTIONARY.md`.

| File | Rows |
|---|---|
| `vendor_master.csv` | 1,000 |
| `purchase_orders.csv` | 19,920 |
| `goods_receipts.csv` | 19,910 |
| `invoices.csv` | 20,000 |
| `approval_logs.csv` | 22,665 |
| `company_policies.csv` | 2 |
| `policy_clauses.csv` | 32 |
| `policy_parameters.csv` | 22 |
| `policy_documents.csv` | 3 |
| `policy_chunks.csv` | 47 |
| `audit_runs.csv` | 1 |
| `audit_results.csv` | 20,000 |
| `audit_flags.csv` | 300 |
| `audit_trail.csv` | 60,000 |
| `review_decisions.csv` | 0 |
| `benchmark_labels.csv` | 20,000 |
| `meta.csv` | 1 |

| Run | Configuration | Policy | Model | Results |
|---|---|---|---|---|
| 2 | C1 | 2.5 | no model | 20,000 |
