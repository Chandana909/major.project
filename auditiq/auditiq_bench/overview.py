"""Overview of the generated datasets, written from their manifests.

    python -m auditiq_bench.overview            writes docs/DATASETS.md
    python -m auditiq_bench.overview --verify   checks every file against the hash in its manifest

Each dataset folder has its own datasheet (README.md) with the counts of that
dataset. This overview puts the datasets side by side and explains how a
ledger is built, how each anomaly is injected and what the data cannot show.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from . import catalog as cat
from .__main__ import PROFILES, PROJECT_ROOT
from .taxonomy import CLASSES, HARD_NEGATIVE_TYPES

DOC = PROJECT_ROOT / "docs" / "DATASETS.md"

USE = {
    "benchmark": "Results are reported on these three ledgers, as mean and spread over the seeds.",
    "pilot": "Development. The only ledger on which prompts and settings may be tried.",
    "policy_swap": "The policy-swap experiment: the same ledger audited under policy v2.5 and v2.6.",
    "large": "The ledger the application is demonstrated on, and precision at a realistic anomaly rate.",
}

# How each class is injected. A test requires one entry per class of the taxonomy.
INJECTION = {
    "R1": "The invoice bills a unit price above or below the order's, so that the invoice amount differs from "
          "the PO amount by more than the tolerance of Rule 2.1.1.",
    "R2": "The receipt records fewer units than the invoice bills; the shortfall is in the "
          "`received_quantity` field itself.",
    "R3": "A second invoice repeats the invoice number of an earlier invoice of the same vendor, with the same "
          "PO, GRN and amount. Only the later invoice is anomalous; the earlier one is its "
          "`related_invoice_id`.",
    "R4": "The GSTIN printed on the invoice is too short or contains a character that is neither a letter nor a "
          "digit (Rule 3.1.1), or it begins with a state code outside the valid range (Rule 3.1.2).",
    "R5": "The GSTIN on the invoice is well formed but is not the one registered for the vendor.",
    "R6": "A vendor has more invoices dated on one day than the daily limit of Rule 4.1.1. Every invoice of "
          "that day is anomalous and they share a `group_id`.",
    "R7": "The invoice is approved by a role whose limit under the policy is below the invoice amount, with no "
          "escalation to a role that could approve it.",
    "R8": "The invoice names neither a PO nor a GRN, names a PO but no GRN, or names a PO that is not on record.",
    "R9": "The invoice comes from a vendor that is blacklisted or whose GST registration is suspended. Blocked "
          "vendors have no other invoices.",
    "R10": "Half are dated on a Saturday or Sunday (Rule 4.2.1); half bill an amount that is an exact multiple "
           "of the round-amount parameter (Rule 4.3.1).",
    "J1": "A second invoice repeats an earlier one of the same vendor (same PO, GRN and amount) under a re-keyed "
          "invoice number: separators removed or changed, leading zeros dropped, a suffix added, two digits "
          "swapped, a zero typed as the letter O, or lower case. The numbers differ as text, so the "
          "exact-duplicate control does not fire.",
    "J2": "Three invoices of one vendor for the same goods, dated on different days within the guide window of "
          "Rule 4.1.2, each just below the approval limit of the role that approved it and together above it. "
          "All three are anomalous and share a `group_id`.",
    "J3": "The invoice describes goods or services of a different kind from what the PO ordered. Amounts and "
          "quantities agree, so no field comparison shows it.",
    "J4": "The receiver's remark says that some units were rejected or returned, while the "
          "`received_quantity` field and the invoice still show the full quantity. Only the free-text remark "
          "contradicts the bill.",
}


def manifests(root: Path) -> list[dict]:
    found = []
    for profile in PROFILES:
        path = root / profile.name / "manifest.json"
        if path.exists():
            found.append(json.loads(path.read_text(encoding="utf-8")))
    return found


def verify(root: Path) -> list[str]:
    """Files whose content does not match the hash recorded when the dataset was generated."""
    problems = []
    for manifest in manifests(root):
        folder = root / manifest["dataset"]
        for name, expected in manifest["sha256"].items():
            path = folder / name
            if not path.exists():
                problems.append(f"{manifest['dataset']}/{name}: missing")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                problems.append(f"{manifest['dataset']}/{name}: content differs from the manifest")
    return problems


def render(root: Path) -> str:
    found = manifests(root)
    total_records = sum(m["counts"]["ledger_records"] for m in found)
    total_invoices = sum(m["counts"]["invoices"] for m in found)
    items = {c: sum(i.category == c for i in cat.ITEMS) for c in cat.CATEGORIES}
    out = [
        "# Datasets", "",
        "AuditIQ-Bench is the set of synthetic procurement ledgers this project is built and evaluated on. "
        "**This file is generated** from the manifests under `data/` by `python -m auditiq_bench.overview`; "
        "the prose is in `auditiq_bench/overview.py`.", "",
        f"There are {len(found)} datasets with {total_invoices:,} invoices and {total_records:,} ledger records "
        "in all. Each is a complete ledger: vendors, purchase orders, goods receipts, invoices and approval "
        "logs that refer to one another, plus the ground truth of every invoice.", "",
        "| Dataset | Seed | Vendors | Purchase orders | Goods receipts | Invoices | Approval entries | "
        "Ledger records | Anomalous | Hard negatives | Evaluation subset |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in found:
        c = m["counts"]
        out.append(f"| [`{m['dataset']}`](../data/{m['dataset']}/README.md) | {m['seed']} | {c['vendors']:,} | "
                   f"{c['purchase_orders']:,} | {c['goods_receipts']:,} | {c['invoices']:,} | "
                   f"{c['approval_logs']:,} | {c['ledger_records']:,} | {c['anomalous']:,} "
                   f"({c['anomalous'] / c['invoices']:.1%}) | {c['hard_negative']:,} | {c['eval_subset']:,} |")
    out += ["", "| Dataset | What it is for |", "|---|---|"]
    out += [f"| `{m['dataset']}` | {USE[m['kind']]} |" for m in found]
    out += [
        "",
        "## Files of a dataset", "",
        "| File | Content | Columns |", "|---|---|---|",
        "| `vendor_master.csv` | one row per vendor | [`vendor_master`](DATA_DICTIONARY.md#vendor_master) |",
        "| `purchase_orders.csv` | one row per order | [`purchase_orders`](DATA_DICTIONARY.md#purchase_orders) |",
        "| `goods_receipts.csv` | one row per receipt | [`goods_receipts`](DATA_DICTIONARY.md#goods_receipts) |",
        "| `invoices.csv` | one row per invoice | [`invoices`](DATA_DICTIONARY.md#invoices) |",
        "| `approval_logs.csv` | one row per approval step | [`approval_logs`](DATA_DICTIONARY.md#approval_logs) |",
        "| `labels.csv` | ground truth, one row per invoice | [`benchmark_labels`](DATA_DICTIONARY.md#benchmark_labels) |",
        "| `eval_subset.csv` | the invoices the LLM configurations audit | `invoice_id`, `stratum`, `weight` |",
        "| `manifest.json` | seed, generator and policy version, period, counts, SHA-256 of every file | |",
        "| `README.md` | the datasheet of the dataset, written from the generated tables | |",
        "",
        "The five ledger files load into the database with `python -m auditiq setup --dataset data/<name>`. "
        "A ledger of your own loads the same way from a folder of these files, a .zip archive of them, or an Excel "
        "workbook with one sheet per file (`python -m auditiq ledger import`, or the Overview page of the web "
        "application); it is checked first, and a ledger with a missing table or column, a repeated or empty "
        "identifier, an amount or date that cannot be read, or a vendor or purchase order that is not in the ledger "
        "replaces nothing. An invoice may name a purchase order or goods receipt that does not exist: that is the "
        "exception of rule 2.1.3. "
        "CSV files are UTF-8 with a header row, amounts have two decimals, dates are `YYYY-MM-DD`, and an empty "
        "field means no value. `labels.csv` of the policy-swap dataset has three more columns "
        "(`alt_policy_version`, `alt_label`, `alt_clause_ids`): the ground truth under the other policy version.",
        "",
        "## How a ledger is built", "",
        "The generator (`auditiq_bench/generator.py`) builds clean transactions first and injects anomalies "
        "into copies of the same process, so that an anomalous invoice differs from a clean one only in what "
        "was injected.", "",
        f"1. **Vendors.** Each vendor has a name, a state, a PAN, a GSTIN built from the two, one of "
        f"{len(cat.CATEGORIES)} spending categories and its own style of invoice numbering. Vendors differ in "
        "how much business they get (log-normal weights), so a few vendors have many invoices and most have few.",
        f"2. **Purchases.** A purchase is an item from the vendor's category ({sum(items.values())} items in "
        f"all: {', '.join(f'{n} {c}' for c, n in items.items())}), a quantity and a unit price. Amounts follow a "
        "log-normal distribution per category.",
        "3. **Documents.** The purchase order is dated first, the goods receipt some business days later, the "
        "invoice after the receipt. The invoice describes the item in the vendor's words, which are often not "
        "the words of the order. All invoices fall in the financial year 2025-26.",
        "4. **Approval.** The invoice is approved by a person whose role can approve its amount under the "
        "policy: the lowest such role, or sometimes the one above. For some invoices approved above Manager "
        "level, the log first shows the role below passing the invoice on (`Escalated`). Every step is an entry "
        "in the approval log.",
        "5. **Injection.** Anomalies and hard negatives are built by the same steps with one thing changed, "
        "and the label is written at that moment.",
        "6. **Validation.** Before anything is written, `auditiq_bench/validate.py` recomputes from the "
        "finished tables which rule-defined clauses every invoice violates and requires the result to equal "
        "the labels in both directions: every labelled violation is present and no unlabelled invoice violates "
        "a rule. It also checks the structure of the judgement classes and that no unlabelled invoice falls "
        "inside their definitions. A dataset that fails is not written. This code shares nothing with the "
        "controls of the pipeline.",
        "",
        "Thresholds are never written into the generator: it reads the tolerance, the daily limit, the "
        "approval limits and the other parameters from the same policy registry the pipeline uses.",
        "",
        "## Anomaly classes", "",
        "Classes R1 to R10 can be decided by comparing fields, and the pipeline decides them with controls. "
        "Classes J1 to J4 need reading or judgement, and the pipeline gives them to agents.", "",
        "| Class | Anomaly | Rule(s) | How it is injected |", "|---|---|---|---|",
    ]
    out += [f"| {k} | {c.name} | {', '.join(c.clauses)} | {INJECTION[k]} |" for k, c in CLASSES.items()]
    out += [
        "",
        "Each anomalous invoice carries exactly one injected anomaly. Classes have equal counts by design, so "
        "that every class can be measured; this is not the mix a real ledger would have.",
        "",
        "## Hard negatives", "",
        "A hard negative is a clean invoice built to sit next to an anomaly class. A detector that flags it "
        "has learned the surface of the class, not the rule. The false-positive rate on hard negatives is "
        "reported separately from the rate on ordinary clean invoices.", "",
        "| Type | What it is |", "|---|---|",
    ]
    out += [f"| {k} | {text} |" for k, text in HARD_NEGATIVE_TYPES.items()]
    out += [
        "",
        "## The policy-swap ledger", "",
        "`swap_seed_404` holds 150 boundary invoices among clean ones: 50 whose invoice amount differs from the "
        "PO amount by more than 1% and less than 5%, 50 that belong to a same-day group of four or five "
        "invoices, and 50 approved by a Manager for an amount between 100,000 and 150,000. Each violates one "
        "rule under policy v2.5 and none under v2.6, which changes exactly those three parameters. The ledger is "
        "validated under both versions.",
        "",
        "## The evaluation subset", "",
        "A configuration with an LLM makes several model calls per invoice, and most invoices of a ledger are "
        "ordinary. `eval_subset.csv` therefore lists the invoices those configurations audit: every anomalous "
        "invoice, every hard negative, every clean invoice that a duplicate copies, and a random sample of the "
        "other clean invoices. Each row has a weight: 1 for the invoices that are all included, and N/n for the "
        "sampled ones, where N is the number of ordinary clean invoices in the ledger and n the number sampled. "
        "The weights of a subset sum to the number of invoices in the ledger.", "",
        "Metrics are ratios of weighted sums, so a rate computed on the subset estimates the rate on the whole "
        "ledger. Recall and the hard-negative false-positive rate are exact, because their strata are complete; "
        "the false-positive rate on ordinary invoices and the precision carry sampling error, which the "
        "bootstrap intervals include (resampling within strata). The agents always see the whole ledger as "
        "vendor history; only the choice of which invoices to audit is restricted. The controls and the "
        "classical detectors cost nothing per invoice and are evaluated on every invoice.",
        "",
        "## Reproducing and checking", "",
        "```bash", "python -m auditiq_bench                  # regenerate every dataset",
        "python -m auditiq_bench --only large_seed_505",
        "python -m auditiq_bench.overview --verify # compare every file with the hash in its manifest",
        "```", "",
        "A dataset is a function of its seed, the generator version and the policy registry. The same command "
        "writes byte-identical files, and `manifest.json` records the SHA-256 of each.",
        "",
        "## What the data cannot show", "",
        "- **It is synthetic.** Vendors, people, GSTINs and invoices are generated. Amount distributions, "
        "vendor concentration and approval routing are plausible by design, not fitted to a real ledger, so "
        "results on this data are results about the system under controlled conditions, not estimates of its "
        "accuracy on a company's books.",
        "- **Injected anomalies are clean cases.** Each anomalous invoice has one anomaly, built to match the "
        "definition of its class. Real exceptions are messier and overlap.",
        "- **Several columns are constant** (currency, payment terms, payment status, quality check and "
        "others, as the data dictionary states). They are there so that the schema is complete; nothing can be "
        "learned from them.",
        "- **Free text is templated.** Descriptions and receipt remarks are drawn from a fixed vocabulary "
        "with variations, which is easier to read than what people type.",
        "- **J1 can be found without judgement, as generated.** In these ledgers an invoice that is not the "
        "first on its purchase order is always a duplicate (R3 or J1), so a rule on the PO reference finds "
        "every J1 without reading the invoice number, and both classical detectors do (`results/summary.md`). "
        "J1 therefore does not test judgement here. Whether to make it a rule-defined class or to let clean "
        "invoices share a purchase order is an open decision (`PLAN.md`, section 6).",
        "- **The classical detectors and the controls see everything; the LLM configurations see the "
        "evaluation subset.** The weights make the rates comparable; the intervals are wider for the latter.",
        "",
    ]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=PROJECT_ROOT / "data")
    ap.add_argument("--verify", action="store_true", help="check the files against their manifests and exit")
    args = ap.parse_args()
    if args.verify:
        problems = verify(args.data)
        print("\n".join(problems) or f"{len(manifests(args.data))} datasets: every file matches its manifest")
        raise SystemExit(1 if problems else 0)
    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text(render(args.data), encoding="utf-8", newline="\n")
    print(f"wrote {DOC}")


if __name__ == "__main__":
    main()
