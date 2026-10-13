"""Tests of the path from a policy document to executed controls.

A policy PDF is read, its thresholds are taken from the wording of its rules,
and the controls then apply those thresholds. No model is involved.
"""
from __future__ import annotations

import json

import pytest

from auditiq import db, policy_extract, service
from auditiq.cli import main as cli_main
from auditiq.graph import PRESETS
from auditiq.policy import business_days, derive_policy, load_policy, load_template, render_policy_text
from auditiq.policy_pdf import write_pdf
from evaluation import policy_change

BASE = load_policy("2.5").registry
EVERYTHING = {
    "2.1.1": {"amount_tolerance_pct": 2.5},
    "3.1.1": {"gstin_length": 14},
    "3.1.2": {"state_code_min": 2, "state_code_max": 35},
    "4.1.1": {"max_invoices_per_vendor_per_day": 6},
    "4.1.2": {"guide_window_days": 10, "guide_band_pct": 20},
    "4.2.1": {"non_business_days": ["Friday", "Saturday"]},
    "4.3.1": {"round_amount_multiple": 25000},
    "4.4.1": {"blocked_gstin_statuses": ["Suspended", "Cancelled", "Inactive"]},
    "5.1.1": {"approval_limits": {"Manager": 75000, "Senior Manager": 400000, "Director": 3000000, "CFO": 12500000}},
}


def document(tmp_path, version: str, overrides: dict, edit=lambda text: text):
    registry = derive_policy(BASE, version, "2026-04-01", overrides)
    text = edit(render_policy_text(registry, load_template()))
    return registry, write_pdf(text, tmp_path / f"policy_v{version}.pdf", f"Company policy, version {version}",
                               f"Company policy | version {version}")


def test_business_days_are_stated_from_the_non_business_days():
    assert business_days(["Saturday", "Sunday"]) == "Monday to Friday"
    assert business_days(["Sunday"]) == "Monday to Saturday"
    assert business_days(["Friday", "Saturday"]) == "Monday, Tuesday, Wednesday, Thursday and Sunday"
    assert "Business days are Monday to Friday." in load_policy("2.5").text      # the released text is unchanged


def test_the_thresholds_of_the_sample_documents_are_read_from_their_wording(pdfs):
    for pdf, version in zip(pdfs[:2], ("2.5", "2.6")):
        read = policy_extract.build(pdf, BASE)
        assert read.usable and read.version == version and read.pages == 3
        assert read.registry["clauses"] == load_policy(version).registry["clauses"]
    assert [(c["clause"], c["parameter"]) for c in read.changes] == [
        ("2.1.1", "amount_tolerance_pct"), ("4.1.1", "max_invoices_per_vendor_per_day"), ("5.1.1", "approval_limits")]
    assert not policy_extract.build(pdfs[0], BASE).changes


def test_a_document_that_changes_every_parameter_is_read_completely(tmp_path):
    intended, pdf = document(tmp_path, "4.0", EVERYTHING)
    read = policy_extract.build(pdf, BASE)
    assert read.problems == [] and read.registry["clauses"] == intended["clauses"]
    assert policy_change.matching_parameters(read.registry, intended) == policy_change.count_parameters(intended) == 14
    assert len(read.changes) == 11                                   # the four limits count as one parameter here
    assert read.registry["effective_date"] == "2026-04-01" and read.registry["policy_name"] == "Company policy"
    # The text kept for the agents states the rules in the document's own words, and the limits as a table.
    assert "- **Rule 2.1.1 (HIGH), amount match.** The invoice amount must equal the PO amount. A difference of up to " \
           "2.5% of the PO amount is tolerated." in read.text
    assert "| Manager | 75,000 |" in read.text and "| CFO | 12,500,000 |" in read.text


@pytest.mark.parametrize("edit, reason", [
    (lambda t: t.replace("A difference of up to 1% of the PO amount is tolerated.", "Small differences are tolerated."),
     "Rule 2.1.1: the value of amount_tolerance_pct was not found"),
    (lambda t: "\n".join(line for line in t.splitlines() if "Rule 4.3.1" not in line),
     "Rule 4.3.1 (round amount) is not in the document"),
    (lambda t: t.replace("### 4.4 Vendor Status", "- **Rule 4.3.2 (LOW), odd amount.** An odd amount is an exception."
                                                  "\n\n### 4.4 Vendor Status"),
     "Rule 4.3.2 is in the document, and the system has no control or agent for it"),
    (lambda t: t.replace("dated on a Saturday or Sunday", "dated on a Caturday or Sunday"),
     "Rule 4.2.1: 'Caturday' is not a day of the week"),
    (lambda t: t.replace("| Manager | 100,000 |\n| Senior Manager | 500,000 |\n| Director | 2,500,000 |\n"
                         "| CFO | 10,000,000 |", "Limits are set by the finance committee."),
     "Rule 5.1.1: no table of approval limits by role was found"),
    (lambda t: t.replace("**Version:** 4.1", "**Edition:** fourth"), "the document states no version"),
])
def test_a_document_the_system_cannot_execute_is_refused_with_the_reason(tmp_path, edit, reason):
    _, pdf = document(tmp_path, "4.1", {}, edit)
    read = policy_extract.build(pdf, BASE)
    assert not read.usable and any(reason in problem for problem in read.problems), read.problems


