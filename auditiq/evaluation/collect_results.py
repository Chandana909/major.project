"""Every measured result of the project in one machine-readable file: results/results.json.

    python -m evaluation.collect_results

The file is built only from the result files the experiments wrote (no number is
typed here), so that a person or a program can read every result in one request.
Each entry says what kind of number it is (measured, pilot or sample), the
question it answers, the files it comes from, with their public raw URLs, and
the command that produced them. RESULTS.md is the same content written for
people. A test checks that this file matches its sources.
"""
from __future__ import annotations

import json
import re

from auditiq.policy import PROJECT_ROOT

RESULTS = PROJECT_ROOT / "results"
OUT = RESULTS / "results.json"
REPOSITORY = "https://github.com/Chandana909/major.project"
RAW = "https://raw.githubusercontent.com/Chandana909/major.project/main/"
BENCHMARK = ["bench_seed_101", "bench_seed_202", "bench_seed_303"]
LEDGERS = BENCHMARK + ["large_seed_505"]
NUMBER = re.compile(r"^-?[\d,]*\.?\d+$")
CELL = re.compile(r"^(-?[\d.]+) \[(-?[\d.]+), (-?[\d.]+)\]$")


def source(path: str) -> dict:
    return {"path": f"auditiq/results/{path}", "raw_url": f"{RAW}auditiq/results/{path}"}


def load(path: str) -> dict:
    return json.loads((RESULTS / path).read_text(encoding="utf-8"))


def num(x):
    if isinstance(x, float):
        return round(x, 4)
    if isinstance(x, dict):
        return {k: num(v) for k, v in x.items()}
    if isinstance(x, list):
        return [num(v) for v in x]
    return x


def cell(text: str):
    """A cell of a markdown table: a number, a number with its interval, or the text."""
    text = text.strip().strip("`")
    if text in ("n/a", "-", "–", ""):
        return None
    found = CELL.match(text)
    if found:
        value, low, high = (float(g) for g in found.groups())
        return {"value": value, "ci_low": low, "ci_high": high}
    if NUMBER.match(text):
        value = float(text.replace(",", ""))
        return int(value) if value.is_integer() and "." not in text else value
    return text


def table(path: str, first_header: str) -> list[dict]:
    """The rows of the markdown table whose header row starts with ``first_header``."""
    lines = (RESULTS / path).read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"| {first_header} |"))
    names = [c.strip() for c in lines[start].strip("|").split("|")]
    rows = []
    for line in lines[start + 2:]:
        if not line.startswith("|"):
            break
        rows.append(dict(zip(names, (cell(c) for c in line.strip("|").split("|")))))
    return rows


def metric_table(path: str) -> dict:
    """A run_pilot report as {metric: {configuration: value}}."""
    out = {}
    for row in table(path, "Metric"):
        metric = row.pop("Metric")
        out[metric] = {re.sub(r"-.*$", "", k): v for k, v in row.items()}
    return out


# ------------------------------------------------------------------ entries
def detection() -> dict:
    ledgers = {}
    for name in LEDGERS:
        m = load(f"{name}/metrics.json")
        keep = ["detection_recall", "detection_precision", "detection_f1", "flagged_share", "fpr_ordinary",
                "fpr_hard_negative"]
        ledgers[name] = {
            "invoices": m["n_invoices"],
            "systems": {system: {k: values[k] for k in keep} for system, values in m["metrics"].items()},
            "share_of_each_class_detected": {system: {k.split(":", 1)[1]: v["value"] for k, v in values.items()
                                                      if k.startswith("detected:")}
                                             for system, values in m["metrics"].items()},
            "mcnemar_holm": {pair: {"only_C1_correct": t["only_a_correct"], "only_detector_correct": t["only_b_correct"],
                                    "p_holm": t["p_holm"]} for pair, t in m["mcnemar_detection"].items()},
            "construction_checks_passed": all(m["construction_checks"].values()),
        }
    mean = {system: {k: sum(ledgers[n]["systems"][system][k]["value"] for n in BENCHMARK) / len(BENCHMARK)
                     for k in ledgers[BENCHMARK[0]]["systems"][system]}
            for system in ledgers[BENCHMARK[0]]["systems"]}
    return {"label": "measured",
            "question": "How do the deterministic controls (C1) compare with an isolation forest and a one-class "
                        "SVM (C0, thresholds cross-fitted on other folds) at finding anomalous invoices?",
            "systems": {"C1": "policy-driven deterministic controls", "C0-IF": "isolation forest",
                        "C0-SVM": "one-class SVM"},
            "note": "95% bootstrap intervals over invoices, 1,000 resamples. The controls' perfect scores on the "
                    "rule-defined classes R1-R10 are by construction: they implement the rules by which these "
                    "anomalies were injected. J1-J4 are left to the language-model agents.",
            "mean_of_the_three_benchmark_ledgers": mean, "ledgers": ledgers,
            "sources": [source(f"{n}/metrics.json") for n in LEDGERS] + [source("summary.md")],
            "command": "python -m evaluation.run_all"}


