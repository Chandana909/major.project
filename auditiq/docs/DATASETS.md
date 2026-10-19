# Datasets

AuditIQ-Bench is the set of synthetic procurement ledgers this project is built and evaluated on. **This file is generated** from the manifests under `data/` by `python -m auditiq_bench.overview`; the prose is in `auditiq_bench/overview.py`.

There are 6 datasets with 45,000 invoices and 187,413 ledger records in all. Each is a complete ledger: vendors, purchase orders, goods receipts, invoices and approval logs that refer to one another, plus the ground truth of every invoice.

| Dataset | Seed | Vendors | Purchase orders | Goods receipts | Invoices | Approval entries | Ledger records | Anomalous | Hard negatives | Evaluation subset |
|---|---|---|---|---|---|---|---|---|---|---|
| [`bench_seed_101`](../data/bench_seed_101/README.md) | 101 | 250 | 4,920 | 4,910 | 5,000 | 5,680 | 20,760 | 420 (8.4%) | 120 | 1,200 |
| [`bench_seed_202`](../data/bench_seed_202/README.md) | 202 | 250 | 4,920 | 4,910 | 5,000 | 5,688 | 20,768 | 420 (8.4%) | 120 | 1,200 |
| [`bench_seed_303`](../data/bench_seed_303/README.md) | 303 | 250 | 4,920 | 4,910 | 5,000 | 5,651 | 20,731 | 420 (8.4%) | 120 | 1,200 |
| [`pilot_seed_909`](../data/pilot_seed_909/README.md) | 909 | 250 | 4,920 | 4,910 | 5,000 | 5,675 | 20,755 | 420 (8.4%) | 120 | 1,200 |
| [`swap_seed_404`](../data/swap_seed_404/README.md) | 404 | 250 | 5,000 | 5,000 | 5,000 | 5,654 | 20,904 | 150 (3.0%) | 0 | 300 |
| [`large_seed_505`](../data/large_seed_505/README.md) | 505 | 1,000 | 19,920 | 19,910 | 20,000 | 22,665 | 83,495 | 420 (2.1%) | 240 | 1,200 |

| Dataset | What it is for |
|---|---|
| `bench_seed_101` | Results are reported on these three ledgers, as mean and spread over the seeds. |
| `bench_seed_202` | Results are reported on these three ledgers, as mean and spread over the seeds. |
| `bench_seed_303` | Results are reported on these three ledgers, as mean and spread over the seeds. |
| `pilot_seed_909` | Development. The only ledger on which prompts and settings may be tried. |
| `swap_seed_404` | The policy-swap experiment: the same ledger audited under policy v2.5 and v2.6. |
| `large_seed_505` | The ledger the application is demonstrated on, and precision at a realistic anomaly rate. |

## Files of a dataset

