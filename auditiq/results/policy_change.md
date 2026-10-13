# Policy-change experiment

Produced by `python -m evaluation.policy_change` on 2026-10-13 22:32. Reference policy: version 2.5. Ledgers: `bench_seed_101`, `bench_seed_202`, `bench_seed_303`, `swap_seed_404`, `large_seed_505`; 40,000 invoices in all. No language model is used anywhere in this experiment.

For each policy variant the system is given only the policy PDF. It reads the thresholds from the wording of the rules, builds the registry it executes, and audits every invoice with the deterministic controls ("policy-driven"). "Frozen" is the same controls with the thresholds of the reference version, which is how a system behaves whose thresholds are written into prompts and tool code. The ground truth under each variant is recomputed from the ledger tables by the dataset generator's validator, which shares no code with the controls.

## 1. Reading the policy documents

| Version | Policy | What changes | Pages | Parameters read correctly | Rules read word for word | Seconds to read |
|---|---|---|---|---|---|---|
| 3.01 | Tolerance 0.5% | amount tolerance 1% to 0.5% | 3 | 14 of 14 | 16 of 16 | 0.02 |
| 3.02 | Tolerance 2% | amount tolerance 1% to 2% | 3 | 14 of 14 | 16 of 16 | 0.03 |
| 3.03 | Tolerance 5% | amount tolerance 1% to 5% | 3 | 14 of 14 | 16 of 16 | 0.02 |
| 3.04 | Daily count 2 | invoices per vendor per day 3 to 2 | 3 | 14 of 14 | 16 of 16 | 0.03 |
| 3.05 | Daily count 5 | invoices per vendor per day 3 to 5 | 3 | 14 of 14 | 16 of 16 | 0.02 |
| 3.06 | Manager limit 50,000 | Manager approval limit 100,000 to 50,000 | 3 | 14 of 14 | 16 of 16 | 0.04 |
| 3.07 | Manager limit 150,000 | Manager approval limit 100,000 to 150,000 | 3 | 14 of 14 | 16 of 16 | 0.02 |
| 3.08 | Senior Manager limit 250,000 | Senior Manager approval limit 500,000 to 250,000 | 3 | 14 of 14 | 16 of 16 | 0.02 |
| 3.09 | Round multiple 5,000 | round-amount multiple 10,000 to 5,000 | 3 | 14 of 14 | 16 of 16 | 0.03 |
| 3.10 | Round multiple 50,000 | round-amount multiple 10,000 to 50,000 | 3 | 14 of 14 | 16 of 16 | 0.03 |
| 3.11 | Six-day week | Saturday becomes a business day | 3 | 14 of 14 | 16 of 16 | 0.03 |
| 3.12 | Strict policy | tolerance 0.5%, daily count 2, Manager 50,000, Senior Manager 250,000, round multiple 5,000 | 3 | 14 of 14 | 16 of 16 | 0.02 |
| 3.13 | Lenient policy | tolerance 5%, daily count 5, Manager 150,000, six-day week, round multiple 50,000 | 3 | 14 of 14 | 16 of 16 | 0.02 |
| 3.14 | Version 2.6 | tolerance 5%, daily count 5, Manager 150,000 (the policy-swap version) | 3 | 14 of 14 | 16 of 16 | 0.03 |

Over the 14 documents: 196 of 196 parameter values and 224 of 224 rules were read correctly; 0 problem(s) were reported.

## 2. Adherence to the policy in force

An invoice is decided correctly when the set of rules cited for it equals the ground truth of the policy in force. "Decisions the change moves" is the number of invoices whose ground truth under the variant differs from their ground truth under the reference version.

Under the reference version itself the controls agree with the independent recomputation on 40,000 of 40,000 invoices.