def policy_change() -> dict:
    r = load("policy_change.json")
    variants = [{"version": v["version"], "policy": v["name"], "change": v["change"],
                 "values_read_correctly": f"{v['parameters_read_correctly']}/{v['parameters']}",
                 "rules_read_word_for_word": f"{v['rules_read_word_for_word']}/{v['rules']}",
                 "read_seconds": v["read_seconds"],
                 "policy_driven_wrong_decisions": v["driven"]["invoices"] - v["driven"]["exact"],
                 "frozen_wrong_decisions": v["frozen"]["invoices"] - v["frozen"]["exact"],
                 "frozen": {k: v["frozen"][k] for k in ("stale_findings", "missed_exceptions", "missed_escalations",
                                                         "needless_escalations")}}
                for v in r["variants"]]
    return {"label": "measured",
            "question": "When the organisation changes its policy and supplies only the new PDF, does the system "
                        "decide every invoice as the new policy requires, and how wrong is a system whose "
                        "thresholds are frozen at version 2.5?",
            "documents": len(variants), "invoices_per_document": r["invoices"], "invoice_audits": r["audits"],
            "values_read_correctly": f"{sum(v['parameters_read_correctly'] for v in r['variants'])}/"
                                     f"{sum(v['parameters'] for v in r['variants'])}",
            "rules_read_word_for_word": f"{sum(v['rules_read_word_for_word'] for v in r['variants'])}/"
                                        f"{sum(v['rules'] for v in r['variants'])}",
            "policy_driven_wrong_decisions": sum(v["policy_driven_wrong_decisions"] for v in variants),
            "frozen_worst_case": max(({"policy": v["policy"], "wrong_decisions": v["frozen_wrong_decisions"],
                                       "share": round(v["frozen_wrong_decisions"] / r["invoices"], 4)}
                                      for v in variants), key=lambda x: x["wrong_decisions"]),
            "audit_seconds_one_process": r["audit_seconds"], "variants": variants,
            "sources": [source("policy_change.json"), source("policy_change.md")],
            "command": "python -m evaluation.policy_change"}


def heldout() -> dict:
    r = load("policy_heldout.json")
    vs = r["variants"]
    return {"label": "measured",
            "question": "Does the reader work on policy values that played no part in building or checking it? "
                        "Twenty documents drawn at random (seed 2026), each changing one to five values.",
            "documents": len(vs), "adopted": sum(v["adopted"] for v in vs),
            "values_read_correctly": f"{sum(v['parameters_read_correctly'] for v in vs)}/{sum(v['parameters'] for v in vs)}",
            "rules_read_word_for_word": f"{sum(v['rules_read_word_for_word'] for v in vs)}/{sum(v['rules'] for v in vs)}",
            "invoice_audits": len(vs) * r["invoices"],
            "policy_driven_wrong_decisions": sum(v["driven"]["invoices"] - v["driven"]["exact"] for v in vs),
            "frozen_worst_case": max(({"version": v["version"], "change": v["change"],
                                       "wrong_decisions": v["frozen"]["invoices"] - v["frozen"]["exact"],
                                       "share": round((v["frozen"]["invoices"] - v["frozen"]["exact"]) / r["invoices"], 4)}
                                      for v in vs), key=lambda x: x["wrong_decisions"]),
            "variants": [{"version": v["version"], "change": v["change"], "adopted": v["adopted"],
                          "frozen_wrong_decisions": v["frozen"]["invoices"] - v["frozen"]["exact"]} for v in vs],
            "sources": [source("policy_heldout.json"), source("policy_heldout.md")],
            "command": "python -m evaluation.policy_heldout"}


def robustness() -> dict:
    docs = load("policy_robustness.json")["documents"]
    before = load("policy_robustness-before-fix.json")["documents"]
    return {"label": "measured",
            "question": "Does the reader either read an edited policy document correctly or refuse it?",
            "documents": len(docs), "handled_as_required": sum(d["as_required"] for d in docs),
            "handled_as_required_before_the_fix": sum(d["as_required"] for d in before),
            "edits": [{k: d[k] for k in ("id", "edit", "expected", "outcome", "as_required")} for d in docs],
            "note": "The first run found two ambiguous documents adopted (a rule stated twice; an approval table "
                    "without a role). Both checks were added to the reader with tests; both runs are kept.",
            "sources": [source("policy_robustness.json"), source("policy_robustness-before-fix.json")],
            "command": "python -m evaluation.policy_robustness"}


def application() -> dict:
    r = load("application_demo.json")
    return {"label": "measured",
            "question": "A policy change through the deployed path: the 20,000-invoice ledger in a database, "
                        "audited, the strict policy PDF adopted, audited again.",
            "ledger": r["ledger"], "store": r["store"], "adopted_version": r["adopted_version"],
            "before": r["before"], "after": r["after"], "seconds": r["seconds"], "changes": r["changes"],
            "sources": [source("application_demo.json"), source("application_demo.md")],
            "command": "python -m evaluation.application_demo"}


