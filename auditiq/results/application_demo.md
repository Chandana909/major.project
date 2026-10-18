# A policy change in the application

Produced by `python -m evaluation.application_demo` on 2026-10-18 23:38. Ledger `large_seed_505` (20,000 invoices) in a SQLite store; Intel64 Family 6 Model 154 Stepping 4, GenuineIntel, Python 3.11.3. Every invoice is audited with the controls (C1) under version 2.5, the strict policy document (`Company_Policy_v3.12.pdf`) is adopted as the active version, and every invoice is audited again. No file of the system is edited in between, and no language model is used.

| | Version 2.5 | After adopting the strict policy |
|---|---|---|
| Findings stored | 300 | 6,546 |
| Invoices waiting for review | 240 | 6,353 |
| Invoices approved automatically | 19,760 | 13,647 |
| Findings under rule 5.1.1 | 30 | 6,060 |
| Findings under rule 4.1.1 | 30 | 216 |
| Findings under rule 2.1.1 | 30 | 60 |
| Findings under rule 4.3.1 | 15 | 15 |
| Findings under rule 2.1.3 | 30 | 30 |
| Findings under rule 2.2.1 | 30 | 30 |

Adopting the document (reading it, storing version 3.12 and its passages) took 0.03 s. Auditing the ledger with storage of every result, finding and trail entry took 50 s before and 43 s after the change.

Changes the document makes to the active version: 2.1.1 amount_tolerance_pct: 1.0 to 0.5; 4.1.1 max_invoices_per_vendor_per_day: 3 to 2; 4.3.1 round_amount_multiple: 10000 to 5000; 5.1.1 approval_limits: {'Manager': 100000, 'Senior Manager': 500000, 'Director': 2500000, 'CFO': 10000000} to {'Manager': 50000, 'Senior Manager': 250000, 'Director': 2500000, 'CFO': 10000000}.
