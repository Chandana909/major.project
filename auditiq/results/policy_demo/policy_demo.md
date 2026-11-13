# Demonstration policies on `final_seed_2025`

25,000 invoices audited by the controls (configuration C1) under each policy read from its PDF. The same ledger and the same code; only the document changes.

## What each policy states

| Policy | Version | Values read | Changes from the baseline | Story |
|---|---|---|---|---|
| Baseline v2.5 | 2.5 | 0/0 | 0 | The procurement SOP of the project. |
| Lean Growth Edition | 5.01 | 14/14 | 6 | The company has tripled its order volume in two years. Approvals were the bottleneck, so the limits are raised, price differences up to 3% are tolerated and the business works six days a week. |
| Strict Controls Edition | 5.02 | 14/14 | 8 | After a fraud that went through on invoices just under the approval limits, the company lowers every limit by a tenth, cuts the tolerance to half a percent, allows two invoices per vendor and day, and treats weekend dates, round sums and malformed tax numbers as serious. |
| Tax Compliance First Edition | 5.03 | 14/14 | 4 | The tax office is auditing input tax credit. Thresholds are unchanged, but an invoice that carries a wrong, malformed or foreign GSTIN cannot support a credit claim, so every GST identity rule is critical. |
| Manufacturing Plant Edition | 5.04 | 14/14 | 4 | The plant runs six days a week and buys in larger lots. Saturday is a business day, orders are bigger, limits rise by half and a difference of 2% on the PO is tolerated for bulk materials. |
| Fraud Prevention Edition | 5.05 | 14/14 | 8 | Thresholds are unchanged. Internal Audit re-ranks the rules by how a fraud looks: mismatches between invoice, order and receipt, and splitting and timing patterns outrank formal errors. |

## How the output changes

| Policy | Invoices with findings | Held for review | Money held | Critical | High | Medium | Different scores |
|---|---|---|---|---|---|---|---|
| Baseline v2.5 | 1,835 | 1,658 | ₹76.2 Cr | 868 | 790 | 143 | 8 |
| Lean Growth Edition | 1,295 | 1,157 | ₹30.4 Cr | 387 | 770 | 109 | 7 |
| Strict Controls Edition | 3,297 | 3,263 | ₹117.9 Cr | 2,096 | 1,167 | 34 | 6 |
| Tax Compliance First Edition | 1,835 | 1,754 | ₹77.4 Cr | 1,440 | 314 | 47 | 8 |
| Manufacturing Plant Edition | 1,530 | 1,369 | ₹53.7 Cr | 649 | 720 | 124 | 8 |
| Fraud Prevention Edition | 1,835 | 1,705 | ₹77.1 Cr | 1,455 | 250 | 34 | 7 |

## Against the frauds of the ledger

The ledger's answer key names 1,835 frauds the controls can decide and 22,725 invoices without a fraud. The key was written for the baseline: under another policy a baseline fraud that falls inside the new limits is no longer an exception of that company, and an invoice the baseline accepts may break the new rules. The table says what the choice of policy costs or hides.

| Policy | Baseline frauds still raised | Baseline frauds no longer raised | Held for review | Invoices without a fraud now raised | Of them held |
|---|---|---|---|---|---|
| Baseline v2.5 | 1,835 | 0 | 1,658 | 0 | 0 |
| Lean Growth Edition | 1,295 | 540 | 1,157 | 0 | 0 |
| Strict Controls Edition | 1,835 | 0 | 1,801 | 1,348 | 1,348 |
| Tax Compliance First Edition | 1,835 | 0 | 1,754 | 0 | 0 |
| Manufacturing Plant Edition | 1,530 | 305 | 1,369 | 0 | 0 |
| Fraud Prevention Edition | 1,835 | 0 | 1,705 | 0 | 0 |

## Against the baseline, invoice by invoice

| Policy | Decisions moved | Newly flagged | Cleared | Score higher | Score lower | Route changes |
|---|---|---|---|---|---|---|
| Lean Growth Edition | 715 | 0 | 540 | 0 | 707 | escalate -> approve: 501 |
| Strict Controls Edition | 1,524 | 1,462 | 0 | 1,688 | 0 | approve -> escalate: 1,605 |
| Tax Compliance First Edition | 0 | 0 | 0 | 663 | 0 | approve -> escalate: 96 |
| Manufacturing Plant Edition | 395 | 0 | 305 | 0 | 382 | escalate -> approve: 289 |
| Fraud Prevention Edition | 0 | 0 | 0 | 744 | 96 | approve -> escalate: 47 |

## Findings by rule

