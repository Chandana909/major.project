"""Robustness of the policy reader: edited documents that must be read correctly or refused.

    python -m evaluation.policy_robustness [--tag before-fix]

The reference policy is rendered to text, edited, written as a PDF and read by
the system (auditiq/policy_extract.py). Three groups of edits:

  A  changes that keep every rule and value: extra prose and a revision table,
     reordered rules and sections, long rules that wrap over many lines, rules
     pushed onto later pages, a reordered approval table, a changed severity,
     amounts in Indian digit grouping. The document must be adopted with every
     value and severity as it states them.
  B  defects that make the document impossible to execute: a threshold
     sentence removed, a rule removed, an unknown rule added, no version, a day
     that is not a day of the week, no approval table, a threshold written in
     words. The document must be refused.
  C  ambiguous documents: a rule stated twice with different values, an
     approval table without one of the approver roles. Refusal is the only safe
     outcome: the system cannot know which value is meant, or what limit applies.

Each document gets one outcome: "read correctly", "refused" (with the reasons
the system gives), or "adopted wrongly", which is the dangerous one: a
document of group A adopted with a value it does not state, or a document of
group B or C adopted at all.

Writes results/policy_robustness[-<tag>].md and .json and the PDFs to
policy/robustness/. No language model is used.
"""
from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path

from auditiq import policy_extract
from auditiq.policy import PROJECT_ROOT, load_policy, load_template, render_policy_text
from auditiq.policy_pdf import write_pdf

from .policy_change import REFERENCE, count_parameters, matching_parameters

RULE_2_1_1 = ("- **Rule 2.1.1 (HIGH), amount match.** The invoice amount must equal the PO amount. A difference of up "
              "to 1% of the PO amount is tolerated. A larger difference, in either direction, is an exception.")
LIMIT_ROWS = "| Manager | 100,000 |\n| Senior Manager | 500,000 |\n| Director | 2,500,000 |\n| CFO | 10,000,000 |"


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f"the edit expects one occurrence of {old[:50]!r}, found {text.count(old)}")
    return text.replace(old, new)


def section(text: str, heading: str) -> str:
    """The block from a '### ' heading to the next heading."""
    start = text.index(heading)
    end = min(i for i in (text.find("\n## ", start + 1), text.find("\n### ", start + 1)) if i != -1)
    return text[start:end + 1]


def long_rules(text: str) -> str:
    extra = (" This rule applies to every invoice of every vendor, whatever its amount, department or channel, "
             "including invoices received by post, by e-mail or through the supplier portal, and it is applied "
             "before the invoice is released for payment.")
    return "\n".join(line + extra if line.startswith("- **Rule") else line for line in text.split("\n"))


def pushed_to_later_pages(text: str) -> str:
    notes = "\n".join(f"Note {i}. Records of the audit, including every finding and its evidence, are kept for eight "
                      f"years and are made available to the external auditor on request." for i in range(1, 46))
    return replace_once(text, "## 4. Vendor Behaviour", notes + "\n\n## 4. Vendor Behaviour")


def reordered(text: str) -> str:
    rule_2_1_3 = next(line for line in text.split("\n") if line.startswith("- **Rule 2.1.3"))
    text = replace_once(text, RULE_2_1_1 + "\n", "")
    text = replace_once(text, rule_2_1_3 + "\n", rule_2_1_3 + "\n" + RULE_2_1_1 + "\n")
    timing, rounds = section(text, "### 4.2 Timing"), section(text, "### 4.3 Round Amounts")
    return replace_once(text, timing + rounds, rounds + timing)


EDITS = [
    # (id, group, description, edit, how the intended registry differs from the reference)
    ("A1", "A", "extra prose and a revision table before the rules",
     lambda t: replace_once(t, "## 1. Introduction\n", "## 1. Introduction\nThis revision was approved by the Audit "
                            "Committee and replaces all earlier versions. Questions about its application go to "
                            "Internal Audit.\n\n| Revision | Date | Change |\n|---|---|---|\n| 2.4 | 2024-10-01 | "
                            "Duplicate rules clarified |\n| 2.5 | 2025-04-01 | Approval limits restated |\n\n"), None),
    ("A2", "A", "rules and sections in another order", reordered, None),
    ("A3", "A", "every rule followed by a long explanation", long_rules, None),
    ("A4", "A", "45 notes before section 4, which push the later rules onto later pages", pushed_to_later_pages, None),
    ("A5", "A", "the approval table in another order",
     lambda t: replace_once(t, LIMIT_ROWS, "| CFO | 10,000,000 |\n| Director | 2,500,000 |\n| Senior Manager | 500,000 |"
                            "\n| Manager | 100,000 |"), None),
    ("A6", "A", "the severity of rule 2.1.1 changed from high to low",
     lambda t: replace_once(t, "Rule 2.1.1 (HIGH)", "Rule 2.1.1 (LOW)"), {"severity": ("2.1.1", "low")}),
    ("A7", "A", "approval limits in Indian digit grouping",
     lambda t: replace_once(t, LIMIT_ROWS, "| Manager | 1,00,000 |\n| Senior Manager | 5,00,000 |\n| Director | "
                            "25,00,000 |\n| CFO | 1,00,00,000 |"), None),
    ("B1", "B", "the threshold sentence of rule 2.1.1 removed",
     lambda t: replace_once(t, " A difference of up to 1% of the PO amount is tolerated.", ""), None),
    ("B2", "B", "rule 4.3.1 removed",
     lambda t: replace_once(t, next(x for x in t.split("\n") if x.startswith("- **Rule 4.3.1")) + "\n", ""), None),
    ("B3", "B", "a rule added that the system has no control for",
     lambda t: replace_once(t, "### 4.4 Vendor Status\n", "### 4.4 Vendor Status\n- **Rule 4.4.2 (HIGH), cash "
                            "payment.** An invoice paid in cash above INR 20,000 is an exception.\n"), None),
    ("B4", "B", "no version stated", lambda t: replace_once(t, "**Version:** 2.5  \n", ""), None),
    ("B5", "B", "a non-business 'day' that is not a day of the week",
     lambda t: replace_once(t, "dated on a Saturday or Sunday is an exception",
                            "dated on a public holiday is an exception"), None),
    ("B6", "B", "the approval table removed",
     lambda t: replace_once(t, "| Approver role | Approval limit (INR) |\n|---|---|\n" + LIMIT_ROWS + "\n", ""), None),
    ("B7", "B", "the tolerance written in words",
     lambda t: replace_once(t, "up to 1% of the PO amount", "up to one per cent of the PO amount"), None),
    ("C1", "C", "rule 2.1.1 stated twice, with 1% and with 2%",
     lambda t: replace_once(t, RULE_2_1_1 + "\n", RULE_2_1_1 + "\n" + RULE_2_1_1.replace("1%", "2%") + "\n"), None),
    ("C2", "C", "the approval table without the CFO",
     lambda t: replace_once(t, "\n| CFO | 10,000,000 |", ""), None),
]


