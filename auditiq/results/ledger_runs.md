# Every ledger through the deployed system

Produced by `python -m evaluation.ledger_runs` on 2026-10-19 09:17; Intel64 Family 6 Model 154 Stepping 4, GenuineIntel, Python 3.11.3. Each ledger is written as an Excel workbook and loaded from it through the checked import, policy version 2.5 is active, and every invoice is audited with the controls (C1) through a SQLite store that keeps every result, finding and trail entry. The outcome below is read back from the store. No language model is used.

## 1. Outcome of the audit

| Ledger | Invoices | Findings | Invoices with a finding | Escalated to review | Approved automatically | Amount waiting for review (INR) | Load from workbook (s) | Audit (s) |
|---|---|---|---|---|---|---|---|---|
| bench_seed_101 | 5,000 | 300 | 300 | 240 | 4,760 | 66,974,538.72 | 16.4 | 24.6 |
| bench_seed_202 | 5,000 | 300 | 300 | 240 | 4,760 | 85,968,710.46 | 16.9 | 23.7 |
| bench_seed_303 | 5,000 | 300 | 300 | 240 | 4,760 | 73,574,489.00 | 12.8 | 20.2 |
| large_seed_505 | 20,000 | 300 | 300 | 240 | 19,760 | 68,552,886.00 | 52.4 | 82.5 |
| pilot_seed_909 | 5,000 | 300 | 300 | 240 | 4,760 | 62,387,249.14 | 12.6 | 20.9 |
| swap_seed_404 | 5,000 | 150 | 150 | 150 | 4,850 | 21,920,589.03 | 12.7 | 20.5 |

## 2. Findings by rule

| Rule | bench_seed_101 | bench_seed_202 | bench_seed_303 | large_seed_505 | pilot_seed_909 | swap_seed_404 |
|---|---|---|---|---|---|---|
| 2.1.1 | 30 | 30 | 30 | 30 | 30 | 50 |
| 2.1.2 | 30 | 30 | 30 | 30 | 30 | 0 |
| 2.1.3 | 30 | 30 | 30 | 30 | 30 | 0 |
| 2.2.1 | 30 | 30 | 30 | 30 | 30 | 0 |
| 3.1.1 | 15 | 15 | 15 | 15 | 15 | 0 |
| 3.1.2 | 15 | 15 | 15 | 15 | 15 | 0 |
| 3.1.3 | 30 | 30 | 30 | 30 | 30 | 0 |
| 4.1.1 | 30 | 30 | 30 | 30 | 30 | 50 |
| 4.2.1 | 15 | 15 | 15 | 15 | 15 | 0 |
| 4.3.1 | 15 | 15 | 15 | 15 | 15 | 0 |
| 4.4.1 | 30 | 30 | 30 | 30 | 30 | 0 |
| 5.1.1 | 30 | 30 | 30 | 30 | 30 | 50 |

## 3. Against the answer key

The answer key of each synthetic ledger (`labels.csv`) is never read by the audit. Each cell is *escalated / with a finding / invoices* of that kind.

| Ledger | rule-defined anomaly | judgement anomaly | hard negative | ordinary clean |
|---|---|---|---|---|
| bench_seed_101 | 240 / 300 / 300 | 0 / 0 / 120 | 0 / 0 / 120 | 0 / 0 / 4,460 |
| bench_seed_202 | 240 / 300 / 300 | 0 / 0 / 120 | 0 / 0 / 120 | 0 / 0 / 4,460 |
| bench_seed_303 | 240 / 300 / 300 | 0 / 0 / 120 | 0 / 0 / 120 | 0 / 0 / 4,460 |
| large_seed_505 | 240 / 300 / 300 | 0 / 0 / 120 | 0 / 0 / 240 | 0 / 0 / 19,340 |
| pilot_seed_909 | 240 / 300 / 300 | 0 / 0 / 120 | 0 / 0 / 120 | 0 / 0 / 4,460 |
| swap_seed_404 | 150 / 150 / 150 | - | - | 0 / 0 / 4,850 |

Reading the table: every rule-defined anomaly gets a finding; those whose findings are all of low or medium severity (a weekend date, a round amount, a GSTIN format) score below the escalation threshold of 50 and are approved with the finding recorded. Judgement anomalies get no finding from the controls: they are the task of the language-model agents. No hard negative and no ordinary invoice gets a finding.

## 4. The review queue

| Ledger | Waiting | By risk level | Vendors with the most invoices waiting |
|---|---|---|---|
| bench_seed_101 | 240 | CRITICAL 90, HIGH 150 | Koshy Inc (7); Goswami, Palla and Bhalla (5); Mani, Wadhwa and Koshy (5) |
| bench_seed_202 | 240 | CRITICAL 90, HIGH 150 | Bahl LLC (8); Hans-Varkey (8); Nayak, Chowdhury and Hora (7) |
| bench_seed_303 | 240 | CRITICAL 90, HIGH 150 | Roy-Doctor (5); Bora, Sankar and Agate (5); Sunder, Yogi and Chada (5) |
| large_seed_505 | 240 | CRITICAL 90, HIGH 150 | Talwar-Verma (5); Choudhry-Khare (5); Rattan, Ghosh and Atwal (5) |
| pilot_seed_909 | 240 | CRITICAL 90, HIGH 150 | Majumdar Inc (7); Balasubramanian, Oza and Mannan (6); Pandey PLC (6) |
| swap_seed_404 | 150 | CRITICAL 50, HIGH 100 | Devan-Sehgal (6); Comar Inc (5); Munshi PLC (5) |