| Policy | Decisions the change moves | Policy-driven: adherence | Frozen: adherence | Frozen: findings the policy no longer supports | Frozen: exceptions not raised | Frozen: needless escalations | Frozen: missed escalations |
|---|---|---|---|---|---|---|---|
| Tolerance 0.5% | 62 (0.2%) | 1.000 (40,000 of 40,000) | 0.998 | 0 | 62 | 0 | 62 |
| Tolerance 2% | 7 (0.0%) | 1.000 (40,000 of 40,000) | 1.000 | 7 | 0 | 7 | 0 |
| Tolerance 5% | 63 (0.2%) | 1.000 (40,000 of 40,000) | 0.998 | 63 | 0 | 63 | 0 |
| Daily count 2 | 429 (1.1%) | 1.000 (40,000 of 40,000) | 0.989 | 0 | 429 | 0 | 428 |
| Daily count 5 | 170 (0.4%) | 1.000 (40,000 of 40,000) | 0.996 | 170 | 0 | 170 | 0 |
| Manager limit 50,000 | 7,677 (19.2%) | 1.000 (40,000 of 40,000) | 0.808 | 0 | 7,677 | 0 | 7,514 |
| Manager limit 150,000 | 69 (0.2%) | 1.000 (40,000 of 40,000) | 0.998 | 69 | 0 | 69 | 0 |
| Senior Manager limit 250,000 | 4,259 (10.6%) | 1.000 (40,000 of 40,000) | 0.894 | 0 | 4,259 | 0 | 4,161 |
| Round multiple 5,000 | 0 (0.0%) | 1.000 (40,000 of 40,000) | 1.000 | 0 | 0 | 0 | 0 |
| Round multiple 50,000 | 43 (0.1%) | 1.000 (40,000 of 40,000) | 0.999 | 43 | 0 | 0 | 0 |
| Six-day week | 35 (0.1%) | 1.000 (40,000 of 40,000) | 0.999 | 35 | 0 | 0 | 0 |
| Strict policy | 12,274 (30.7%) | 1.000 (40,000 of 40,000) | 0.693 | 0 | 12,427 | 0 | 12,012 |
| Lenient policy | 380 (0.9%) | 1.000 (40,000 of 40,000) | 0.991 | 380 | 0 | 302 | 0 |
| Version 2.6 | 302 (0.8%) | 1.000 (40,000 of 40,000) | 0.992 | 302 | 0 | 302 | 0 |

Policy-driven controls: 0 wrong decision(s) in 560,000 invoice audits. Auditing took 13 s for 560,000 invoice audits (44,444 invoices per second, one process; Intel64 Family 6 Model 154 Stepping 4, GenuineIntel, Python 3.11.3).

A needless escalation is an invoice the frozen system sends to a reviewer although the policy in force would approve it; a missed escalation is one it approves although the policy in force requires review (count-based score, threshold 50).

## 3. By ledger

| Policy | `bench_seed_101`: moved | `bench_seed_202`: moved | `bench_seed_303`: moved | `swap_seed_404`: moved | `large_seed_505`: moved |
|---|---|---|---|---|---|
| Tolerance 0.5% | 11 | 9 | 12 | 0 | 30 |
| Tolerance 2% | 0 | 0 | 0 | 7 | 0 |
| Tolerance 5% | 1 | 1 | 6 | 50 | 5 |
| Daily count 2 | 81 | 63 | 48 | 51 | 186 |
| Daily count 5 | 30 | 30 | 30 | 50 | 30 |
| Manager limit 50,000 | 937 | 919 | 967 | 938 | 3,916 |
| Manager limit 150,000 | 3 | 4 | 7 | 50 | 5 |
| Senior Manager limit 250,000 | 541 | 583 | 501 | 520 | 2,114 |
| Round multiple 5,000 | 0 | 0 | 0 | 0 | 0 |
| Round multiple 50,000 | 14 | 9 | 10 | 0 | 10 |
| Six-day week | 12 | 8 | 9 | 0 | 6 |
| Strict policy | 1,544 | 1,552 | 1,514 | 1,493 | 6,171 |
| Lenient policy | 60 | 52 | 62 | 150 | 56 |
| Version 2.6 | 34 | 35 | 43 | 150 | 40 |

## How to read this

- Full adherence of the policy-driven controls is a check, not a discovery: the controls and the ground truth are two implementations of the same written rules, and they agree. What the check establishes is that the thresholds were read correctly from each document and that no control keeps a threshold of its own.
- The numbers that are not fixed by construction are the columns for the frozen system: they measure how many decisions an ordinary policy revision moves in these ledgers, and so the size of the error of any system that has to be edited by hand to follow the policy.
- The documents follow the wording of the SOP template. A policy written in other words is refused with the list of rules and thresholds that could not be read; it is not guessed at.
- The ledgers are synthetic. The counts say how these ledgers react to these changes, not how a particular company's books would.
