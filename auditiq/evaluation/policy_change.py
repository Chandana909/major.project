"""The policy-change experiment: does the audit follow the organisation's policy document?

    python -m evaluation.policy_change

An organisation changes its policy: a tighter tolerance, a lower approval limit,
a six-day working week. This experiment gives the system nothing but the new
policy *document* and measures whether its decisions are the ones the new
policy requires, on every invoice of five ledgers.

For each policy variant below:

1. The variant's registry is rendered to the policy text and to a PDF, as an
   organisation would issue it.
2. The system reads the PDF (auditiq/policy_extract.py), extracts every
   threshold from the wording of the rules, and builds the registry it will
   execute. The extracted parameters are compared with the intended ones.
3. Every invoice of every ledger is audited with the deterministic controls
   under the extracted registry ("policy-driven").
4. The same invoices are audited with the thresholds of the reference version
   2.5 ("frozen"): the behaviour of a system whose thresholds are written into
   prompts and tool code, as in the prototype this project started from.
5. The ground truth under the variant is recomputed from the ledger tables by
   auditiq_bench/validate.py, which belongs to the dataset generator and shares
   no code with the controls.

Policy adherence is the share of invoices for which the set of cited rules
equals the ground truth of the variant. Writes results/policy_change.md,
results/policy_change.json, results/policy_change_table.tex and the variant
PDFs to policy/variants/.

Reading the result: the controls and the ground truth are two implementations
of the same written rules by the same authors, so full adherence is a check
that they agree and that the document was read correctly; it is not a detection
result. The measured quantities that are not fixed by construction are how many
decisions a policy change moves, and therefore how wrong a frozen system is.
"""
from __future__ import annotations

import argparse
import json
import platform
import time
from pathlib import Path

import pandas as pd

from auditiq import policy_extract, scoring
from auditiq.controls import run_controls
from auditiq.extraction import extract
from auditiq.policy import PROJECT_ROOT, clause_texts, derive_policy, load_policy, load_template, render_policy_text
from auditiq.policy_pdf import write_pdf
from auditiq_bench.validate import rule_clauses

LEDGERS = ["bench_seed_101", "bench_seed_202", "bench_seed_303", "swap_seed_404", "large_seed_505"]
TABLES = ["vendor_master", "purchase_orders", "goods_receipts", "invoices", "approval_logs"]
REFERENCE = "2.5"

# (version, short name, what changes, overrides). Single changes first, then three whole policies.
VARIANTS = [
    ("3.01", "Tolerance 0.5%", "amount tolerance 1% to 0.5%", {"2.1.1": {"amount_tolerance_pct": 0.5}}),
    ("3.02", "Tolerance 2%", "amount tolerance 1% to 2%", {"2.1.1": {"amount_tolerance_pct": 2.0}}),
    ("3.03", "Tolerance 5%", "amount tolerance 1% to 5%", {"2.1.1": {"amount_tolerance_pct": 5.0}}),
    ("3.04", "Daily count 2", "invoices per vendor per day 3 to 2", {"4.1.1": {"max_invoices_per_vendor_per_day": 2}}),
    ("3.05", "Daily count 5", "invoices per vendor per day 3 to 5", {"4.1.1": {"max_invoices_per_vendor_per_day": 5}}),
    ("3.06", "Manager limit 50,000", "Manager approval limit 100,000 to 50,000",
     {"5.1.1": {"approval_limits": {"Manager": 50000}}}),
    ("3.07", "Manager limit 150,000", "Manager approval limit 100,000 to 150,000",
     {"5.1.1": {"approval_limits": {"Manager": 150000}}}),
    ("3.08", "Senior Manager limit 250,000", "Senior Manager approval limit 500,000 to 250,000",
     {"5.1.1": {"approval_limits": {"Senior Manager": 250000}}}),
    ("3.09", "Round multiple 5,000", "round-amount multiple 10,000 to 5,000", {"4.3.1": {"round_amount_multiple": 5000}}),
    ("3.10", "Round multiple 50,000", "round-amount multiple 10,000 to 50,000",
     {"4.3.1": {"round_amount_multiple": 50000}}),
    ("3.11", "Six-day week", "Saturday becomes a business day", {"4.2.1": {"non_business_days": ["Sunday"]}}),
    ("3.12", "Strict policy", "tolerance 0.5%, daily count 2, Manager 50,000, Senior Manager 250,000, round multiple 5,000",
     {"2.1.1": {"amount_tolerance_pct": 0.5}, "4.1.1": {"max_invoices_per_vendor_per_day": 2},
      "5.1.1": {"approval_limits": {"Manager": 50000, "Senior Manager": 250000}},
      "4.3.1": {"round_amount_multiple": 5000}}),
    ("3.13", "Lenient policy", "tolerance 5%, daily count 5, Manager 150,000, six-day week, round multiple 50,000",
     {"2.1.1": {"amount_tolerance_pct": 5.0}, "4.1.1": {"max_invoices_per_vendor_per_day": 5},
      "5.1.1": {"approval_limits": {"Manager": 150000}}, "4.2.1": {"non_business_days": ["Sunday"]},
      "4.3.1": {"round_amount_multiple": 50000}}),
    ("3.14", "Version 2.6", "tolerance 5%, daily count 5, Manager 150,000 (the policy-swap version)",
     {"2.1.1": {"amount_tolerance_pct": 5.0}, "4.1.1": {"max_invoices_per_vendor_per_day": 5},
      "5.1.1": {"approval_limits": {"Manager": 150000}}}),
]


