# Judgement-rule leads against the answer keys

Source: `python -m evaluation.leads_eval`. A lead is an invoice the code lists for a reviewer under rule 2.2.2 (near duplicate) or 4.1.2 (structuring across days), with the policy's guide values; it is not a finding. Precision counts every listed invoice that is not labelled for the rule, hard negatives included. The method was developed on `final_seed_2025` (first version: 136 of 141 near duplicates, 35 of 141 structuring invoices; changed once, then frozen); the other ledgers are held out.

| Ledger | Invoices | Held out | Rule | Labelled | Listed | Listed and labelled | Recall | Precision | Listed otherwise |
|---|---|---|---|---|---|---|---|---|---|
| final_seed_2025 | 25,000 | no | 2.2.2 | 141 | 141 | 141 | 100.0% | 100.0% | none |
| final_seed_2025 | 25,000 | no | 4.1.2 | 141 | 141 | 141 | 100.0% | 100.0% | none |
| bench_seed_101 | 5,000 | yes | 2.2.2 | 30 | 30 | 30 | 100.0% | 100.0% | none |
| bench_seed_101 | 5,000 | yes | 4.1.2 | 30 | 30 | 30 | 100.0% | 100.0% | none |
| bench_seed_202 | 5,000 | yes | 2.2.2 | 30 | 30 | 30 | 100.0% | 100.0% | none |
| bench_seed_202 | 5,000 | yes | 4.1.2 | 30 | 30 | 30 | 100.0% | 100.0% | none |
| bench_seed_303 | 5,000 | yes | 2.2.2 | 30 | 30 | 30 | 100.0% | 100.0% | none |
| bench_seed_303 | 5,000 | yes | 4.1.2 | 30 | 30 | 30 | 100.0% | 100.0% | none |
| large_seed_505 | 20,000 | yes | 2.2.2 | 30 | 30 | 30 | 100.0% | 100.0% | none |
| large_seed_505 | 20,000 | yes | 4.1.2 | 30 | 30 | 30 | 100.0% | 100.0% | none |
| pilot_seed_909 | 5,000 | yes | 2.2.2 | 30 | 30 | 30 | 100.0% | 100.0% | none |
| pilot_seed_909 | 5,000 | yes | 4.1.2 | 30 | 30 | 30 | 100.0% | 100.0% | none |

The generator plants J1 and J2 in the pattern the policy describes, and keeps clean invoices clear of the structuring guide with a wider margin, so agreement here shows that the code follows the policy's wording on these ledgers; it is not an estimate of how real duplicates or split purchases look.
