"""Generate the AuditIQ-Bench datasets.

    python -m auditiq_bench                         every dataset below
    python -m auditiq_bench --only bench_seed_101   one of them
    python -m auditiq_bench --list

    bench_seed_101, _202, _303   benchmark ledgers: 5,000 invoices, 250 vendors
    pilot_seed_909               same composition; the only ledger prompts may be tuned on
    swap_seed_404                policy-swap ledger: 150 boundary invoices among 4,850 clean ones
    large_seed_505               a ledger at a realistic anomaly rate: 20,000 invoices, 1,000 vendors

Output, per dataset, under data/<name>/:
    vendor_master.csv, purchase_orders.csv, goods_receipts.csv, invoices.csv,
    approval_logs.csv   the ledger; column names as in the database
    labels.csv          ground truth, written at injection
    eval_subset.csv     the invoices the LLM configurations audit, with weights
    manifest.json       seed, versions, counts, file hashes
    README.md           datasheet, written from the generated tables
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from . import GENERATOR_VERSION
from .datasheet import datasheet, evaluation_subset
from .export import to_tables
from .generator import Builder
from .taxonomy import CLASSES, HARD_NEGATIVE_TYPES, PER_CLASS, PER_HARD_NEGATIVE_TYPE
from .validate import validate

PROJECT_ROOT = Path(__file__).resolve().parents[1]
START, END = date(2025, 4, 1), date(2026, 3, 31)   # financial year 2025-26
POLICY_DIR = PROJECT_ROOT / "policy"
TABLES = ["vendor_master", "purchase_orders", "goods_receipts", "invoices", "approval_logs", "labels", "eval_subset"]


@dataclass(frozen=True)
class Profile:
    name: str
    kind: str                      # benchmark, pilot, policy_swap, large
    seed: int
    n_invoices: int
    n_vendors: int
    purpose: str
    per_class: int = PER_CLASS
    per_hard_negative: int = PER_HARD_NEGATIVE_TYPE
    eval_ordinary: int = 600       # ordinary clean invoices sampled into the evaluation subset
    approver_counts: tuple[int, ...] = (16, 10, 6, 2)


BENCHMARK = ("A benchmark ledger of AuditIQ-Bench. It holds the 420 anomalous invoices (30 of each of the fourteen "
             "classes) and the 120 hard negatives of the evaluation protocol inside a ledger of 5,000 invoices from "
             "250 vendors. Results in the paper are reported on the three benchmark ledgers (seeds 101, 202, 303).")
PROFILES = [
    Profile("bench_seed_101", "benchmark", 101, 5000, 250, BENCHMARK),
    Profile("bench_seed_202", "benchmark", 202, 5000, 250, BENCHMARK),
    Profile("bench_seed_303", "benchmark", 303, 5000, 250, BENCHMARK),
    Profile("pilot_seed_909", "pilot", 909, 5000, 250,
            "The pilot ledger: same composition as a benchmark ledger, different seed. Prompts and settings are "
            "tried and fixed on this ledger only, so that nothing is tuned on the ledgers results are reported on."),
    Profile("swap_seed_404", "policy_swap", 404, 5000, 250,
            "The policy-swap ledger. 150 boundary invoices violate one rule under policy v2.5 and none under v2.6, "
            "which differs in the amount tolerance, the daily invoice count and the Manager approval limit; the "
            "other 4,850 invoices are clean under both. It tests that a change of policy changes the outcome with "
            "no change to the pipeline.", eval_ordinary=150),
    Profile("large_seed_505", "large", 505, 20000, 1000,
            "A ledger at a realistic anomaly rate: the 420 anomalous invoices of a benchmark ledger among 20,000 "
            "invoices from 1,000 vendors (2.1% anomalous), with twice the hard negatives. It is the ledger the "
            "application is demonstrated on, and the one on which precision at a realistic rate is measured.",
            per_hard_negative=2 * PER_HARD_NEGATIVE_TYPE, eval_ordinary=480, approver_counts=(40, 25, 12, 2)),
]


def load_policy(version: str) -> dict:
    return json.loads((POLICY_DIR / f"policy_v{version}.json").read_text(encoding="utf-8"))


def write_dataset(out: Path, tables: dict[str, pd.DataFrame], manifest: dict, readme: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    files = {}
    for name in TABLES:
        path = out / f"{name}.csv"
        tables[name].to_csv(path, index=False, lineterminator="\n", float_format="%.2f", encoding="utf-8")
        files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest["sha256"] = files
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (out / "README.md").write_text(readme, encoding="utf-8", newline="\n")


def check_subset(tables: dict[str, pd.DataFrame]) -> list[str]:
    labels, subset = tables["labels"], tables["eval_subset"]
    problems = []
    must = set(labels.loc[labels["label"] != "clean", "invoice_id"]) | (set(labels["related_invoice_id"]) - {""})
    if not must <= set(subset["invoice_id"]):
        problems.append("the evaluation subset misses an anomalous invoice, a hard negative or a duplicate's original")
    if abs(subset["weight"].sum() - len(labels)) > 1e-6:
        problems.append("the weights of the evaluation subset do not sum to the number of invoices")
    if subset["invoice_id"].duplicated().any():
        problems.append("the evaluation subset lists an invoice twice")
    return problems


def generate(profile: Profile, out_root: Path, policy_version: str = "2.5", alt_version: str = "2.6") -> dict:
    """Generate, validate and write one dataset; returns its manifest."""
    policy = load_policy(policy_version)
    n_blocked = max(4, profile.n_vendors // 30)
    manifest = {"dataset": profile.name, "kind": profile.kind, "seed": profile.seed,
                "generator_version": GENERATOR_VERSION, "policy_version": policy["version"],
                "period": [START.isoformat(), END.isoformat()]}

    if profile.kind == "policy_swap":
        other = load_policy(alt_version)
        limits = tuple(other["clauses"]["5.1.1"]["params"]["approval_limits"].values())
        builder = Builder(profile.seed, policy, START, END, extra_band_limits=limits, n_vendors=profile.n_vendors,
                          n_blocked_vendors=n_blocked, approver_counts=profile.approver_counts)
        per_kind = 50
        builder.build_boundary(other, per_kind, n_ordinary=profile.n_invoices - 3 * per_kind)
        tables = to_tables(builder)
        problems = validate(tables, policy)
        # Under the other version the whole ledger must be clean.
        alt = {t: df.copy() for t, df in tables.items()}
        alt["labels"][["label", "class_id", "clause_ids", "severity"]] = ["clean", "", "", ""]
        problems += [f"under v{other['version']}: {p}" for p in validate(alt, other)]
        labels = tables["labels"]
        if len(labels) != profile.n_invoices or int((labels["label"] == "anomalous").sum()) != 3 * per_kind:
            problems.append("wrong number of invoices or of boundary invoices")
        boundary = labels["label"] == "anomalous"
        labels.insert(5, "alt_policy_version", other["version"])
        labels.insert(6, "alt_label", "clean")
        labels.insert(7, "alt_clause_ids", "")
        assert boundary.sum() == 3 * per_kind
        manifest["alt_policy_version"] = other["version"]
    else:
        builder = Builder(profile.seed, policy, START, END, n_vendors=profile.n_vendors,
                          n_blocked_vendors=n_blocked, approver_counts=profile.approver_counts)
        n_ordinary = (profile.n_invoices - profile.per_class * len(CLASSES)
                      - profile.per_hard_negative * len(HARD_NEGATIVE_TYPES))
        builder.build_main(profile.per_class, profile.per_hard_negative, n_ordinary)
        tables = to_tables(builder)
        expected = {
            "classes": list(CLASSES), "hard_negatives": list(HARD_NEGATIVE_TYPES),
            "values": {"invoices": profile.n_invoices, "vendors": profile.n_vendors, "clean": n_ordinary,
                       **{f"class:{c}": profile.per_class for c in CLASSES},
                       **{f"hn:{h}": profile.per_hard_negative for h in HARD_NEGATIVE_TYPES}},
        }
        problems = validate(tables, policy, expected)

    labels = tables["labels"]
    tables["eval_subset"] = evaluation_subset(labels, profile.eval_ordinary, builder.rng)
    problems += check_subset(tables)
    if problems:
        print(f"{profile.name}: {len(problems)} validation problem(s)")
        for line in problems[:40]:
            print("   ", line)
        raise SystemExit(1)

    manifest["counts"] = {
        "invoices": len(labels),
        "anomalous": int((labels["label"] == "anomalous").sum()),
        "hard_negative": int((labels["label"] == "hard_negative").sum()),
        "clean": int((labels["label"] == "clean").sum()),
        "purchase_orders": len(tables["purchase_orders"]),
        "goods_receipts": len(tables["goods_receipts"]),
        "approval_logs": len(tables["approval_logs"]),
        "vendors": len(tables["vendor_master"]),
        "ledger_records": sum(len(tables[t]) for t in TABLES[:5]),
        "eval_subset": len(tables["eval_subset"]),
    }
    write_dataset(out_root / profile.name, tables, manifest,
                  datasheet(profile.name, profile.purpose, manifest, tables, policy))
    print(f"{profile.name}: {manifest['counts']['invoices']:,} invoices, {manifest['counts']['ledger_records']:,} "
          f"records in the ledger, evaluation subset {manifest['counts']['eval_subset']:,}; validation passed")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="+", metavar="NAME", help="generate only these datasets")
    ap.add_argument("--list", action="store_true", help="list the datasets and exit")
    ap.add_argument("--out", type=Path, default=PROJECT_ROOT / "data")
    args = ap.parse_args()

    if args.list:
        for p in PROFILES:
            print(f"{p.name:16s} {p.kind:12s} {p.n_invoices:6,} invoices  {p.n_vendors:5,} vendors  seed {p.seed}")
        return
    names = {p.name for p in PROFILES}
    unknown = set(args.only or []) - names
    if unknown:
        raise SystemExit(f"unknown dataset(s): {sorted(unknown)}; use --list")
    for profile in PROFILES:
        if not args.only or profile.name in args.only:
            generate(profile, args.out)


if __name__ == "__main__":
    main()
