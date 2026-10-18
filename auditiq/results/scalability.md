# Scalability of the control stage

Produced by `python -m evaluation.scalability` on 2026-10-13 23:28. Machine: Intel64 Family 6 Model 154 Stepping 4, GenuineIntel, Python 3.11.3, 12 logical CPUs. Each figure is the median of 3 runs. All worker processes run on this one machine.

## 1. Worker processes

300,000 invoice audits: the 20,000 invoices of `large_seed_505` under 15 policy versions. Every row produced 16,840 findings.

| Worker processes | Seconds | Invoices per second | Speed-up |
|---|---|---|---|
| 1 | 5.29 | 56,660 | 1.00 |
| 2 | 3.10 | 96,724 | 1.71 |
| 4 | 2.50 | 119,780 | 2.12 |
| 8 | 1.74 | 172,226 | 3.04 |

## 2. Ledger size, one process, reference policy

| Invoices | Seconds | Invoices per second | Microseconds per invoice |
|---|---|---|---|
| 5,000 | 0.089 | 56,117 | 17.8 |
| 20,000 | 0.389 | 51,433 | 19.4 |
| 40,000 | 0.731 | 54,722 | 18.3 |

The time measured is the control stage in memory. Loading a ledger and storing results in the database are not included; with storage of every result, finding and trail entry, one process audits 20,000 invoices in SQLite in under a minute (see `application_demo.md`).
