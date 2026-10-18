# Held-out policy documents

Produced by `python -m evaluation.policy_heldout` on 2026-10-18 09:45. 20 policy variants drawn at random (seed 2026) from values that were not used to build or check the reader; each is applied to the 40,000 invoices of 5 ledgers. Reference policy: version 2.5. No language model is used.

| Version | What changes | Values read correctly | Rules read word for word | Adopted | Decisions the change moves | Policy-driven: adherence | Frozen: adherence |
|---|---|---|---|---|---|---|---|
| 4.01 | guide_window_days 14; CFO limit 20,000,000; non_business_days ['Sunday']; amount_tolerance_pct 4.0; max_invoices_per_vendor_per_day 6 | 14 of 14 | 16 of 16 | yes | 252 (0.6%) | 1.000 | 0.994 |
| 4.02 | Director limit 2,000,000 | 14 of 14 | 16 of 16 | yes | 139 (0.3%) | 1.000 | 0.997 |
| 4.03 | non_business_days ['Saturday'] | 14 of 14 | 16 of 16 | yes | 25 (0.1%) | 1.000 | 0.999 |
| 4.04 | CFO limit 20,000,000; round_amount_multiple 25000; Manager limit 125,000; guide_window_days 10; guide_band_pct 20 | 14 of 14 | 16 of 16 | yes | 74 (0.2%) | 1.000 | 0.998 |
| 4.05 | non_business_days ['Saturday'] | 14 of 14 | 16 of 16 | yes | 25 (0.1%) | 1.000 | 0.999 |
| 4.06 | guide_window_days 10; Senior Manager limit 300,000 | 14 of 14 | 16 of 16 | yes | 3,046 (7.6%) | 1.000 | 0.924 |
| 4.07 | blocked_gstin_statuses ['Suspended', 'Cancelled']; guide_band_pct 10; amount_tolerance_pct 1.5; CFO limit 20,000,000 | 14 of 14 | 16 of 16 | yes | 1 (0.0%) | 1.000 | 1.000 |
| 4.08 | Manager limit 200,000; blocked_gstin_statuses ['Suspended', 'Cancelled'] | 14 of 14 | 16 of 16 | yes | 85 (0.2%) | 1.000 | 0.998 |
| 4.09 | Director limit 5,000,000; CFO limit 20,000,000 | 14 of 14 | 16 of 16 | yes | 22 (0.1%) | 1.000 | 0.999 |
| 4.10 | max_invoices_per_vendor_per_day 4; blocked_gstin_statuses ['Suspended', 'Cancelled']; non_business_days ['Friday', 'Saturday']; CFO limit 20,000,000 | 14 of 14 | 16 of 16 | yes | 7,953 (19.9%) | 1.000 | 0.801 |
| 4.11 | non_business_days ['Friday', 'Saturday'] | 14 of 14 | 16 of 16 | yes | 7,861 (19.7%) | 1.000 | 0.803 |
| 4.12 | round_amount_multiple 1000; CFO limit 20,000,000; amount_tolerance_pct 1.5; non_business_days ['Friday', 'Saturday'] | 14 of 14 | 16 of 16 | yes | 7,867 (19.7%) | 1.000 | 0.803 |
| 4.13 | guide_window_days 10; max_invoices_per_vendor_per_day 4; CFO limit 20,000,000 | 14 of 14 | 16 of 16 | yes | 120 (0.3%) | 1.000 | 0.997 |
| 4.14 | blocked_gstin_statuses ['Suspended', 'Cancelled'] | 14 of 14 | 16 of 16 | yes | 0 (0.0%) | 1.000 | 1.000 |
| 4.15 | Senior Manager limit 750,000; blocked_gstin_statuses ['Suspended', 'Cancelled'] | 14 of 14 | 16 of 16 | yes | 9 (0.0%) | 1.000 | 1.000 |
| 4.16 | amount_tolerance_pct 1.5; Senior Manager limit 750,000; guide_band_pct 10 | 14 of 14 | 16 of 16 | yes | 10 (0.0%) | 1.000 | 1.000 |
| 4.17 | Senior Manager limit 750,000 | 14 of 14 | 16 of 16 | yes | 9 (0.0%) | 1.000 | 1.000 |
| 4.18 | Manager limit 75,000; guide_band_pct 10; non_business_days ['Sunday'] | 14 of 14 | 16 of 16 | yes | 3,408 (8.5%) | 1.000 | 0.915 |
| 4.19 | non_business_days ['Sunday']; amount_tolerance_pct 3.0; Senior Manager limit 750,000 | 14 of 14 | 16 of 16 | yes | 71 (0.2%) | 1.000 | 0.998 |
| 4.20 | non_business_days ['Friday', 'Saturday']; guide_band_pct 10 | 14 of 14 | 16 of 16 | yes | 7,861 (19.7%) | 1.000 | 0.803 |

## Summary

- Reading: 280 of 280 values and 320 of 320 rules were read correctly; 20 of 20 documents were adopted.
- Policy-driven controls: 0 wrong decision(s) in 800,000 invoice audits.
- Frozen at version 2.5: the worst variant (v4.10: max_invoices_per_vendor_per_day 4; blocked_gstin_statuses ['Suspended', 'Cancelled']; non_business_days ['Friday', 'Saturday']; CFO limit 20,000,000) decides 7,953 invoices (19.9%) against the policy in force.

The variants are synthetic and follow the template wording; this checks that the reader and the controls follow values they were not developed on. It is not a test of policies written in other words (see `policy_llm.md`).
