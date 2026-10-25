# Sample of the evaluation subset on `bench_seed_202`

Model: qwen2.5:7b-ctx12k. Invoices: the 90 listed in `bench202_sample_ids.txt`, from the evaluation subset of 1,200 invoices.

**A sample of the evaluation subset, not the full run.** Compare configurations only with the McNemar tests below, and remember how few invoices each class has.

Dataset `bench_seed_202`, policy v2.5, 90 invoices (60 anomalous); an unweighted sample: rates describe the sample only. Intervals: 95% bootstrap, 1000 resamples.

| Metric | C1-igpu90 | C3-igpu90 | C4-igpu90 | C5-igpu90 | C2-igpu90 |
|---|---|---|---|---|---|
| Macro-F1, rule-defined classes | n/a | n/a | n/a | n/a | 0.000 [0.000, 0.000] |
| Macro-F1, judgement classes | 0.000 [0.000, 0.000] | 0.468 [0.400, 0.525] | 0.405 [0.321, 0.481] | 0.405 [0.321, 0.481] | 0.172 [0.115, 0.214] |
| Macro-recall, judgement classes | 0.000 [0.000, 0.000] | 0.567 [0.486, 0.646] | 0.400 [0.321, 0.481] | 0.400 [0.321, 0.481] | 0.167 [0.103, 0.227] |
| Recall, J1 near-duplicate | 0.000 [0.000, 0.000] | 0.867 [0.667, 1.000] | 0.467 [0.214, 0.727] | 0.467 [0.214, 0.727] | 0.000 [0.000, 0.000] |
| Recall, J2 structuring across days | 0.000 [0.000, 0.000] | 0.400 [0.166, 0.667] | 0.133 [0.000, 0.333] | 0.133 [0.000, 0.333] | 0.000 [0.000, 0.000] |
| Recall, J3 description against the PO | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| Recall, J4 goods-receipt remark | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.667 [0.412, 0.909] |
| Invoice-level recall | 0.000 [0.000, 0.000] | 0.683 [0.569, 0.793] | 0.533 [0.410, 0.661] | 0.533 [0.410, 0.661] | 0.917 [0.840, 0.983] |
| Invoice-level precision | n/a | 0.745 [0.629, 0.854] | 0.800 [0.667, 0.921] | 0.800 [0.667, 0.921] | 0.671 [0.557, 0.760] |
| FPR, ordinary clean | 0.000 [0.000, 0.000] | 0.100 [0.000, 0.333] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.900 [0.667, 1.000] |
| FPR, hard negatives | 0.000 [0.000, 0.000] | 0.650 [0.435, 0.857] | 0.400 [0.185, 0.625] | 0.400 [0.185, 0.625] | 0.900 [0.750, 1.000] |
| Precision at 2% prevalence | n/a | 0.029 [0.020, 0.047] | 0.039 [0.023, 0.097] | 0.039 [0.023, 0.097] | 0.020 [0.018, 0.024] |
| Citation correctness | n/a | 0.654 [0.559, 0.756] | 0.750 [0.593, 0.903] | 0.750 [0.593, 0.903] | 0.042 [0.020, 0.065] |
| Model findings naming a violated rule | n/a | 0.493 [0.389, 0.592] | 0.600 [0.454, 0.757] | 0.600 [0.454, 0.757] | 0.030 [0.014, 0.046] |
| Exact match of cited clauses | 0.333 [0.244, 0.433] | 0.433 [0.333, 0.533] | 0.511 [0.411, 0.611] | 0.511 [0.411, 0.611] | 0.033 [0.000, 0.078] |
| Escalation precision | n/a | 0.709 [0.580, 0.818] | 0.775 [0.639, 0.895] | 0.778 [0.633, 0.900] | 0.481 [0.372, 0.583] |
| Escalation recall | 0.000 [0.000, 0.000] | 0.867 [0.763, 0.956] | 0.689 [0.556, 0.818] | 0.622 [0.479, 0.765] | 0.867 [0.762, 0.957] |
| Invoices in sampled review | 0 | 0 | 0 | 4 | 0 |
| True anomalies in sampled review | 0 | 0 | 0 | 3 | 0 |
| High or critical anomalies auto-approved | 45 | 6 | 14 | 14 | 6 |
| LLM calls per invoice | 0.00 [0.00, 0.00] | 3.00 [3.00, 3.00] | 3.61 [3.51, 3.71] | 4.94 [4.58, 5.32] | 1.16 [1.09, 1.23] |
| Tokens per invoice | 0 | 9501 | 11718 | 16058 | 5768 |

| Comparison | Only first correct | Only second correct | p | Holm-adjusted p |
|---|---|---|---|---|
| C3-igpu90 vs C2-igpu90 | 37 | 1 | 2.84e-10 | 8.51e-10 |
| C4-igpu90 vs C3-igpu90 | 11 | 4 | 0.118 | 0.237 |
| C5-igpu90 vs C4-igpu90 | 0 | 0 | 1 | 1 |


| Run | Invoices | LLM calls | Cache hits | Prompt tokens | Completion tokens | Model time (s) | Failed stages | Repaired replies | Out-of-remit flags |
|---|---|---|---|---|---|---|---|---|---|
| C1-igpu90 | 90 | 0 | 0 | 0 | 0 | 0.0 | 0 | 0 | 0 |
| C3-igpu90 | 90 | 270 | 2 | 845652 | 9458 | 21276.2 | 0 | 0 | 0 |
| C4-igpu90 | 90 | 325 | 270 | 1042040 | 12624 | 23764.1 | 0 | 0 | 0 |
| C5-igpu90 | 90 | 445 | 325 | 1420850 | 24328 | 31344.3 | 0 | 0 | 0 |
| C2-igpu90 | 90 | 104 | 0 | 478707 | 40442 | 27975.8 | 5 | 9 | 0 |

Model time is the waiting time of every call the configuration needs, summed; a call that came from the cache counts with the time it took when it was made. The three agents call the model at the same time, so on a server that answers one call at a time each call also waits for the others and the sum exceeds the time that passed.
