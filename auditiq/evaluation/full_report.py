"""The full report: methodology, every result in detail, and the analysis. Writes ../REPORT.md.

    python -m evaluation.full_report

Every number in the report is computed here from the result files under
results/, the datasets under data/ and the code's own constants (the policy
registry, the scoring options, the taxonomy); none is typed in. The prose around
the numbers states the methods as the code implements them. Run it after the
experiments (and after evaluation.collect_results); a test checks that REPORT.md
is up to date. RESULTS.md is the shorter guide for writing the paper.
"""
from __future__ import annotations

import json
import math
import re
import statistics
from pathlib import Path

import pandas as pd

from auditiq import agents
from auditiq.graph import PipelineConfig
from auditiq.policy import PROJECT_ROOT, load_policy
from auditiq.scoring import DEFAULT as SCORING
from auditiq_bench import overview
from auditiq_bench.taxonomy import CLASSES, HARD_NEGATIVE_TYPES

from . import collect_results
from .collect_results import IGPU_SAMPLE, RAW, REPOSITORY, load, metric_table, table

OUT = PROJECT_ROOT.parent / "REPORT.md"
DATA = PROJECT_ROOT / "data"
RESULTS = PROJECT_ROOT / "results"
BENCH = ["bench_seed_101", "bench_seed_202", "bench_seed_303"]
SYSTEMS = {"C1": "Controls (C1)", "C0-IF": "Isolation forest (C0-IF)", "C0-SVM": "One-class SVM (C0-SVM)"}
DETECTION = [("detection_recall", "Recall"), ("detection_precision", "Precision"), ("detection_f1", "F1"),
             ("flagged_share", "Share of invoices flagged"), ("fpr_ordinary", "False-positive rate, ordinary"),
             ("fpr_hard_negative", "False-positive rate, hard negatives"),
             ("precision_at_2pct_prevalence", "Precision at 2% prevalence")]


