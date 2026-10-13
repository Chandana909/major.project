# Vendor history under the cap

An agent is shown at most 40 other invoices of the vendor per selection rule (`auditiq/agents.py`). The table counts the labelled invoices whose vendor history exceeds the cap and whose case depends on other invoices, and how many of them still see every one of those invoices. "Owning stage" is the agent whose remit covers the case; the single-prompt auditor of C2 uses both rules.

| Dataset | Invoices above the cap | Kind | Cases | Complete for the owning stage | Complete for the single auditor |
|---|---|---|---|---|---|
| `bench_seed_101` | 955 of 5,000 | HN_DAILY_LIMIT | 6 | 6 | 6 |
| `bench_seed_101` | 955 of 5,000 | HN_RECURRING | 24 | 24 | 24 |
| `bench_seed_101` | 955 of 5,000 | HN_SIMILAR_NUMBER | 6 | 6 | 6 |
| `bench_seed_101` | 955 of 5,000 | J1 | 7 | 7 | 7 |
| `bench_seed_101` | 955 of 5,000 | J2 | 12 | 12 | 12 |
| `bench_seed_101` | 955 of 5,000 | R3 | 5 | 5 | 5 |
| `bench_seed_101` | 955 of 5,000 | R6 | 5 | 5 | 5 |
| `bench_seed_202` | 1,034 of 5,000 | HN_DAILY_LIMIT | 3 | 3 | 3 |
| `bench_seed_202` | 1,034 of 5,000 | HN_RECURRING | 8 | 8 | 8 |
| `bench_seed_202` | 1,034 of 5,000 | HN_SIMILAR_NUMBER | 2 | 2 | 2 |
| `bench_seed_202` | 1,034 of 5,000 | J1 | 6 | 6 | 6 |
| `bench_seed_202` | 1,034 of 5,000 | J2 | 9 | 9 | 9 |
| `bench_seed_202` | 1,034 of 5,000 | R3 | 9 | 9 | 9 |
| `bench_seed_202` | 1,034 of 5,000 | R6 | 17 | 17 | 17 |
| `bench_seed_303` | 1,062 of 5,000 | HN_DAILY_LIMIT | 6 | 6 | 6 |
| `bench_seed_303` | 1,062 of 5,000 | HN_SIMILAR_NUMBER | 8 | 8 | 8 |
| `bench_seed_303` | 1,062 of 5,000 | J1 | 5 | 5 | 5 |
| `bench_seed_303` | 1,062 of 5,000 | J2 | 15 | 15 | 15 |
| `bench_seed_303` | 1,062 of 5,000 | R3 | 8 | 8 | 8 |
| `large_seed_505` | 4,055 of 20,000 | HN_DAILY_LIMIT | 3 | 3 | 3 |
| `large_seed_505` | 4,055 of 20,000 | HN_RECURRING | 8 | 8 | 8 |
| `large_seed_505` | 4,055 of 20,000 | HN_SIMILAR_NUMBER | 10 | 10 | 10 |
| `large_seed_505` | 4,055 of 20,000 | J1 | 4 | 4 | 4 |
| `large_seed_505` | 4,055 of 20,000 | R3 | 6 | 6 | 6 |
| `large_seed_505` | 4,055 of 20,000 | R6 | 4 | 4 | 4 |
| `pilot_seed_909` | 1,333 of 5,000 | HN_DAILY_LIMIT | 3 | 3 | 3 |
| `pilot_seed_909` | 1,333 of 5,000 | HN_RECURRING | 24 | 24 | 24 |
| `pilot_seed_909` | 1,333 of 5,000 | HN_SIMILAR_NUMBER | 12 | 12 | 12 |
| `pilot_seed_909` | 1,333 of 5,000 | J1 | 6 | 6 | 6 |
| `pilot_seed_909` | 1,333 of 5,000 | J2 | 9 | 9 | 9 |
| `pilot_seed_909` | 1,333 of 5,000 | R3 | 17 | 17 | 17 |
| `pilot_seed_909` | 1,333 of 5,000 | R6 | 4 | 4 | 4 |

Cases that lose an invoice they depend on: 0.
