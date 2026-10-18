# AuditIQ-Bench: results of the configurations that need no LLM

Produced by `python -m evaluation.run_all` on 2026-10-18 13:57. Policy v2.5. Benchmark ledgers: seeds 101, 202, 303, 5,000 invoices each, of which 420 are anomalous (8.4%) and 120 are hard negatives.
Intervals are 95% percentile bootstrap intervals over invoices, 1000 resamples.
C0 is the pair of classical detectors (isolation forest, one-class SVM) with cross-fitted thresholds;
C1 is the deterministic controls alone.

Configurations C2 to C5 use an LLM and are not in this file. Nothing here is evidence for or
against hypotheses H1 to H6 of the paper.

## 1. Construction checks (Section VII-A)

These outcomes follow from the design. A failure means a defect in the generator, the controls or
the scorer.

| Check | bench_seed_101 | bench_seed_202 | bench_seed_303 | large_seed_505 |
|---|---|---|---|---|
| C1 reports every invoice of R1-R10 under the labelled clause | pass | pass | pass | pass |
| C1 reports no invoice of J1-J4 | pass | pass | pass | pass |
| C1 raises no flag on ordinary clean invoices | pass | pass | pass | pass |
| C1 raises no flag on hard negatives | pass | pass | pass | pass |
| every clause cited by C1 on an anomalous invoice is the labelled clause | pass | pass | pass | pass |
| C1 routes no transaction to sampled review | pass | pass | pass | pass |

## 2. Invoice-level detection on the whole benchmark ledgers

An invoice counts as detected when the configuration reports it at all. The classical detectors
name no clause, so this is the only level at which they can be compared with C1. Every invoice is
decided with a threshold chosen on the other four folds.

Seed 101:

| Metric | C0-IF | C0-SVM | C1 |
|---|---|---|---|
| Recall | 0.598 [0.549, 0.646] | 0.460 [0.412, 0.507] | 0.714 [0.673, 0.755] |
| Precision | 0.470 [0.427, 0.509] | 0.542 [0.493, 0.594] | 1.000 [1.000, 1.000] |
| F1 | 0.526 [0.485, 0.564] | 0.497 [0.454, 0.540] | 0.833 [0.804, 0.860] |
| Share of invoices flagged | 0.107 [0.099, 0.116] | 0.071 [0.064, 0.078] | 0.060 [0.054, 0.067] |
| FPR, ordinary clean | 0.052 [0.046, 0.059] | 0.024 [0.020, 0.029] | 0.000 [0.000, 0.000] |
| FPR, hard negatives | 0.408 [0.324, 0.500] | 0.467 [0.383, 0.557] | 0.000 [0.000, 0.000] |

Seed 202:

| Metric | C0-IF | C0-SVM | C1 |
|---|---|---|---|
| Recall | 0.562 [0.514, 0.608] | 0.431 [0.379, 0.477] | 0.714 [0.669, 0.754] |
| Precision | 0.505 [0.462, 0.551] | 0.588 [0.526, 0.647] | 1.000 [1.000, 1.000] |
| F1 | 0.532 [0.494, 0.569] | 0.497 [0.446, 0.541] | 0.833 [0.802, 0.860] |
| Share of invoices flagged | 0.093 [0.085, 0.101] | 0.062 [0.055, 0.068] | 0.060 [0.053, 0.066] |
| FPR, ordinary clean | 0.040 [0.034, 0.046] | 0.017 [0.013, 0.021] | 0.000 [0.000, 0.000] |
| FPR, hard negatives | 0.442 [0.352, 0.529] | 0.417 [0.331, 0.504] | 0.000 [0.000, 0.000] |

Seed 303:

