"""Demonstration policies: the same ledger, audited under different company policies.

    python -m auditiq.policy_demo            write the policy PDFs to policy/demo/

Every organisation states its own limits, tolerances and priorities. These five documents are five organisations'
versions of the procurement SOP, each issued as a PDF that can be uploaded on the Policy page (preview, simulate,
adopt, activate) to show how the audit changes when only the document changes:

    5.01  Lean Growth            a fast-growing company takes the friction out: wide tolerance, high limits, six-day week
    5.02  Strict Controls        a company that was defrauded tightens everything and treats timing and round sums as serious
    5.03  Tax Compliance First   thresholds of the baseline; every GST identity rule is critical (the audit is by the tax office)
    5.04  Manufacturing Plant    six-day week, larger orders, higher limits and a slightly wider tolerance
    5.05  Fraud Prevention       thresholds of the baseline; what a fraud looks like (mismatches, splitting, timing) outranks the rest

Each takes effect on 2025-04-01 like the baseline (version 2.5), so a policy chosen governs the whole financial year,
and the ledgers of the project (financial year 2025-26) can be audited under it from the first invoice.

The documents are rendered from the policy template with the thresholds and the severities of the scenario, the same
way as every other policy of the project, so the text the agents read is exactly what the controls execute. A sixth
document, the incomplete draft, leaves out a rule and the table of approval limits: the system must refuse it and say
why. That is part of the demonstration: an uploaded policy is checked before it governs anything.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .policy import POLICY_DIR, derive_policy, load_policy, load_template, render_policy_text
from .policy_pdf import write_pdf

DEMO_DIR = POLICY_DIR / "demo"
EFFECTIVE = "2025-04-01"
BASELINE = "2.5"
RULE_HEAD = re.compile(r"\*\*Rule (\d+\.\d+\.\d+) \((\w+)\)")


@dataclass(frozen=True)
class Scenario:
    version: str
    file: str                          # the PDF's name without the version
    name: str
    owner: str
    story: str                         # why the organisation changed its policy (printed in the document)
    params: dict = field(default_factory=dict)         # {clause: {parameter: value}}, as policy.derive_policy
    severities: dict = field(default_factory=dict)     # {clause: "critical" | "high" | "medium" | "low"}
    shows: str = ""                    # what the demonstration is meant to show


SCENARIOS = [
    Scenario(
        "5.01", "Lean_Growth", "Lean Growth Edition", "Finance Controller, a fast-growing distributor",
        "The company has tripled its order volume in two years. Approvals were the bottleneck, so the limits are "
        "raised, price differences up to 3% are tolerated and the business works six days a week.",
        {"2.1.1": {"amount_tolerance_pct": 3.0}, "4.1.1": {"max_invoices_per_vendor_per_day": 5},
         "4.2.1": {"non_business_days": ["Sunday"]}, "4.3.1": {"round_amount_multiple": 50000},
         "5.1.1": {"approval_limits": {"Manager": 250000, "Senior Manager": 1000000, "Director": 5000000,
                                       "CFO": 20000000}}},
        {"4.2.1": "low"},
        "Fewer findings and a lighter review queue, and the price: frauds that sit inside the wider limits and "
        "tolerances are no longer found."),
    Scenario(
        "5.02", "Strict_Controls", "Strict Controls Edition", "Chief Financial Officer, after a payment fraud",
        "After a fraud that went through on invoices just under the approval limits, the company lowers every limit by a "
        "tenth, cuts the tolerance to half a percent, allows two invoices per vendor and day, and treats weekend "
        "dates, round sums and malformed tax numbers as serious.",
        {"2.1.1": {"amount_tolerance_pct": 0.5}, "4.1.1": {"max_invoices_per_vendor_per_day": 2},
         "4.3.1": {"round_amount_multiple": 5000},
         "5.1.1": {"approval_limits": {"Manager": 90000, "Senior Manager": 450000, "Director": 2250000,
                                       "CFO": 9000000}}},
        {"4.2.1": "high", "4.3.1": "medium", "3.1.1": "high", "3.1.2": "high"},
        "More findings and about twice as many invoices held for review: the cost of safety is a reviewer's time, "
        "and it includes invoices the baseline would have accepted."),
    Scenario(
        "5.03", "Tax_Compliance_First", "Tax Compliance First Edition", "Head of Indirect Tax, ahead of a GST audit",
        "The tax office is auditing input tax credit. Thresholds are unchanged, but an invoice that carries a wrong, "
        "malformed or foreign GSTIN cannot support a credit claim, so every GST identity rule is critical.",
        {}, {"3.1.1": "critical", "3.1.2": "critical", "3.1.3": "critical", "2.1.1": "critical"},
        "The same invoices are found as under the baseline, but their priority changes: tax-identity findings move to "
        "the top of the queue and the scores of the affected invoices rise."),
    Scenario(
        "5.04", "Manufacturing_Plant", "Manufacturing Plant Edition", "Plant Controller, a six-day manufacturer",
        "The plant runs six days a week and buys in larger lots. Saturday is a business day, orders are bigger, "
        "limits rise by half and a difference of 2% on the PO is tolerated for bulk materials.",
        {"2.1.1": {"amount_tolerance_pct": 2.0}, "4.1.1": {"max_invoices_per_vendor_per_day": 4},
         "4.2.1": {"non_business_days": ["Sunday"]},
         "5.1.1": {"approval_limits": {"Manager": 150000, "Senior Manager": 750000, "Director": 3750000,
                                       "CFO": 15000000}}},
        {},
        "Saturday invoices stop being exceptions and a larger share of the invoices are within authority: a policy "
        "fitted to the business removes noise without a large loss of coverage."),
    Scenario(
        "5.05", "Fraud_Prevention", "Fraud Prevention Edition", "Head of Internal Audit, fraud risk programme",
        "Thresholds are unchanged. Internal Audit re-ranks the rules by how a fraud looks: mismatches between invoice, "
        "order and receipt, and splitting and timing patterns outrank formal errors.",
        {}, {"2.1.1": "critical", "2.1.2": "critical", "2.1.3": "critical", "4.1.1": "critical", "4.2.1": "high",
             "4.3.1": "medium", "3.1.1": "low", "3.1.2": "low"},
        "The same findings with a new order: fraud patterns reach critical, formal errors drop out of review."),
]


def registry_of(scenario: Scenario, base: dict | None = None) -> dict:
    """The clause registry a scenario's document states."""
    base = base or load_policy(BASELINE).registry
    registry = derive_policy(base, scenario.version, EFFECTIVE, scenario.params)
    registry["policy_name"] = f"{base['policy_name']}, {scenario.name}"
    for clause, severity in scenario.severities.items():
        registry["clauses"][clause]["severity"] = severity
    return registry


