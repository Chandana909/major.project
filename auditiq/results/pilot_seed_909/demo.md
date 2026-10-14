# Pilot on `pilot_seed_909`

Model: qwen2.5:7b-ctx12k. Sample: the 6 invoices listed in `demo_ids.txt`.

**This is a pilot.** It shows that the pipeline runs end to end against this model and what an invoice costs. The sample is far too small to compare configurations: the intervals are wide and no difference between configurations can be claimed from it.

Dataset `pilot_seed_909`, policy v2.5, 6 invoices (4 anomalous); an unweighted sample: rates describe the sample only. Intervals: 95% bootstrap, 1000 resamples.

| Metric | C1-demo | C3-demo | C4-demo | C5-demo | C2-demo |
|---|---|---|---|---|---|
| Macro-F1, rule-defined classes | n/a | n/a | n/a | n/a | 0.000 [0.000, 0.000] |
| Macro-F1, judgement classes | 0.000 [0.000, 0.000] | 0.375 [0.000, 0.667] | 0.250 [0.000, 0.500] | 0.250 [0.000, 0.500] | 0.250 [0.000, 0.500] |
| Macro-recall, judgement classes | 0.000 [0.000, 0.000] | 0.500 [0.000, 1.000] | 0.250 [0.000, 0.500] | 0.250 [0.000, 0.500] | 0.250 [0.000, 0.500] |
| Invoice-level recall | 0.000 [0.000, 0.000] | 0.750 [0.250, 1.000] | 0.500 [0.000, 1.000] | 0.500 [0.000, 1.000] | 1.000 [1.000, 1.000] |
| Invoice-level precision | n/a | 0.750 [0.250, 1.000] | 0.667 [0.000, 1.000] | 0.667 [0.000, 1.000] | 0.667 [0.333, 1.000] |
| FPR, ordinary clean | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] |
| FPR, hard negatives | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| Precision at 2% prevalence | n/a | 0.030 [0.008, 1.000] | 0.020 [0.000, 1.000] | 0.020 [0.000, 1.000] | 0.020 [0.020, 0.020] |
| Citation correctness | n/a | 0.667 [0.000, 1.000] | 0.500 [0.000, 1.000] | 0.500 [0.000, 1.000] | 0.071 [0.000, 0.200] |
| Model findings naming a violated rule | n/a | 0.400 [0.000, 1.000] | 0.333 [0.000, 1.000] | 0.333 [0.000, 1.000] | 0.048 [0.000, 0.137] |
| Exact match of cited clauses | 0.333 [0.000, 0.667] | 0.500 [0.167, 0.833] | 0.333 [0.000, 0.667] | 0.333 [0.000, 0.667] | 0.000 [0.000, 0.000] |
| Escalation precision | n/a | 0.500 [0.000, 1.000] | 0.333 [0.000, 1.000] | 0.500 [0.000, 1.000] | 0.500 [0.167, 0.833] |
| Escalation recall | 0.000 [0.000, 0.000] | 0.667 [0.000, 1.000] | 0.333 [0.000, 1.000] | 0.333 [0.000, 1.000] | 1.000 [1.000, 1.000] |
| Invoices in sampled review | 0 | 0 | 0 | 1 | 0 |
| True anomalies in sampled review | 0 | 0 | 0 | 1 | 0 |
| High or critical anomalies auto-approved | 3 | 1 | 2 | 2 | 0 |
| LLM calls per invoice | 0.00 [0.00, 0.00] | 3.00 [3.00, 3.00] | 3.67 [3.33, 4.00] | 5.17 [3.83, 6.50] | 1.17 [1.00, 1.50] |
| Tokens per invoice | 0 | 9744 | 12422 | 18137 | 5978 |

| Comparison | Only first correct | Only second correct | p | Holm-adjusted p |
|---|---|---|---|---|
| C3-demo vs C2-demo | 3 | 0 | 0.25 | 0.75 |
| C4-demo vs C3-demo | 0 | 1 | 1 | 1 |
| C5-demo vs C4-demo | 0 | 0 | 1 | 1 |


| Run | Invoices | LLM calls | Cache hits | Prompt tokens | Completion tokens | Model time (s) | Failed stages | Repaired replies | Out-of-remit flags |
|---|---|---|---|---|---|---|---|---|---|
| C1-demo | 6 | 0 | 0 | 0 | 0 | 0.0 | 0 | 0 | 0 |
| C3-demo | 6 | 18 | 17 | 57767 | 694 | 5933.8 | 0 | 0 | 0 |
| C4-demo | 6 | 22 | 22 | 73597 | 932 | 6818.6 | 0 | 0 | 0 |
| C5-demo | 6 | 31 | 31 | 106948 | 1876 | 8157.4 | 0 | 0 | 0 |
| C2-demo | 6 | 7 | 0 | 33520 | 2351 | 2641.5 | 0 | 1 | 0 |

Model time is the waiting time of every call the configuration needs, summed; a call that came from the cache counts with the time it took when it was made. The three agents call the model at the same time, so on a server that answers one call at a time each call also waits for the others and the sum exceeds the time that passed.
