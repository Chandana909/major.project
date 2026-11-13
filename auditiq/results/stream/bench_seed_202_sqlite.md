# Kafka ingestion: bench_seed_202 on sqlite

5,000 invoices of `bench_seed_202` and 2,105 vendor e-mails (`auditiq_bench.correspondence`, seed 7) published as one burst to four topics of 4 partitions on a local broker (127.0.0.1:9092); invoice workers audit with C1. Machine: Intel64 Family 6 Model 154 Stepping 4, GenuineIntel, 12 logical CPUs, Windows 10. Measured 2026-10-27 23:58 by `python -m evaluation.stream_eval`.

Each setting was run 3 times: the table gives the median run by time (the times of every run in brackets); the findings and e-mail columns give the worst of the runs and the errors their sum.

| Invoice workers | Seconds to the last result | Invoices/s | Latency median / p95 (ms) | Invoices per partition | Same findings as batch | F1 | E-mails linked right | Errors |
|---:|---:|---:|---:|---|---:|---:|---:|---:|
| 1 | 21.92 (19.35, 24.75, 21.92) | 228.1 | 12,770.0 / 21,178 | 1435 / 1307 / 1107 / 1151 | 5,000 of 5,000 | 0.833 | 2,100 of 2,105 | 0 |
| 2 | 17.56 (19.97, 17.56, 16.95) | 284.8 | 11,043.5 / 16,185 | 1435 / 1307 / 1107 / 1151 | 5,000 of 5,000 | 0.833 | 2,102 of 2,105 | 0 |

Batch audit of the same ledger (C1, one process): 6.76 s, F1 0.833 (precision 1.000, recall 0.714).

Latency is the time from publication to the stored result, for a burst published at once: it is mostly time spent waiting in the topic, and falls as workers are added.
