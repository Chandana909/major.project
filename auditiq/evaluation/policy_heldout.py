"""Held-out policy documents: the policy-change experiment on variants drawn at random.

    python -m evaluation.policy_heldout

The fourteen variants of evaluation.policy_change were written by hand. This
script draws twenty further variants at random, with a fixed seed, from ranges
of values none of which was used to build or check the reader: each variant
changes between one and five values (tolerance, daily count, round-amount
multiple, non-business days, blocked registration statuses, the limit of any of
the four approver roles, and the two guide values of the judgement rule 4.1.2).
Every variant is rendered as a PDF, read back by the system, and applied with
the deterministic controls to every invoice of the five ledgers; the ground
truth is recomputed by the dataset generator's validator, as in the
policy-change experiment.

The GSTIN length and the state-code range are not varied: the validator
recomputes those rules with fixed values, so a variant that changed them could
not be checked.

Writes results/policy_heldout.md, results/policy_heldout.json and the PDFs to
policy/variants_heldout/. No language model is used.
"""
from __future__ import annotations

import argparse
import json
import platform
import time
from pathlib import Path

import numpy as np

from auditiq import policy_extract
from auditiq.extraction import extract
from auditiq.policy import PROJECT_ROOT, clause_texts, derive_policy, load_policy, load_template, render_policy_text
from auditiq.policy_pdf import write_pdf
from auditiq_bench.validate import rule_clauses

from .policy_change import (
    LEDGERS,
    REFERENCE,
    add,
    compare,
    controls_decisions,
    count_parameters,
    load_tables,
    matching_parameters,
)

SEED = 2026
COUNT = 20
ROLES = ["Manager", "Senior Manager", "Director", "CFO"]
# Values never used by the hand-written variants or by the tests of the reader.
CHOICES = {
    "tolerance": ("2.1.1", "amount_tolerance_pct", [0.25, 0.75, 1.5, 2.5, 3.0, 4.0]),
    "daily": ("4.1.1", "max_invoices_per_vendor_per_day", [1, 4, 6, 8]),
    "multiple": ("4.3.1", "round_amount_multiple", [1000, 2000, 25000, 100000]),
    "days": ("4.2.1", "non_business_days", [["Saturday"], ["Friday", "Saturday"], ["Sunday"]]),
    "blocked": ("4.4.1", "blocked_gstin_statuses", [["Suspended", "Cancelled"]]),
    "guide_days": ("4.1.2", "guide_window_days", [5, 10, 14]),
    "guide_band": ("4.1.2", "guide_band_pct", [10, 20, 25]),
}
LIMITS = {"Manager": [75000, 125000, 200000], "Senior Manager": [300000, 400000, 750000],
          "Director": [1500000, 2000000, 5000000], "CFO": [5000000, 20000000]}


