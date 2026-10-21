"""The steps of evaluation.huge, run on the small test ledger instead of the 500,000-invoice one.

The huge ledger itself takes hours; these tests check that every step runs, writes what the report reads,
and that the generate step refuses a ledger whose files differ from the committed hashes.
"""
from __future__ import annotations

import json
import shutil

import pytest

from auditiq_bench.__main__ import HUGE, ON_REQUEST, PROFILES
from evaluation import huge


def test_the_huge_profile_is_generated_only_on_request_and_its_counts_fit_the_generator():
    assert HUGE in ON_REQUEST and HUGE not in PROFILES
    assert HUGE.n_invoices == 500_000 and HUGE.per_class % 3 == 0 and HUGE.per_hard_negative % 24 == 0
    anomalous = 14 * HUGE.per_class
    assert round(anomalous / HUGE.n_invoices, 3) == 0.020     # the anomaly rate of the large ledger


def test_every_step_runs_on_a_ledger_and_the_report_reads_them(small_dataset, tmp_path):
    work, results = tmp_path / "work", tmp_path / "results"
    common = ["--dataset", str(small_dataset), "--work", str(work), "--results", str(results), "--resamples", "5",
              "--reference", str(small_dataset), "--repeats", "2"]
    for step in huge.STEPS:
        assert huge.main(["--step", step, *common]) == 0, step

    out = results / huge.NAME
    assert json.loads((out / "generate.json").read_text(encoding="utf-8"))["status"] == "hashes recorded"
    policy = json.loads((out / "policy_change.json").read_text(encoding="utf-8"))
    assert policy["reference_check"]["exact"] == policy["invoices"] == 1200 and len(policy["variants"]) == 14
    assert all(v["driven"]["exact"] == 1200 for v in policy["variants"])     # the policy-driven controls never err
    app = json.loads((out / "application.json").read_text(encoding="utf-8"))
    assert app["before"]["invoices"] == app["after"]["invoices"] == 1200 and app["adopted_version"] == "3.12"
    size = json.loads((out / "size.json").read_text(encoding="utf-8"))
    assert size["invoices"] == size["reference"]["invoices"] == 1200 and size["findings"] == size["reference"]["findings"]
    assert size["repeats"] == 2 and size["ratio"] > 0
    report = (out / "huge.md").read_text(encoding="utf-8")
    assert "timed in turn with it" in report and "per earlier invoice" in report
    assert sum(b["invoices"] for b in size["history"]["bins"]) == 1200 and size["history"]["us_per_history_record"] > 0
    for heading in ("## Data", "## Detection on every invoice", "## Policy change", "## The deployed path",
                    "## The control stage over the whole ledger"):
        assert heading in report

    # A second generate step compares with the hashes recorded the first time.
    assert huge.main(["--step", "generate", *common]) == 0
    assert json.loads((out / "generate.json").read_text(encoding="utf-8"))["status"] == "identical to the committed hashes"


def test_a_ledger_whose_files_differ_from_the_committed_hashes_is_refused(small_dataset, tmp_path):
    copy = tmp_path / "ledger"
    shutil.copytree(small_dataset, copy)
    results = tmp_path / "results"
    common = ["--dataset", str(copy), "--work", str(tmp_path / "work"), "--results", str(results)]
    assert huge.main(["--step", "generate", *common]) == 0                   # records the hashes
    manifest = json.loads((copy / "manifest.json").read_text(encoding="utf-8"))
    recorded = json.loads((results / huge.NAME / "manifest.json").read_text(encoding="utf-8"))
    recorded["sha256"]["invoices.csv"] = "0" * 64
    (results / huge.NAME / "manifest.json").write_text(json.dumps(recorded), encoding="utf-8")
    with pytest.raises(SystemExit, match="differ from"):
        huge.main(["--step", "generate", *common])
    assert manifest["counts"]["invoices"] == 1200


def test_the_generator_refuses_more_vendors_than_it_has_invoice_number_prefixes():
    from datetime import date

    from auditiq_bench.__main__ import load_policy
    from auditiq_bench.generator import Builder

    assert HUGE.n_vendors <= 17_000
    with pytest.raises(ValueError, match="three-letter prefix"):
        Builder(1, load_policy("2.5"), date(2025, 4, 1), date(2026, 3, 31), n_vendors=17_001)