def intended_registry(base: dict, change: dict | None) -> dict:
    registry = copy.deepcopy(base)
    if change and "severity" in change:
        clause, severity = change["severity"]
        registry["clauses"][clause]["severity"] = severity
    return registry


def outcome(group: str, read: policy_extract.Extraction, intended: dict) -> tuple[str, dict]:
    detail = {"adopted": read.usable, "problems": read.problems}
    if not read.usable:
        return "refused", detail
    if group != "A":
        return "adopted wrongly", detail
    clauses = read.registry["clauses"]
    detail["values_read_correctly"] = matching_parameters(read.registry, intended)
    detail["values"] = count_parameters(intended)
    detail["severities_read_correctly"] = sum(clauses.get(k, {}).get("severity") == v["severity"]
                                              for k, v in intended["clauses"].items())
    detail["rules"] = len(intended["clauses"])
    right = (detail["values_read_correctly"] == detail["values"]
             and detail["severities_read_correctly"] == detail["rules"])
    return ("read correctly" if right else "adopted wrongly"), detail


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=PROJECT_ROOT / "results")
    ap.add_argument("--pdfs", type=Path, default=PROJECT_ROOT / "policy" / "robustness")
    ap.add_argument("--tag", default="", help="suffix of the output files, e.g. 'before-fix'")
    args = ap.parse_args()

    base = load_policy(REFERENCE).registry
    text = render_policy_text(base, load_template())
    rows = []
    for edit_id, group, description, edit, change in EDITS:
        pdf = write_pdf(edit(text), args.pdfs / f"robustness_{edit_id}.pdf", f"Robustness test {edit_id}",
                        f"Robustness test {edit_id}")
        read = policy_extract.build(pdf, base)
        verdict, detail = outcome(group, read, intended_registry(base, change))
        expected = "read correctly" if group == "A" else "refused"
        rows.append({"id": edit_id, "group": group, "edit": description, "expected": expected, "outcome": verdict,
                     "as_required": verdict == expected} | detail)
        print(f"{edit_id}: {verdict}" + (f" ({'; '.join(read.problems)})" if read.problems else ""), flush=True)

    suffix = f"-{args.tag}" if args.tag else ""
    result = {"produced": time.strftime("%Y-%m-%d %H:%M"), "reference_version": REFERENCE, "tag": args.tag,
              "documents": rows}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"policy_robustness{suffix}.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8",
                                                               newline="\n")
    (args.out / f"policy_robustness{suffix}.md").write_text(report(result), encoding="utf-8", newline="\n")
    print(f"wrote {args.out / f'policy_robustness{suffix}.md'}")


def report(r: dict) -> str:
    rows = r["documents"]
    ok = sum(x["as_required"] for x in rows)
    wrong = [x for x in rows if x["outcome"] == "adopted wrongly"]
    lines = [
        "# Robustness of the policy reader" + (f" ({r['tag']})" if r["tag"] else ""), "",
        f"Produced by `python -m evaluation.policy_robustness{' --tag ' + r['tag'] if r['tag'] else ''}` on "
        f"{r['produced']}. The reference policy (version {r['reference_version']}) is edited, written as a PDF and "
        "read by the system. Group A edits keep every rule and value and must be read correctly; group B edits make "
        "the document impossible to execute and must be refused; group C edits make it ambiguous, and refusal is "
        "the only safe outcome. No language model is used.", "",
        "| Id | Group | Edit | Required | Outcome | Values read correctly | Reasons given by the system |",
        "|---|---|---|---|---|---|---|",
    ]
    for x in rows:
        values = f"{x['values_read_correctly']} of {x['values']}" if "values" in x else "–"
        reasons = "; ".join(x["problems"]) if x["problems"] else "–"
        lines.append(f"| {x['id']} | {x['group']} | {x['edit']} | {x['expected']} | **{x['outcome']}** | {values} | "
                     f"{reasons} |")
    lines += ["", f"{ok} of {len(rows)} documents were handled as required; {len(wrong)} were adopted wrongly"
                  + (": " + ", ".join(x["id"] for x in wrong) + "." if wrong else "."), ""]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