def load_tables(dataset: Path) -> dict[str, pd.DataFrame]:
    """The ledger tables as the validator of the generator expects them."""
    tables = {name: pd.read_csv(dataset / f"{name}.csv", dtype=str, keep_default_na=False) for name in TABLES}
    tables["vendor_master"]["blacklisted"] = tables["vendor_master"]["blacklisted"] == "True"
    return tables


def count_parameters(registry: dict) -> int:
    """Number of values a policy states: every parameter, with the limit of each role counted once."""
    return sum(len(v) if isinstance(v, dict) else 1 for c in registry["clauses"].values() for v in c["params"].values())


def matching_parameters(read: dict, intended: dict) -> int:
    same = 0
    for clause, spec in intended["clauses"].items():
        got = read["clauses"].get(clause, {}).get("params", {})
        for name, value in spec["params"].items():
            if isinstance(value, dict):
                same += sum(got.get(name, {}).get(role) == limit for role, limit in value.items())
            else:
                same += got.get(name) == value
    return same


def route_of(clauses: set[str], registry: dict) -> str:
    """Route of an invoice with these findings under the count-based score."""
    flags = [{"severity": registry["clauses"][k]["severity"], "confidence": 1.0} for k in clauses]
    return scoring.route(scoring.count_score(flags), scoring.count_score(flags))


def controls_decisions(transactions: list[dict], registry: dict) -> dict[str, set[str]]:
    return {t["invoice"]["invoice_id"]: {f["clause"] for f in run_controls(t, registry["clauses"])} for t in transactions}


def compare(decided: dict[str, set[str]], truth: dict[str, set[str]], registry: dict) -> dict:
    """How a set of decisions stands against the ground truth of one policy."""
    exact = stale = missed = needless = unescalated = 0
    for invoice_id, want in truth.items():
        got = decided[invoice_id]
        exact += got == want
        stale += len(got - want)                    # findings the policy does not support
        missed += len(want - got)                   # exceptions of the policy that were not raised
        route_got, route_want = route_of(got, registry), route_of(want, registry)
        needless += route_got == "escalate" and route_want == "approve"
        unescalated += route_got == "approve" and route_want == "escalate"
    return {"invoices": len(truth), "exact": exact, "stale_findings": stale, "missed_exceptions": missed,
            "needless_escalations": needless, "missed_escalations": unescalated}