def ledger_runs() -> dict:
    r = load("ledger_runs.json")
    return {"label": "measured",
            "question": "What does the deployed system produce when each ledger of the project is loaded from an "
                        "Excel workbook and audited with the controls through the data store?",
            "policy_version": r["policy_version"], "configuration": r["configuration"], "ledgers": r["ledgers"],
            "sources": [source("ledger_runs.json"), source("ledger_runs.md")],
            "command": "python -m evaluation.ledger_runs"}


def scalability() -> dict:
    r = load("scalability.json")
    return {"label": "measured",
            "question": "How fast is the control stage, against worker processes and ledger size?",
            "machine": r["machine"], "logical_cpus": r["logical_cpus"], "by_workers": r["by_workers"],
            "by_size": r["by_size"],
            "note": "The control stage in memory on one laptop, median of three runs. A rerun under background load "
                    "gave the same findings with 21-36% lower throughput (RESULTS.md, Section 5).",
            "sources": [source("scalability.json"), source("scalability.md")],
            "command": "python -m evaluation.scalability"}


def own_wording() -> dict:
    r = load("policy_llm.json")
    return {"label": "measured",
            "question": "Policies written in their own wording: a local 7B model proposes the values, code verifies "
                        "each against the document, a person confirms. Six documents, 14 values each.",
            "model": r["model"], "total": r["total"],
            "documents": [{"file": d["file"], "style": d["style"], **d["counts"]} for d in r["documents"]],
            "sources": [source("policy_llm.json"), source("policy_llm.md")],
            "command": "python -m evaluation.policy_llm_eval"}


def retrieval() -> dict:
    return {"label": "measured",
            "question": "Policy search: recall of the right passage for 48 fixed questions (16 in the policy's "
                        "wording, 32 paraphrases split into dev and test).",
            "rows": table("retrieval.md", "Ranker"),
            "sources": [source("retrieval.md")], "command": "python -m evaluation.retrieval_eval --rewrite"}


def history_cap() -> dict:
    return {"label": "measured",
            "question": "Does the cap of 40 vendor-history invoices per rule hide an invoice that a labelled case "
                        "depends on?", "rows": table("history_cap.md", "Dataset"),
            "sources": [source("history_cap.md")], "command": "python -m evaluation.history_cap"}


def model_runs(path: str, label: str, question: str, command: str) -> dict:
    return {"label": label, "question": question, "configurations": {
                "C1": "controls only", "C2": "one LLM prompt, no controls", "C3": "controls and three agents",
                "C4": "C3 and the challenger", "C5": "C4 and confidence (sampled review)"},
            "metrics": metric_table(path), "sources": [source(path)], "command": command,
            "note": "Too few invoices to compare configurations: no difference between them is significant."}


def build() -> dict:
    return {
        "title": "AuditIQ: every measured result, machine-readable",
        "repository": REPOSITORY,
        "for_people": {"path": "RESULTS.md", "raw_url": f"{RAW}RESULTS.md"},
        "full_report": {"path": "REPORT.md", "raw_url": f"{RAW}REPORT.md",
                        "about": "methodology, every result in detail, per-invoice analysis, threats to validity"},
        "paper": {"path": "paper/auditiq_paper.pdf", "url": f"{REPOSITORY}/blob/main/paper/auditiq_paper.pdf"},
        "labels": {"measured": "a script of the repository produced it on the data stated",
                   "pilot": "measured on 20 invoices of the development ledger; shows that the stages work",
                   "sample": "measured on 34 invoices of benchmark ledger 101; too small to compare configurations",
                   "expected": "targets fixed before measurement; not results (RESULTS.md, Section 10)"},
        "data": "Synthetic ledgers of AuditIQ-Bench (auditiq/data/): three benchmark ledgers of 5,000 invoices "
                "(8.4% anomalous), a policy-swap ledger, a development ledger and a large ledger of 20,000 invoices.",
        "results": num({
            "controls_against_classical_detectors": detection(),
            "policy_change": policy_change(),
            "held_out_policy_documents": heldout(),
            "robustness_of_the_reader": robustness(),
            "policy_change_in_the_application": application(),
            "every_ledger_through_the_deployed_system": ledger_runs(),
            "scalability_of_the_control_stage": scalability(),
            "policies_in_their_own_wording": own_wording(),
            "policy_search": retrieval(),
            "vendor_history_cap": history_cap(),
            "llm_stages_pilot_20_invoices": model_runs(
                "pilot_seed_909/pilot20.md", "pilot", "The five configurations with a local 7B model on 20 invoices "
                "of the development ledger.", "python -m evaluation.run_pilot --dataset data/pilot_seed_909 "
                "--ids-file evaluation/pilot_ids.txt --tag pilot20"),
            "llm_stages_sample_34_invoices": model_runs(
                "bench_seed_101/sample34.md", "sample", "The five configurations with a local 7B model and frozen "
                "prompts on 34 invoices of benchmark ledger 101.", "python -m evaluation.run_pilot --dataset "
                "data/bench_seed_101 --ids-file evaluation/bench101_sample_ids.txt --tag sample34"),
        }),
    }


def main() -> None:
    OUT.write_text(json.dumps(build(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
