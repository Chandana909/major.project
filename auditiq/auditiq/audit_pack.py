"""The audit pack: the record of one audited transaction (Section VIII of the paper).

The pack is assembled by code from the verified flags. No LLM writes it, so it
cannot state anything the pipeline did not establish.
"""
from __future__ import annotations

ACTIONS = {
    "approve": "Approved automatically. No human review required.",
    "sample": "Sampled-review queue: escalated only by weakly supported findings. Not approved automatically.",
    "escalate": "Escalated to a human reviewer. Payment is held until the review is recorded.",
}


def build_pack(txn: dict, flags: list[dict], removed: list[dict], score: dict, review: dict | None,
               clauses: dict, *, policy_version: str, configuration: str, model: str | None) -> dict:
    def describe(flag: dict) -> dict:
        known = clauses.get(flag["clause"])
        out = {
            "clause": flag["clause"],
            "title": known["title"] if known else "clause not in the policy",
            "severity": flag["severity"],
            "source": "control" if flag["source"] == "D" else f"agent ({flag.get('agent', 'unknown')})",
            "confidence": flag.get("confidence"),
            "evidence": flag.get("evidence", []),
            "message": flag.get("message", ""),
        }
        if flag["source"] != "D":
            out["confidence_terms"] = {k: flag.get(k) for k in ("g", "p", "a")}
        return out

    return {
        "invoice_id": txn["invoice"]["invoice_id"],
        "vendor_id": txn["vendor"]["vendor_id"],
        "vendor_name": txn["vendor"].get("vendor_name"),
        "policy_version": policy_version,
        "configuration": configuration,
        "model": model,
        "route": score["route"],
        "risk_level": score["risk_level"],
        "count_based_risk": score["r0"],
        "weighted_risk": score["rc"],
        "threshold": score["threshold"],
        "flags": [describe(f) for f in flags],
        "removed_by_challenger": [
            {"clause": f["clause"], "agent": f.get("agent"), "message": f.get("message", ""),
             "reason": f.get("removal_reason", "")} for f in removed],
        "review": review,
        "recommended_action": ACTIONS[score["route"]],
    }


def _number(x) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)


def render_markdown(pack: dict) -> str:
    lines = [
        f"# Audit pack: {pack['invoice_id']}",
        "",
        f"- Vendor: {pack['vendor_name']} ({pack['vendor_id']})",
        f"- Policy version applied: {pack['policy_version']}",
        f"- Route: **{pack['route']}** (weighted risk {_number(pack['weighted_risk'])}, "
        f"count-based risk {_number(pack['count_based_risk'])}, threshold {_number(pack['threshold'])})",
        f"- {pack['recommended_action']}",
        "",
        "## Findings",
        "",
    ]
    if not pack["flags"]:
        lines.append("No exception was found.")
    for i, f in enumerate(pack["flags"], start=1):
        confidence = "not computed" if f["confidence"] is None else f"{f['confidence']:.2f}"
        lines.append(f"{i}. **Rule {f['clause']}, {f['title'].lower()}** ({f['severity']}; {f['source']}; "
                     f"confidence {confidence})")
        if f["message"]:
            lines.append(f"   {f['message']}")
        if f.get("citation"):
            lines.append(f"   Source: {f['citation']['document']}, page {f['citation']['page']}")
        for e in f["evidence"]:
            if isinstance(e, dict):
                lines.append(f"   - `{e.get('field')}` = `{e.get('value')}`")
        terms = f.get("confidence_terms")
        if terms and terms.get("g") is not None:
            agreement = "not computed" if terms.get("a") is None else f"{terms['a']:.2f}"
            lines.append(f"   - evidence found in the records: {'yes' if terms['g'] else 'no'}; "
                         f"clause in the policy: {'yes' if terms['p'] else 'no'}; "
                         f"reproduced by re-runs: {agreement}")
    if pack["removed_by_challenger"]:
        lines += ["", "## Removed by the challenger", ""]
        for f in pack["removed_by_challenger"]:
            lines.append(f"- Rule {f['clause']} ({f['agent']}): {f['message']} Removed because: {f['reason']}")
    review = pack.get("review")
    if review:
        lines += ["", "## Review", "", f"- Decision: {review.get('decision')}"]
        if review.get("reviewer"):
            lines.append(f"- Reviewer: {review['reviewer']}")
        if review.get("justification"):
            lines.append(f"- Justification: {review['justification']}")
    return "\n".join(lines) + "\n"
