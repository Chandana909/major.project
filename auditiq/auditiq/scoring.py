"""Confidence, risk scores and routing (features E2 to E4 of the paper).

    c(f)  = 1                         for a flag from a deterministic control
          = (g + p + a) / 3           for a flag from an LLM agent            (3)
    R0(x) = min(100, sum of w_s)      plus floors                             (2)
    Rc(x) = min(100, sum of w_s * c)  plus floors for flags with c >= theta   (4)
    route = escalate if Rc >= tau; sample if Rc < tau <= R0; approve if R0 < tau  (5)

Equation numbers refer to the paper.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .controls import approving_entry

EPS = 1e-9
SEVERITIES = ("critical", "high", "medium", "low")


@dataclass(frozen=True)
class ScoringOptions:
    weights: dict = field(default_factory=lambda: {"critical": 30, "high": 20, "medium": 10, "low": 5})
    floors: dict = field(default_factory=lambda: {"critical": 70, "high": 50})
    tau: float = 50
    theta: float = 2 / 3
    # Weights of grounding, clause validity and agreement. Equal by default; the
    # sensitivity analysis of Section VI-D varies them.
    confidence_weights: tuple[float, float, float] = (1.0, 1.0, 1.0)
    # False: the count-based score decides alone (the pipeline without E3).
    use_confidence: bool = True


DEFAULT = ScoringOptions()


def clause_id(raw) -> str:
    """'Rule 2.1.1', '2.1.1.' and 'SOP 2.1.1' all name clause 2.1.1."""
    match = re.search(r"\d+(?:\.\d+)+", "" if raw is None else str(raw))
    return match.group(0) if match else ""


_MISSING = object()


def resolve(txn: dict, path):
    """Resolve an evidence path against the extracted transaction.

        invoice.amount   po.description   grn.notes   vendor.official_gstin
        approval.approver_role            the approving entry
        approvals[0].action_taken
        history.INV40012.invoice_number   another invoice of the vendor

    Returns ``_MISSING`` when the path does not exist.
    """
    parts = str("" if path is None else path).strip().split(".")
    head, parts = parts[0], parts[1:]
    indexed = re.fullmatch(r"approvals\[(\d+)\]", head)
    if indexed:
        entries = txn.get("approvals") or []
        index = int(indexed.group(1))
        node = entries[index] if index < len(entries) else None
    elif head == "approval":
        node = approving_entry(txn)
    elif head in ("history", "vendor_history"):
        if not parts:
            return _MISSING
        wanted, parts = parts[0], parts[1:]
        node = next((h for h in txn.get("vendor_history") or [] if h.get("invoice_id") == wanted), None)
    elif head in ("invoice", "po", "grn", "vendor"):
        node = txn.get(head)
    else:
        return _MISSING
    if not parts:
        return _MISSING                      # a whole record is not a field
    for key in parts:
        if not isinstance(node, dict) or key not in node:
            return _MISSING
        node = node[key]
    return _MISSING if isinstance(node, (dict, list)) else node


def as_number(x) -> float | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if not isinstance(x, str):
        return None
    cleaned = re.sub(r"[,\s₹]|INR|Rs\.?", "", x, flags=re.IGNORECASE)
    return float(cleaned) if re.fullmatch(r"[-+]?(\d+\.?\d*|\.\d+)", cleaned) else None


def same_value(stated, actual) -> bool:
    if actual is _MISSING:
        return False
    if stated is None or stated == "":
        return actual is None or actual == ""
    if actual is None:
        return False
    if isinstance(actual, bool) or isinstance(stated, bool):
        return str(stated).strip().lower() == str(actual).strip().lower()
    # A value is compared as a number only when the record holds a number, so
    # that an identifier such as "00123" is not equated with 123.
    if isinstance(actual, (int, float)):
        n = as_number(stated)
        return n is not None and abs(n - actual) <= 0.005 + 1e-9 * abs(actual)
    return str(stated).strip().lower() == str(actual).strip().lower()


def grounding(flag: dict, txn: dict) -> int:
    """g(f): 1 if every evidence field exists in the transaction with the stated value.

    A flag without evidence is not grounded.
    """
    evidence = flag.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return 0
    return int(all(isinstance(e, dict) and same_value(e.get("value"), resolve(txn, e.get("field")))
                   for e in evidence))


def clause_validity(flag: dict, clauses: dict) -> int:
    """p(f): 1 if the cited clause exists in the active policy version."""
    return int(clause_id(flag.get("clause")) in clauses)


def confidence(flag: dict, txn: dict, clauses: dict, agreement: float | None = None,
               options: ScoringOptions = DEFAULT) -> dict:
    """Confidence of one flag.

    ``agreement`` is a(f), the fraction of the m re-runs of the originating
    agent that cite the same clause. It is required for an LLM flag and ignored
    for a control flag.
    """
    if flag.get("source") == "D":
        return {"g": 1, "p": 1, "a": 1.0, "c": 1.0}
    if isinstance(agreement, bool) or not isinstance(agreement, (int, float)) or not 0 <= agreement <= 1:
        raise TypeError("agreement in [0, 1] is required for an LLM flag")
    wg, wp, wa = options.confidence_weights
    g, p = grounding(flag, txn), clause_validity(flag, clauses)
    return {"g": g, "p": p, "a": float(agreement), "c": (wg * g + wp * p + wa * agreement) / (wg + wp + wa)}


def normalize_flag(flag: dict, clauses: dict) -> dict:
    """Bring a flag into canonical form.

    In the policy every clause has exactly one severity, so a flag that cites a
    valid clause takes the severity of that clause. The severity stated by an
    agent is used only for an unknown clause.
    """
    cid = clause_id(flag.get("clause"))
    stated = str(flag.get("severity") or "").lower()
    if cid in clauses:
        severity = clauses[cid]["severity"]
    else:
        severity = stated if stated in SEVERITIES else "medium"
    return {**flag, "clause": cid or str(flag.get("clause") or ""), "severity": severity,
            "source": "D" if flag.get("source") == "D" else "L"}


def _with_floor(base: float, flags: list[dict], floors: dict) -> float:
    if any(f["severity"] == "critical" for f in flags):
        return max(base, floors["critical"])
    if any(f["severity"] == "high" for f in flags):
        return max(base, floors["high"])
    return base


def count_score(flags: list[dict], options: ScoringOptions = DEFAULT) -> float:
    """R0, equation (2): every flag counts fully."""
    base = min(100, sum(options.weights[f["severity"]] for f in flags))
    return _with_floor(base, flags, options.floors)


def weighted_score(flags: list[dict], options: ScoringOptions = DEFAULT) -> float:
    """Rc, equation (4): a flag counts in proportion to its confidence; only
    flags with confidence >= theta can trigger a floor."""
    base = min(100, sum(options.weights[f["severity"]] * f["confidence"] for f in flags))
    return _with_floor(base, [f for f in flags if f["confidence"] >= options.theta - EPS], options.floors)


def route(r0: float, rc: float, options: ScoringOptions = DEFAULT) -> str:
    """Equation (5)."""
    if rc >= options.tau:
        return "escalate"
    if r0 >= options.tau:
        return "sample"
    return "approve"


def risk_level(score_value: float) -> str:
    if score_value >= 70:
        return "CRITICAL"
    if score_value >= 50:
        return "HIGH"
    if score_value >= 30:
        return "MEDIUM"
    return "LOW"


def score(flags: list[dict], options: ScoringOptions = DEFAULT) -> dict:
    """Score one transaction. Each flag must be normalized and carry ``confidence``."""
    r0 = count_score(flags, options)
    rc = weighted_score(flags, options) if options.use_confidence else r0
    return {"r0": r0, "rc": rc, "route": route(r0, rc, options), "risk_level": risk_level(rc),
            "threshold": options.tau}
