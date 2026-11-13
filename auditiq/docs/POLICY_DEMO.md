# Demonstration policies

Five company policies, each a PDF, to show that the audit follows the document: the same ledger, the same code, a different policy uploaded, a different result. The numbers below are measured by `python -m evaluation.policy_demo` on the ledger `final_seed_2025` (25,000 invoices), the controls of configuration C1 deciding the twelve rules they decide. The documents are in `policy/demo/`; `auditiq/policy_demo.py` renders them.

## The demonstration, step by step

1. Start the application with `start.bat`. The Overview shows the baseline policy (v2.5): 1,835 invoices with findings, 1,658 held for review.
2. Open **Policy**. Upload one PDF from `policy/demo/`. The page reads it and shows what it states and what differs from the policy in force, rule by rule.
3. Choose **Simulate**: every invoice of the ledger is audited in memory under the document and compared with the policy in force. Nothing is stored. The result says how many decisions move and how many invoices newly need a reviewer. The comparison is with the policy in force at that moment, so activate the baseline (version 2.5) and apply it between two demonstrations if the numbers are to be read against it.
4. Choose **Adopt and activate**, then **Apply**. The ledger is audited again under the new policy; the Overview, the review queue, the risk levels, the analytics and the vendor rings all follow it.
5. Upload the next policy and compare. To return, activate version 2.5 and apply again.
6. Upload `Draft_Incomplete_v5.99.pdf`: the system refuses it and says which rules the document leaves out.

## The policies

| Policy | File | What it changes from the baseline |
|---|---|---|
| **Lean Growth Edition** (v5.01) | `Lean_Growth_v5.01.pdf` | Rule 2.1.1, amount tolerance pct: 1 to 3; Rule 4.1.1, max invoices per vendor per day: 3 to 5; Rule 4.2.1, non business days: Saturday, Sunday to Sunday; Rule 4.2.1, severity: medium to low; Rule 4.3.1, round amount multiple: 10000 to 50000; Rule 5.1.1, approval limits: Manager 100,000, Senior Manager 500,000, Director 2,500,000, CFO 10,000,000 to Manager 250,000, Senior Manager 1,000,000, Director 5,000,000, CFO 20,000,000 |
| **Strict Controls Edition** (v5.02) | `Strict_Controls_v5.02.pdf` | Rule 2.1.1, amount tolerance pct: 1 to 0.5; Rule 3.1.1, severity: medium to high; Rule 3.1.2, severity: medium to high; Rule 4.1.1, max invoices per vendor per day: 3 to 2; Rule 4.2.1, severity: medium to high; Rule 4.3.1, round amount multiple: 10000 to 5000; Rule 4.3.1, severity: low to medium; Rule 5.1.1, approval limits: Manager 100,000, Senior Manager 500,000, Director 2,500,000, CFO 10,000,000 to Manager 90,000, Senior Manager 450,000, Director 2,250,000, CFO 9,000,000 |
| **Tax Compliance First Edition** (v5.03) | `Tax_Compliance_First_v5.03.pdf` | Rule 2.1.1, severity: high to critical; Rule 3.1.1, severity: medium to critical; Rule 3.1.2, severity: medium to critical; Rule 3.1.3, severity: high to critical |
| **Manufacturing Plant Edition** (v5.04) | `Manufacturing_Plant_v5.04.pdf` | Rule 2.1.1, amount tolerance pct: 1 to 2; Rule 4.1.1, max invoices per vendor per day: 3 to 4; Rule 4.2.1, non business days: Saturday, Sunday to Sunday; Rule 5.1.1, approval limits: Manager 100,000, Senior Manager 500,000, Director 2,500,000, CFO 10,000,000 to Manager 150,000, Senior Manager 750,000, Director 3,750,000, CFO 15,000,000 |
| **Fraud Prevention Edition** (v5.05) | `Fraud_Prevention_v5.05.pdf` | Rule 2.1.1, severity: high to critical; Rule 2.1.2, severity: high to critical; Rule 2.1.3, severity: high to critical; Rule 3.1.1, severity: medium to low; Rule 3.1.2, severity: medium to low; Rule 4.1.1, severity: high to critical; Rule 4.2.1, severity: medium to high; Rule 4.3.1, severity: low to medium |

## What happens

### Lean Growth Edition

The company has tripled its order volume in two years. Approvals were the bottleneck, so the limits are raised, price differences up to 3% are tolerated and the business works six days a week.