| Rule | Baseline v2.5 | Lean Growth Edition | Strict Controls Edition | Tax Compliance First Edition | Manufacturing Plant Edition | Fraud Prevention Edition |
|---|---|---|---|---|---|---|
| 2.1.1 | 141 | 135 | 173 | 141 | 141 | 141 |
| 2.1.2 | 291 | 291 | 291 | 291 | 291 | 291 |
| 2.1.3 | 141 | 141 | 141 | 141 | 141 | 141 |
| 2.2.1 | 141 | 141 | 141 | 141 | 141 | 141 |
| 3.1.1 | 71 | 71 | 71 | 71 | 71 | 71 |
| 3.1.2 | 70 | 70 | 70 | 70 | 70 | 70 |
| 3.1.3 | 563 | 563 | 563 | 563 | 563 | 563 |
| 4.1.1 | 141 | 0 | 414 | 141 | 5 | 141 |
| 4.2.1 | 70 | 34 | 70 | 70 | 34 | 70 |
| 4.3.1 | 71 | 11 | 71 | 71 | 71 | 71 |
| 4.4.1 | 141 | 141 | 141 | 141 | 141 | 141 |
| 5.1.1 | 601 | 111 | 1,835 | 601 | 377 | 601 |

## One invoice, five verdicts

The invoices the policies judge most differently (score and route under each policy).

**INV43977**, ₹640,000.00

| Policy | Rules | Score | Level | Route |
|---|---|---|---|---|
| Baseline v2.5 | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 75 | CRITICAL | escalate |
| Lean Growth Edition | 2.1.2, 3.1.3 | 50 | HIGH | escalate |
| Strict Controls Edition | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 80 | CRITICAL | escalate |
| Tax Compliance First Edition | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 85 | CRITICAL | escalate |
| Manufacturing Plant Edition | 2.1.2, 3.1.3, 4.3.1 | 50 | HIGH | escalate |
| Fraud Prevention Edition | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 90 | CRITICAL | escalate |

**INV42229**, ₹250,000.00

| Policy | Rules | Score | Level | Route |
|---|---|---|---|---|
| Baseline v2.5 | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 75 | CRITICAL | escalate |
| Lean Growth Edition | 2.1.2, 3.1.3, 4.3.1 | 50 | HIGH | escalate |
| Strict Controls Edition | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 80 | CRITICAL | escalate |
| Tax Compliance First Edition | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 85 | CRITICAL | escalate |
| Manufacturing Plant Edition | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 75 | CRITICAL | escalate |
| Fraud Prevention Edition | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 90 | CRITICAL | escalate |

**INV42051**, ₹210,000.00

| Policy | Rules | Score | Level | Route |
|---|---|---|---|---|
| Baseline v2.5 | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 75 | CRITICAL | escalate |
| Lean Growth Edition | 2.1.2, 3.1.3 | 50 | HIGH | escalate |
| Strict Controls Edition | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 80 | CRITICAL | escalate |
| Tax Compliance First Edition | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 85 | CRITICAL | escalate |
| Manufacturing Plant Edition | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 75 | CRITICAL | escalate |
| Fraud Prevention Edition | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 90 | CRITICAL | escalate |

**INV47346**, ₹320,000.00

| Policy | Rules | Score | Level | Route |
|---|---|---|---|---|
| Baseline v2.5 | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 75 | CRITICAL | escalate |
| Lean Growth Edition | 2.1.2, 3.1.3, 5.1.1 | 70 | CRITICAL | escalate |
| Strict Controls Edition | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 80 | CRITICAL | escalate |
| Tax Compliance First Edition | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 85 | CRITICAL | escalate |
| Manufacturing Plant Edition | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 75 | CRITICAL | escalate |
| Fraud Prevention Edition | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 90 | CRITICAL | escalate |

**INV51379**, ₹310,000.00

| Policy | Rules | Score | Level | Route |
|---|---|---|---|---|
| Baseline v2.5 | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 75 | CRITICAL | escalate |
| Lean Growth Edition | 2.1.2, 3.1.3, 5.1.1 | 70 | CRITICAL | escalate |
| Strict Controls Edition | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 80 | CRITICAL | escalate |
| Tax Compliance First Edition | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 85 | CRITICAL | escalate |
| Manufacturing Plant Edition | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 75 | CRITICAL | escalate |
| Fraud Prevention Edition | 2.1.2, 3.1.3, 4.3.1, 5.1.1 | 90 | CRITICAL | escalate |

## A policy that is refused

`Draft_Incomplete_v5.99.pdf` leaves out rules. The system reads it and refuses it, with the reasons:

- Rule 4.4.1 (blocked vendor) is not in the document; the system needs every rule it executes to be stated
- Rule 5.1.1: no table of approval limits by role was found
