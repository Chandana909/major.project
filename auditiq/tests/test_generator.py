"""Tests of the benchmark generator and its validator.

    python -m pytest tests/test_generator.py
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from auditiq_bench.export import rekey_variants, to_tables
from auditiq_bench.generator import Builder
from auditiq_bench.taxonomy import CLASSES, HARD_NEGATIVE_TYPES, N_INVOICES
from auditiq_bench.validate import rule_clauses, validate

ROOT = Path(__file__).resolve().parents[1]

START, END = date(2025, 4, 1), date(2026, 3, 31)


def policy(version: str) -> dict:
    return json.loads((ROOT / "policy" / f"policy_v{version}.json").read_text(encoding="utf-8"))


def build(seed: int) -> dict[str, pd.DataFrame]:
    b = Builder(seed, policy("2.5"), START, END)
    b.build_main()
    return to_tables(b)


@pytest.fixture(scope="module")
def tables() -> dict[str, pd.DataFrame]:
    return build(7)


def copy(tables):
    return {k: v.copy() for k, v in tables.items()}


def first(tables, **where) -> str:
    labels = tables["labels"].fillna("")
    for column, value in where.items():
        labels = labels[labels[column] == value]
    return labels["invoice_id"].iloc[0]


def test_composition(tables):
    labels = tables["labels"]
    assert len(labels) == N_INVOICES
    assert labels["label"].value_counts().to_dict() == {"clean": 660, "anomalous": 420, "hard_negative": 120}
    assert all((labels["class_id"] == c).sum() == 30 for c in CLASSES)
    assert all((labels["hard_negative_type"] == h).sum() == 24 for h in HARD_NEGATIVE_TYPES)


def test_validator_accepts_generated_data(tables):
    assert validate(tables, policy("2.5")) == []


def test_same_seed_gives_identical_tables(tables):
    again = build(7)
    for name, frame in tables.items():
        pd.testing.assert_frame_equal(frame, again[name])


def test_different_seed_gives_different_data(tables):
    assert not tables["invoices"]["amount"].equals(build(8)["invoices"]["amount"])


def test_identifiers_do_not_reveal_the_label(tables):
    labels = tables["labels"].copy()
    labels["seq"] = labels["invoice_id"].str[3:].astype(int)
    means = labels.groupby("label")["seq"].mean()
    assert means.max() - means.min() < 80      # of 1,200; ordered by date, not by class


# ---- the validator must notice a wrong label or a wrong record ---------------

def test_validator_rejects_clean_invoice_labelled_anomalous(tables):
    t = copy(tables)
    target = first(t, label="clean")
    row = t["labels"]["invoice_id"] == target
    t["labels"].loc[row, ["label", "class_id", "clause_ids"]] = ["anomalous", "R1", "2.1.1"]
    assert any(target in p for p in validate(t, policy("2.5")))


def test_validator_rejects_anomalous_invoice_labelled_clean(tables):
    t = copy(tables)
    target = first(t, class_id="R7")
    row = t["labels"]["invoice_id"] == target
    t["labels"].loc[row, ["label", "class_id", "clause_ids", "severity"]] = ["clean", "", "", ""]
    assert any(target in p for p in validate(t, policy("2.5")))


def test_validator_rejects_unlabelled_amount_change(tables):
    t = copy(tables)
    target = first(t, label="clean")
    row = t["invoices"]["invoice_id"] == target
    t["invoices"].loc[row, "amount"] = (t["invoices"].loc[row, "amount"] * 1.5).round(2)
    assert any(target in p for p in validate(t, policy("2.5")))


def test_validator_rejects_benign_remark_on_j4(tables):
    t = copy(tables)
    target = first(t, class_id="J4")
    grn_id = t["invoices"].set_index("invoice_id").at[target, "grn_id"]
    t["goods_receipts"].loc[t["goods_receipts"]["grn_id"] == grn_id, "notes"] = "Received in good condition."
    assert any(grn_id in p for p in validate(t, policy("2.5")))


def test_validator_rejects_unlabelled_description_change(tables):
    t = copy(tables)
    inv = t["invoices"].set_index("invoice_id")
    po = t["purchase_orders"].set_index("po_id")
    clean = t["labels"].loc[t["labels"]["label"] == "clean", "invoice_id"]
    # A clean invoice whose PO is not for audit fees.
    target = next(i for i in clean if "audit" not in po.at[inv.at[i, "po_id"], "description"].lower())
    t["invoices"].loc[t["invoices"]["invoice_id"] == target, "description"] = "Statutory audit fees"
    assert any(target in p for p in validate(t, policy("2.5")))


def test_validator_rejects_unlabelled_weekend_date(tables):
    t = copy(tables)
    target = first(t, label="hard_negative", hard_negative_type="HN_TOLERANCE")
    t["invoices"].loc[t["invoices"]["invoice_id"] == target, "date"] = "2025-06-07"   # a Saturday
    assert any(target in p for p in validate(t, policy("2.5")))


# ---- class-specific structure -------------------------------------------------

def test_hard_negatives_and_clean_invoices_violate_no_rule_clause(tables):
    found = rule_clauses(tables, policy("2.5"))
    labels = tables["labels"].set_index("invoice_id")
    assert all(not found[i] for i in labels.index[labels["label"] != "anomalous"])


def test_judgement_classes_violate_no_rule_clause(tables):
    found = rule_clauses(tables, policy("2.5"))
    labels = tables["labels"].set_index("invoice_id")
    assert all(not found[i] for i in labels.index[labels["class_id"].isin(["J1", "J2", "J3", "J4"])])


def test_near_duplicate_numbers_differ_from_every_number_of_the_vendor(tables):
    inv = tables["invoices"].set_index("invoice_id")
    labels = tables["labels"].set_index("invoice_id")
    for invoice_id in labels.index[labels["class_id"] == "J1"]:
        row = inv.loc[invoice_id]
        same_vendor = inv[(inv["vendor_id"] == row["vendor_id"]) & (inv.index != invoice_id)]
        assert row["invoice_number"] not in set(same_vendor["invoice_number"])
        original = inv.loc[labels.at[invoice_id, "related_invoice_id"]]
        assert row["invoice_number"] in rekey_variants(original["invoice_number"])


def test_rekey_variants_never_return_the_number_itself():
    for number in ["ABC/25-26/00123", "ABC-000123", "INV-ABC-0105", "ABC00777", "ABC/INV/0042"]:
        variants = rekey_variants(number)
        assert variants and number not in variants


def test_boundary_set_is_anomalous_under_v25_and_clean_under_v26():
    v25, v26 = policy("2.5"), policy("2.6")
    limits = tuple(v26["clauses"]["5.1.1"]["params"]["approval_limits"].values())
    b = Builder(11, v25, START, END, extra_band_limits=limits)
    b.build_boundary(v26, per_kind=50)
    t = to_tables(b)
    assert len(t["labels"]) == 150 and (t["labels"]["label"] == "anomalous").all()
    assert t["labels"]["class_id"].value_counts().to_dict() == {"R1": 50, "R6": 50, "R7": 50}
    assert validate(t, v25) == []
    assert all(not hit for hit in rule_clauses(t, v26).values())


# ---- datasets as written to disk ---------------------------------------------

def test_every_shipped_dataset_is_a_full_size_ledger():
    from auditiq_bench.__main__ import PROFILES
    assert {p.name for p in PROFILES} == {"bench_seed_101", "bench_seed_202", "bench_seed_303", "pilot_seed_909",
                                          "swap_seed_404", "large_seed_505"}
    assert all(p.n_invoices >= 5000 for p in PROFILES)            # at least about 20,000 records in the ledger
    assert len({p.seed for p in PROFILES}) == len(PROFILES)


def test_evaluation_subset_keeps_what_matters_and_its_weights_sum_to_the_ledger(small_dataset):
    labels = pd.read_csv(small_dataset / "labels.csv", dtype=str, keep_default_na=False)
    subset = pd.read_csv(small_dataset / "eval_subset.csv")
    strata = subset.groupby("stratum").agg(n=("weight", "size"), weight=("weight", "first"))
    assert strata.loc["anomalous", "n"] == 420 and strata.loc["hard_negative", "n"] == 120
    assert strata.loc["duplicate_original", "n"] == 60            # the clean invoices that R3 and J1 copy
    assert set(labels.loc[labels["label"] != "clean", "invoice_id"]) <= set(subset["invoice_id"])
    assert set(labels["related_invoice_id"]) - {""} <= set(subset["invoice_id"])
    assert abs(subset["weight"].sum() - len(labels)) < 1e-9
    assert (subset.loc[subset["stratum"] != "ordinary", "weight"] == 1).all()


def test_a_sampled_subset_weights_the_ordinary_invoices():
    import numpy as np

    from auditiq_bench.datasheet import evaluation_subset
    labels = pd.DataFrame({
        "invoice_id": [f"I{n:03d}" for n in range(100)],
        "label": ["anomalous"] * 5 + ["hard_negative"] * 5 + ["clean"] * 90,
        "related_invoice_id": ["I010"] + [""] * 99,              # I010 is the original that I000 copies
    })
    subset = evaluation_subset(labels, 20, np.random.default_rng(1))
    counts = subset["stratum"].value_counts().to_dict()
    assert counts == {"ordinary": 20, "anomalous": 5, "hard_negative": 5, "duplicate_original": 1}
    assert subset.loc[subset["stratum"] == "ordinary", "weight"].iloc[0] == 89 / 20
    assert abs(subset["weight"].sum() - 100) < 1e-9
    assert subset.equals(evaluation_subset(labels, 20, np.random.default_rng(1)))      # reproducible


def test_each_dataset_folder_documents_itself(small_dataset, boundary_dataset):
    text = (small_dataset / "README.md").read_text(encoding="utf-8")
    assert "# Dataset `small_seed_7`" in text and "| J4 | GRN remark contradicts the billed quantity | 2.1.4 | an agent | high | 30 |" in text
    assert "| `invoices.csv` | 1,200 |" in text and "## Evaluation subset" in text
    manifest = __import__("json").loads((small_dataset / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["invoices"] == 1200 and set(manifest["sha256"]) >= {"invoices.csv", "eval_subset.csv"}
    swap = (boundary_dataset / "README.md").read_text(encoding="utf-8")
    assert "clean under policy v2.6" in swap and "| R6 |" in swap and "| J1 |" not in swap
