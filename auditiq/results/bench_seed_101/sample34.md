# Pilot on `bench_seed_101`

Model: qwen2.5:7b-ctx12k. Sample: the 34 invoices listed in `bench101_sample_ids.txt`.

**This is a pilot.** It shows that the pipeline runs end to end against this model and what an invoice costs. The sample is far too small to compare configurations: the intervals are wide and no difference between configurations can be claimed from it.

Dataset `bench_seed_101`, policy v2.5, 34 invoices (20 anomalous); an unweighted sample: rates describe the sample only. Intervals: 95% bootstrap, 1000 resamples.

| Metric | C1-sample34 | C3-sample34 | C4-sample34 | C5-sample34 | C2-sample34 |
|---|---|---|---|---|---|
| Macro-F1, rule-defined classes | n/a | n/a | n/a | n/a | 0.000 [0.000, 0.000] |
| Macro-F1, judgement classes | 0.000 [0.000, 0.000] | 0.468 [0.287, 0.596] | 0.447 [0.233, 0.602] | 0.447 [0.233, 0.602] | 0.222 [0.125, 0.250] |
| Macro-recall, judgement classes | 0.000 [0.000, 0.000] | 0.600 [0.418, 0.781] | 0.400 [0.207, 0.613] | 0.400 [0.207, 0.613] | 0.200 [0.083, 0.250] |
| Recall, J1 near-duplicate | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] | 0.200 [0.000, 0.667] | 0.200 [0.000, 0.667] | 0.000 [0.000, 0.000] |
| Recall, J2 structuring across days | 0.000 [0.000, 0.000] | 0.400 [0.000, 1.000] | 0.400 [0.000, 1.000] | 0.400 [0.000, 1.000] | 0.000 [0.000, 0.000] |
| Recall, J3 description against the PO | 0.000 [0.000, 0.000] | 0.200 [0.000, 0.667] | 0.200 [0.000, 0.667] | 0.200 [0.000, 0.667] | 0.000 [0.000, 0.000] |
| Recall, J4 goods-receipt remark | 0.000 [0.000, 0.000] | 0.800 [0.333, 1.000] | 0.800 [0.333, 1.000] | 0.800 [0.333, 1.000] | 0.800 [0.333, 1.000] |
| Invoice-level recall | 0.000 [0.000, 0.000] | 0.700 [0.476, 0.889] | 0.550 [0.333, 0.773] | 0.550 [0.333, 0.773] | 0.900 [0.750, 1.000] |
| Invoice-level precision | n/a | 0.560 [0.370, 0.760] | 0.647 [0.429, 0.875] | 0.647 [0.429, 0.875] | 0.621 [0.444, 0.800] |
| FPR, ordinary clean | 0.000 [0.000, 0.000] | 0.750 [0.000, 1.000] | 0.500 [0.000, 1.000] | 0.500 [0.000, 1.000] | 1.000 [1.000, 1.000] |
| FPR, hard negatives | 0.000 [0.000, 0.000] | 0.800 [0.500, 1.000] | 0.400 [0.111, 0.728] | 0.400 [0.111, 0.728] | 0.700 [0.357, 1.000] |
| Precision at 2% prevalence | n/a | 0.018 [0.012, 0.027] | 0.026 [0.013, 0.064] | 0.026 [0.013, 0.064] | 0.023 [0.017, 0.033] |
| Citation correctness | n/a | 0.632 [0.474, 0.800] | 0.727 [0.437, 1.000] | 0.727 [0.437, 1.000] | 0.049 [0.012, 0.084] |
| Model findings naming a violated rule | n/a | 0.375 [0.235, 0.538] | 0.471 [0.235, 0.714] | 0.471 [0.235, 0.714] | 0.031 [0.008, 0.057] |
| Exact match of cited clauses | 0.412 [0.235, 0.588] | 0.294 [0.147, 0.441] | 0.471 [0.294, 0.647] | 0.471 [0.294, 0.647] | 0.088 [0.000, 0.176] |
| Escalation precision | n/a | 0.480 [0.280, 0.692] | 0.625 [0.375, 0.867] | 0.583 [0.300, 0.875] | 0.448 [0.276, 0.633] |
| Escalation recall | 0.000 [0.000, 0.000] | 0.800 [0.571, 1.000] | 0.667 [0.400, 0.895] | 0.467 [0.214, 0.714] | 0.867 [0.687, 1.000] |
| Invoices in sampled review | 0 | 0 | 0 | 4 | 0 |
| True anomalies in sampled review | 0 | 0 | 0 | 3 | 0 |
| High or critical anomalies auto-approved | 15 | 3 | 5 | 5 | 2 |
| LLM calls per invoice | 0.00 [0.00, 0.00] | 3.00 [3.00, 3.00] | 3.74 [3.59, 3.88] | 5.24 [4.62, 5.88] | 1.21 [1.09, 1.35] |
| Tokens per invoice | 0 | 9678 | 12562 | 17828 | 6259 |

| Comparison | Only first correct | Only second correct | p | Holm-adjusted p |
|---|---|---|---|---|
| C3-sample34 vs C2-sample34 | 10 | 3 | 0.0923 | 0.277 |
| C4-sample34 vs C3-sample34 | 8 | 2 | 0.109 | 0.277 |
| C5-sample34 vs C4-sample34 | 0 | 0 | 1 | 1 |


| Run | Invoices | LLM calls | Cache hits | Prompt tokens | Completion tokens | Model time (s) | Failed stages | Repaired replies | Out-of-remit flags |
|---|---|---|---|---|---|---|---|---|---|
| C1-sample34 | 34 | 0 | 0 | 0 | 0 | 0.0 | 0 | 0 | 0 |
| C3-sample34 | 34 | 102 | 2 | 324539 | 4519 | 49293.0 | 0 | 0 | 0 |
| C4-sample34 | 34 | 127 | 102 | 421110 | 6002 | 53631.9 | 0 | 0 | 0 |
| C5-sample34 | 34 | 178 | 127 | 594219 | 11927 | 62582.1 | 0 | 0 | 0 |
| C2-sample34 | 34 | 41 | 0 | 195236 | 17586 | 11638.4 | 4 | 3 | 0 |

Model time is the waiting time of every call the configuration needs, summed; a call that came from the cache counts with the time it took when it was made. The three agents call the model at the same time, so on a server that answers one call at a time each call also waits for the others and the sum exceeds the time that passed.