def add(total: dict, part: dict) -> None:
    for key, value in part.items():
        total[key] = total.get(key, 0) + value


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=PROJECT_ROOT / "data")
    ap.add_argument("--out", type=Path, default=PROJECT_ROOT / "results")
    ap.add_argument("--pdfs", type=Path, default=PROJECT_ROOT / "policy" / "variants")
    ap.add_argument("--from-json", action="store_true", help="rewrite the report, the table and the figure from "
                                                             "results/policy_change.json without auditing again")
    args = ap.parse_args()
    if args.from_json:
        write_outputs(json.loads((args.out / "policy_change.json").read_text(encoding="utf-8")), args.out)
        return

    base = load_policy(REFERENCE).registry
    template = load_template()

    # 1 and 2: every variant as a document, and what the system reads from it.
    documents = []
    for version, name, change, overrides in VARIANTS:
        intended = derive_policy(base, version, "2026-04-01", overrides)
        text = render_policy_text(intended, template)
        pdf = write_pdf(text, args.pdfs / f"Company_Policy_v{version}.pdf", f"{intended['policy_name']}, version {version}",
                        f"{intended['policy_name']} | version {version}")
        began = time.perf_counter()
        read = policy_extract.build(pdf, base)
        seconds = time.perf_counter() - began
        rules_in_text = clause_texts(text)
        rules_read = clause_texts(read.text)
        documents.append({
            "version": version, "name": name, "change": change, "intended": intended, "read": read.registry,
            "problems": read.problems, "pages": read.pages, "read_seconds": round(seconds, 3),
            "parameters": count_parameters(intended), "parameters_read_correctly": matching_parameters(read.registry, intended),
            "rules": len(rules_in_text), "rules_read_word_for_word": sum(rules_read.get(k) == v for k, v in rules_in_text.items()),
            "parameters_changed": len(read.changes),
        })
        print(f"v{version} {name}: {documents[-1]['parameters_read_correctly']}/{documents[-1]['parameters']} parameters, "
              f"{documents[-1]['rules_read_word_for_word']}/{documents[-1]['rules']} rules read from the PDF", flush=True)

    # 3 to 5: audit every ledger under every variant.
    rows = {d["version"]: {"driven": {}, "frozen": {}, "affected": 0, "per_ledger": {}} for d in documents}
    reference_check, audit_seconds, audited = {}, 0.0, 0
    for ledger in LEDGERS:
        dataset = args.data / ledger
        tables, transactions = load_tables(dataset), extract(dataset)
        truth_reference = rule_clauses(tables, base)
        frozen = controls_decisions(transactions, base)
        reference_check[ledger] = compare(frozen, truth_reference, base)
        for d in documents:
            truth = rule_clauses(tables, d["intended"])
            began = time.perf_counter()
            driven = controls_decisions(transactions, d["read"])
            audit_seconds += time.perf_counter() - began
            audited += len(transactions)
            affected = sum(truth[i] != truth_reference[i] for i in truth)
            a, b = compare(driven, truth, d["intended"]), compare(frozen, truth, d["intended"])
            row = rows[d["version"]]
            add(row["driven"], a)
            add(row["frozen"], b)
            row["affected"] += affected
            row["per_ledger"][ledger] = {"affected": affected, "driven": a, "frozen": b}
        print(f"{ledger}: {len(transactions):,} invoices audited under {len(documents)} policies", flush=True)

    invoices = sum(r["invoices"] for r in reference_check.values())
    result = {
        "produced": time.strftime("%Y-%m-%d %H:%M"), "reference_version": REFERENCE, "ledgers": LEDGERS,
        "invoices": invoices, "machine": f"{platform.processor() or platform.machine()}, Python {platform.python_version()}",
        "reference_check": reference_check, "audit_seconds": round(audit_seconds, 1), "audits": audited,
        "variants": [{k: v for k, v in d.items() if k not in ("intended", "read")} | rows[d["version"]] for d in documents],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "policy_change.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8", newline="\n")
    write_outputs(result, args.out)


