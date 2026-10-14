"""Reading policies in their own wording: how often is the model right, and what does the code check catch?

    python -m evaluation.policy_llm_eval                 needs a configured model
    python -m evaluation.policy_llm_eval --documents     only writes the policy PDFs

Six policy documents are written in two styles that share no wording with the
SOP template: a memorandum in running prose, and a handbook with lettered
clauses, number words and Indian digit grouping. Each style states three
policies (the reference thresholds, a strict policy, a lenient policy). The
documents carry no rule numbers of the system, so the model has to find each
rule by its meaning.

For each document the model proposes the passages and the values
(auditiq/policy_llm.py), code verifies them against the document, and the
result is compared with the policy the document was written from:

    value:  right and verified      accepted by code, and correct
            right, held back        correct, but code could not confirm it in the quote
            wrong, caught           incorrect, and code held it back
            wrong, passed           incorrect, and code accepted it: only the person can stop it
            missing                 the model gave no value
    rule:   located                 a quote was found word for word in the document
            at the right passage    one of those quotes is the passage that states the rule

Writes results/policy_llm.md and results/policy_llm.json. The documents were
written by the authors of the system; this is a first measurement on six
documents, not an estimate for policies in general.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import time
from pathlib import Path

from auditiq import policy_llm
from auditiq.llm import LLMSettings, OpenAIChatClient, ResponseCache
from auditiq.policy import POLICY_DIR, PROJECT_ROOT, derive_policy, fmt_number, join_words, load_policy
from auditiq.policy_pdf import write_pdf

from .policy_change import VARIANTS

FREEFORM = POLICY_DIR / "freeform"
STYLES = {"memo": "Accounts Payable Control Memorandum", "handbook": "Procure-to-Pay Compliance Handbook"}
POLICIES = {"reference": {}, "strict": next(v[3] for v in VARIANTS if v[1] == "Strict policy"),
            "lenient": next(v[3] for v in VARIANTS if v[1] == "Lenient policy")}
# A phrase of the passage that states each rule, per style: how a located quote is judged to be the right one.
ANCHORS = {
    "memo": {
        "2.1.1": ["of the order value"], "2.1.2": ["units billed may never be greater"],
        "2.1.3": ["does not quote a purchase order"], "2.1.4": ["rejected, damaged, sent back"],
        "2.1.5": ["what the order asked for"], "2.2.1": ["has already used"], "2.2.2": ["re-typed"],
        "3.1.1": ["letters and digits"], "3.1.2": ["state code"], "3.1.3": ["vendor master"],
        "4.1.1": ["bearing the same date"], "4.1.2": ["cut into pieces", "under the approver's ceiling"],
        "4.2.1": ["do not work on"], "4.3.1": ["exact multiple"], "4.4.1": ["blacklist"],
        "5.1.1": ["up to a ceiling", "ceiling is below"],
    },
    "handbook": {
        "2.1.1": ["variance"], "2.1.2": ["invoiced quantity in excess"], "2.1.3": ["cite a purchase order"],
        "2.1.4": ["receiving remarks"], "2.1.5": ["narration"], "2.2.1": ["re-use by a vendor"],
        "2.2.2": ["re-keyed variant"], "3.1.1": ["alphanumeric characters long"], "3.1.2": ["state code"],
        "3.1.3": ["vendor master"], "4.1.1": ["same invoice date"], "4.1.2": ["structuring", "sanctioning limit of the approver"],
        "4.2.1": ["office is closed"], "4.3.1": ["exact multiple"], "4.4.1": ["blacklisted"],
        "5.1.1": ["sanctioning limit of a manager", "sanctioned by an officer"],
    },
}


def render(style: str, registry: dict) -> str:
    """The policy of a registry in the wording of one style."""
    c = {k: v["params"] for k, v in registry["clauses"].items()}
    limits = c["5.1.1"]["approval_limits"]
    values = {
        "version": registry["version"],
        "tolerance": fmt_number(c["2.1.1"]["amount_tolerance_pct"]),
        "gstin_length": c["3.1.1"]["gstin_length"], "gstin_length_word": policy_llm.WORDS[c["3.1.1"]["gstin_length"]],
        "state_min": f'{c["3.1.2"]["state_code_min"]:02d}', "state_max": f'{c["3.1.2"]["state_code_max"]:02d}',
        "daily": c["4.1.1"]["max_invoices_per_vendor_per_day"],
        "daily_word": policy_llm.WORDS[c["4.1.1"]["max_invoices_per_vendor_per_day"]],
        "window": c["4.1.2"]["guide_window_days"], "window_word": policy_llm.WORDS[c["4.1.2"]["guide_window_days"]],
        "band": fmt_number(c["4.1.2"]["guide_band_pct"]),
        "off_days": join_words([day + "s" for day in c["4.2.1"]["non_business_days"]], "and"),
        "round": fmt_number(c["4.3.1"]["round_amount_multiple"]),
        "round_indian": policy_llm.indian(c["4.3.1"]["round_amount_multiple"]),
        "statuses": join_words(c["4.4.1"]["blocked_gstin_statuses"]),
    }
    for role, limit in limits.items():
        key = "limit_" + role.lower().replace(" ", "_")
        values[key], values[key + "_indian"] = fmt_number(limit), policy_llm.indian(limit)
    text = (FREEFORM / f"{style}_template.md").read_text(encoding="utf-8")
    for name, value in values.items():
        text = text.replace("{{" + name + "}}", str(value))
    assert "{{" not in text, "a placeholder of the template was not filled"
    return text


def documents(out: Path) -> list[dict]:
    """Write the six policy PDFs; returns one entry per document with the policy it states."""
    base = load_policy("2.5").registry
    made = []
    for s, style in enumerate(STYLES, start=1):
        for p, (policy, overrides) in enumerate(POLICIES.items(), start=1):
            version = f"5.{(s - 1) * len(POLICIES) + p}"
            intended = derive_policy(base, version, "2026-04-01", overrides)
            path = write_pdf(render(style, intended), out / f"{style}_{policy}_v{version}.pdf",
                             f"{STYLES[style]}, version {version}", f"{STYLES[style]} | version {version}")
            made.append({"style": style, "policy": policy, "version": version, "intended": intended, "path": path})
    return made


def score(proposal: policy_llm.Proposal, intended: dict, style: str) -> dict:
    """Compare a verified proposal with the policy the document was written from."""
    counts = {"values": 0, "right_verified": 0, "right_held_back": 0, "wrong_caught": 0, "wrong_passed": 0, "missing": 0,
              "rules": len(proposal.rules), "located": 0, "right_passage": 0}
    details = []
    for item in proposal.items:
        want = intended["clauses"][item["clause"]]["params"][item["parameter"]]
        parts = [(f"{item['parameter']}: {role}", (item["value"] or {}).get(role) if isinstance(item["value"], dict) else None,
                  limit) for role, limit in want.items()] if isinstance(want, dict) else [(item["parameter"], item["value"], want)]
        for name, got, expected in parts:
            counts["values"] += 1
            right = got == expected
            if got is None:
                outcome = "missing"
            elif item["status"] == policy_llm.VERIFIED:
                outcome = "right_verified" if right else "wrong_passed"
            else:
                outcome = "right_held_back" if right else "wrong_caught"
            counts[outcome] += 1
            if outcome != "right_verified":
                details.append({"rule": item["clause"], "parameter": name, "proposed": got, "intended": expected,
                                "outcome": outcome, "reason": item["reason"]})
    for clause, rule in proposal.rules.items():
        counts["located"] += rule["located"]
        quoted = " ".join(policy_llm.normalize(q) for q, _ in rule["quotes"])
        counts["right_passage"] += any(anchor in quoted for anchor in ANCHORS[style][clause])
    # A reviewer who accepts every verified value, types the right value for every other one and gives the
    # passage of any rule the model did not locate: the stored policy is then the intended one exactly when no
    # wrong value passed the code check.
    counts["policy_correct_after_confirmation"] = counts["wrong_passed"] == 0
    return {"counts": counts, "details": details}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--documents", action="store_true", help="write the policy PDFs and stop")
    ap.add_argument("--pdfs", type=Path, default=FREEFORM / "pdf")
    ap.add_argument("--out", type=Path, default=PROJECT_ROOT / "results")
    args = ap.parse_args()
    docs = documents(args.pdfs)
    if args.documents:
        print("\n".join(str(d["path"]) for d in docs))
        return

    reference = load_policy("2.5").registry
    settings = dataclasses.replace(LLMSettings.from_env(), max_tokens=2500)
    client = OpenAIChatClient(settings, ResponseCache())
    rows = []
    for d in docs:
        proposal = policy_llm.propose(d["path"], reference, client)
        rows.append({"style": d["style"], "policy": d["policy"], "version": d["version"], "file": d["path"].name,
                     "usage": proposal.usage, "problems": proposal.problems, **score(proposal, d["intended"], d["style"])})
        c = rows[-1]["counts"]
        print(f"{d['path'].name}: {c['right_verified']}/{c['values']} values right and verified, {c['wrong_passed']} wrong "
              f"passed, {c['right_passage']}/{c['rules']} rules at the right passage, {proposal.usage['seconds']} s", flush=True)

    keys = ["values", "right_verified", "right_held_back", "wrong_caught", "wrong_passed", "missing", "rules", "located",
            "right_passage"]
    total = {k: sum(r["counts"][k] for r in rows) for k in keys}
    result = {"produced": time.strftime("%Y-%m-%d %H:%M"), "model": settings.model, "documents": rows, "total": total}
    lines = ["# Reading policies in their own wording", "",
             f"Produced by `python -m evaluation.policy_llm_eval` on {result['produced']}. Model: `{settings.model}`, "
             "temperature 0, one call per document. Six documents in two styles (a memorandum in prose; a handbook with "
             "lettered clauses, number words and Indian digit grouping), each stating three policies. None uses the "
             "wording or the rule numbers of the SOP template.", "",
             "The model proposes passages and values; code checks that each quote is in the document and that each "
             "value is written in a quote of its rule; a person then confirms. The table compares the proposals with "
             "the policy each document was written from.", "",
             "| Document | Values | Right and verified | Right, held back | Wrong, caught | Wrong, passed | Missing | "
             "Rules located | At the right passage | Seconds |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        c = r["counts"]
        lines.append(f"| `{r['file']}` | {c['values']} | {c['right_verified']} | {c['right_held_back']} | "
                     f"{c['wrong_caught']} | {c['wrong_passed']} | {c['missing']} | {c['located']} of {c['rules']} | "
                     f"{c['right_passage']} of {c['rules']} | {r['usage']['seconds']} |")
    lines.append(f"| **All** | {total['values']} | {total['right_verified']} | {total['right_held_back']} | "
                 f"{total['wrong_caught']} | {total['wrong_passed']} | {total['missing']} | {total['located']} of "
                 f"{total['rules']} | {total['right_passage']} of {total['rules']} | |")
    correct = sum(r["counts"]["policy_correct_after_confirmation"] for r in rows)
    lines += ["", f"Documents for which a reviewer who accepts the verified values, supplies the others and gives the "
                  f"passage of any rule that was not located ends with exactly the intended policy: {correct} of "
                  f"{len(rows)}.", "",
              "\"Wrong, passed\" is the dangerous cell: a value that is not the document's, which the code check "
              "nevertheless accepted. Only the confirming person stands between it and the controls.", ""]
    notes = [(r["file"], d) for r in rows for d in r["details"]]
    if notes:
        lines += ["## Values that were not right and verified", "",
                  "| Document | Rule | Parameter | Proposed | Intended | Outcome | Reason given by the check |",
                  "|---|---|---|---|---|---|---|"]
        lines += [f"| `{f}` | {d['rule']} | {d['parameter']} | {json.dumps(d['proposed'])} | {json.dumps(d['intended'])} | "
                  f"{d['outcome'].replace('_', ' ')} | {d['reason']} |" for f, d in notes]
        lines.append("")
    lines += ["The six documents were written by the authors of the system and are short. This measures one model on "
              "them; it is not an estimate for policies in general.", ""]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "policy_llm.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8", newline="\n")
    (args.out / "policy_llm.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"wrote {args.out / 'policy_llm.md'}")


if __name__ == "__main__":
    main()