| Metric | C0-IF | C0-SVM | C1 |
|---|---|---|---|
| Recall | 0.571 [0.522, 0.624] | 0.502 [0.452, 0.549] | 0.714 [0.673, 0.759] |
| Precision | 0.529 [0.483, 0.577] | 0.499 [0.452, 0.546] | 1.000 [1.000, 1.000] |
| F1 | 0.549 [0.508, 0.591] | 0.501 [0.458, 0.542] | 0.833 [0.804, 0.863] |
| Share of invoices flagged | 0.091 [0.083, 0.099] | 0.085 [0.077, 0.092] | 0.060 [0.054, 0.067] |
| FPR, ordinary clean | 0.038 [0.033, 0.044] | 0.033 [0.027, 0.038] | 0.000 [0.000, 0.000] |
| FPR, hard negatives | 0.358 [0.276, 0.444] | 0.558 [0.472, 0.651] | 0.000 [0.000, 0.000] |

Mean over the seeds:

| Metric | C0-IF | C0-SVM | C1 |
|---|---|---|---|
| Recall | 0.577 | 0.464 | 0.714 |
| Precision | 0.501 | 0.543 | 1.000 |
| F1 | 0.536 | 0.498 | 0.833 |
| Share of invoices flagged | 0.097 | 0.072 | 0.060 |
| FPR, ordinary clean | 0.044 | 0.025 | 0.000 |
| FPR, hard negatives | 0.403 | 0.481 | 0.000 |

McNemar's exact test on per-invoice detection correctness, Holm-adjusted over the two comparisons
of each seed:

| Seed | Comparison | Only C1 correct | Only C0 correct | Holm-adjusted p |
|---|---|---|---|---|
| 101 | C1 vs C0-IF | 373 | 41 | 8.11e-68 |
| 101 | C1 vs C0-SVM | 301 | 31 | 1.04e-56 |
| 202 | C1 vs C0-IF | 333 | 38 | 1.09e-59 |
| 202 | C1 vs C0-SVM | 276 | 30 | 5.56e-51 |
| 303 | C1 vs C0-IF | 309 | 35 | 6.11e-56 |
| 303 | C1 vs C0-SVM | 337 | 36 | 4.16e-62 |

## 3. Share of each class that is reported (mean over the seeds)

C1 reports the rule-defined classes because its controls implement the definitions used to inject
them; that part is circular and is not a finding. The judgement classes are the ones the specialist
agents are meant to add.

| Class | Anomaly | C0-IF | C0-SVM | C1 |
|---|---|---|---|---|
| R1 | Invoice amount differs from PO amount beyond the tolerance | 0.367 | 1.000 | 1.000 |
| R2 | Billed quantity exceeds received quantity | 0.622 | 0.833 | 1.000 |
| R3 | Duplicate invoice number for the same vendor | 1.000 | 0.978 | 1.000 |
| R4 | Malformed GSTIN or invalid state code | 0.956 | 0.033 | 1.000 |
| R5 | Invoice GSTIN differs from the vendor master | 0.933 | 0.033 | 1.000 |
| R6 | Same-day invoice splitting above the daily count | 0.889 | 0.978 | 1.000 |
| R7 | Invoice amount exceeds the approver's limit | 0.400 | 0.844 | 1.000 |
| R8 | Missing PO or GRN reference | 0.767 | 0.033 | 1.000 |
| R9 | Vendor blacklisted or suspended | 0.200 | 0.100 | 1.000 |
| R10 | Weekend-dated or round-amount invoice | 0.678 | 0.589 | 1.000 |
| J1 | Near-duplicate invoice: re-keyed number, same vendor and amount | 1.000 | 1.000 | 0.000 |
| J2 | Cross-day structuring just below an approval limit | 0.222 | 0.067 | 0.000 |
| J3 | Invoice description inconsistent with the PO description | 0.022 | 0.011 | 0.000 |
| J4 | GRN remark contradicts the billed quantity | 0.022 | 0.000 | 0.000 |

## 4. Routing of the controls-only configuration

The escalation tier is judged against the invoices that carry a high or critical ground-truth
anomaly (330 per ledger: eight rule-defined classes, and J1, J2 and J4).

