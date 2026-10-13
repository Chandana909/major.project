"""From a policy document to an executable policy.

    python -m auditiq policy adopt company_policy.pdf --activate

An organisation's policy arrives as a document. This module reads the PDF,
finds every numbered rule, reads the thresholds out of the wording of the rules
(the tolerance, the daily invoice count, the approval limit of each role and so
on) and builds the clause registry that the controls execute. Nothing is typed
in by hand, so the thresholds the controls apply are the ones the document
states.

    PDF --read_lines, chunk_lines (PyMuPDF)--> rules and paragraphs with pages
        --extract_parameters (one pattern per parameter)--> parameters
        --build (with the clause list of a reference version)--> registry + text
        --adopt--> stored as a policy version, document ingested for citations

The reading is by pattern, not by a language model: a threshold is either found
in the expected sentence or reported as missing, and a document whose rules the
system cannot execute is refused with the reasons. The cost is that the
document must state its rules in the wording of the SOP template; a policy in
free prose needs an extraction step with human confirmation in front of this
one.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import db, policy_ingest
from .policy import WEEK, Policy, fmt_number

NUMBER = r"(\d[\d,]*(?:\.\d+)?)"


def _number(text: str) -> float:
    return float(text.replace(",", ""))


def _words(text: str) -> list[str]:
    """'Saturday or Sunday' and 'Suspended, Cancelled or Inactive' as lists."""
    return [w.strip() for w in re.split(r",\s*|\s+or\s+|\s+and\s+", text) if w.strip()]


# One pattern per parameter, matched against the text of its rule. Each pattern
# is the sentence of the SOP in which the threshold stands.
PATTERNS: dict[str, dict[str, tuple[str, object]]] = {
    "2.1.1": {"amount_tolerance_pct": (rf"difference of up to {NUMBER}\s*% of the PO amount", _number)},
    "3.1.1": {"gstin_length": (rf"exactly {NUMBER} alphanumeric characters", _number)},
    "3.1.2": {"state_code_min": (rf"state code from {NUMBER} to \d+", _number),
              "state_code_max": (rf"state code from \d+ to {NUMBER}", _number)},
    "4.1.1": {"max_invoices_per_vendor_per_day": (rf"at most {NUMBER} invoices dated on the same day", _number)},
    "4.1.2": {"guide_window_days": (rf"as a guide, {NUMBER} days", _number),
              "guide_band_pct": (rf"within {NUMBER}\s*% of the limit", _number)},
    "4.2.1": {"non_business_days": (r"dated on a (.+?) is an exception", _words)},
    "4.3.1": {"round_amount_multiple": (rf"exact multiple of INR {NUMBER}", _number)},
    "4.4.1": {"blocked_gstin_statuses": (r"registration status is (.+?), is an exception", _words)},
}
LIMIT_TABLE = re.compile(r"Approver role\s+Approval limit \(INR\)\s+(.*)$")
LIMIT_ROW = re.compile(rf"([A-Za-z][A-Za-z ]*?)\s+{NUMBER}(?=\s|$)")
RULE_HEAD = re.compile(r"^(Rule (\d+(?:\.\d+)+) \((\w+)\), [^.]*\.) (.*)$")
EFFECTIVE = re.compile(r"Effective Date:\s*(\d{4}-\d{2}-\d{2})")
SEVERITIES = {"low", "medium", "high", "critical"}


@dataclass
class Extraction:
    """What was read from one policy document."""
    file: str
    title: str
    version: str | None
    pages: int
    registry: dict | None = None
    text: str = ""
    problems: list[str] = field(default_factory=list)       # reasons the document cannot be executed
    changes: list[dict] = field(default_factory=list)       # parameters that differ from the reference version

    @property
    def usable(self) -> bool:
        return self.registry is not None and not self.problems


def _like(reference, value):
    """``value`` in the type the reference registry uses for this parameter."""
    if isinstance(reference, bool) or not isinstance(reference, (int, float)):
        return value
    return int(value) if isinstance(reference, int) and float(value).is_integer() else float(value)


def extract_parameters(chunks: list[dict]) -> tuple[dict[str, dict], list[str]]:
    """``{clause: {parameter: value}}`` read from the chunks of a document, and what could not be read."""
    rules = {c["clause_id"]: c["text"] for c in chunks if c["kind"] == "clause"}
    found: dict[str, dict] = {}
    missing: list[str] = []
    for clause, patterns in PATTERNS.items():
        if clause not in rules:
            continue                                        # a missing rule is reported by build()
        for name, (pattern, convert) in patterns.items():
            match = re.search(pattern, rules[clause])
            if match:
                found.setdefault(clause, {})[name] = convert(match.group(1))
            else:
                missing.append(f"Rule {clause}: the value of {name} was not found in the wording of the rule")
    table = next((LIMIT_TABLE.search(c["text"]) for c in chunks if c["kind"] == "text" and LIMIT_TABLE.search(c["text"])),
                 None)
    if table:
        limits = {role.strip(): _number(amount) for role, amount in LIMIT_ROW.findall(table.group(1))}
        if limits:
            found.setdefault("5.1.1", {})["approval_limits"] = limits
    if "5.1.1" in rules and "approval_limits" not in found.get("5.1.1", {}):
        missing.append("Rule 5.1.1: no table of approval limits by role was found")
    return found, missing


def policy_markdown(title: str, header: str, chunks: list[dict], limits: dict | None) -> str:
    """The document as the policy text the agents read: headings, rules in their own wording, the limits as a table."""
    lines, section = [f"# {title}", "", header, ""], None
    for chunk in chunks:
        if chunk["section"] != section:
            section = chunk["section"]
            number = section.split(" ", 1)[0].rstrip(".")
            lines += [("### " if "." in number else "## ") + section]
        if chunk["kind"] == "clause":
            head = RULE_HEAD.match(chunk["text"])
            lines.append(f"- **{head.group(1)}** {head.group(4)}" if head else f"- {chunk['text']}")
            continue
        table = LIMIT_TABLE.search(chunk["text"])
        if table and limits:
            lines += [chunk["text"][: table.start()].strip(), "", "| Approver role | Approval limit (INR) |", "|---|---|"]
            lines += [f"| {role} | {fmt_number(limit)} |" for role, limit in limits.items()] + [""]
        else:
            lines += [chunk["text"], ""]
    return "\n".join(lines).strip() + "\n"


def build(path: Path, reference: dict) -> Extraction:
    """Read a policy PDF into a registry, using ``reference`` for what the system can execute.

    The reference registry says which rules the system has a control or an
    agent for, and which parameters each of them needs. Titles and kinds come
    from it; rule numbers, severities and every parameter come from the
    document.
    """
    path = Path(path)
    lines, pages, title = policy_ingest.read_lines(path)
    chunks, header = policy_ingest.chunk_lines(lines)
    version = policy_ingest.VERSION.search(header)
    out = Extraction(file=path.name, title=title or path.stem, version=version.group(1) if version else None, pages=pages)
    if out.version is None:
        out.problems.append("the document states no version (expected 'Version: <number>' before the first section)")

    rules = {c["clause_id"]: c for c in chunks if c["kind"] == "clause"}
    known = reference["clauses"]
    out.problems += [f"Rule {k} ({known[k]['title'].lower()}) is not in the document; the system needs every rule it "
                     "executes to be stated" for k in known if k not in rules]
    out.problems += [f"Rule {k} is in the document, and the system has no control or agent for it" for k in rules
                     if k not in known]
    found, missing = extract_parameters(chunks)
    out.problems += missing

    clauses = {}
    for clause, spec in known.items():
        if clause not in rules:
            continue
        severity = policy_ingest.CLAUSE_START.match(rules[clause]["text"]).group(2).lower()
        if severity not in SEVERITIES:
            out.problems.append(f"Rule {clause}: '{severity}' is not a severity (low, medium, high, critical)")
        params = {}
        for name, old in spec["params"].items():
            if name not in found.get(clause, {}):
                continue                                    # already reported as missing
            value = found[clause][name]
            if isinstance(old, dict):
                value = {role: _like(next(iter(old.values())), limit) for role, limit in value.items()}
            elif not isinstance(old, list):
                value = _like(old, value)
            params[name] = value
            if value != old:
                out.changes.append({"clause": clause, "parameter": name, "from": old, "to": value})
        clauses[clause] = {"title": spec["title"], "severity": severity, "kind": spec["kind"], "params": params}
        if severity != spec["severity"] and severity in SEVERITIES:
            out.changes.append({"clause": clause, "parameter": "severity", "from": spec["severity"], "to": severity})

    off_days = clauses.get("4.2.1", {}).get("params", {}).get("non_business_days", [])
    out.problems += [f"Rule 4.2.1: '{d}' is not a day of the week" for d in off_days if d not in WEEK]
    limits = clauses.get("5.1.1", {}).get("params", {}).get("approval_limits")
    effective = EFFECTIVE.search(header)
    out.registry = {"policy_name": re.sub(r",?\s*version\s+[\d.]+$", "", out.title), "version": out.version,
                    "effective_date": effective.group(1) if effective else None, "clauses": clauses}
    out.text = policy_markdown(out.title, header, chunks, limits)
    return out


def adopt(conn: db.Database, path: Path, reference_version: str | None = None, activate: bool = False,
          replace: bool = False) -> dict:
    """Store the policy a document states as a policy version, and ingest the document for citations.

    The reference version (the active one by default) defines what the system
    can execute. A document that cannot be executed is not stored; the report
    says why. An existing version is replaced only when ``replace`` is set.
    """
    reference = db.read_policy(conn, reference_version).registry
    found = build(Path(path), reference)
    report = {"file": found.file, "version": found.version, "pages": found.pages, "adopted": False,
              "reference_version": reference["version"], "changes": found.changes, "problems": list(found.problems)}
    if not found.usable:
        return report
    stored = conn.scalar("SELECT registry FROM company_policies WHERE version = ?", (found.version,))
    if stored and json.loads(stored)["clauses"] != found.registry["clauses"] and not replace:
        report["problems"].append(f"version {found.version} is already stored with other parameters; give the document "
                                  "a new version number, or pass replace")
        return report
    db.store_policy(conn, Policy(found.registry, found.text), active=False)
    ingestion = policy_ingest.ingest(conn, Path(path))
    report.update(adopted=True, rules=len(found.registry["clauses"]), unverified=ingestion["unverified"])
    if activate:
        db.set_active_policy(conn, found.version)
        report["active"] = True
    conn.commit()
    return report