def test_adopting_a_document_changes_what_the_controls_decide(lib, tmp_path, capsys):
    # An invoice a Manager approved for an amount between 50,000 and 100,000, clean under version 2.5.
    invoice_id = lib.scalar(
        "SELECT i.invoice_id FROM invoices i JOIN approval_logs a ON a.transaction_id = i.invoice_id "
        "JOIN benchmark_labels l ON l.invoice_id = i.invoice_id WHERE a.action_taken = 'Approved' "
        "AND a.approver_role = 'Manager' AND i.amount > 60000 AND i.amount < 90000 AND l.label = 'clean' "
        "ORDER BY i.invoice_id")
    assert invoice_id

    def cited() -> list[str]:
        service.audit_invoices(lib, PRESETS["C1"], db.read_policy(lib), None, [invoice_id])
        pack = json.loads(db.latest_result(lib, invoice_id)["audit_pack"])
        return [(f["clause"], f.get("citation", {}).get("document")) for f in pack["flags"]]

    assert cited() == []
    _, pdf = document(tmp_path, "4.2", {"5.1.1": {"approval_limits": {"Manager": 50000}}})
    report = policy_extract.adopt(lib, pdf, activate=True)
    assert report["adopted"] and report["active"] and report["unverified"] == [] and report["rules"] == 16
    assert [(c["clause"], c["parameter"]) for c in report["changes"]] == [("5.1.1", "approval_limits")]
    assert db.read_policy(lib).version == "4.2"
    assert lib.scalar("SELECT param_value FROM policy_parameters WHERE version = '4.2' AND clause_id = '5.1.1'") == \
        json.dumps({"Manager": 50000, "Senior Manager": 500000, "Director": 2500000, "CFO": 10000000})
    # The same invoice is now an exception, and the finding cites the adopted document.
    assert cited() == [("5.1.1", "policy_v4.2.pdf")]

    # A document that states an existing version with other thresholds does not silently replace it.
    _, clash = document(tmp_path / "other", "4.2", {"2.1.1": {"amount_tolerance_pct": 3.0}})
    refused = policy_extract.adopt(lib, clash)
    assert not refused["adopted"] and "already stored with other parameters" in refused["problems"][-1]
    assert policy_extract.adopt(lib, clash, replace=True)["adopted"]


def test_the_adopt_command_reports_the_changes_and_refuses_an_unreadable_document(sqlite_library, tmp_path, capsys):
    _, pdf = document(tmp_path, "4.3", {"2.1.1": {"amount_tolerance_pct": 0.5}})
    assert cli_main(["--db", sqlite_library, "policy", "adopt", str(pdf), "--activate"]) == 0
    out = capsys.readouterr().out
    assert "Rule 2.1.1 amount_tolerance_pct: 1.0 -> 0.5" in out and "adopted as policy version 4.3 (16 rules)" in out
    _, bad = document(tmp_path, "4.4", {}, lambda t: t.replace("at most 3 invoices dated", "few invoices dated"))
    assert cli_main(["--db", sqlite_library, "policy", "adopt", str(bad)]) == 1
    assert "max_invoices_per_vendor_per_day was not found" in capsys.readouterr().err
    conn = db.connect(sqlite_library)
    assert conn.scalar("SELECT COUNT(*) FROM company_policies WHERE version = '4.4'") == 0
    conn.close()


def test_a_frozen_system_is_scored_against_the_policy_in_force():
    strict = derive_policy(BASE, "9.9", "2026-04-01", {"5.1.1": {"approval_limits": {"Manager": 50000}}})
    truth = {"A": {"5.1.1"}, "B": set(), "C": {"4.3.1"}}
    frozen = {"A": set(), "B": {"2.1.1"}, "C": {"4.3.1"}}
    assert policy_change.compare(frozen, truth, strict) == {
        "invoices": 3, "exact": 1, "stale_findings": 1, "missed_exceptions": 1,
        "needless_escalations": 1, "missed_escalations": 1}
    assert policy_change.route_of({"4.3.1"}, strict) == "approve" and policy_change.route_of({"5.1.1"}, strict) == "escalate"
    versions = [v[0] for v in policy_change.VARIANTS]
    assert len(set(versions)) == len(versions) == 14