| Metric | seed 101 | seed 202 | seed 303 |
|---|---|---|---|
| Escalation precision | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| Escalation recall | 0.727 [0.680, 0.772] | 0.727 [0.682, 0.771] | 0.727 [0.682, 0.775] |
| Share escalated | 0.048 [0.042, 0.054] | 0.048 [0.042, 0.054] | 0.048 [0.043, 0.054] |
| Share auto-approved | 0.952 [0.946, 0.958] | 0.952 [0.946, 0.958] | 0.952 [0.946, 0.957] |
| High or critical anomalies auto-approved | 90 [73, 108] | 90 [73, 107] | 90 [72, 109] |
| Macro-F1, rule-defined classes | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| Macro-F1, judgement classes | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |

## 5. The weighted evaluation subset reproduces the whole ledger

The LLM configurations audit the evaluation subset of each ledger (1,200 of 5,000 invoices: every anomalous invoice, every hard negative, every original of a
duplicate, and a weighted sample of the other clean invoices). The table compares, for the configurations
that can be run on everything, the metric on the whole ledger with its weighted estimate from the subset
(mean over the seeds). Rates over complete strata agree exactly; rates over the sampled stratum agree
within sampling error.

| Metric | C0-IF, whole | C0-IF, subset | C0-SVM, whole | C0-SVM, subset | C1, whole | C1, subset |
|---|---|---|---|---|---|---|
| Recall | 0.577 | 0.577 | 0.464 | 0.464 | 0.714 | 0.714 |
| Precision | 0.501 | 0.515 | 0.543 | 0.551 | 1.000 | 1.000 |
| F1 | 0.536 | 0.542 | 0.498 | 0.501 | 0.833 | 0.833 |
| Share of invoices flagged | 0.097 | 0.095 | 0.072 | 0.072 | 0.060 | 0.060 |
| FPR, ordinary clean | 0.044 | 0.041 | 0.025 | 0.024 | 0.000 | 0.000 |
| FPR, hard negatives | 0.403 | 0.403 | 0.481 | 0.481 | 0.000 | 0.000 |

## 6. Policy swap, controls only

The policy-swap ledger (seed 404) has 5,000 invoices. 150 boundary invoices violate one clause under v2.5 and none under v2.6, which differs in the amount tolerance, the
daily invoice count and the Manager approval limit; the others are clean under both. The same controls
are run with each policy file. The paper's experiment (H6) is this comparison for the full pipeline C4.

| Configuration | Policy adherence | Boundary invoices flagged | Other invoices flagged |
|---|---|---|---|
| C1 under v2.5 | 1.000 [1.000, 1.000] | 150 | 0 |
| C1 under v2.6 | 1.000 [1.000, 1.000] | 0 | 0 |

## 7. A ledger at a realistic anomaly rate (20,000 invoices, seed 505)

The same 420 anomalous invoices as in a benchmark ledger, in a ledger of 20,000: 2.1% of the invoices are anomalous. Here precision is measured, not computed from the formula
of Section VI-C.

| Metric | C0-IF | C0-SVM | C1 |
|---|---|---|---|
| Recall | 0.162 [0.129, 0.200] | 0.402 [0.359, 0.448] | 0.714 [0.672, 0.757] |
| Precision | 0.301 [0.248, 0.362] | 0.460 [0.410, 0.510] | 1.000 [1.000, 1.000] |
| F1 | 0.211 [0.170, 0.253] | 0.429 [0.389, 0.470] | 0.833 [0.804, 0.862] |
| Share of invoices flagged | 0.011 [0.010, 0.013] | 0.018 [0.017, 0.020] | 0.015 [0.013, 0.017] |
| FPR, ordinary clean | 0.007 [0.006, 0.009] | 0.005 [0.004, 0.006] | 0.000 [0.000, 0.000] |
| FPR, hard negatives | 0.054 [0.026, 0.085] | 0.412 [0.353, 0.481] | 0.000 [0.000, 0.000] |

Share of each judgement class that is reported:

| Class | C0-IF | C0-SVM | C1 |
|---|---|---|---|
| J1 | 0.467 | 1.000 | 0.000 |
| J2 | 0.067 | 0.000 | 0.000 |
| J3 | 0.000 | 0.000 | 0.000 |
| J4 | 0.033 | 0.033 | 0.000 |
