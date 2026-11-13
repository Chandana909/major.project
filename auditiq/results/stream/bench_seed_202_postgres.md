# Kafka ingestion: bench_seed_202 on postgres

5,000 invoices of `bench_seed_202` and 2,105 vendor e-mails (`auditiq_bench.correspondence`, seed 7) published as one burst to four topics of 4 partitions on a local broker (127.0.0.1:9092); invoice workers audit with C1. Machine: Intel64 Family 6 Model 154 Stepping 4, GenuineIntel, 12 logical CPUs, Windows 10. Measured 2026-10-28 00:05 by `python -m evaluation.stream_eval`.

Each setting was run 3 times: the table gives the median run by time (the times of every run in brackets); the findings and e-mail columns give the worst of the runs and the errors their sum.

| Invoice workers | Seconds to the last result | Invoices/s | Latency median / p95 (ms) | Invoices per partition | Same findings as batch | F1 | E-mails linked right | Errors |
|---:|---:|---:|---:|---|---:|---:|---:|---:|
| 1 | 27.2 (32.91, 27.2, 26.38) | 183.8 | 16,213.0 / 26,753 | 1435 / 1307 / 1107 / 1151 | 5,000 of 5,000 | 0.833 | 2,102 of 2,105 | 0 |
| 2 | 23.22 (23.22, 23.3, 22.66) | 215.3 | 14,001.5 / 20,891 | 1435 / 1307 / 1107 / 1151 | 5,000 of 5,000 | 0.833 | 2,101 of 2,105 | 0 |
| 4 | 18.04 (18.46, 18.04, 17.24) | 277.2 | 12,947.5 / 17,572 | 1435 / 1307 / 1107 / 1151 | 5,000 of 5,000 | 0.833 | 2,101 of 2,105 | 0 |

Batch audit of the same ledger (C1, one process): 7.7 s, F1 0.833 (precision 1.000, recall 0.714).

Latency is the time from publication to the stored result, for a burst published at once: it is mostly time spent waiting in the topic, and falls as workers are added.
