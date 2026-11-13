"""The demonstration policies: each is read correctly from its PDF, changes the audit in the intended direction, and an
incomplete draft is refused.

    python -m pytest tests/test_policy_demo.py
"""
from __future__ import annotations

from pathlib import Path

import pytest

from auditiq import policy_demo, policy_extract
from auditiq.extraction import extract
from auditiq.policy import PROJECT_ROOT, load_policy
from evaluation.policy_change import count_parameters, matching_parameters
from evaluation.policy_demo import audit, compare, showcase, summarise

LEDGER = PROJECT_ROOT / "data" / "bench_seed_101"


@pytest.fixture(scope="module")
def base() -> dict:
    return load_policy(policy_demo.BASELINE).registry


@pytest.fixture(scope="module")
def pdfs(tmp_path_factory) -> dict[str, Path]:
    return {p.name: p for p in policy_demo.write_all(tmp_path_factory.mktemp("demo"))}


def test_versions_are_distinct_and_all_take_effect_with_the_baseline(base):
    versions = [s.version for s in policy_demo.SCENARIOS]
    assert len(set(versions)) == len(versions) and not set(versions) & {"2.5", "2.6"}
    assert all(policy_demo.registry_of(s, base)["effective_date"] == base["effective_date"] for s in policy_demo.SCENARIOS)


@pytest.mark.parametrize("scenario", policy_demo.SCENARIOS, ids=lambda s: s.file)
def test_a_document_is_read_exactly_as_it_is_stated(scenario, pdfs, base):
    read = policy_extract.build(pdfs[policy_demo.pdf_name(scenario)], base)
    intended = policy_demo.registry_of(scenario, base)
    assert read.usable and read.version == scenario.version
    assert matching_parameters(read.registry, intended) == count_parameters(intended)
    assert {k: v["severity"] for k, v in read.registry["clauses"].items()} == \
           {k: v["severity"] for k, v in intended["clauses"].items()}
    assert read.changes                                    # a demonstration policy that changes nothing shows nothing
    assert read.registry["policy_name"].endswith(scenario.name)


def test_the_documents_are_byte_identical_when_written_again(pdfs, tmp_path):
    again = {p.name: p for p in policy_demo.write_all(tmp_path)}
    assert {n: p.read_bytes() for n, p in again.items()} == {n: p.read_bytes() for n, p in pdfs.items()}


def test_an_incomplete_draft_is_refused_and_says_why(pdfs, base):
    draft = policy_extract.build(pdfs["Draft_Incomplete_v5.99.pdf"], base)
    assert not draft.usable
    assert any("Rule 4.4.1" in p for p in draft.problems) and any("approval limits" in p for p in draft.problems)


@pytest.fixture(scope="module")
def audited(pdfs, base) -> dict[str, dict]:
    if not (LEDGER / "invoices.csv").exists():
        pytest.skip("the benchmark ledgers have not been generated here")
    transactions = extract(LEDGER)
    out = {"base": audit(transactions, base["clauses"])}
    for scenario in policy_demo.SCENARIOS:
        read = policy_extract.build(pdfs[policy_demo.pdf_name(scenario)], base)
        out[scenario.file] = audit(transactions, read.registry["clauses"])
    out["amounts"] = {t["invoice"]["invoice_id"]: float(t["invoice"]["amount"] or 0) for t in transactions}
    return out


def held(rows: dict) -> int:
    return sum(r["route"] == "escalate" for r in rows.values())


def test_relaxed_policies_hold_fewer_invoices_and_strict_ones_more(audited):
    base = held(audited["base"])
    assert held(audited["Lean_Growth"]) < base < held(audited["Strict_Controls"])
    assert held(audited["Manufacturing_Plant"]) < base


def test_severity_only_policies_find_what_the_baseline_finds_and_rank_it_differently(audited):
    for name in ("Tax_Compliance_First", "Fraud_Prevention"):
        c = compare(audited["base"], audited[name])
        assert c["decisions_moved"] == 0                       # the same rules fire on the same invoices
        assert c["score_higher"] > 0                           # but the scores are not the baseline's


def test_the_same_invoice_gets_different_verdicts_under_different_policies(audited):
    keys = ["base", *[s.file for s in policy_demo.SCENARIOS]]
    top = showcase({k: audited[k] for k in keys}, audited["amounts"], count=1)[0]
    scores = {round(o["score"]) for o in top["outcomes"].values()}
    assert len(scores) >= 3


def test_summary_counts_are_consistent(audited):
    s = summarise(audited["base"], audited["amounts"])
    assert s["escalated"] + s["approved"] == s["invoices"] and sum(s["levels"].values()) == s["invoices"]
