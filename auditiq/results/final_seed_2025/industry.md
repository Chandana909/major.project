# `final_seed_2025` from the auditors' side

Source: `python -m evaluation.industry` on a store audited with C1 (controls only). The answer key is the ledger's labels, which the audit never reads. Numbers are counts of the store's latest results.

## Workload and outcome

25,000 invoices (2,275 anomalous, 22,425 clean, 300 hard_negative).

| Measure | Value |
|---|---|
| Invoices sent to a person | 1,658 (6.6%) |
| Share of the spend sent to a person | 14.1% |
| Of those, anomalous (queue precision) | 1,658 (100.0%) |
| Clean invoices sent to a person | 0 |
| Hard negatives sent to a person | 0 |
| Anomalous invoices sent to a person (recall) | 72.9% |
| Anomalous spend | ₹878,634,698 of ₹5,399,865,632 |
| Anomalous spend sent to a person | ₹762,029,168 (86.7%) |

## Anomalous invoices by class

| Class | Labelled | Sent to a person | Approved, no finding | Approved with a finding |
|---|---|---|---|---|
| J1 | 141 | 0 | 141 | 0 |
| J2 | 141 | 0 | 141 | 0 |
| J3 | 141 | 58 | 83 | 0 |
| J4 | 141 | 66 | 75 | 0 |
| R1 | 141 | 141 | 0 | 0 |
| R2 | 141 | 141 | 0 | 0 |
| R3 | 141 | 141 | 0 | 0 |
| R4 | 141 | 45 | 0 | 96 |
| R5 | 157 | 157 | 0 | 0 |
| R6 | 141 | 141 | 0 | 0 |
| R7 | 426 | 426 | 0 | 0 |
| R8 | 141 | 141 | 0 | 0 |
| R9 | 141 | 141 | 0 | 0 |
| R10 | 141 | 60 | 0 | 81 |

Approved without a person: 440 with no finding (the judgement classes J1 to J4 need a model; C1 runs none) and 177 with a finding whose score routes it to approval (risk levels {'MEDIUM': 143, 'LOW': 34}).

## Ranking for a review budget

Precision in the top k is the expected value with ties broken at random. C0 scores are out-of-fold (each invoice scored by a threshold fitted without its label); the C1 score uses no label at all.

| Ranker | Distinct scores | Average precision | ROC AUC | P@100 | P@250 | P@500 | P@1000 | P@2000 |
|---|---|---|---|---|---|---|---|---|
| C1 risk score | 9 | 0.824 | 0.903 | 100.0% | 100.0% | 100.0% | 100.0% | 91.9% |
| C0-IF | 21,378 | 0.553 | 0.893 | 80.0% | 77.2% | 68.8% | 70.2% | 61.1% |
| C0-SVM | 24,693 | 0.606 | 0.882 | 91.0% | 93.2% | 84.0% | 74.8% | 65.2% |

## Hard negatives (near misses that break no rule)

| Type | Invoices | Sent to a person |
|---|---|---|
| HN_DAILY_LIMIT | 60 | 0 |
| HN_NEAR_LIMIT | 60 | 0 |
| HN_RECURRING | 60 | 0 |
| HN_SIMILAR_NUMBER | 60 | 0 |
| HN_TOLERANCE | 60 | 0 |

## Repeatability

Runs 3 and 4 (C1, every invoice): 0 of 25,000 invoices differ in route, score, risk level or findings.

## Benford's law, first digit

MAD 0.0048: close conformity (chi-square 80.5, 8 degrees of freedom).

## The sealed record

`auditiq/seal.py`, verified in 3.2 s: **intact**. Results: 50,000 sealed and intact, 0 altered, 50,000 stored before sealing. Trail entries: 300,000, 0 broken. Runs: 2 sealed, 0 altered, 2 finished before sealing. Digest of the sealed runs: `bc5ee88642bb022e3498d9caaacd71f836d20264feaf13774f643e780e1bf60f`.

Evidence re-performed in 1.6 s: of 25,000 latest results with an evidence fingerprint, 25,000 still match the ledger and 0 were based on records changed since; 0 were stored before evidence was fingerprinted.

## Data reliability of the ledger (ISA 500)

`auditiq/reliability.py`, 1.2 s: 18 of 19 checks without exceptions; reliable: the ledger's records are complete and consistent for the audit's purpose: the exceptions found are findings the audit's rules decide. Exceptions: po-on-file 47. Ledger fingerprint `db6d43da06847a0ca3446d6a69193ba91912e93afe75cab4b8c06798225417f5`.

