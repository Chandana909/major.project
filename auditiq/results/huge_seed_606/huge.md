# The huge ledger (`huge_seed_606`)

Produced by `python -m evaluation.huge`. 500,000 invoices from 15,000 vendors at the anomaly rate of the large ledger; generated from its seed into a work folder (not committed) and checked against the file hashes in `results/huge_seed_606/manifest.json`. No language model is used.

## Data

500,000 invoices (9,996 anomalous, 2.0%; 720 hard negatives), 15,000 vendors, 2,078,077 records in the five tables. Files: 7, hashes recorded. The duration of this first generation was not measured: the laptop slept during it.

## Detection on every invoice

Bootstrap intervals over invoices, 200 resamples. Thresholds of the classical detectors by five-fold cross-fitting, as on the benchmark ledgers.

| Measure | Controls (C1) | Isolation forest | One-class SVM |
|---|---|---|---|
| Recall | 0.714 [0.706, 0.722] | 0.192 [0.185, 0.200] | 0.376 [0.368, 0.386] |
| Precision | 1.000 [1.000, 1.000] | 0.191 [0.184, 0.199] | 0.504 [0.495, 0.515] |
| F1 | 0.833 [0.828, 0.838] | 0.192 [0.185, 0.199] | 0.431 [0.423, 0.439] |
| False-positive rate, hard negatives | 0.000 [0.000, 0.000] | 0.108 [0.083, 0.133] | 0.521 [0.488, 0.554] |
| False-positive rate, ordinary invoices | 0.000 [0.000, 0.000] | 0.016 [0.016, 0.017] | 0.007 [0.007, 0.007] |

| Comparison | Only the controls correct | Only the detector correct | Holm-adjusted p |
|---|---|---|---|
| C1 vs C0-IF | 13,730 | 413 | 0 |
| C1 vs C0-SVM | 7,913 | 831 | 0 |

The step took 1,054 s.

## Policy change

The fourteen policy documents of the policy-change experiment, read from their PDFs, applied to 500,000 invoices each (7,000,000 audits; the controls took 247 s). Under version 2.5 the controls agree with the ground truth on 500,000 of 500,000 invoices.

| Policy | Decisions moved | Adherence, policy-driven | Adherence, frozen | Missed exceptions | Missed escalations | Unsupported findings | Needless escalations |
|---|---|---|---|---|---|---|---|
| Tolerance 0.5% | 78 (0.0%) | 1.0000 | 0.9998 | 78 | 78 | 0 | 0 |
| Tolerance 2% | 0 (0.0%) | 1.0000 | 1.0000 | 0 | 0 | 0 | 0 |
| Tolerance 5% | 78 (0.0%) | 1.0000 | 0.9998 | 0 | 0 | 78 | 78 |
| Daily count 2 | 9,720 (1.9%) | 1.0000 | 0.9806 | 9,720 | 9,629 | 0 | 0 |
| Daily count 5 | 714 (0.1%) | 1.0000 | 0.9986 | 0 | 0 | 714 | 714 |
| Manager limit 50,000 | 96,382 (19.3%) | 1.0000 | 0.8072 | 96,382 | 95,503 | 0 | 0 |
| Manager limit 150,000 | 116 (0.0%) | 1.0000 | 0.9998 | 0 | 0 | 116 | 116 |
| Senior Manager limit 250,000 | 52,418 (10.5%) | 1.0000 | 0.8952 | 52,418 | 51,899 | 0 | 0 |
| Round multiple 5,000 | 3 (0.0%) | 1.0000 | 1.0000 | 3 | 0 | 0 | 0 |
| Round multiple 50,000 | 294 (0.1%) | 1.0000 | 0.9994 | 0 | 0 | 294 | 0 |
| Six-day week | 170 (0.0%) | 1.0000 | 0.9997 | 0 | 0 | 170 | 0 |
| Strict policy | 155,826 (31.2%) | 1.0000 | 0.6883 | 158,601 | 154,356 | 0 | 0 |
| Lenient policy | 1,372 (0.3%) | 1.0000 | 0.9973 | 0 | 0 | 1,372 | 908 |
| Version 2.6 | 908 (0.2%) | 1.0000 | 0.9982 | 0 | 0 | 908 | 908 |

## The deployed path

The ledger loaded into a new SQLite store in 36 s; every invoice audited with the controls, with every result, finding and trail entry stored, in 708 s; the strict policy document adopted in 0.02 s; every invoice audited again in 755 s.

| | Before (v2.5) | After (strict policy) |
|---|---|---|
| Invoices audited | 500,000 | 500,000 |
| Findings | 7,140 | 165,741 |
| Waiting for review | 5,712 | 160,068 |
| Approved automatically | 494,288 | 339,932 |

## The application on the whole ledger

The web application's requests on the store of the deployed path (SQLite: 500,000 invoices from 15,000 vendors, 1,000,000 results of which 500,000 are the latest, 160,068 invoices waiting for review), through the API in one process; median of 3 requests.

| Page | Request | Seconds | Answer (KB) |
|---|---|---|---|
| Health (every page) | `/api/health` | 0.01 | 0 |
| Overview | `/api/overview` | 4.64 | 3 |
| Risk map (overview, 3D) | `/api/risk-map` | 5.51 | 2,639 |
| Review queue | `/api/queue?limit=200` | 1.89 | 55 |
| Invoice search | `/api/invoices?q=INV5&limit=50` | 1.05 | 10 |
| Invoice page | `/api/invoices/INV316514` | 0.01 | 14 |
| Policy page | `/api/policy` | 0.50 | 3 |
| Policy search | `/api/search?q=weekend%20invoice` | 0.11 | 2 |

## The control stage over the whole ledger

500,000 invoices in 9.2 s in one process: 18.4 µs per invoice (54,371 invoices per second), 7,140 findings; median of 3 run(s).
In the same process, timed in turn with it, the 20,000-invoice ledger `large_seed_505` took 14.6 µs per invoice (300 findings): the cost per invoice of the larger ledger is 1.26 times that of the smaller.

Two controls (2.2.1, exact duplicate; 4.1.1, invoices of the vendor on one day) read the vendor's other invoices, so an invoice costs more the longer its vendor's history. Each invoice timed alone (the timer adds a little to every figure):

| Earlier invoices of the vendor | Invoices (huge_seed_606) | Median µs | Invoices (large_seed_505) | Median µs |
|---|---|---|---|---|
| 0 to 24 | 104,977 | 11.4 | 9,780 | 10.7 |
| 25 to 49 | 201,472 | 11.5 | 7,578 | 10.7 |
| 50 to 74 | 107,694 | 11.6 | 1,998 | 10.6 |
| 75 to 99 | 45,876 | 11.7 | 485 | 10.8 |
| 100 to 124 | 22,190 | 11.9 | 0 |  |
| 125 to 149 | 10,285 | 11.9 | 0 |  |
| 150 or more | 7,506 | 12.1 | 159 | 10.8 |

A straight line through the times of single invoices: 13.9 µs plus 0.006 µs per earlier invoice on this ledger (mean history 49.4); 13.0 µs plus 0.02 µs on `large_seed_505` (mean history 29.4).

Machine: Intel64 Family 6 Model 154 Stepping 4, GenuineIntel, Python 3.11.3.
