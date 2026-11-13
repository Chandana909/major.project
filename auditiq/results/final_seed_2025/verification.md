# Verification of `final_seed_2025` against its ground truth

25,000 invoices audited; 1,835 with a finding.

## Score spread

8 different risk scores occur among the invoices with a finding; the most common (70.0) takes 46.4% of them. The check requires at least 8 different scores and no value above 60%: **passed**.

| Score | 0 | 1–10 | 11–20 | 21–30 | 31–40 | 41–50 | 51–60 | 61–70 | 71–80 | 81–90 | 91–100 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Invoices | 23,165 | 177 | 0 | 0 | 0 | 780 | 10 | 852 | 13 | 3 | 0 |

Risk levels: low 23,199, critical 868, high 790, medium 143. Routes: approve 23,342, escalate 1,658.

## Rules decided by the controls

| Clause | Labelled | Flagged | True positive | False positive | Missed | Precision | Recall |
|---|---|---|---|---|---|---|---|
| 2.1.1 | 141 | 141 | 141 | 0 | 0 | 100.0% | 100.0% |
| 2.1.2 | 291 | 291 | 291 | 0 | 0 | 100.0% | 100.0% |
| 2.1.3 | 141 | 141 | 141 | 0 | 0 | 100.0% | 100.0% |
| 2.2.1 | 141 | 141 | 141 | 0 | 0 | 100.0% | 100.0% |
| 3.1.1 | 71 | 71 | 71 | 0 | 0 | 100.0% | 100.0% |
| 3.1.2 | 70 | 70 | 70 | 0 | 0 | 100.0% | 100.0% |
| 3.1.3 | 563 | 563 | 563 | 0 | 0 | 100.0% | 100.0% |
| 4.1.1 | 141 | 141 | 141 | 0 | 0 | 100.0% | 100.0% |
| 4.2.1 | 70 | 70 | 70 | 0 | 0 | 100.0% | 100.0% |
| 4.3.1 | 71 | 71 | 71 | 0 | 0 | 100.0% | 100.0% |
| 4.4.1 | 141 | 141 | 141 | 0 | 0 | 100.0% | 100.0% |
| 5.1.1 | 601 | 601 | 601 | 0 | 0 | 100.0% | 100.0% |

Invoices with a rule violation (labelled or found): 1,835; their findings equal the labelled rules exactly on 100.0%. Hard negatives flagged: 0 of 300. Ordinary clean invoices flagged: 0 of 22,425 (0.0%).

## Judgement classes (need a model, C2 to C5)

| Clause | Labelled | Flagged by the controls |
|---|---|---|
| 2.1.4 | 141 | 0 |
| 2.1.5 | 141 | 0 |
| 2.2.2 | 141 | 0 |
| 4.1.2 | 141 | 0 |

## By number of labelled violations on the invoice

| Violations | Invoices | Flagged | Mean score | Lowest | Highest | Distinct scores |
|---|---|---|---|---|---|---|
| 1 | 1,717 | 1,277 | 39.9 | 0 | 70 | 5 |
| 2 | 395 | 395 | 57.0 | 50 | 70 | 2 |
| 3 | 153 | 153 | 67.0 | 50 | 80 | 4 |
| 4 | 10 | 10 | 78.5 | 70 | 90 | 3 |

## Planted rings

10 of 10 planted rings were recovered by the detector; it reports 7 rings in all, 0 of them without a planted vendor.

| Ring | Kind | Vendors | Approver | Vendors found | Approver found | Recovered |
|---|---|---|---|---|---|---|
| RING-01 | identity | 2 |  | 100.0% |  | yes |
| RING-02 | identity | 2 |  | 100.0% |  | yes |
| RING-03 | identity | 2 |  | 100.0% |  | yes |
| RING-04 | identity | 2 |  | 100.0% |  | yes |
| RING-05 | approver | 4 | Qasim Pandey | 100.0% | yes | yes |
| RING-06 | approver | 5 | Frado Deep | 100.0% | yes | yes |
| RING-07 | approver | 5 | Ubika Gour | 100.0% | yes | yes |
| RING-08 | approver | 4 | Orinder Merchant | 100.0% | yes | yes |
| RING-09 | approver | 4 | Lakshit Pau | 100.0% | yes | yes |
| RING-10 | approver | 3 | Meera Kapoor | 100.0% | yes | yes |