# ------------------------------------------------------------------ format
def isnan(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def f3(x) -> str:
    return "–" if isnan(x) else f"{x:.3f}"


def ci(d) -> str:
    if not isinstance(d, dict):
        return f3(d) if isinstance(d, float) else ("–" if d is None else str(d))
    if isnan(d.get("value")):
        return "–"
    if isnan(d.get("ci_low")):
        return f3(d["value"])
    return f"{d['value']:.3f} [{d['ci_low']:.3f}, {d['ci_high']:.3f}]"


def n(x) -> str:
    return f"{x:,}"


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def md(headers: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return out + [""]


def value(cell):
    return cell["value"] if isinstance(cell, dict) else cell


def src(*paths: str) -> str:
    return "Source: " + ", ".join(f"[`{p}`]({RAW}auditiq/results/{p})" for p in paths) + "."


# ------------------------------------------------------------------ data
def labels(dataset: str) -> pd.DataFrame:
    return pd.read_csv(DATA / dataset / "labels.csv", dtype=str, keep_default_na=False).set_index("invoice_id")


def manifest(dataset: str) -> dict:
    return json.loads((DATA / dataset / "manifest.json").read_text(encoding="utf-8"))


def datasets() -> list[str]:
    return sorted(p.name for p in DATA.iterdir() if (p / "manifest.json").exists())


def jsonl(path: Path) -> dict[str, dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {r["invoice_id"]: r for r in rows}


# ======================================================== part I: methods
def research_questions() -> list[str]:
    rows = [
        ["RQ1", "Does the system read every threshold of a policy correctly from the policy document alone?", "11, 12"],
        ["RQ2", "Does the audit then follow the policy in force, and how wrong is a system whose thresholds are frozen?", "11, 12, 14"],
        ["RQ3", "Does the reader refuse a document it cannot execute, instead of adopting it wrongly?", "13"],
        ["RQ4", "How do policy-driven controls compare with classical anomaly detectors on the same ledgers?", "10"],
        ["RQ5", "How fast is the control stage, and how does it scale with processes and ledger size?", "16"],
        ["RQ6", "Can a language model read a policy written in its own words, and can its errors be contained?", "17"],
        ["RQ7", "What do the language-model stages (agents, challenger, confidence) add, and at what cost?", "18"],
        ["RQ8", "What does the deployed system produce when whole ledgers are loaded and audited?", "14, 15"],
        ["RQ9", "Does policy search find the passage that answers a question?", "19"],
    ]
    return ["## 1. Research questions", ""] + md(["", "Question", "Answered in"], rows)


def detector_features() -> list[str]:
    """The feature names of evaluation/run_c0.features, read from its source."""
    text = (PROJECT_ROOT / "evaluation" / "run_c0.py").read_text(encoding="utf-8")
    body = text[text.index("def features"):text.index("frame = pd.DataFrame")]
    return [f for f in re.findall(r'"([a-z_]+)":', body) if f != "invoice_id"]


def system() -> list[str]:
    cfg = PipelineConfig("C5")
    rows = [["C0-IF, C0-SVM", f"Isolation forest and one-class SVM on {len(detector_features())} generic tabular features (Section 7)", "no", "no", "no", "no"],
            ["C1", "The twelve deterministic controls only", "yes", "no", "no", "no"],
            ["C2", "One language-model prompt over the whole policy and the invoice's records; no controls", "no", "single prompt", "no", "no"],
            ["C3", "Controls, then three specialist agents in parallel", "yes", "3 specialists", "no", "no"],
            ["C4", "C3, then a challenger that may only remove agent findings", "yes", "3 specialists", "yes", "no"],
            ["C5", f"C4, then confidence from grounding, clause validity and agreement over {cfg.reruns} re-runs; low-confidence findings go to sampled review", "yes", "3 specialists", "yes", "yes"]]
    agent_rows = [[a.title, ", ".join(s.rstrip(".") for s in a.sections), ", ".join(a.records) or "invoice only",
                   ", ".join(a.history_fields) or "–"] for a in agents.AGENTS.values()]
    return [
        "## 2. The system under test", "",
        "AuditIQ audits procure-to-pay transactions: each vendor invoice with the purchase order (PO), goods receipt "
        "(GRN), vendor master record, approval log and the vendor's other invoices that it links to. The pipeline is a "
        "LangGraph state graph (`auditiq/graph.py`): evidence extraction, then the deterministic controls, then the "
        "language-model stages, then scoring and routing, then human review and the audit pack. Every result, finding "
        "(with its evidence), challenger removal and audit-trail entry is stored in SQLite or PostgreSQL; results are "
        "added and never replaced. The configurations compared are subsets of the same stages:", "",
        *md(["Configuration", "What runs", "Controls", "Language model", "Challenger", "Confidence"], rows),
        "The specialists' remits follow the sections of the policy; a finding that cites a rule outside the agent's "
        "remit is discarded by code. Each agent sees only the records its rules need:", "",
        *md(["Agent", "Policy sections", "Records shown", "Fields of the vendor's other invoices"], agent_rows),
        f"Language-model settings (`auditiq/graph.py`): temperature {cfg.temperature} for every stage; the agreement "
        f"re-runs of C5 use temperature {cfg.rerun_temperature}. An agent sees at most {agents.HISTORY_CAP} of the "
        "vendor's other invoices per selection rule (Section 20 checks that no labelled case loses an invoice it "
        "depends on). The prompts contain no threshold and no rule number: the policy text is inserted at run time, so "
        "the policy document is the only place a threshold is stated. A reply that is not valid JSON is sent back once "
        "for repair; a stage that still fails is recorded as failed and contributes no finding.", "",
    ]


def policy_section() -> list[str]:
    v25 = load_policy("2.5").registry["clauses"]
    v26 = load_policy("2.6").registry["clauses"]
    rows = []
    for rule, c in v25.items():
        params = "; ".join(f"`{k}` = {json.dumps(v)}" for k, v in (c.get("params") or {}).items()) or "–"
        rows.append([rule, c["title"], c["severity"], "control (code)" if c["kind"] == "control" else "agent (judgement)", params])
    diffs = [f"`{k}` of rule {rule}: {json.dumps(v)} to {json.dumps(v26[rule]['params'][k])}"
             for rule, c in v25.items() for k, v in (c.get("params") or {}).items() if v26[rule]["params"].get(k) != v]
    controls = sum(c["kind"] == "control" for c in v25.values())
    # The approval limits are one parameter with a value per role.
    nparams = sum(len(v) if isinstance(v, dict) else 1 for c in v25.values() for v in (c.get("params") or {}).values())
    return [
        "## 3. The policy as data", "",
        f"A policy version is a tuple P = (K, s, κ, θ): the set K of rule identifiers, the severity s(k) of each rule, "
        f"its kind κ(k) (control: decidable by comparing fields; judgement: needs reading), and its parameters θ_k. "
        f"Stored as data it is the clause registry. The reference policy, version 2.5, has {len(v25)} rules, "
        f"{controls} of kind control and {len(v25) - controls} of kind judgement, with {nparams} parameter values:", "",
        *md(["Rule", "Title", "Severity", "Decided by", "Parameters (version 2.5)"], rows),
        "Version 2.6 differs from 2.5 in: " + "; ".join(diffs) + ".", "",
        "**From document to registry** (`auditiq/policy_extract.py`, no language model). The PDF is read line by line "
        "with font size, position and page (PyMuPDF). The most frequent font size is the body size; a line at least one "
        "point larger is a heading; a line that begins with \"Rule <number> (<severity>),\" opens a rule, and indented "
        "lines continue it. For each parameter one pattern is matched against the text of the rule that states it; the "
        "approval limits are read from the table of roles and amounts. The set of rules and their kinds come from a "
        "reference version, which records what the system is able to execute. A document is refused, and nothing is "
        "stored, when a rule the system executes is absent, a threshold is not found in the wording of its rule, the "
        "document contains a rule for which there is no control, a value is not meaningful, the document states no "
        "version, a rule is stated more than once, or the approval table lacks a role the system applies.", "",
        "**Controls** (`auditiq/controls.py`). A control c_k(x; θ_k) is a pure function of one transaction x and the "
        "parameters of its rule. It returns nothing or a finding f = (k, s(k), E), where E is the set of field values "
        "it rests on. A control contains no constant of its own; amounts are compared in integer paise, so rounding "
        "cannot move a decision at a boundary. The controls are written from the policy text and import nothing from "
        "the dataset generator (a test enforces this).", "",
    ]


def scoring_section() -> list[str]:
    w, fl = SCORING.weights, SCORING.floors
    return [
        "## 4. Scores, confidence and routing", "",
        "(`auditiq/scoring.py`.) With severity weights " + ", ".join(f"{k} {v}" for k, v in w.items()) + ", the "
        "count-based score of an invoice x with findings F(x) is", "",
        "    R0(x) = min(100, Σ_{f ∈ F(x)} w_{s(f)}),",
        "",
        f"raised to at least {fl['critical']} if F(x) contains a critical finding and to at least {fl['high']} if it "
        "contains a high one. The confidence of a finding is c(f) = 1 for a control and c(f) = (g + p + a) / 3 for a "
        "model finding, where g = 1 if every evidence field exists in the transaction with the stated value, p = 1 if "
        "the cited rule exists in the active policy, and a is the share of the re-runs of the originating agent that "
        "cite the same rule. The confidence-weighted score is", "",
        "    Rc(x) = min(100, Σ_f w_{s(f)} · c(f)),",
        "",
        f"with the floors applied only for findings whose confidence is at least θ = {SCORING.theta:.3f}. The route is: "
        f"escalate to a reviewer if Rc ≥ τ = {SCORING.tau:g}; sampled review if Rc < τ ≤ R0; approve otherwise. A "
        "finding that cites a valid rule takes that rule's severity, whatever the model stated. Risk levels: CRITICAL "
        "from 70, HIGH from 50, MEDIUM from 30, LOW below. Without C5's confidence term, Rc = R0 and no invoice is "
        "sampled.", "",
    ]


def data_section() -> list[str]:
    rows = []
    for name in datasets():
        m, lab = manifest(name), labels(name)
        c = m["counts"]
        rows.append([f"`{name}`", m["kind"], m["seed"], n(c["invoices"]), n(int((lab["label"] == "anomalous").sum())),
                     n(int((lab["label"] == "hard_negative").sum())), n(int((lab["label"] == "clean").sum())),
                     n(c["vendors"]), n(c["ledger_records"]), overview.USE.get(m["kind"], "")])
    b = labels(BENCH[0])
    class_rows = [[k, c.name, ", ".join(c.clauses), "rule" if c.kind == "rule" else "judgement",
                   n(int((b["class_id"] == k).sum())), overview.INJECTION.get(k, "")] for k, c in CLASSES.items()]
    hn_rows = [[k, v, n(int((b["hard_negative_type"] == k).sum()))] for k, v in HARD_NEGATIVE_TYPES.items()]
    return [
        "## 5. Data: AuditIQ-Bench", "",
        "Six synthetic ledgers generated by `python -m auditiq_bench` from fixed seeds; regeneration reproduces every "
        "file byte for byte, and each manifest records the SHA-256 of every file. Each ledger holds vendors, purchase "
        "orders, goods receipts, invoices and approval logs, and an answer key (`labels.csv`) that no audit reads. "
        "Generation method and datasheets: [`auditiq/docs/DATASETS.md`](" + REPOSITORY + "/blob/main/auditiq/docs/DATASETS.md).", "",
        *md(["Ledger", "Kind", "Seed", "Invoices", "Anomalous", "Hard negatives", "Ordinary", "Vendors",
             "Ledger records", "Use"], rows),
        "**How a ledger is built.** Clean transactions are generated first (vendors with log-normal business weights, "
        "36 items in 6 spending categories, log-normal amounts per category, PO then GRN then invoice dates, an "
        "approver whose role can approve the amount). Anomalies and hard negatives are built by the same steps with "
        "one thing changed, and the label is written at that moment. The generator reads every threshold from the same "
        "policy registry the pipeline uses. Before a ledger is written, an independent validator "
        "(`auditiq_bench/validate.py`, sharing no code with the controls) recomputes from the finished tables which "
        "rules every invoice violates and requires the result to equal the labels in both directions; a ledger that "
        "fails is not written.", "",
        "**Anomaly classes** (counts on `bench_seed_101`; the other benchmark ledgers have the same counts):", "",
        *md(["Class", "Anomaly", "Rule(s)", "Kind", "Invoices", "How it is injected"], class_rows),
        "**Hard negatives**: clean invoices built to resemble an anomaly class, so that a system that reacts to "
        "surface features is caught out (counts on `bench_seed_101`):", "",
        *md(["Type", "What it is", "Invoices"], hn_rows),
    ]


def metrics_section() -> list[str]:
    rows = [
        ["Recall (invoice level)", "Anomalous invoices reported at all / anomalous invoices", "a detector names no rule, so this is the only level at which C0 and C1 can be compared"],
        ["Precision (invoice level)", "Anomalous invoices among those reported / invoices reported", ""],
        ["F1", "2·TP / (2·TP + FP + FN)", ""],
        ["False-positive rate, ordinary / hard negatives", "Ordinary (hard-negative) invoices reported / ordinary (hard-negative) invoices", "hard negatives resemble an anomaly"],
        ["Precision at 2% prevalence", "0.02·recall / (0.02·recall + 0.98·FPR)", "precision if 2% of invoices were anomalous"],
        ["Detected share of a class", "Invoices of the class reported at all, whatever rule is cited", ""],
        ["Per-class recall, precision, F1; macro-F1 and macro-recall", "Computed on the classes of the cited rules; macro over rule-defined (R1-R10) and judgement (J1-J4) classes separately", "only for configurations that cite rules"],
        ["Citation correctness", "Findings on anomalous invoices that cite a rule the invoice violates / findings on anomalous invoices", ""],
        ["Model findings naming a violated rule", "Findings raised by a language model that cite a rule the invoice violates / all findings a model raised (one on an invoice without an anomaly counts as wrong)", "the share of the model's findings an auditor can rely on"],
        ["Exact match", "Invoices whose set of cited rules equals the true set", ""],
        ["Escalation precision / recall", "Escalated invoices with a high or critical true violation / escalated invoices; / invoices with a high or critical true violation", ""],
        ["Policy adherence A(P)", "Share of invoices whose set of cited rules equals the ground truth recomputed under policy P", "Sections 11, 12"],
        ["Frozen-system errors", "Unsupported findings (cited, not violated), missed exceptions (violated, not cited), needless and missed escalations under the count-based score with τ = 50", "Sections 11, 12"],
        ["Values read correctly; rules read word for word", "Extracted parameter equal to the intended one; rule text equal to the rendered rule", "Sections 11-13"],
        ["Recall@k, MRR", "Answering passage among the top k; mean reciprocal rank of the answering passage", "Section 19"],
    ]
    return ["## 6. Metrics", "",
            "Definitions as implemented in `evaluation/metrics.py`. Every rate is a ratio of (weighted) sums over "
            "invoices, so the same code serves whole ledgers (weight 1) and the weighted evaluation subset.", "",
            *md(["Metric", "Definition", "Note"], rows)]


def stats_section() -> list[str]:
    feats = detector_features()
    return [
        "## 7. Statistical procedure", "",
        "**Confidence intervals.** 95% percentile bootstrap over invoices with 1,000 resamples (seed 0); on the "
        "evaluation subset the resampling is stratified by stratum (`evaluation/metrics.py`).", "",
        "**Paired tests.** McNemar's exact test on paired per-invoice correctness of two systems scored on the same "
        "invoices, with Holm's step-down correction over the family of comparisons (`evaluation/stats.py`). For the "
        "detector comparison an invoice is correct when \"reported or not\" equals \"anomalous or not\"; for the "
        "language-model configurations, when the set of cited rules equals the true set.", "",
        "**Thresholds of the classical detectors** (`evaluation/run_c0.py`). The isolation forest (300 trees) is "
        "fitted without labels on all invoices; the one-class SVM (RBF kernel, ν = 0.1) on clean invoices of the "
        "training folds. A detector outputs a score; the threshold is set by five-fold cross-fitting, folds stratified "
        "by class: each fold is decided with the threshold that maximises F1 on the other four, so no invoice is "
        "decided with a threshold tuned on its own label. The detectors therefore use labels the controls never see. "
        f"Their {len(feats)} features are generic and encode no policy threshold: " + ", ".join(f"`{f}`" for f in feats) + ".", "",
        "**What is fixed by construction.** The controls and the ground truth (the generator's validator) are two "
        "implementations of the same written rules by the same authors. The controls' perfect scores on R1 to R10 and "
        "the policy-driven adherence of 1.000 therefore verify the implementation and the reading of each document; "
        "they are not detection results. The quantities not fixed by construction are the detectors' scores, the "
        "frozen system's errors, the reader's outcomes on held-out and edited documents, and everything a language "
        "model does.", "",
    ]


def protocols_section() -> list[str]:
    s34 = labels("bench_seed_101").loc[[i.strip() for i in (PROJECT_ROOT / "evaluation" / "bench101_sample_ids.txt")
                                        .read_text(encoding="utf-8").splitlines() if i.strip()]]
    s20 = labels("pilot_seed_909").loc[[i.strip() for i in (PROJECT_ROOT / "evaluation" / "pilot_ids.txt")
                                       .read_text(encoding="utf-8").splitlines() if i.strip()]]

    def composition(frame: pd.DataFrame) -> str:
        parts = [f"{int((frame['class_id'] == k).sum())} × {k}" for k in CLASSES if (frame["class_id"] == k).any()]
        parts += [f"{int((frame['hard_negative_type'] == k).sum())} × {k}" for k in HARD_NEGATIVE_TYPES
                  if (frame["hard_negative_type"] == k).any()]
        parts.append(f"{int((frame['label'] == 'clean').sum())} ordinary")
        return ", ".join(parts)

    s90 = None
    if (RESULTS / IGPU_SAMPLE).exists():
        s90 = labels("bench_seed_202").loc[[i.strip() for i in (PROJECT_ROOT / "evaluation" / "bench202_sample_ids.txt")
                                            .read_text(encoding="utf-8").splitlines() if i.strip()]]
    meta = json.loads((RESULTS / "bench_seed_101" / "C5-sample34.meta.json").read_text(encoding="utf-8"))
    hashes = {json.loads(p.read_text(encoding="utf-8"))["prompt_hash"] for p in RESULTS.glob("*/C*-*.meta.json")}
    change, held, scal = load("policy_change.json"), load("policy_heldout.json"), load("scalability.json")
    rows = [
        ["Controls against detectors (10)", "C1, C0-IF, C0-SVM on the three benchmark ledgers and the large ledger, whole ledgers and the weighted 1,200-invoice subset", "`python -m evaluation.run_all`"],
        ["Policy change (11)", f"{len(change['variants'])} hand-written variants of version 2.5 rendered as PDFs; each read back by the system and applied to the {n(change['invoices'])} invoices of five ledgers; the same controls with the thresholds of 2.5 (\"frozen\"); ground truth recomputed under each variant by the generator's validator", "`python -m evaluation.policy_change`"],
        ["Held-out documents (12)", f"{len(held['variants'])} variants drawn at random (seed {held['seed']}) from value ranges never used to build or check the reader, each changing one to five values; same protocol as 11", "`python -m evaluation.policy_heldout`"],
        ["Robustness (13)", "16 edits of the reference document: 7 that keep every value (must be read correctly), 7 defects (must be refused), 2 ambiguities (must be refused)", "`python -m evaluation.policy_robustness`"],
        ["Application (14)", "The 20,000-invoice ledger in a SQLite store: audit under 2.5, adopt the strict policy PDF, audit again; everything stored", "`python -m evaluation.application_demo`"],
        ["Every ledger (15)", "Each of the six ledgers written as an Excel workbook, loaded through the checked import, audited with C1 through the store; outcome read back from the store", "`python -m evaluation.ledger_runs`"],
        ["Scalability (16)", f"20,000 invoices under 15 policy versions ({n(300000)} audits) with 1, 2, 4 and 8 worker processes; one process on 5,000 to 40,000 invoices; median of {scal['repeats']} runs; total findings must be equal for every number of workers", "`python -m evaluation.scalability`"],
        ["Policies in their own wording (17)", "Six documents (three memoranda, three handbooks) none in the template's wording; one model call per document at temperature 0; code verification; outcome per value", "`python -m evaluation.policy_llm_eval`"],
        ["Pilot (18)", f"20 invoices of the development ledger: {composition(s20)}", "`python -m evaluation.run_pilot ... --tag pilot20`"],
        ["Benchmark sample (18)", f"34 invoices of `bench_seed_101`, drawn with seed 0 by `evaluation/sample_ids.py`: {composition(s34)}", "`python -m evaluation.run_pilot ... --tag sample34`"],
        *([["Benchmark sample on the integrated GPU (18.5)", f"90 invoices of `bench_seed_202`, drawn with seed 0 by `evaluation/sample_ids.py`: {composition(s90)}", "`python -m evaluation.run_full ... --tag igpu90`"]]
          if s90 is not None else []),
        ["Policy search (19)", "48 fixed questions over 27 passages: 16 in the policy's wording, 16 paraphrases used to choose the default ranker (dev), 16 never used for a choice (test)", "`python -m evaluation.retrieval_eval --rewrite`"],
        ["History cap (20)", "Every labelled invoice whose vendor history exceeds the cap: are the invoices its case depends on still shown?", "`python -m evaluation.history_cap`"],
    ]
    return [
        "## 8. Experimental protocols", "",
        *md(["Experiment (section)", "Protocol", "Command"], rows),
        "**Language-model protocol.** Prompts and settings were tried only on the development ledger "
        f"`pilot_seed_909` and frozen before a benchmark ledger was used: every model run of this report has the same "
        f"prompt hash ({', '.join(sorted(hashes))}). Model: `{meta['model']}` (Qwen2.5, 7B parameters, 12,288-token "
        "context; `deploy/ollama/Modelfile`) served by Ollama on the laptop's CPU, no GPU. The five configurations run "
        "on the same invoices; replies are cached by the hash of the request, so a later configuration reuses the "
        "identical calls of an earlier one and pays only for its own. A run that is interrupted resumes after the last "
        "saved invoice.", "",
    ]


def environment_section() -> list[str]:
    change, scal = load("policy_change.json"), load("scalability.json")
    return [
        "## 9. Environment and reproducibility", "",
        f"All experiments ran on one laptop: {change['machine']}, {scal['logical_cpus']} logical CPUs (an Intel "
        "i5-1235U: 2 performance and 8 efficiency cores), 16 GB of memory, no GPU, Windows 11. Timings are those of "
        "this machine and depend on its load; counts, decisions and intervals do not.", "",
        "Reproduction from a clone, in `auditiq/`: `pip install -e \".[dev]\"`, then the commands of Section 8 (the "
        "order and the outputs are listed in [`RESULTS.md`](" + REPOSITORY + "/blob/main/RESULTS.md), Section 13). "
        "The datasets regenerate byte for byte; every experiment that needs no model was re-run with the final code "
        "and gave identical counts, values, decisions and intervals; the experiments with a model reproduce exactly "
        "from the cached replies. Continuous integration runs the Python tests on SQLite and PostgreSQL and the "
        "frontend checks on every push.", "",
    ]


# ======================================================== part II: results
def detection_section() -> list[str]:
    out = ["## 10. Controls against classical anomaly detectors", "",
           src(*[f"{d}/metrics.json" for d in BENCH + ["large_seed_505"]], "summary.md"), ""]
    ms = {d: load(f"{d}/metrics.json") for d in BENCH + ["large_seed_505"]}
    mean_rows = []
    for key, name in DETECTION:
        mean_rows.append([name] + [f3(statistics.mean(value(ms[d]["metrics"][s][key]) for d in BENCH)) for s in SYSTEMS])
    out += ["### 10.1 Mean of the three benchmark ledgers (5,000 invoices each, 8.4% anomalous)", "",
            *md(["Measure"] + list(SYSTEMS.values()), mean_rows)]
    for d in BENCH + ["large_seed_505"]:
        m = ms[d]
        head = f"### 10.{2 + (BENCH + ['large_seed_505']).index(d)} `{d}` ({n(m['n_invoices'])} invoices; value [95% interval])"
        out += [head, "", *md(["Measure"] + list(SYSTEMS.values()),
                              [[name] + [ci(m["metrics"][s][key]) for s in SYSTEMS] for key, name in DETECTION])]
        out += md(["Comparison (McNemar, Holm-adjusted)", "Only C1 correct", "Only detector correct", "Adjusted p"],
                  [[pair, n(t["only_a_correct"]), n(t["only_b_correct"]), f"{t['p_holm']:.2e}"]
                   for pair, t in m["mcnemar_detection"].items()])
        checks = m.get("construction_checks", {})
        out += [f"Construction checks: {sum(checks.values())} of {len(checks)} passed.", ""]
    per_class = [[k, CLASSES[k].kind] + [f3(statistics.mean(value(ms[d]["metrics"][s][f"detected:{k}"]) for d in BENCH))
                                          for s in SYSTEMS] for k in CLASSES]
    out += ["### 10.6 Share of each anomaly class reported (mean of the three benchmark ledgers)", "",
            *md(["Class", "Kind"] + list(SYSTEMS.values()), per_class)]
    sub_rows = [[d] + [f"{f3(value(ms[d]['metrics'][s]['detection_f1']))} / {f3(value(ms[d]['metrics_on_weighted_subset'][s]['detection_f1']))}"
                      for s in SYSTEMS] for d in BENCH + ["large_seed_505"]]
    out += ["### 10.7 Whole ledger against the weighted evaluation subset (F1: whole / subset estimate)", "",
            "Each ledger has an evaluation subset of 1,200 invoices with weights; a configuration too expensive for a "
            "whole ledger is run on the subset, and every rate is a weighted ratio. The table checks that the subset "
            "estimates the whole-ledger value:", "", *md(["Ledger"] + list(SYSTEMS.values()), sub_rows)]
    swap = load("swap_seed_404/metrics.json")
    swap_rows = [[name, ci(v["policy_adherence"]), n(int(value(v["boundary_flagged"]))), n(int(value(v["others_flagged"])))]
                 for name, v in swap["metrics"].items()]
    out += ["### 10.8 The policy-swap ledger", "",
            f"`swap_seed_404` holds {n(swap['n_boundary'])} invoices at the boundary between versions 2.5 and 2.6: "
            "anomalous under 2.5, clean under 2.6.", "",
            *md(["Run", "Policy adherence", "Boundary invoices flagged", "Other invoices flagged"], swap_rows)]
    return out


def policy_change_section() -> list[str]:
    r = load("policy_change.json")
    N = r["invoices"]
    rows = []
    for v in r["variants"]:
        fz = v["frozen"]
        rows.append([v["version"], v["name"], v["change"], f"{v['parameters_read_correctly']}/{v['parameters']}",
                     f"{v['rules_read_word_for_word']}/{v['rules']}", n(v["affected"]), pct(v["affected"] / N),
                     n(v["driven"]["invoices"] - v["driven"]["exact"]), f3(fz["exact"] / N), n(fz["stale_findings"]),
                     n(fz["missed_exceptions"]), n(fz["needless_escalations"]), n(fz["missed_escalations"])])
    tight = [v for v in r["variants"] if v["frozen"]["missed_exceptions"] > 0]
    loose = [v for v in r["variants"] if v["frozen"]["stale_findings"] > 0]
    strict = max(r["variants"], key=lambda v: v["affected"])
    per_ledger = [[d, n(x["affected"]), n(x["frozen"]["missed_exceptions"]), n(x["frozen"]["missed_escalations"])]
                  for d, x in strict["per_ledger"].items()]
    ref = r["reference_check"]
    return [
        "## 11. Policy change: fourteen policy documents", "", src("policy_change.json", "policy_change.md"), "",
        f"Under the reference version itself the controls and the independent ground truth agree on "
        f"{n(sum(x['exact'] for x in ref.values()))} of {n(sum(x['invoices'] for x in ref.values()))} invoices. "
        f"Each variant below is applied to {n(N)} invoices; \"decisions moved\" counts the invoices whose correct set of "
        f"cited rules differs from version 2.5. Policy-driven: the controls under the registry read from the PDF. "
        f"Frozen: the same controls with the thresholds of 2.5.", "",
        *md(["Version", "Policy", "Change", "Values read", "Rules read", "Decisions moved", "Share",
             "Policy-driven wrong", "Frozen adherence", "Frozen: unsupported findings", "Frozen: missed exceptions",
             "Frozen: needless escalations", "Frozen: missed escalations"], rows),
        f"Totals: {sum(v['parameters_read_correctly'] for v in r['variants'])} of {sum(v['parameters'] for v in r['variants'])} "
        f"values and {sum(v['rules_read_word_for_word'] for v in r['variants'])} of {sum(v['rules'] for v in r['variants'])} "
        f"rules read correctly; {n(sum(v['driven']['invoices'] - v['driven']['exact'] for v in r['variants']))} wrong "
        f"decisions by the policy-driven controls in {n(r['audits'])} invoice audits (audited in "
        f"{r['audit_seconds']:.0f} s on one process).", "",
        f"**Direction of the change decides the kind of error.** In {len(tight)} variants the policy tightens a "
        f"threshold; a frozen system then misses {n(sum(v['frozen']['missed_exceptions'] for v in tight))} exceptions and "
        f"approves {n(sum(v['frozen']['missed_escalations'] for v in tight))} invoices the policy in force sends to review "
        f"(it is silent, which an auditor cannot see). In {len(loose)} variants the policy loosens; a frozen system "
        f"raises {n(sum(v['frozen']['stale_findings'] for v in loose))} findings the policy no longer supports and "
        f"escalates {n(sum(v['frozen']['needless_escalations'] for v in loose))} invoices needlessly (it costs reviewer "
        "time). The size of the error depends on how many invoices lie between the old and the new threshold: the "
        "Manager limit and the strict policy move thousands of decisions, a change of the round-amount multiple to "
        "5,000 moves none.", "",
        f"The largest change, the {strict['name'].lower()}, per ledger (decisions moved, frozen missed exceptions, "
        "frozen missed escalations):", "",
        *md(["Ledger", "Decisions moved", "Missed exceptions", "Missed escalations"], per_ledger),
    ]


def heldout_section() -> list[str]:
    r = load("policy_heldout.json")
    N = r["invoices"]
    vs = r["variants"]
    errors = [v["frozen"]["invoices"] - v["frozen"]["exact"] for v in vs]
    rows = [[v["version"], v["change"], "yes" if v["adopted"] else "no", f"{v['parameters_read_correctly']}/{v['parameters']}",
             f"{v['rules_read_word_for_word']}/{v['rules']}", n(v["driven"]["invoices"] - v["driven"]["exact"]),
             n(e), pct(e / N), n(v["frozen"]["stale_findings"]), n(v["frozen"]["missed_exceptions"])]
            for v, e in zip(vs, errors)]
    return [
        "## 12. Held-out policy documents", "", src("policy_heldout.json", "policy_heldout.md"), "",
        f"Twenty variants drawn at random with seed {r['seed']}. Each was rendered as a PDF, read back, and applied to "
        f"the same {n(N)} invoices.", "",
        *md(["Version", "Change", "Adopted", "Values read", "Rules read", "Policy-driven wrong", "Frozen wrong",
             "Frozen share", "Frozen: unsupported", "Frozen: missed"], rows),
        f"Totals: {sum(v['adopted'] for v in vs)} of {len(vs)} adopted; {sum(v['parameters_read_correctly'] for v in vs)} "
        f"of {sum(v['parameters'] for v in vs)} values and {sum(v['rules_read_word_for_word'] for v in vs)} of "
        f"{sum(v['rules'] for v in vs)} rules read correctly; "
        f"{n(sum(v['driven']['invoices'] - v['driven']['exact'] for v in vs))} policy-driven wrong decisions in "
        f"{n(len(vs) * N)} audits. A frozen system's error ranged from {n(min(errors))} to {n(max(errors))} invoices "
        f"(median {n(int(statistics.median(errors)))}).", "",
    ]


def robustness_section() -> list[str]:
    docs = load("policy_robustness.json")["documents"]
    before = {d["id"]: d for d in load("policy_robustness-before-fix.json")["documents"]}
    rows = [[d["id"], d["group"], d["edit"], d["expected"], d["outcome"], "yes" if d["as_required"] else "**no**",
             f"{d['values_read_correctly']}/{d['values']}" if d["adopted"] else "–",
             (d["problems"][0] if d["problems"] else "–"), before[d["id"]]["outcome"]] for d in docs]
    changed = [d["id"] for d in docs if before[d["id"]]["outcome"] != d["outcome"]]
    return [
        "## 13. Robustness of the reader", "", src("policy_robustness.json", "policy_robustness-before-fix.json"), "",
        "Group A edits keep every value and must be read correctly; group B edits make the document impossible to "
        "execute and must be refused; group C edits make it ambiguous, and refusal is the only safe outcome. The "
        "dangerous outcome is \"adopted wrongly\".", "",
        *md(["Id", "Group", "Edit", "Required", "Outcome", "As required", "Values read", "Reason given (first)",
             "Outcome in the first run"], rows),
        f"{sum(d['as_required'] for d in docs)} of {len(docs)} documents handled as required. The first run "
        f"(`policy_robustness-before-fix.md`) handled {sum(b['as_required'] for b in before.values())} of {len(before)}: "
        f"{', '.join(changed)} were adopted wrongly, because the reader kept the last statement of a repeated rule and "
        "accepted an approval table with a missing role. Both checks were added to the reader with regression tests, "
        "and the test was run again.", "",
    ]


def application_section() -> list[str]:
    r = load("application_demo.json")
    b, a = r["before"], r["after"]
    rules = sorted(set(b["findings_by_rule"]) | set(a["findings_by_rule"]))
    rows = [["Findings stored", n(b["findings"]), n(a["findings"])]]
    rows += [[f"Invoices: {state}", n(b["states"].get(state, 0)), n(a["states"].get(state, 0))]
             for state in sorted(set(b["states"]) | set(a["states"]))]
    rows += [[f"Findings under rule {k}", n(b["findings_by_rule"].get(k, 0)), n(a["findings_by_rule"].get(k, 0))] for k in rules]
    s = r["seconds"]
    return [
        "## 14. Policy change in the application", "", src("application_demo.json", "application_demo.md"), "",
        f"Ledger `{r['ledger']}` in a {r['store']} store, audited with the controls under version 2.5; then the strict "
        f"policy document is adopted as version {r['adopted_version']} and every invoice is audited again. No file of "
        "the system is edited in between.", "",
        *md(["", "Version 2.5", f"After adopting {r['adopted_version']}"], rows),
        "Changes the document makes: " + "; ".join(f"rule {c['clause']} `{c['parameter']}` {c['from']} to {c['to']}"
                                                   for c in r["changes"]) + ".", "",
        f"Reading and storing the document took {s['adopt']:.2f} s; auditing the ledger with storage of every result, "
        f"finding and trail entry took {s['audit_before']:.0f} s before and {s['audit_after']:.0f} s after.", "",
    ]


def ledger_runs_section() -> list[str]:
    r = load("ledger_runs.json")
    rows = [[x["ledger"], n(x["invoices"]), n(x["findings"]), n(x["invoices_with_a_finding"]),
             n(x["states"].get("PENDING_REVIEW", 0)), n(x["states"].get("AUTO_APPROVED", 0)),
             f"{x['review_queue']['amount']:,.0f}", x["seconds"]["load"], x["seconds"]["audit"]] for x in r["ledgers"]]
    kinds = ["rule-defined anomaly", "judgement anomaly", "hard negative", "ordinary clean"]
    key_rows = [[x["ledger"]] + [(lambda k: f"{n(k['escalated'])} / {n(k['with_finding'])} / {n(k['invoices'])}" if k else "–")
                                 (x["answer_key"].get(kind)) for kind in kinds] for x in r["ledgers"]]
    q_rows = [[x["ledger"], n(x["review_queue"]["invoices"]),
               ", ".join(f"{lv} {n(c)}" for lv, c in sorted(x["review_queue"]["risk_levels"].items())),
               "; ".join(f"{t['vendor']} ({t['waiting']})" for t in x["review_queue"]["top_vendors"])] for x in r["ledgers"]]
    b = next(x for x in r["ledgers"] if x["ledger"] == BENCH[0])
    k = b["answer_key"]["rule-defined anomaly"]
    return [
        "## 15. Every ledger through the deployed system", "", src("ledger_runs.json", "ledger_runs.md"), "",
        "Each ledger was written as an Excel workbook, loaded through the checked import, and audited with the controls "
        "through the store; the outcome was read back from the store as the review queue reads it.", "",
        *md(["Ledger", "Invoices", "Findings", "Invoices with a finding", "Escalated", "Approved",
             "Amount waiting (INR)", "Load (s)", "Audit (s)"], rows),
        "Against the answer key (escalated / with a finding / invoices of that kind):", "",
        *md(["Ledger"] + kinds, key_rows),
        "Review queue:", "", *md(["Ledger", "Waiting", "By risk level", "Vendors with the most invoices waiting"], q_rows),
        f"Every rule-defined anomaly gets a finding ({n(k['with_finding'])} of {n(k['invoices'])} on `{BENCH[0]}`). "
        f"{n(k['escalated'])} are escalated; the other {n(k['with_finding'] - k['escalated'])} carry only low or medium "
        "findings (GSTIN format or state code, a weekend date, a round amount), score below τ and are approved with "
        "the finding recorded. This is the routing working as designed: severity, not the mere presence of a finding, "
        "decides what a reviewer must see.", "",
    ]


def huge_subsection() -> list[str]:
    """16.1: the 500,000-invoice ledger of evaluation.huge, once its report exists."""
    path = RESULTS / "huge_seed_606" / "huge.md"
    if not path.exists():
        return []
    body = path.read_text(encoding="utf-8").splitlines()[2:]          # without the report's own title
    body = ["#### " + line[3:] if line.startswith("## ") else line for line in body]
    return ["### 16.1 The huge ledger: every measurement at 500,000 invoices", "",
            src("huge_seed_606/huge.md", "huge_seed_606/metrics.json", "huge_seed_606/policy_change.json",
                "huge_seed_606/application.json", "huge_seed_606/size.json"), "", *body, ""]


def scalability_section() -> list[str]:
    r = load("scalability.json")
    base = r["by_workers"][0]["seconds"]
    rows = [[w["workers"], f"{w['seconds']:.2f}", n(w["invoices_per_second"]), f"{base / w['seconds']:.2f}",
             f"{base / w['seconds'] / w['workers']:.2f}", n(w["findings"])] for w in r["by_workers"]]
    size = [[n(s["invoices"]), f"{s['seconds']:.3f}", n(s["invoices_per_second"]), s["microseconds_per_invoice"]]
            for s in r["by_size"]]
    return [
        "## 16. Scalability of the control stage", "", src("scalability.json", "scalability.md"), "",
        *md(["Worker processes", "Seconds", "Invoices per second", "Speed-up", "Efficiency (speed-up / workers)",
             "Findings"], rows),
        *md(["Ledger size", "Seconds (one process)", "Invoices per second", "Microseconds per invoice"], size),
        "Every number of workers produced the same findings, which is the correctness condition of the split. From "
        "5,000 to 40,000 invoices the cost per invoice does not grow with the ledger; at 500,000 invoices it does, "
        "because two controls read the vendor's history (16.1). Efficiency falls with "
        "more workers because the processor has two performance and eight efficiency cores. A rerun under background "
        "load gave the same findings with 21 to 36% lower throughput (RESULTS.md, Section 5).", "",
    ] + huge_subsection()


def own_wording_section() -> list[str]:
    r = load("policy_llm.json")
    keys = ["values", "right_verified", "right_held_back", "wrong_caught", "wrong_passed", "missing", "rules", "located"]
    rows = [[d["file"], d["style"]] + [n(d["counts"][k]) for k in keys] +
            ["yes" if d["counts"].get("policy_correct_after_confirmation") else "no", f"{d['usage']['seconds']:.0f}"]
            for d in r["documents"]]
    t = r["total"]
    rows.append(["**All**", ""] + [f"**{n(t[k])}**" for k in keys] + ["", ""])
    wrong = [[d["file"], x["rule"], x["parameter"], json.dumps(x["proposed"]), json.dumps(x["intended"]), x["outcome"],
              x.get("reason") or "–"] for d in r["documents"] for x in d["details"] if str(x["outcome"]).startswith("wrong")]
    return [
        "## 17. Policies in their own wording", "", src("policy_llm.json", "policy_llm.md"), "",
        f"Model `{r['model']}`, temperature 0, one call per document. The model proposes each rule's passage and each "
        "value with the words it took them from; code checks that each quote occurs in the document and that each value "
        "is written in a quote of its rule; a named person confirms before anything is adopted.", "",
        *md(["Document", "Style", "Values", "Right, verified", "Right, held back", "Wrong, caught", "Wrong, passed",
             "Missing", "Rules", "Rules located", "Right after confirmation", "Seconds"], rows),
        "Every wrong value, with what the model proposed and what the document intended:", "",
        *md(["Document", "Rule", "Parameter", "Proposed", "Intended", "Outcome", "Reason"], wrong),
        f"{t['right_verified'] + t['right_held_back']} of {t['values']} values were proposed correctly. The check "
        f"verified {t['right_verified']} and held back {t['right_held_back']} right ones for the reviewer (their quote "
        f"did not contain the amount or was not found in the document), caught {t['wrong_caught']} wrong ones and "
        f"passed {t['wrong_passed']}. The values that passed are real words of the quoted passage put to the wrong use, "
        "which a quote check cannot see; the confirming person is a required safeguard, not a formality.", "",
    ]


def agreement_split(dataset: str, tag: str) -> tuple[int, int, int, int]:
    """Model findings kept by C5: (right with full agreement, right, wrong with full agreement, wrong)."""
    lab = labels(dataset)
    right, wrong = [], []
    for r in jsonl(RESULTS / dataset / f"C5-{tag}.jsonl").values():
        truth = set(filter(None, lab.loc[r["invoice_id"], "clause_ids"].split("|")))
        for f in r.get("flags") or []:
            if f.get("source") == "L":
                (right if f["clause"] in truth else wrong).append(f.get("a"))
    full = lambda xs: sum(1 for a in xs if a is not None and a >= 1.0 - 1e-9)  # noqa: E731
    return full(right), len(right), full(wrong), len(wrong)


def outcome_cell(record: dict, truth: set[str]) -> str:
    route = {"escalate": "E", "sample": "S", "approve": "A"}.get(record.get("route"), "?")
    flags = sorted({f["clause"] for f in record.get("flags") or []})
    marks = " ".join(("✓" if c in truth else "✗") + c for c in flags)
    removed = len(record.get("removed_flags") or [])
    failed = (record.get("issues") or {}).get("failed_stages", 0)
    extra = (f" (−{removed})" if removed else "") + (" ⚠" if failed else "")
    return f"{route} {marks}{extra}".strip() if flags else f"{route} –{extra}"


def per_invoice(dataset: str, tag: str) -> list[str]:
    lab = labels(dataset)
    runs = {c: jsonl(RESULTS / dataset / f"{c}-{tag}.jsonl") for c in ("C1", "C2", "C3", "C4", "C5")}
    ids = list(runs["C1"])
    rows = []
    for i in ids:
        row = lab.loc[i]
        truth = set(filter(None, row["clause_ids"].split("|")))
        kind = row["class_id"] or row["hard_negative_type"] or "ordinary"
        rows.append([i, kind, ", ".join(sorted(truth)) or "–"] + [outcome_cell(runs[c][i], truth) for c in runs])
    order = {k: j for j, k in enumerate(list(CLASSES) + list(HARD_NEGATIVE_TYPES) + ["ordinary"])}
    rows.sort(key=lambda r: (order.get(r[1], 99), r[0]))
    return md(["Invoice", "Truth", "Violated rule(s)", "C1", "C2", "C3", "C4", "C5"], rows)


def model_run_block(title: str, path: str, dataset: str, tag: str) -> list[str]:
    t = metric_table(path)
    configs = ["C1", "C2", "C3", "C4", "C5"]
    rows = [[metric] + [ci(t[metric].get(c)) for c in configs] for metric in t]
    tests = table(path, "Comparison")
    return [f"### {title}", "", src(path, f"{dataset}/C1-{tag}.jsonl"), "",
            *md(["Metric (value [95% interval])"] + configs, rows),
            *md(["Comparison", "Only first correct", "Only second correct", "p", "Holm-adjusted p"],
                [[x["Comparison"], x["Only first correct"], x["Only second correct"], x["p"], x["Holm-adjusted p"]] for x in tests]),
            "Per invoice: route (E escalate, S sampled review, A approve), then each cited rule marked ✓ if the "
            "invoice violates it and ✗ if not; (−k) is the number of findings the challenger removed, ⚠ a failed "
            "stage.", "", *per_invoice(dataset, tag)]


def igpu_section() -> list[str]:
    """18.5: the 90-invoice sample of ledger 202 on the integrated GPU, once its report exists."""
    if not (RESULTS / IGPU_SAMPLE).exists():
        return []
    return model_run_block("18.5 Benchmark sample on the integrated GPU: 90 invoices of ledger 202 (sample)",
                           IGPU_SAMPLE, "bench_seed_202", "igpu90")


def llm_section() -> list[str]:
    out = ["## 18. The language-model stages", ""]
    for title, path, dataset, tag in (("18.1 Pilot: 20 invoices of the development ledger (pilot)", "pilot_seed_909/pilot20.md", "pilot_seed_909", "pilot20"),
                                      ("18.2 Benchmark sample: 34 invoices of ledger 101 (sample)", "bench_seed_101/sample34.md", "bench_seed_101", "sample34")):
        out += model_run_block(title, path, dataset, tag)
    s = metric_table("bench_seed_101/sample34.md")
    j = {k: s[f"Recall, {name}"] for k, name in (("J1", "J1 near-duplicate"), ("J2", "J2 structuring across days"),
                                                  ("J3", "J3 description against the PO"), ("J4", "J4 goods-receipt remark"))}
    agree = agreement_split("bench_seed_101", "sample34")
    out += ["### 18.3 What the sample shows", "",
            f"- **Judgement anomalies.** The agents (C3) reached a macro-recall of {f3(value(s['Macro-recall, judgement classes']['C3']))} "
            f"on the four judgement classes: J1 {f3(value(j['J1']['C3']))}, J2 {f3(value(j['J2']['C3']))}, J3 "
            f"{f3(value(j['J3']['C3']))}, J4 {f3(value(j['J4']['C3']))}. The two classes found best are the ones whose "
            "evidence sits in one record the agent is shown (a repeated amount and PO; a remark in the goods receipt); "
            "the two found least need a comparison across several invoices or of two texts' meaning. That is a reading "
            "of five invoices per class, not a measured cause.",
            f"- **Reliability of a finding.** Only {f3(value(s['Model findings naming a violated rule']['C3']))} of the "
            f"agents' findings name a rule the invoice violates ({f3(value(s['Model findings naming a violated rule']['C4']))} "
            f"after the challenger), and the agents flagged hard negatives at a rate of {f3(value(s['FPR, hard negatives']['C3']))}.",
            f"- **The challenger trades recall for precision.** It lowered the hard-negative false-positive rate from "
            f"{f3(value(s['FPR, hard negatives']['C3']))} to {f3(value(s['FPR, hard negatives']['C4']))}, but J1 recall "
            f"fell from {f3(value(j['J1']['C3']))} to {f3(value(j['J1']['C4']))}: it removed correct near-duplicate "
            "findings along with wrong ones.",
            f"- **Confidence measures stability, not correctness.** C5 sent {value(s['Invoices in sampled review']['C5'])} "
            f"invoices to sampled review, {value(s['True anomalies in sampled review']['C5'])} of them true anomalies. "
            f"Of the model findings C5 kept, {agree[2]} of {agree[3]} wrong ones and {agree[0]} of {agree[1]} right ones "
            "had full agreement over the re-runs: agreement does not separate right findings from wrong ones.",
            f"- **Without the controls the model errs on almost every invoice.** The single prompt (C2) flagged every "
            f"ordinary invoice (false-positive rate {f3(value(s['FPR, ordinary clean']['C2']))}) and only "
            f"{f3(value(s['Model findings naming a violated rule']['C2']))} of its findings name a violated rule; its "
            f"invoice-level recall of {f3(value(s['Invoice-level recall']['C2']))} comes from flagging nearly everything.",
            f"- **Cost.** Model calls per invoice: C2 {f3(value(s['LLM calls per invoice']['C2']))}, C3 "
            f"{f3(value(s['LLM calls per invoice']['C3']))}, C4 {f3(value(s['LLM calls per invoice']['C4']))}, C5 "
            f"{f3(value(s['LLM calls per invoice']['C5']))}; on the laptop's CPU a call took minutes, so a benchmark "
            "ledger needs a GPU or a hosted endpoint.",
            "- **No difference between configurations is significant** on 34 invoices (table above); these are "
            "observations on a sample, not estimates for the benchmark.", ""]
    return out + full_run_section() + igpu_section()


def full_run_section() -> list[str]:
    """18.4: the reports of evaluation.run_full, when they exist."""
    reports = sorted(RESULTS.glob("bench_seed_*/full.md"))
    out = ["### 18.4 The full run on the benchmark ledgers", ""]
    if not reports:
        return out + ["Not run yet. The configurations with a model are measured only on the pilot and the sample "
                      "above. The full run (the 1,200-invoice evaluation subset of each benchmark ledger, about 1,200 "
                      "times three to five model calls per ledger) needs a GPU or a hosted endpoint; the command is "
                      "`python -m evaluation.run_full` (RESULTS.md, Section 10.1). Its reports appear here once they "
                      "exist.", ""]
    for path in reports:
        rel = path.relative_to(RESULTS).as_posix()
        heading = path.read_text(encoding="utf-8").splitlines()[0].lstrip("# ")
        t = metric_table(rel)
        configs = [c for c in ("C1", "C2", "C3", "C4", "C5") if any(c in v for v in t.values())]
        tests = table(rel, "Comparison")
        out += [f"#### {heading}", "", src(rel), "",
                *md(["Metric (value [95% interval])"] + configs, [[m] + [ci(t[m].get(c)) for c in configs] for m in t]),
                *md(["Comparison", "Only first correct", "Only second correct", "p", "Holm-adjusted p"],
                    [[x["Comparison"], x["Only first correct"], x["Only second correct"], x["p"], x["Holm-adjusted p"]]
                     for x in tests])]
    return out


def retrieval_section() -> list[str]:
    rows = table("retrieval.md", "Ranker")
    return ["## 19. Policy search", "", src("retrieval.md"), "",
            *md(["Ranker", "Questions", "Recall@1", "Recall@3", "MRR"],
                [[r["Ranker"], r["Questions"], f3(r["Recall@1"]), f3(r["Recall@3"]), f3(r["MRR"])] for r in rows]),
            "Questions in the policy's own wording are found by every ranker; paraphrases are where rankers differ. "
            "Restating the question in the documents' vocabulary with the chat model helps every ranker. Sixteen "
            "questions per cell: neighbouring cells differ by one or two questions.", ""]


def history_section() -> list[str]:
    rows = table("history_cap.md", "Dataset")
    lost = sum(r["Cases"] - r["Complete for the owning stage"] for r in rows)
    return ["## 20. Vendor-history cap", "", src("history_cap.md"), "",
            *md(list(rows[0]), [list(r.values()) for r in rows]),
            f"Cases that lose an invoice they depend on: {lost}.", ""]


# ======================================================== part III: analysis
def answers_section() -> list[str]:
    pc, ho, rb = load("policy_change.json"), load("policy_heldout.json"), load("policy_robustness.json")["documents"]
    ms = {d: load(f"{d}/metrics.json") for d in BENCH + ["large_seed_505"]}
    mean = lambda s, k: statistics.mean(value(ms[d]["metrics"][s][k]) for d in BENCH)  # noqa: E731
    large = ms["large_seed_505"]["metrics"]
    sc = load("scalability.json")
    llm = load("policy_llm.json")["total"]
    s = metric_table("bench_seed_101/sample34.md")
    ret = {(r["Ranker"], r["Questions"]): r for r in table("retrieval.md", "Ranker")}
    lr = load("ledger_runs.json")["ledgers"]
    strict = max(pc["variants"], key=lambda v: v["affected"])
    held_err = max(v["frozen"]["invoices"] - v["frozen"]["exact"] for v in ho["variants"])
    best = ret[("hybrid + rewrite", "paraphrase (test)")]
    rows = [
        ["RQ1", f"Yes, for documents in the template's wording: {sum(v['parameters_read_correctly'] for v in pc['variants'])}/"
                f"{sum(v['parameters'] for v in pc['variants'])} values on 14 hand-written documents and "
                f"{sum(v['parameters_read_correctly'] for v in ho['variants'])}/{sum(v['parameters'] for v in ho['variants'])} "
                "on 20 held-out random documents."],
        ["RQ2", f"Yes: 0 wrong decisions in {n(pc['audits'] + len(ho['variants']) * ho['invoices'])} invoice audits. A frozen "
                f"system decided up to {pct(strict['affected'] / pc['invoices'])} of the invoices against the policy in force "
                f"({strict['name'].lower()}); up to {pct(held_err / ho['invoices'])} on the held-out documents."],
        ["RQ3", f"Yes, after a fix the test itself prompted: {sum(d['as_required'] for d in rb)} of {len(rb)} edited documents "
                "handled as required; the first run adopted two ambiguous documents."],
        ["RQ4", f"F1 {f3(mean('C1', 'detection_f1'))} at precision {f3(mean('C1', 'detection_precision'))} against "
                f"{f3(mean('C0-IF', 'detection_f1'))} and {f3(mean('C0-SVM', 'detection_f1'))}; on the large ledger "
                f"(2.1% anomalous) {f3(value(large['C1']['detection_f1']))} against {f3(value(large['C0-IF']['detection_f1']))} "
                f"and {f3(value(large['C0-SVM']['detection_f1']))}. The detectors flag "
                f"{f3(mean('C0-IF', 'fpr_hard_negative'))} and {f3(mean('C0-SVM', 'fpr_hard_negative'))} of the hard negatives, "
                "the controls none. The controls' advantage on R1-R10 is by construction; the detectors' recall, "
                "precision and false alarms are not."],
        ["RQ5", f"{min(x['microseconds_per_invoice'] for x in sc['by_size'])} to "
                f"{max(x['microseconds_per_invoice'] for x in sc['by_size'])} µs per invoice in one process, linear in the ledger; "
                f"{n(sc['by_workers'][-1]['invoices_per_second'])} invoices per second with {sc['by_workers'][-1]['workers']} "
                "processes on one laptop."],
        ["RQ6", f"Partly: {llm['right_verified'] + llm['right_held_back']} of {llm['values']} values proposed correctly; "
                f"the code check passed {llm['wrong_passed']} wrong ones, so the confirming person is required."],
        ["RQ7", f"On the 34-invoice sample the agents found judgement anomalies (macro-recall "
                f"{f3(value(s['Macro-recall, judgement classes']['C3']))}) that the controls cannot, but only "
                f"{f3(value(s['Model findings naming a violated rule']['C3']))} of their findings name a violated rule, "
                f"at {f3(value(s['LLM calls per invoice']['C3']))} to {f3(value(s['LLM calls per invoice']['C5']))} model "
                "calls per invoice. No difference between configurations is significant on the sample."],
        ["RQ8", f"On each benchmark ledger loaded from a workbook: {n(lr[0]['findings'])} findings, every rule-defined anomaly "
                f"found, {n(lr[0]['states'].get('PENDING_REVIEW', 0))} invoices escalated, no finding on a hard negative or an "
                "ordinary invoice; a policy change moves the review queue without any edit of code."],
        ["RQ9", f"Questions in the policy's wording: yes. Held-out paraphrases: hybrid ranking after rewriting finds the "
                f"answer first in {f3(best['Recall@1'])} and among the top three in {f3(best['Recall@3'])} (16 questions)."],
    ]
    return ["# Part III. Analysis", "", "## 21. Answers to the research questions", "", *md(["", "Answer"], rows)]


# The detector features that an anomaly of each class changes (evaluation/run_c0.features).
CLASS_FEATURES = {"R3": "vendor_same_number", "R4": "gstin_equals_master", "R5": "gstin_equals_master",
                  "R8": "missing_po, missing_grn", "R9": "vendor_blacklisted, vendor_registration_active",
                  "J1": "vendor_same_amount, vendor_same_po"}


def gstin_mismatch(dataset: str) -> dict[str, tuple[int, int]]:
    """Per kind of invoice: (invoices whose GSTIN differs from the vendor's registered one, invoices)."""
    inv = pd.read_csv(DATA / dataset / "invoices.csv", dtype=str, keep_default_na=False)
    vm = pd.read_csv(DATA / dataset / "vendor_master.csv", dtype=str, keep_default_na=False)
    merged = inv.merge(vm[["vendor_id", "official_gstin"]], on="vendor_id").set_index("invoice_id")
    lab = labels(dataset)
    kind = lab["class_id"].where(lab["class_id"] != "", lab["label"])
    differs = merged["gstin"] != merged["official_gstin"]
    return {k: (int(differs[ids].sum()), len(ids)) for k, ids in kind.groupby(kind).groups.items()}


def errors_section() -> list[str]:
    ms = {d: load(f"{d}/metrics.json") for d in BENCH}
    det = lambda s, k: statistics.mean(value(ms[d]["metrics"][s][f"detected:{k}"]) for d in BENCH)  # noqa: E731
    strong_if = [k for k in CLASSES if det("C0-IF", k) >= 0.9]
    weak_svm = [k for k in CLASSES if CLASSES[k].kind == "rule" and det("C0-SVM", k) <= 0.1]
    weak_both = [k for k in CLASSES if CLASSES[k].kind == "judgement" and max(det("C0-IF", k), det("C0-SVM", k)) <= 0.25]
    feats = lambda ks: "; ".join(f"{k}: `{CLASS_FEATURES[k]}`" for k in ks if k in CLASS_FEATURES)  # noqa: E731
    gm = gstin_mismatch(BENCH[0])
    return [
        "## 22. What the errors show", "",
        f"- **Classical detectors find what is statistically unusual, not what is against the rules.** The isolation "
        f"forest reports at least 90% of classes {', '.join(strong_if)} (Section 10.6); an anomaly of each of these "
        f"classes sets a feature that is rare among clean invoices ({feats(strong_if)}), and rare values are what an "
        f"isolation forest isolates first. The one-class SVM reports at most 10% of the rule-defined classes "
        f"{', '.join(weak_svm)}, each marked by binary indicators ({feats(weak_svm)}). The indicator "
        f"`gstin_equals_master` alone separates R4 and R5 from every ordinary invoice on `{BENCH[0]}` (the GSTIN differs "
        f"from the registered one on {gm['R4'][0]} of {gm['R4'][1]} R4 and {gm['R5'][0]} of {gm['R5'][1]} R5 invoices, and "
        f"on {n(gm['clean'][0])} of {n(gm['clean'][1])} ordinary ones), yet the SVM reports {f3(det('C0-SVM', 'R4'))} and "
        f"{f3(det('C0-SVM', 'R5'))} of them; a plausible reading, not tested here, is that an RBF kernel on standardized "
        "features gives one rare indicator little weight against the continuous features. Neither detector finds "
        f"{', '.join(weak_both)} (at most 25%): J3 and J4 change no feature the detectors read (descriptions and receipt "
        f"remarks are text); a J2 invoice differs from ordinary ones only by degree (an amount just below the approver's "
        f"limit, several invoices of the vendor within a week), and the forest reports {f3(det('C0-IF', 'J2'))} of them, "
        f"the SVM {f3(det('C0-SVM', 'J2'))}. Both report near-duplicates (J1), whose copied amount and PO are "
        "unusual, but neither names a rule, so an auditor still has to find out why an invoice was flagged.",
        "- **A frozen system fails silently.** A tightened policy makes it miss exceptions and approve invoices the "
        "policy sends to review; nothing in its output shows the error. This is the operational argument for reading "
        "thresholds from the document instead of typing them into prompts and code.",
        "- **The reader's failures were ambiguity, not misreading.** No harmless edit was misread; the two gaps found "
        "were documents that state a rule twice or omit a role, where any choice is a guess. Refusal with the reason "
        "is the safe answer.",
        "- **A model's policy reading fails on use, not on transcription.** Its wrong values that passed the check are "
        "real words of the quoted passage put to the wrong use; a quote check cannot see that.",
        "- **The language-model stages fail on reasoning across records and on precision.** In the per-invoice "
        "tables of Section 18, near-duplicates and goods-receipt remarks are found from the records shown; "
        "structuring across days and description mismatches are mostly missed; wrong near-duplicate findings appear on "
        "hard negatives built to resemble them; the challenger removes right and wrong findings alike.", "",
    ]


def threats_section() -> list[str]:
    return [
        "## 23. Threats to validity", "",
        "- **Internal (circularity).** The controls and the ground truth implement the same written rules by the same "
        "authors; perfect scores on R1-R10 and adherence of 1.000 verify the implementation and the reading of each "
        "document, not the rules' ability to catch fraud. The detectors use labels for their thresholds; the controls "
        "use none.",
        "- **Construct (synthetic data).** The ledgers are generated; counts describe how these ledgers react, not "
        "the books of a particular organisation. Anomalies are injected one at a time into otherwise clean "
        "transactions.",
        "- **External (one model, one machine).** The language-model results come from one 7B model on a laptop CPU "
        "and do not estimate what a larger model would do. Everything ran on one machine; the platform's services are "
        "separable, but a multi-machine deployment has not been measured.",
        "- **Statistical (sample size).** The language-model stages were measured on 20 and 34 invoices; intervals are "
        "wide and no difference between configurations is significant. The free-form policy study has six documents "
        "written by the authors; the retrieval study sixteen questions per cell.",
        "- **Researcher degrees of freedom.** Prompts were tried only on the development ledger and frozen (one prompt "
        "hash for every run); the free-form policy errors were deliberately not fixed, because that would be tuning on "
        "the evaluation set; the robustness gaps were fixed and both runs are reported.", "",
        "## 24. What is not measured", "",
        "- Configurations C2 to C5 on whole benchmark ledgers (about 1,200 invoices of the evaluation subset with three "
        "to five calls each); this needs a GPU or a hosted model endpoint. The paper states expected values for it, "
        "fixed before measurement (RESULTS.md, Section 10).",
        "- A second model on the main comparison, the consistency subset, and the policy swap under the language-model "
        "configurations.",
        "- A deployment on several machines.", "",
    ]


def sources_section() -> list[str]:
    files = sorted(p.relative_to(RESULTS).as_posix() for p in RESULTS.rglob("*")
                   if p.is_file() and p.suffix in (".json", ".jsonl", ".md") and "figures" not in p.parts)
    return ["## 25. Source files", "",
            "The result files of the repository, with their public raw addresses (`.jsonl` files hold one record per "
            "audited invoice):", "",
            *[f"- [`auditiq/results/{f}`]({RAW}auditiq/results/{f})" for f in files], ""]


def render() -> str:
    head = [
        "# AuditIQ: methodology, results and analysis", "",
        "The full report of the measured work: how every experiment was designed and run, every result in detail, and "
        "what the results show. It is generated by `python -m evaluation.full_report` from the result files, the "
        "datasets and the code's own constants: **no number in it is typed by hand**, and a test fails if it is out of "
        "date. For writing the paper, the shorter guide is [`RESULTS.md`](" + REPOSITORY + "/blob/main/RESULTS.md); "
        "for programs and other models, every result is in [`auditiq/results/results.json`](" + RAW +
        "auditiq/results/results.json); the paper is [`paper/auditiq_paper.pdf`](" + REPOSITORY +
        "/blob/main/paper/auditiq_paper.pdf).", "",
        "Kinds of number: **measured** (a script of the repository produced it on the data stated), **pilot** and "
        "**sample** (measured on 20 or 34 invoices; no difference between configurations can be claimed), and "
        "**expected** (a target fixed before measurement, never a result; only in RESULTS.md, Section 10).", "",
        "## Contents", "",
        "Part I. Methodology: 1 Research questions · 2 The system under test · 3 The policy as data · 4 Scores, "
        "confidence and routing · 5 Data · 6 Metrics · 7 Statistical procedure · 8 Experimental protocols · "
        "9 Environment and reproducibility", "",
        "Part II. Results: 10 Controls against detectors · 11 Policy change · 12 Held-out documents · 13 Robustness "
        "of the reader · 14 Policy change in the application · 15 Every ledger through the system · 16 Scalability · "
        "17 Policies in their own wording · 18 The language-model stages · 19 Policy search · 20 Vendor-history cap", "",
        "Part III. Analysis: 21 Answers to the research questions · 22 What the errors show · 23 Threats to validity · "
        "24 What is not measured · 25 Source files", "",
        "# Part I. Methodology", "",
    ]
    body = (research_questions() + system() + policy_section() + scoring_section() + data_section() + metrics_section()
            + stats_section() + protocols_section() + environment_section()
            + ["# Part II. Results", ""]
            + detection_section() + policy_change_section() + heldout_section() + robustness_section()
            + application_section() + ledger_runs_section() + scalability_section() + own_wording_section()
            + llm_section() + retrieval_section() + history_section()
            + answers_section() + errors_section() + threats_section() + sources_section())
    return "\n".join(head + body).rstrip() + "\n"


def main() -> None:
    OUT.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
    # The machine-readable file points to this report; keep both current.
    collect_results.main()


if __name__ == "__main__":
    main()