def render(scenario: Scenario, registry: dict | None = None, template: str | None = None) -> str:
    """The text of a scenario's document: the template with the scenario's thresholds, severities and story."""
    template = template or load_template()
    registry = registry or registry_of(scenario)
    # The template carries the severities of the baseline; the registry is rendered against them and the scenario's
    # severities are written into the rule headings afterwards, so that one registry says everything the text says.
    in_template = dict(RULE_HEAD.findall(template))
    plain = {**registry, "clauses": {k: {**v, "severity": in_template[k].lower()} for k, v in registry["clauses"].items()}}
    text = render_policy_text(plain, template)
    text = RULE_HEAD.sub(lambda m: f"**Rule {m.group(1)} ({registry['clauses'][m.group(1)]['severity'].upper()})", text)
    text = text.replace("# Standard Operating Procedure (SOP): Procurement & Vendor Auditing",
                        f"# Standard Operating Procedure (SOP): Procurement & Vendor Auditing, {scenario.name}", 1)
    text = text.replace("Internal Audit (synthetic policy written for AuditIQ-Bench)",
                        f"{scenario.owner} (synthetic policy written for the AuditIQ demonstration)", 1)
    intro = "Amounts are in INR and exclude tax."
    return text.replace(intro, f"{intro}\n\n**Purpose of this edition.** {scenario.story}", 1)


def incomplete_draft() -> tuple[str, str]:
    """A draft that leaves out Rule 4.4.1 and the table of approval limits, as a half-finished document would."""
    scenario = SCENARIOS[1]
    lines = []
    for line in render(scenario).splitlines():
        if "**Rule 4.4.1" in line or line.startswith("| Approver role") or line.startswith("|---") or re.match(
                r"\| (Manager|Senior Manager|Director|CFO) \|", line):
            continue
        lines.append(line)
    text = "\n".join(lines).replace("**Version:** 5.02", "**Version:** 5.99", 1)
    return "Draft_Incomplete", text.replace("Strict Controls Edition", "Draft, incomplete")


def pdf_name(scenario: Scenario) -> str:
    return f"{scenario.file}_v{scenario.version}.pdf"


def write_all(out: Path = DEMO_DIR) -> list[Path]:
    """The five policies and the incomplete draft as PDFs (same text, same file: no creation date in them)."""
    base = load_policy(BASELINE).registry
    template = load_template()
    written = []
    for scenario in SCENARIOS:
        registry = registry_of(scenario, base)
        written.append(write_pdf(render(scenario, registry, template), out / pdf_name(scenario),
                                 f"{registry['policy_name']}, version {scenario.version}",
                                 f"{base['policy_name']} | {scenario.name} | version {scenario.version}"))
    name, text = incomplete_draft()
    written.append(write_pdf(text, out / f"{name}_v5.99.pdf", f"{base['policy_name']}, Draft, incomplete, version 5.99",
                             f"{base['policy_name']} | Draft | version 5.99"))
    return written


if __name__ == "__main__":
    for path in write_all():
        print("wrote", path)
