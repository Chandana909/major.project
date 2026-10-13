"""The policy store: one clause registry and one policy text per version.

The registry (policy/policy_v<version>.json) holds, for every clause, its
title, severity, kind (control or judgement) and parameters. The text
(policy/SOP_v<version>.md) is rendered from the registry by
policy/build_policy.py and is what the agents read. Nothing else in the
pipeline contains a threshold.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY_DIR = PROJECT_ROOT / "policy"


@dataclass(frozen=True)
class Policy:
    registry: dict
    text: str

    @property
    def version(self) -> str:
        return self.registry["version"]

    @property
    def clauses(self) -> dict:
        return self.registry["clauses"]

    def clause_ids(self, kind: str | None = None) -> list[str]:
        return [k for k, v in self.clauses.items() if kind is None or v["kind"] == kind]


_RULE_LINE = re.compile(r"^- \*\*(Rule (\d+(?:\.\d+)+) \(\w+\), .+?)\*\* (.+)$")


def clause_texts(policy_text: str) -> dict[str, str]:
    """The wording of every numbered rule in a policy text, without Markdown.

    '- **Rule 2.1.2 (HIGH), quantity match.** The quantity ...' gives
    {'2.1.2': 'Rule 2.1.2 (HIGH), quantity match. The quantity ...'}.
    """
    found = {}
    for line in policy_text.splitlines():
        match = _RULE_LINE.match(line.strip())
        if match:
            found[match.group(2)] = f"{match.group(1)} {match.group(3)}"
    return found


WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def fmt_number(x) -> str:
    """1000000 -> '1,000,000'; 1.0 -> '1'; 0.5 -> '0.5'."""
    if isinstance(x, float) and x.is_integer():
        x = int(x)
    return f"{x:,}" if isinstance(x, int) else str(x)


def join_words(items: list[str], last: str = "or") -> str:
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f" {last} " + items[-1]


def business_days(non_business_days: list[str]) -> str:
    """'Monday to Friday' for a Saturday-Sunday weekend; a list when the days are not one run."""
    working = [d for d in WEEK if d not in non_business_days]
    run = WEEK[WEEK.index(working[0]): WEEK.index(working[-1]) + 1]
    return f"{working[0]} to {working[-1]}" if working == run and len(working) > 1 else join_words(working, "and")


def render_policy_text(registry: dict, template: str) -> str:
    """The policy text of one version: the template with the parameters of the registry filled in.

    This is the only way a threshold reaches the text, so the text the agents
    read and the parameters the controls apply cannot differ.
    """
    c = registry["clauses"]
    limits = c["5.1.1"]["params"]["approval_limits"]
    off_days = c["4.2.1"]["params"]["non_business_days"]
    values = {
        "version": registry["version"],
        "effective_date": registry["effective_date"],
        "state_code_min": f'{c["3.1.2"]["params"]["state_code_min"]:02d}',
        "state_code_max": f'{c["3.1.2"]["params"]["state_code_max"]:02d}',
        "business_days": business_days(off_days),
        "non_business_days": join_words(off_days),
        "round_amount_multiple": fmt_number(c["4.3.1"]["params"]["round_amount_multiple"]),
        "blocked_gstin_statuses": join_words(c["4.4.1"]["params"]["blocked_gstin_statuses"]),
        "approval_limit_rows": "\n".join(f"| {role} | {fmt_number(limit)} |" for role, limit in limits.items()),
    }

    def fill(match: re.Match) -> str:
        key = match.group(1)
        if key in values:
            return str(values[key])
        clause, _, param = key.rpartition(".")
        return fmt_number(c[clause]["params"][param])

    text = re.sub(r"\{\{([^}]+)\}\}", fill, template)
    # Every numbered rule in the text must be in the registry with the same severity, and the other way round.
    in_text = dict(re.findall(r"\*\*Rule (\d+\.\d+\.\d+) \((\w+)\)", text))
    in_registry = {k: v["severity"].upper() for k, v in c.items()}
    if in_text != in_registry:
        raise ValueError(f"policy text and clause registry disagree: {in_text} vs {in_registry}")
    return text


def derive_policy(base: dict, version: str, effective_date: str, overrides: dict) -> dict:
    """A registry that differs from ``base`` in the given parameters: ``{clause: {parameter: value}}``.

    A dictionary value, such as the approval limits, is merged role by role.
    """
    registry = json.loads(json.dumps(base))
    registry["version"], registry["effective_date"] = version, effective_date
    for clause, changes in overrides.items():
        params = registry["clauses"][clause]["params"]
        for name, value in changes.items():
            if name not in params:
                raise KeyError(f"clause {clause} has no parameter {name}")
            if isinstance(value, dict):
                params[name].update(value)
            else:
                params[name] = value
    return registry


def load_template(directory: Path = POLICY_DIR) -> str:
    return (directory / "SOP_template.md").read_text(encoding="utf-8")


def load_policy(version: str = "2.5", directory: Path = POLICY_DIR) -> Policy:
    registry = json.loads((directory / f"policy_v{version}.json").read_text(encoding="utf-8"))
    text = (directory / f"SOP_v{version}.md").read_text(encoding="utf-8")
    return Policy(registry, text)
