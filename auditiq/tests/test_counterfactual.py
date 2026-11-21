"""Counterfactual explanations of control findings (auditiq/counterfactual.py)."""
from __future__ import annotations

import copy
from collections import defaultdict
from datetime import date

import pytest

from auditiq import controls, counterfactual
from auditiq.extraction import extract
from auditiq.policy import load_policy

PARAMETERISED = {"2.1.1", "3.1.2", "4.1.1", "4.2.1", "4.3.1", "5.1.1"}


@pytest.fixture(scope="module")
def flagged(small_dataset) -> dict[str, list[dict]]:
    """The small ledger's transactions by the rule of each control finding."""
    clauses = load_policy("2.5").clauses
    out: dict[str, list[dict]] = defaultdict(list)
    for t in extract(small_dataset):
        for f in controls.run_controls(t, clauses):
            out[f["clause"]].append(t)
    return out


def test_every_finding_of_every_control_has_a_verified_way_to_clear_it(flagged):
    policy = load_policy("2.5")
    assert set(flagged) == {"2.1.1", "2.1.2", "2.1.3", "2.2.1", "3.1.1", "3.1.2", "3.1.3", "4.1.1", "4.2.1", "4.3.1",
                            "4.4.1", "5.1.1"}
    for clause, transactions in flagged.items():
        for txn in transactions[:6]:
            found = {f["clause"]: f for f in counterfactual.explain(txn, policy, lambda c: flagged[c])}
            entry = found[clause]
            assert entry["record"], (clause, txn["invoice"]["invoice_id"])
            for option in entry["record"] + entry["policy"]:
                assert option["clears"] is True
                # an option is checked by running the controls again: applying it must clear the finding
            if clause in PARAMETERISED:
                assert entry["policy"] and all(o["also_clears"] is not None for o in entry["policy"])
            assert entry["no_parameter"] == (clause in counterfactual.RULES_WITHOUT_PARAMETER)


def test_the_approval_limit_states_its_margin_and_the_role_that_covers_the_amount(flagged):
    policy = load_policy("2.5")
    limits = policy.clauses["5.1.1"]["params"]["approval_limits"]
    for txn in flagged["5.1.1"][:5]:
        entry = next(f for f in counterfactual.explain(txn, policy) if f["clause"] == "5.1.1")
        role = controls.approving_entry(txn)["approver_role"]
        amount = float(txn["invoice"]["amount"])
        assert entry["margin"]["value"] == pytest.approx(amount - limits[role], abs=0.01)
        needed = min((v, r) for r, v in limits.items() if v >= amount)[1]
        assert entry["record"][0]["edit"] == {"approval.approver_role": needed}
        policy_option = entry["policy"][0]
        assert policy_option["parameter"] == f"5.1.1.approval_limits.{role}" and policy_option["to"] >= amount
        assert policy_option["also_clears"] is None                 # no ledger given: no count


def test_a_policy_change_counts_the_other_findings_it_would_clear(flagged):
    policy = load_policy("2.5")

    def weekday(t: dict) -> str:
        return controls.DAY_NAMES[date.fromisoformat(str(t["invoice"]["date"])[:10]).weekday()]

    txn = flagged["4.2.1"][0]
    entry = next(f for f in counterfactual.explain(txn, policy, lambda c: flagged[c]) if f["clause"] == "4.2.1")
    same_day = [t for t in flagged["4.2.1"]
                if t["invoice"]["invoice_id"] != txn["invoice"]["invoice_id"] and weekday(t) == weekday(txn)]
    option = entry["policy"][0]
    assert option["also_clears"] == len(same_day) and weekday(txn) not in option["to"]


def test_an_explanation_changes_nothing_in_the_transaction(flagged):
    policy = load_policy("2.5")
    for clause in ("2.1.1", "2.1.2", "2.1.3", "4.1.1", "5.1.1"):
        txn = flagged[clause][0]
        before = copy.deepcopy({k: v for k, v in txn.items() if k != "vendor_history"})
        counterfactual.explain(txn, policy, lambda c: flagged[c])
        assert {k: v for k, v in txn.items() if k != "vendor_history"} == before


def test_a_change_that_hides_the_duplicate_says_so_and_a_clean_invoice_has_nothing_to_explain(flagged, small_dataset):
    policy = load_policy("2.5")
    entry = next(f for f in counterfactual.explain(flagged["2.2.1"][0], policy) if f["clause"] == "2.2.1")
    assert "2.2.2" in entry["record"][0]["caution"]
    clean = next(t for t in extract(small_dataset) if not controls.run_controls(t, policy.clauses))
    assert counterfactual.explain(clean, policy) == []