def write_outputs(result: dict, out: Path) -> None:
    (out / "policy_change.md").write_text(report(result), encoding="utf-8", newline="\n")
    (out / "policy_change_table.tex").write_text(latex_table(result), encoding="utf-8", newline="\n")
    figure(result, out / "policy_change.pdf")
    figure(result, out / "policy_change.png")
    print(f"wrote {out / 'policy_change.md'}, policy_change_table.tex, policy_change.pdf, policy_change.png")


def figure(r: dict, path: Path) -> None:
    """Share of invoices a frozen system decides wrongly under each policy, one bar per policy."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n = r["invoices"]
    rows = sorted(((v["name"], 100 * (n - v["frozen"]["exact"]) / n, n - v["frozen"]["exact"]) for v in r["variants"]),
                  key=lambda row: row[1])
    names, shares, counts = zip(*rows)
    fig, ax = plt.subplots(figsize=(3.5, 3.0))
    bars = ax.barh(names, shares, color="#2a78d6", height=0.68)
    for bar, share, count in zip(bars, shares, counts):
        ax.text(bar.get_width() + 0.6, bar.get_y() + bar.get_height() / 2, f"{share:.1f}%  ({count:,})",
                va="center", ha="left", fontsize=6.5, color="#222222")
    ax.set_xlim(0, max(shares) * 1.5)
    ax.set_xlabel("Invoices decided against the policy in force (%)", fontsize=7)
    ax.tick_params(axis="both", labelsize=6.5, length=0)
    ax.xaxis.grid(True, color="#dddddd", linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#999999")
    fig.tight_layout()
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def pct(part: int, whole: int) -> str:
    return f"{part / whole:.3f}" if whole else "n/a"


def report(r: dict) -> str:
    n = r["invoices"]
    check = r["reference_check"]
    lines = [
        "# Policy-change experiment", "",
        f"Produced by `python -m evaluation.policy_change` on {r['produced']}. Reference policy: version "
        f"{r['reference_version']}. Ledgers: {', '.join('`' + name + '`' for name in r['ledgers'])}; {n:,} invoices in all. "
        "No language model is used anywhere in this experiment.", "",
        "For each policy variant the system is given only the policy PDF. It reads the thresholds from the wording "
        "of the rules, builds the registry it executes, and audits every invoice with the deterministic controls "
        "(\"policy-driven\"). \"Frozen\" is the same controls with the thresholds of the reference version, which is "
        "how a system behaves whose thresholds are written into prompts and tool code. The ground truth under each "
        "variant is recomputed from the ledger tables by the dataset generator's validator, which shares no code "
        "with the controls.", "",
        "## 1. Reading the policy documents", "",
        "| Version | Policy | What changes | Pages | Parameters read correctly | Rules read word for word | Seconds to read |",
        "|---|---|---|---|---|---|---|",
    ]
    for v in r["variants"]:
        lines.append(f"| {v['version']} | {v['name']} | {v['change']} | {v['pages']} | "
                     f"{v['parameters_read_correctly']} of {v['parameters']} | {v['rules_read_word_for_word']} of "
                     f"{v['rules']} | {v['read_seconds']:.2f} |")
    total_p = sum(v["parameters"] for v in r["variants"])
    read_p = sum(v["parameters_read_correctly"] for v in r["variants"])
    total_r = sum(v["rules"] for v in r["variants"])
    read_r = sum(v["rules_read_word_for_word"] for v in r["variants"])
    problems = sum(len(v["problems"]) for v in r["variants"])
    lines += ["", f"Over the {len(r['variants'])} documents: {read_p} of {total_p} parameter values and {read_r} of "
                  f"{total_r} rules were read correctly; {problems} problem(s) were reported.", "",
              "## 2. Adherence to the policy in force", "",
              "An invoice is decided correctly when the set of rules cited for it equals the ground truth of the "
              "policy in force. \"Decisions the change moves\" is the number of invoices whose ground truth under "
              "the variant differs from their ground truth under the reference version.", "",
              f"Under the reference version itself the controls agree with the independent recomputation on "
              f"{sum(c['exact'] for c in check.values()):,} of {n:,} invoices.", "",
              "| Policy | Decisions the change moves | Policy-driven: adherence | Frozen: adherence | Frozen: findings the "
              "policy no longer supports | Frozen: exceptions not raised | Frozen: needless escalations | Frozen: "
              "missed escalations |", "|---|---|---|---|---|---|---|---|"]
    for v in r["variants"]:
        d, f = v["driven"], v["frozen"]
        lines.append(f"| {v['name']} | {v['affected']:,} ({v['affected'] / n:.1%}) | {pct(d['exact'], n)} "
                     f"({d['exact']:,} of {n:,}) | {pct(f['exact'], n)} | {f['stale_findings']:,} | "
                     f"{f['missed_exceptions']:,} | {f['needless_escalations']:,} | {f['missed_escalations']:,} |")
    wrong = sum(n - v["driven"]["exact"] for v in r["variants"])
    lines += ["", f"Policy-driven controls: {wrong} wrong decision(s) in {len(r['variants']) * n:,} invoice audits. "
                  f"Auditing took {r['audit_seconds']:.0f} s for {r['audits']:,} invoice audits "
                  f"({r['audits'] / max(r['audit_seconds'], 1e-9):,.0f} invoices per second, one process; {r['machine']}).",
              "",
              "A needless escalation is an invoice the frozen system sends to a reviewer although the policy in force "
              "would approve it; a missed escalation is one it approves although the policy in force requires review "
              "(count-based score, threshold 50).", "",
              "## 3. By ledger", "",
              "| Policy | " + " | ".join(f"`{name}`: moved" for name in r["ledgers"]) + " |",
              "|---|" + "---|" * len(r["ledgers"])]
    for v in r["variants"]:
        lines.append(f"| {v['name']} | " + " | ".join(f"{v['per_ledger'][name]['affected']:,}" for name in r["ledgers"]) + " |")
    lines += ["", "## How to read this", "",
              "- Full adherence of the policy-driven controls is a check, not a discovery: the controls and the "
              "ground truth are two implementations of the same written rules, and they agree. What the check "
              "establishes is that the thresholds were read correctly from each document and that no control keeps "
              "a threshold of its own.",
              "- The numbers that are not fixed by construction are the columns for the frozen system: they measure "
              "how many decisions an ordinary policy revision moves in these ledgers, and so the size of the error "
              "of any system that has to be edited by hand to follow the policy.",
              "- The documents follow the wording of the SOP template. A policy written in other words is refused "
              "with the list of rules and thresholds that could not be read; it is not guessed at.",
              "- The ledgers are synthetic. The counts say how these ledgers react to these changes, not how a "
              "particular company's books would.", ""]
    return "\n".join(lines)


def latex_table(r: dict) -> str:
    n = r["invoices"]
    lines = ["% Generated by python -m evaluation.policy_change; do not edit by hand.",
             r"\begin{tabular}{L{4.2cm}rrrrrr}", r"\toprule",
             r"Policy variant & Decisions moved & \multicolumn{1}{c}{Policy-driven} & \multicolumn{4}{c}{Frozen at v"
             + r["reference_version"] + r"} \\", r"\cmidrule(lr){3-3}\cmidrule(lr){4-7}",
             r" & & Adherence & Adherence & Unsupported findings & Missed exceptions & Missed escalations \\", r"\midrule"]
    for v in r["variants"]:
        d, f = v["driven"], v["frozen"]
        lines.append(f"{v['name'].replace('%', chr(92) + '%')} & {v['affected']:,} & {pct(d['exact'], n)} & "
                     f"{pct(f['exact'], n)} & {f['stale_findings']:,} & {f['missed_exceptions']:,} & "
                     f"{f['missed_escalations']:,} " + r"\\")
    lines += [r"\bottomrule", r"\end{tabular}", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