1,295 invoices have findings (baseline 1,835) and 1,157 are held for review (baseline 1,658), ₹30.4 Cr against ₹76.2 Cr. Risk levels: 387 critical, 770 high, 109 medium. Against the baseline: 715 decisions move, 0 invoices score higher and 707 lower. 540 of the baseline's 1,835 frauds are no longer raised; 0 invoices the baseline accepts are now raised.

What it shows: Fewer findings and a lighter review queue, and the price: frauds that sit inside the wider limits and tolerances are no longer found.

### Strict Controls Edition

After a fraud that went through on invoices just under the approval limits, the company lowers every limit by a tenth, cuts the tolerance to half a percent, allows two invoices per vendor and day, and treats weekend dates, round sums and malformed tax numbers as serious.

3,297 invoices have findings (baseline 1,835) and 3,263 are held for review (baseline 1,658), ₹117.9 Cr against ₹76.2 Cr. Risk levels: 2,096 critical, 1,167 high, 34 medium. Against the baseline: 1,524 decisions move, 1,688 invoices score higher and 0 lower. 0 of the baseline's 1,835 frauds are no longer raised; 1,348 invoices the baseline accepts are now raised.

What it shows: More findings and about twice as many invoices held for review: the cost of safety is a reviewer's time, and it includes invoices the baseline would have accepted.

### Tax Compliance First Edition

The tax office is auditing input tax credit. Thresholds are unchanged, but an invoice that carries a wrong, malformed or foreign GSTIN cannot support a credit claim, so every GST identity rule is critical.

1,835 invoices have findings (baseline 1,835) and 1,754 are held for review (baseline 1,658), ₹77.4 Cr against ₹76.2 Cr. Risk levels: 1,440 critical, 314 high, 47 medium. Against the baseline: 0 decisions move, 663 invoices score higher and 0 lower. 0 of the baseline's 1,835 frauds are no longer raised; 0 invoices the baseline accepts are now raised.

What it shows: The same invoices are found as under the baseline, but their priority changes: tax-identity findings move to the top of the queue and the scores of the affected invoices rise.

### Manufacturing Plant Edition

The plant runs six days a week and buys in larger lots. Saturday is a business day, orders are bigger, limits rise by half and a difference of 2% on the PO is tolerated for bulk materials.

1,530 invoices have findings (baseline 1,835) and 1,369 are held for review (baseline 1,658), ₹53.7 Cr against ₹76.2 Cr. Risk levels: 649 critical, 720 high, 124 medium. Against the baseline: 395 decisions move, 0 invoices score higher and 382 lower. 305 of the baseline's 1,835 frauds are no longer raised; 0 invoices the baseline accepts are now raised.

What it shows: Saturday invoices stop being exceptions and a larger share of the invoices are within authority: a policy fitted to the business removes noise without a large loss of coverage.

### Fraud Prevention Edition

Thresholds are unchanged. Internal Audit re-ranks the rules by how a fraud looks: mismatches between invoice, order and receipt, and splitting and timing patterns outrank formal errors.

1,835 invoices have findings (baseline 1,835) and 1,705 are held for review (baseline 1,658), ₹77.1 Cr against ₹76.2 Cr. Risk levels: 1,455 critical, 250 high, 34 medium. Against the baseline: 0 decisions move, 744 invoices score higher and 96 lower. 0 of the baseline's 1,835 frauds are no longer raised; 0 invoices the baseline accepts are now raised.

What it shows: The same findings with a new order: fraud patterns reach critical, formal errors drop out of review.

## One invoice, many verdicts

INV43977 (₹640,000.00) breaks the same rules wherever it is read, yet its score and the rules it breaks depend on the policy:

| Policy | Rules | Score | Level | Route |
|---|---|---|---|---|
| Baseline v2.5 | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 75 | CRITICAL | escalate |
| Lean Growth Edition | 2.1.2, 3.1.3 | 50 | HIGH | escalate |
| Strict Controls Edition | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 80 | CRITICAL | escalate |
| Tax Compliance First Edition | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 85 | CRITICAL | escalate |
| Manufacturing Plant Edition | 2.1.2, 3.1.3, 4.3.1 | 50 | HIGH | escalate |
| Fraud Prevention Edition | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 90 | CRITICAL | escalate |

The full comparison is in `results/policy_demo/policy_demo.md`.

## A word of caution on reading the numbers

- The answer key of a ledger is written for one policy (the baseline). Under another policy a baseline fraud that is inside the new limits is not an exception of that company; the tables say what a policy hides or adds, not which policy is right.
- The judgement rules (2.1.4, 2.1.5, 2.2.2, 4.1.2) need a model and are not part of these figures.
- Each policy takes effect on 2025-04-01, so the one chosen governs the whole financial year of the ledger.
