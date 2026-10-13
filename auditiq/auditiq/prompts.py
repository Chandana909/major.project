"""Prompt texts of the LLM stages.

No template contains a threshold, a rule number or an example taken from the
benchmark: the policy is inserted at run time. The system message is the same
for every stage and every invoice under one policy version, so a server that
caches prompt prefixes processes the policy text once. The hash of the
templates is stored with every run, to tie results to the exact wording.
"""
from __future__ import annotations

import hashlib

SYSTEM = """\
You work in an audit pipeline for vendor invoices. Each request states your task and gives the records of one invoice, the INVOICE UNDER AUDIT. The policy below is the only source of rules. Apply each rule as it is written, including what it says is not an exception.

POLICY (version {version})
{policy_text}"""

EVIDENCE_AND_OUTPUT = """\
Evidence
- For every exception, cite the record fields it rests on, each with its value copied exactly from the records.
- Field paths: invoice.<field>, po.<field>, grn.<field>, vendor.<field>, approval.<field> (the approving entry of the approval log), history.<invoice_id>.<field> (another invoice of the same vendor).
- Never cite a value that is not in the records.

Output
Reply with one JSON object and nothing else:
{"flags": [{"clause": "<rule number>", "evidence": [{"field": "<field path>", "value": <value>}], "explanation": "<one sentence>"}]}
If the invoice under audit has no exception, reply {"flags": []}"""

SPECIALIST_TASK = """\
TASK
You are the {title} of the pipeline.

Division of work
- Deterministic controls have already checked every rule that can be decided by comparing field values. Their findings are listed under CONTROL FINDINGS. They are final: do not repeat them and do not question them.
- Your remit is limited to {remit}. Do not report any other rule.

How to decide
- Report an exception only when the records show that the invoice under audit violates a rule of your remit as the policy defines it.
- Most invoices have no exception.

""" + EVIDENCE_AND_OUTPUT

SINGLE_TASK = """\
TASK
You are the auditor. Audit the invoice under audit against every rule of the policy.

How to decide
- Report every rule that the records show the invoice under audit violates, as the policy defines it.
- Most invoices have no exception.

""" + EVIDENCE_AND_OUTPUT

CHALLENGER_TASK = """\
TASK
You are the challenger of the pipeline. Specialist agents have proposed the findings listed under PROPOSED FINDINGS. Your only task is to test each proposed finding against the records and the policy.

Remove a proposed finding when at least one of these holds:
- a value it cites is not in the records;
- the records do not show that the invoice under audit violates the cited rule as the policy defines it;
- the policy says that the situation is not an exception.
Otherwise keep it.

Do not add findings. Do not rule on the CONTROL FINDINGS: they come from deterministic checks, are final, and are shown only for context.

Output
Reply with one JSON object and nothing else, with exactly one verdict for every proposed finding:
{"verdicts": [{"id": <id of the proposed finding>, "verdict": "keep" or "remove", "reason": "<one sentence>"}]}"""

REPAIR = "Your reply was not a JSON object of the required form. Reply again with the JSON object only."

# Section headings of the user message, after the task. A section that does not
# apply to a stage is left out (the single-prompt auditor has no control findings).
CONTROL_HEADING = "CONTROL FINDINGS"
PROPOSED_HEADING = "PROPOSED FINDINGS"
RECORDS_HEADING = "RECORDS"


def system_message(version: str, policy_text: str) -> str:
    # str.replace, not str.format: a policy text may contain braces.
    return SYSTEM.replace("{version}", version).replace("{policy_text}", policy_text.strip())


def user_message(task: str, records: str, control_findings: str | None = None,
                 proposed: str | None = None) -> str:
    parts = [task]
    if control_findings is not None:
        parts += ["", CONTROL_HEADING, control_findings]
    if proposed is not None:
        parts += ["", PROPOSED_HEADING, proposed]
    parts += ["", RECORDS_HEADING, records]
    return "\n".join(parts)


def prompt_hash() -> str:
    """Short hash of every template, for the run metadata."""
    material = "\n---\n".join([SYSTEM, SPECIALIST_TASK, SINGLE_TASK, CHALLENGER_TASK, REPAIR,
                               CONTROL_HEADING, PROPOSED_HEADING, RECORDS_HEADING])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