## Fraud schemes against the answer key (`auditiq/audit_program.py`)

A labelled invoice counts for a scheme when a kept finding (or a lead) names a rule that addresses that scheme. Which rule addresses which scheme is the program's written judgement.

| Scheme | Labelled | Found by a rule | Listed by a lead only | Missed | Reached |
|---|---|---|---|---|---|
| shell-company | 914 | 914 | 0 | 0 | 100.0% |
| overbilling | 914 | 827 | 0 | 87 | 90.5% |
| duplicate-billing | 282 | 141 | 141 | 0 | 100.0% |
| not-received | 573 | 432 | 0 | 141 | 75.4% |
| personal-purchases | 141 | 0 | 0 | 141 | 0.0% |
| limit-evasion | 282 | 141 | 141 | 0 | 100.0% |
| override | 601 | 601 | 0 | 0 | 100.0% |
| conflict-of-interest | 141 | 141 | 0 | 0 | 100.0% |
| tax-misuse | 704 | 704 | 0 | 0 | 100.0% |

Untested: assertions none; schemes bid-rigging.

## Working papers (`auditiq/workpapers.py`)

Built in 7.1 s (334,930 bytes as a workbook): 2,442 findings, 1,658 invoices waiting for review, sample seed 160336519 (from the digest of the sealed runs). Built twice from the same store, the report digest repeats: `10e23ea26b08089e6d881c6c0f37dc80e9f137130a204c4ffa016aaedf30fa2f`.

## Leads under the judgement rules (2.2.2, 4.1.2)

`auditiq/leads.py`: invoices listed for a reviewer, with the policy's guide values; not findings. Held-out ledgers: `results/leads/leads.md`.

| Rule | Listed invoices | Amount | Approved without a person | Labelled | Recall | Precision | Listed otherwise |
|---|---|---|---|---|---|---|---|
| 2.2.2 | 141 | ₹21,402,194 | 141 | 141 | 100.0% | 100.0% | none |
| 4.1.2 | 141 | ₹36,179,518 | 141 | 141 | 100.0% | 100.0% | none |

## Monetary-unit sampling of the approved invoices (ISA 530)

`auditiq/sampling.py`: 23,342 invoices approved without a person, ₹4,637,836,464; 95 % confidence, tolerable misstatement 2 % (₹92,756,729), no expected misstatement: sample of 150, interval ₹30,918,910. The answer key stands in for the examination (an anomalous invoice misstated in full), over 1,000 random starts.

| Population | True misstatement | Upper limit covers it | Upper limit within tolerable (reliance) | Misstatements found per sample | Median upper limit |
|---|---|---|---|---|---|
| As approved | ₹116,605,530 | 97.4% | 2.6% | 3.69 (0 to 12) | ₹239,734,606 |
| Anomalous invoices removed | ₹0 | 100.0% | 100.0% | 0.00 | ₹90,295,983 |

The approved population holds more anomalous money than the tolerable misstatement, so an auditor should not rely on the approval, and the sample says so in the share of draws in the fourth column; with the anomalies removed it supports reliance.

## API answer times on this store

In-process (FastAPI test client, no network), gzip accepted; the store's analyses are cached until it changes, so the first request computes and the others read the cache.

| Endpoint | Status | First (ms) | Median (ms) | 95th percentile (ms) | Bytes on the wire |
|---|---|---|---|---|---|
| `/api/overview` | 200 | 170 | 7.2 | 8.1 | 1,382 |
| `/api/queue` | 200 | 59 | 9.1 | 10.2 | 6,184 |
| `/api/risk-map` | 200 | 126 | 16.7 | 27.4 | 30,939 |
| `/api/analytics` | 200 | 318 | 7.7 | 9.5 | 7,106 |
| `/api/rings` | 200 | 300 | 9.9 | 11.3 | 12,534 |
| `/api/case-graph` | 200 | 436 | 10.4 | 11.6 | 5,616 |
| `/api/invoices?q=INV41` | 200 | 14 | 7.7 | 8.9 | 1,491 |
| `/api/policy` | 200 | 121 | 7.4 | 8.6 | 860 |
| `/api/leads` | 200 | 338 | 10.9 | 13.5 | 12,511 |
| `/api/sampling?seed=1` | 200 | 182 | 214.3 | 235.2 | 4,063 |
| `/api/trail/verify` | 200 | 5,027 | 5,229.5 | 5,583.4 | 607 |