def draw_variants(base: dict, count: int = COUNT, seed: int = SEED) -> list[tuple[str, str, dict]]:
    """``count`` variants as (version, description, overrides), each changing one to five values."""
    rng = np.random.default_rng(seed)
    slots = list(CHOICES) + [f"limit:{role}" for role in ROLES]
    variants = []
    for i in range(count):
        overrides: dict[str, dict] = {}
        words = []
        k = int(rng.integers(1, 6))
        for slot in rng.choice(slots, size=k, replace=False):
            if slot.startswith("limit:"):
                role = slot.split(":", 1)[1]
                limits = dict(base["clauses"]["5.1.1"]["params"]["approval_limits"])
                limits.update(overrides.get("5.1.1", {}).get("approval_limits", {}))
                value = int(rng.choice(LIMITS[role]))
                limits[role] = value
                if [limits[r] for r in ROLES] != sorted(limits[r] for r in ROLES):
                    continue                                  # an approver may never have a higher limit than the next
                overrides.setdefault("5.1.1", {}).setdefault("approval_limits", {})[role] = value
                words.append(f"{role} limit {value:,}")
            else:
                clause, name, values = CHOICES[slot]
                value = values[int(rng.integers(len(values)))]
                value = value.item() if hasattr(value, "item") else value
                overrides.setdefault(clause, {})[name] = value
                words.append(f"{name} {value}")
        if not overrides:                                     # every draw was refused: change the tolerance
            overrides = {"2.1.1": {"amount_tolerance_pct": 1.5}}
            words = ["amount_tolerance_pct 1.5"]
        variants.append((f"4.{i + 1:02d}", "; ".join(words), overrides))
    return variants


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=PROJECT_ROOT / "data")
    ap.add_argument("--out", type=Path, default=PROJECT_ROOT / "results")
    ap.add_argument("--pdfs", type=Path, default=PROJECT_ROOT / "policy" / "variants_heldout")
    args = ap.parse_args()

    base = load_policy(REFERENCE).registry
    template = load_template()
    documents = []
    for version, change, overrides in draw_variants(base):
        intended = derive_policy(base, version, "2026-10-01", overrides)
        text = render_policy_text(intended, template)
        pdf = write_pdf(text, args.pdfs / f"Company_Policy_v{version}.pdf", f"{intended['policy_name']}, version {version}",
                        f"{intended['policy_name']} | version {version}")
        read = policy_extract.build(pdf, base)
        rules_in_text, rules_read = clause_texts(text), clause_texts(read.text)
        documents.append({
            "version": version, "change": change, "intended": intended, "read": read.registry,
            "problems": read.problems, "adopted": read.usable,
            "parameters": count_parameters(intended),
            "parameters_read_correctly": matching_parameters(read.registry, intended) if read.registry else 0,
            "rules": len(rules_in_text),
            "rules_read_word_for_word": sum(rules_read.get(k) == v for k, v in rules_in_text.items()),
        })
        d = documents[-1]
        print(f"v{version}: {d['parameters_read_correctly']}/{d['parameters']} values, "
              f"{d['rules_read_word_for_word']}/{d['rules']} rules, {'adopted' if d['adopted'] else 'refused'}", flush=True)

    rows = {d["version"]: {"driven": {}, "frozen": {}, "affected": 0} for d in documents}
    invoices = 0
    for ledger in LEDGERS:
        dataset = args.data / ledger
        tables, transactions = load_tables(dataset), extract(dataset)
        truth_reference = rule_clauses(tables, base)
        frozen = controls_decisions(transactions, base)
        invoices += len(transactions)
        for d in documents:
            truth = rule_clauses(tables, d["intended"])
            row = rows[d["version"]]
            if d["adopted"]:
                add(row["driven"], compare(controls_decisions(transactions, d["read"]), truth, d["intended"]))
            add(row["frozen"], compare(frozen, truth, d["intended"]))
            row["affected"] += sum(truth[i] != truth_reference[i] for i in truth)
        print(f"{ledger}: {len(transactions):,} invoices audited under {len(documents)} policies", flush=True)

    result = {"produced": time.strftime("%Y-%m-%d %H:%M"), "seed": SEED, "reference_version": REFERENCE,
              "ledgers": LEDGERS, "invoices": invoices,
              "machine": f"{platform.processor() or platform.machine()}, Python {platform.python_version()}",
              "variants": [{k: v for k, v in d.items() if k not in ("intended", "read")} | rows[d["version"]]
                           for d in documents]}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "policy_heldout.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8", newline="\n")
    (args.out / "policy_heldout.md").write_text(report(result), encoding="utf-8", newline="\n")
    print(f"wrote {args.out / 'policy_heldout.md'}")


def report(r: dict) -> str:
    n = r["invoices"]
    v = r["variants"]
    adopted = [x for x in v if x["adopted"]]
    lines = [
        "# Held-out policy documents", "",
        f"Produced by `python -m evaluation.policy_heldout` on {r['produced']}. {len(v)} policy variants drawn at random "
        f"(seed {r['seed']}) from values that were not used to build or check the reader; each is applied to the "
        f"{n:,} invoices of {len(r['ledgers'])} ledgers. Reference policy: version {r['reference_version']}. "
        "No language model is used.", "",
        "| Version | What changes | Values read correctly | Rules read word for word | Adopted | "
        "Decisions the change moves | Policy-driven: adherence | Frozen: adherence |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for x in v:
        driven = f"{x['driven']['exact'] / n:.3f}" if x["adopted"] else "refused"
        lines.append(f"| {x['version']} | {x['change']} | {x['parameters_read_correctly']} of {x['parameters']} | "
                     f"{x['rules_read_word_for_word']} of {x['rules']} | {'yes' if x['adopted'] else 'no'} | "
                     f"{x['affected']:,} ({x['affected'] / n:.1%}) | {driven} | {x['frozen']['exact'] / n:.3f} |")
    read_p, total_p = sum(x["parameters_read_correctly"] for x in v), sum(x["parameters"] for x in v)
    read_r, total_r = sum(x["rules_read_word_for_word"] for x in v), sum(x["rules"] for x in v)
    wrong = sum(n - x["driven"]["exact"] for x in adopted)
    worst = max(v, key=lambda x: n - x["frozen"]["exact"])
    lines += ["", "## Summary", "",
              f"- Reading: {read_p} of {total_p} values and {read_r} of {total_r} rules were read correctly; "
              f"{len(adopted)} of {len(v)} documents were adopted"
              + ("." if len(adopted) == len(v) else
                 "; the others were refused with these reasons: "
                 + "; ".join(f"v{x['version']}: {', '.join(x['problems'])}" for x in v if not x["adopted"]) + "."),
              f"- Policy-driven controls: {wrong} wrong decision(s) in {len(adopted) * n:,} invoice audits.",
              f"- Frozen at version {r['reference_version']}: the worst variant (v{worst['version']}: {worst['change']}) "
              f"decides {n - worst['frozen']['exact']:,} invoices ({(n - worst['frozen']['exact']) / n:.1%}) against "
              f"the policy in force.", "",
              "The variants are synthetic and follow the template wording; this checks that the reader and the controls "
              "follow values they were not developed on. It is not a test of policies written in other words "
              "(see `policy_llm.md`).", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