| File | Content | Columns |
|---|---|---|
| `vendor_master.csv` | one row per vendor | [`vendor_master`](DATA_DICTIONARY.md#vendor_master) |
| `purchase_orders.csv` | one row per order | [`purchase_orders`](DATA_DICTIONARY.md#purchase_orders) |
| `goods_receipts.csv` | one row per receipt | [`goods_receipts`](DATA_DICTIONARY.md#goods_receipts) |
| `invoices.csv` | one row per invoice | [`invoices`](DATA_DICTIONARY.md#invoices) |
| `approval_logs.csv` | one row per approval step | [`approval_logs`](DATA_DICTIONARY.md#approval_logs) |
| `labels.csv` | ground truth, one row per invoice | [`benchmark_labels`](DATA_DICTIONARY.md#benchmark_labels) |
| `eval_subset.csv` | the invoices the LLM configurations audit | `invoice_id`, `stratum`, `weight` |
| `manifest.json` | seed, generator and policy version, period, counts, SHA-256 of every file | |
| `README.md` | the datasheet of the dataset, written from the generated tables | |

The five ledger files load into the database with `python -m auditiq setup --dataset data/<name>`. A ledger of your own loads the same way from a folder of these files, a .zip archive of them, or an Excel workbook with one sheet per file (`python -m auditiq ledger import`, or the Overview page of the web application); it is checked first, and a ledger with a missing table or column, a repeated or empty identifier, an amount or date that cannot be read, or a vendor or purchase order that is not in the ledger replaces nothing. An invoice may name a purchase order or goods receipt that does not exist: that is the exception of rule 2.1.3. CSV files are UTF-8 with a header row, amounts have two decimals, dates are `YYYY-MM-DD`, and an empty field means no value. `labels.csv` of the policy-swap dataset has three more columns (`alt_policy_version`, `alt_label`, `alt_clause_ids`): the ground truth under the other policy version.

## How a ledger is built

The generator (`auditiq_bench/generator.py`) builds clean transactions first and injects anomalies into copies of the same process, so that an anomalous invoice differs from a clean one only in what was injected.

1. **Vendors.** Each vendor has a name, a state, a PAN, a GSTIN built from the two, one of 6 spending categories and its own style of invoice numbering. Vendors differ in how much business they get (log-normal weights), so a few vendors have many invoices and most have few.
2. **Purchases.** A purchase is an item from the vendor's category (36 items in all: 6 Logistics, 6 IT Services, 6 Raw Materials, 6 MRO, 6 Professional Services, 6 Utilities), a quantity and a unit price. Amounts follow a log-normal distribution per category.
3. **Documents.** The purchase order is dated first, the goods receipt some business days later, the invoice after the receipt. The invoice describes the item in the vendor's words, which are often not the words of the order. All invoices fall in the financial year 2025-26.
4. **Approval.** The invoice is approved by a person whose role can approve its amount under the policy: the lowest such role, or sometimes the one above. For some invoices approved above Manager level, the log first shows the role below passing the invoice on (`Escalated`). Every step is an entry in the approval log.
5. **Injection.** Anomalies and hard negatives are built by the same steps with one thing changed, and the label is written at that moment.
6. **Validation.** Before anything is written, `auditiq_bench/validate.py` recomputes from the finished tables which rule-defined clauses every invoice violates and requires the result to equal the labels in both directions: every labelled violation is present and no unlabelled invoice violates a rule. It also checks the structure of the judgement classes and that no unlabelled invoice falls inside their definitions. A dataset that fails is not written. This code shares nothing with the controls of the pipeline.

Thresholds are never written into the generator: it reads the tolerance, the daily limit, the approval limits and the other parameters from the same policy registry the pipeline uses.

## Anomaly classes

Classes R1 to R10 can be decided by comparing fields, and the pipeline decides them with controls. Classes J1 to J4 need reading or judgement, and the pipeline gives them to agents.

| Class | Anomaly | Rule(s) | How it is injected |
|---|---|---|---|
| R1 | Invoice amount differs from PO amount beyond the tolerance | 2.1.1 | The invoice bills a unit price above or below the order's, so that the invoice amount differs from the PO amount by more than the tolerance of Rule 2.1.1. |
| R2 | Billed quantity exceeds received quantity | 2.1.2 | The receipt records fewer units than the invoice bills; the shortfall is in the `received_quantity` field itself. |
| R3 | Duplicate invoice number for the same vendor | 2.2.1 | A second invoice repeats the invoice number of an earlier invoice of the same vendor, with the same PO, GRN and amount. Only the later invoice is anomalous; the earlier one is its `related_invoice_id`. |
| R4 | Malformed GSTIN or invalid state code | 3.1.1, 3.1.2 | The GSTIN printed on the invoice is too short or contains a character that is neither a letter nor a digit (Rule 3.1.1), or it begins with a state code outside the valid range (Rule 3.1.2). |
| R5 | Invoice GSTIN differs from the vendor master | 3.1.3 | The GSTIN on the invoice is well formed but is not the one registered for the vendor. |
| R6 | Same-day invoice splitting above the daily count | 4.1.1 | A vendor has more invoices dated on one day than the daily limit of Rule 4.1.1. Every invoice of that day is anomalous and they share a `group_id`. |
| R7 | Invoice amount exceeds the approver's limit | 5.1.1 | The invoice is approved by a role whose limit under the policy is below the invoice amount, with no escalation to a role that could approve it. |
| R8 | Missing PO or GRN reference | 2.1.3 | The invoice names neither a PO nor a GRN, names a PO but no GRN, or names a PO that is not on record. |
| R9 | Vendor blacklisted or suspended | 4.4.1 | The invoice comes from a vendor that is blacklisted or whose GST registration is suspended. Blocked vendors have no other invoices. |
| R10 | Weekend-dated or round-amount invoice | 4.2.1, 4.3.1 | Half are dated on a Saturday or Sunday (Rule 4.2.1); half bill an amount that is an exact multiple of the round-amount parameter (Rule 4.3.1). |
| J1 | Near-duplicate invoice: re-keyed number, same vendor and amount | 2.2.2 | A second invoice repeats an earlier one of the same vendor (same PO, GRN and amount) under a re-keyed invoice number: separators removed or changed, leading zeros dropped, a suffix added, two digits swapped, a zero typed as the letter O, or lower case. The numbers differ as text, so the exact-duplicate control does not fire. |
| J2 | Cross-day structuring just below an approval limit | 4.1.2 | Three invoices of one vendor for the same goods, dated on different days within the guide window of Rule 4.1.2, each just below the approval limit of the role that approved it and together above it. All three are anomalous and share a `group_id`. |
| J3 | Invoice description inconsistent with the PO description | 2.1.5 | The invoice describes goods or services of a different kind from what the PO ordered. Amounts and quantities agree, so no field comparison shows it. |
| J4 | GRN remark contradicts the billed quantity | 2.1.4 | The receiver's remark says that some units were rejected or returned, while the `received_quantity` field and the invoice still show the full quantity. Only the free-text remark contradicts the bill. |

Each anomalous invoice carries exactly one injected anomaly. Classes have equal counts by design, so that every class can be measured; this is not the mix a real ledger would have.

## Hard negatives

A hard negative is a clean invoice built to sit next to an anomaly class. A detector that flags it has learned the surface of the class, not the rule. The false-positive rate on hard negatives is reported separately from the rate on ordinary clean invoices.

| Type | What it is |
|---|---|
| HN_TOLERANCE | Invoice-PO variance just inside the tolerance (resembles R1) |
| HN_DAILY_LIMIT | Invoice count exactly at the daily limit (resembles R6) |
| HN_NEAR_LIMIT | Amount just inside an approval limit (resembles R7 and J2) |
| HN_SIMILAR_NUMBER | Consecutive invoice numbers and equal amounts for separate deliveries (resembles J1) |
| HN_RECURRING | Identical recurring monthly amounts (resembles R3 and J1) |

## The policy-swap ledger

`swap_seed_404` holds 150 boundary invoices among clean ones: 50 whose invoice amount differs from the PO amount by more than 1% and less than 5%, 50 that belong to a same-day group of four or five invoices, and 50 approved by a Manager for an amount between 100,000 and 150,000. Each violates one rule under policy v2.5 and none under v2.6, which changes exactly those three parameters. The ledger is validated under both versions.

## The evaluation subset

A configuration with an LLM makes several model calls per invoice, and most invoices of a ledger are ordinary. `eval_subset.csv` therefore lists the invoices those configurations audit: every anomalous invoice, every hard negative, every clean invoice that a duplicate copies, and a random sample of the other clean invoices. Each row has a weight: 1 for the invoices that are all included, and N/n for the sampled ones, where N is the number of ordinary clean invoices in the ledger and n the number sampled. The weights of a subset sum to the number of invoices in the ledger.

Metrics are ratios of weighted sums, so a rate computed on the subset estimates the rate on the whole ledger. Recall and the hard-negative false-positive rate are exact, because their strata are complete; the false-positive rate on ordinary invoices and the precision carry sampling error, which the bootstrap intervals include (resampling within strata). The agents always see the whole ledger as vendor history; only the choice of which invoices to audit is restricted. The controls and the classical detectors cost nothing per invoice and are evaluated on every invoice.

## Reproducing and checking

```bash
python -m auditiq_bench                  # regenerate every dataset
python -m auditiq_bench --only large_seed_505
python -m auditiq_bench.overview --verify # compare every file with the hash in its manifest
```

A dataset is a function of its seed, the generator version and the policy registry. The same command writes byte-identical files, and `manifest.json` records the SHA-256 of each.

## What the data cannot show

- **It is synthetic.** Vendors, people, GSTINs and invoices are generated. Amount distributions, vendor concentration and approval routing are plausible by design, not fitted to a real ledger, so results on this data are results about the system under controlled conditions, not estimates of its accuracy on a company's books.
- **Injected anomalies are clean cases.** Each anomalous invoice has one anomaly, built to match the definition of its class. Real exceptions are messier and overlap.
- **Several columns are constant** (currency, payment terms, payment status, quality check and others, as the data dictionary states). They are there so that the schema is complete; nothing can be learned from them.
- **Free text is templated.** Descriptions and receipt remarks are drawn from a fixed vocabulary with variations, which is easier to read than what people type.
- **J1 can be found without judgement, as generated.** In these ledgers an invoice that is not the first on its purchase order is always a duplicate (R3 or J1), so a rule on the PO reference finds every J1 without reading the invoice number, and both classical detectors do (`results/summary.md`). J1 therefore does not test judgement here. Whether to make it a rule-defined class or to let clean invoices share a purchase order is an open decision (`PLAN.md`, section 6).
- **The classical detectors and the controls see everything; the LLM configurations see the evaluation subset.** The weights make the rates comparable; the intervals are wider for the latter.
