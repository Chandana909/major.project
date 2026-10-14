# Pilot on `pilot_seed_909`

Model: qwen2.5:7b-ctx12k. Sample: the 20 invoices listed in `pilot_ids.txt`.

**This is a pilot.** It shows that the pipeline runs end to end against this model and what an invoice costs. The sample is far too small to compare configurations: the intervals are wide and no difference between configurations can be claimed from it.

Dataset `pilot_seed_909`, policy v2.5, 20 invoices (14 anomalous); an unweighted sample: rates describe the sample only. Intervals: 95% bootstrap, 1000 resamples.

| Metric | C1-pilot20 | C3-pilot20 | C4-pilot20 | C5-pilot20 | C2-pilot20 |
|---|---|---|---|---|---|
| Macro-F1, rule-defined classes | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.095 [0.017, 0.172] |
| Macro-F1, judgement classes | 0.000 [0.000, 0.000] | 0.170 [0.000, 0.383] | 0.167 [0.000, 0.333] | 0.167 [0.000, 0.333] | 0.167 [0.000, 0.500] |
| Macro-recall, judgement classes | 0.000 [0.000, 0.000] | 0.500 [0.000, 1.000] | 0.250 [0.000, 0.500] | 0.250 [0.000, 0.500] | 0.250 [0.000, 0.500] |
| Invoice-level recall | 0.714 [0.467, 0.933] | 0.929 [0.750, 1.000] | 0.857 [0.643, 1.000] | 0.857 [0.643, 1.000] | 0.929 [0.765, 1.000] |
| Invoice-level precision | 1.000 [1.000, 1.000] | 0.812 [0.600, 1.000] | 0.800 [0.571, 1.000] | 0.800 [0.571, 1.000] | 0.722 [0.500, 0.895] |
| FPR, ordinary clean | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 1.000 [1.000, 1.000] |
| FPR, hard negatives | 0.000 [0.000, 0.000] | 0.600 [0.000, 1.000] | 0.600 [0.000, 1.000] | 0.600 [0.000, 1.000] | 0.800 [0.392, 1.000] |
| Precision at 2% prevalence | 1.000 [1.000, 1.000] | 0.037 [0.020, 1.000] | 0.034 [0.017, 1.000] | 0.034 [0.017, 1.000] | 0.022 [0.016, 0.039] |
| Citation correctness | 1.000 [1.000, 1.000] | 0.500 [0.370, 0.700] | 0.688 [0.529, 0.883] | 0.688 [0.529, 0.883] | 0.091 [0.033, 0.176] |
| Model findings naming a violated rule | n/a | 0.111 [0.000, 0.308] | 0.111 [0.000, 0.334] | 0.111 [0.000, 0.334] | 0.067 [0.022, 0.123] |
| Exact match of cited clauses | 0.800 [0.600, 0.950] | 0.450 [0.200, 0.650] | 0.500 [0.299, 0.700] | 0.500 [0.299, 0.700] | 0.100 [0.000, 0.250] |
| Escalation precision | 1.000 [1.000, 1.000] | 0.667 [0.411, 0.895] | 0.643 [0.364, 0.883] | 0.750 [0.461, 1.000] | 0.556 [0.316, 0.765] |
| Escalation recall | 0.727 [0.444, 1.000] | 0.909 [0.700, 1.000] | 0.818 [0.571, 1.000] | 0.818 [0.571, 1.000] | 0.909 [0.700, 1.000] |
| Invoices in sampled review | 0 | 0 | 0 | 2 | 0 |
| True anomalies in sampled review | 0 | 0 | 0 | 2 | 0 |
| High or critical anomalies auto-approved | 3 | 1 | 2 | 2 | 1 |
| LLM calls per invoice | 0.00 [0.00, 0.00] | 3.00 [3.00, 3.00] | 3.60 [3.40, 3.80] | 4.95 [4.15, 5.85] | 1.15 [1.00, 1.35] |
| Tokens per invoice | 0 | 9557 | 12005 | 16779 | 5835 |

| Comparison | Only first correct | Only second correct | p | Holm-adjusted p |
|---|---|---|---|---|
| C3-pilot20 vs C2-pilot20 | 9 | 2 | 0.0654 | 0.196 |
| C4-pilot20 vs C3-pilot20 | 2 | 1 | 1 | 1 |
| C5-pilot20 vs C4-pilot20 | 0 | 0 | 1 | 1 |


| Run | Invoices | LLM calls | Cache hits | Prompt tokens | Completion tokens | Model time (s) | Failed stages | Repaired replies | Out-of-remit flags |
|---|---|---|---|---|---|---|---|---|---|
| C1-pilot20 | 20 | 0 | 0 | 0 | 0 | 0.0 | 0 | 0 | 0 |
| C3-pilot20 | 20 | 60 | 18 | 188804 | 2343 | 20079.0 | 0 | 0 | 0 |
| C4-pilot20 | 20 | 72 | 64 | 236970 | 3136 | 23273.2 | 0 | 0 | 0 |
| C5-pilot20 | 20 | 99 | 81 | 330078 | 5510 | 28183.2 | 0 | 0 | 0 |
| C2-pilot20 | 20 | 23 | 7 | 107478 | 9216 | 9776.2 | 2 | 1 | 0 |

Model time is the waiting time of every call the configuration needs, summed; a call that came from the cache counts with the time it took when it was made. The three agents call the model at the same time, so on a server that answers one call at a time each call also waits for the others and the sum exceeds the time that passed.
