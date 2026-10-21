"""The huge ledger: 500,000 invoices from 15,000 vendors, at the anomaly rate of the large ledger (2.0%).

    python -m evaluation.huge                                  # every step; about two hours on a laptop
    python -m evaluation.huge --work D:/auditiq-huge           # keep the 2 GB of working files elsewhere
    python -m evaluation.huge --steps detection report         # some steps again

The ledger is too large for the repository (about 330 MB of CSV; with its predictions and the database another
2 GB), so it is generated from its seed into a work folder (default data_huge/, not committed). Its file hashes
are committed in results/huge_seed_606/manifest.json: a regenerated ledger must match them byte for byte.

Each step runs in its own process, so that memory is returned between steps, and writes results/huge_seed_606/:
  generate     the ledger, checked against the committed hashes (or, the first time, recorded)
  detection    the controls (C1) against the isolation forest and the one-class SVM, on every invoice
  policy       the fourteen policy documents of the policy-change experiment: policy-driven against frozen
  application  the ledger loaded into a SQLite store, audited with every result stored, the strict policy
               adopted, and the ledger audited again: the deployed path
  size         the control stage over the whole ledger in one process
  report       huge.md, from the files of the other steps
No language model is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

from auditiq.policy import PROJECT_ROOT

RESULTS = PROJECT_ROOT / "results"
NAME = "huge_seed_606"
STEPS = ["generate", "detection", "policy", "application", "size", "report"]


def out_dir(results: Path) -> Path:
    path = results / NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=1) + "\n", encoding="utf-8", newline="\n")


def machine() -> str:
    return f"{platform.processor() or platform.machine()}, Python {platform.python_version()}"


# ------------------------------------------------------------------ steps
def step_generate(dataset: Path, results: Path) -> None:
    from auditiq_bench.__main__ import HUGE, generate

    out = out_dir(results)
    committed = out / "manifest.json"
    if not (dataset / "manifest.json").exists():
        began = time.process_time()               # processor time: a laptop that sleeps stops the clock too
        generate(HUGE, dataset.parent)
        seconds = round(time.process_time() - began, 1)
    else:
        seconds = None
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    actual = {name: hashlib.sha256((dataset / name).read_bytes()).hexdigest() for name in manifest["sha256"]}
    if actual != manifest["sha256"]:
        raise SystemExit(f"{dataset}: the files do not match their own manifest")
    if committed.exists():
        recorded = json.loads(committed.read_text(encoding="utf-8"))
        same = recorded["sha256"] == manifest["sha256"] and recorded["counts"] == manifest["counts"]
        status = "identical to the committed hashes" if same else "DIFFERENT from the committed hashes"
        if not same:
            raise SystemExit(f"{NAME}: regenerated files differ from results/{NAME}/manifest.json")
    else:
        shutil.copyfile(dataset / "manifest.json", committed)
        shutil.copyfile(dataset / "README.md", out / "README.md")
        status = "hashes recorded"
    write_json(out / "generate.json", {"produced": time.strftime("%Y-%m-%d %H:%M"), "machine": machine(),
                                       "seconds": seconds, "files": len(actual), "status": status,
                                       "counts": manifest["counts"]})
    print(f"{NAME}: {manifest['counts']['invoices']:,} invoices; {status}")


def step_detection(dataset: Path, results: Path, work: Path, resamples: int) -> None:
    from evaluation.run_all import clean_json, evaluate_ledger

    began = time.perf_counter()
    result = evaluate_ledger(dataset, work / "predictions" / dataset.name, resamples)
    result["seconds"] = round(time.perf_counter() - began, 1)
    result["produced"], result["machine"] = time.strftime("%Y-%m-%d %H:%M"), machine()
    write_json(out_dir(results) / "metrics.json", clean_json(result))
    print(f"detection: {result['seconds']} s")


def step_policy(dataset: Path, results: Path) -> None:
    from auditiq import policy_extract
    from auditiq.extraction import extract
    from auditiq.policy import derive_policy, load_policy
    from auditiq_bench.validate import rule_clauses
    from evaluation.policy_change import REFERENCE, VARIANTS, compare, controls_decisions, load_tables

    base = load_policy(REFERENCE).registry
    documents = []
    for version, name, change, overrides in VARIANTS:
        pdf = PROJECT_ROOT / "policy" / "variants" / f"Company_Policy_v{version}.pdf"
        read = policy_extract.build(pdf, base)
        if read.problems:
            raise SystemExit(f"{pdf.name}: {read.problems}")
        documents.append((version, name, change, derive_policy(base, version, "2026-04-01", overrides), read.registry))
    began = time.perf_counter()
    tables, transactions = load_tables(dataset), extract(dataset)
    load_seconds = time.perf_counter() - began
    truth_reference = rule_clauses(tables, base)
    frozen = controls_decisions(transactions, base)
    variants, audit_seconds = [], 0.0
    for version, name, change, intended, read in documents:
        truth = rule_clauses(tables, intended)
        began = time.perf_counter()
        driven = controls_decisions(transactions, read)
        audit_seconds += time.perf_counter() - began
        variants.append({"version": version, "name": name, "change": change,
                         "affected": sum(truth[i] != truth_reference[i] for i in truth),
                         "driven": compare(driven, truth, intended), "frozen": compare(frozen, truth, intended)})
        print(f"v{version} {name}: done", flush=True)
    write_json(out_dir(results) / "policy_change.json", {
        "produced": time.strftime("%Y-%m-%d %H:%M"), "machine": machine(), "ledger": dataset.name,
        "invoices": len(transactions), "reference_version": REFERENCE,
        "reference_check": compare(frozen, truth_reference, base), "load_seconds": round(load_seconds, 1),
        "audits": len(transactions) * len(documents), "audit_seconds": round(audit_seconds, 1), "variants": variants})


def step_application(dataset: Path, results: Path, work: Path) -> None:
    from evaluation.application_demo import demo

    result, load_seconds = demo(dataset, work / "huge.db")
    result["seconds"]["load"] = load_seconds
    write_json(out_dir(results) / "application.json", result)
    print(f"application: load {load_seconds} s, audit {result['seconds']['audit_before']} s")


def step_size(dataset: Path, results: Path) -> None:
    from evaluation.scalability import measure_size

    result = measure_size([dataset], repeats=1)
    result.update(produced=time.strftime("%Y-%m-%d %H:%M"), machine=machine())
    write_json(out_dir(results) / "size.json", result)
    print(f"size: {result['microseconds_per_invoice']} µs per invoice")


# ------------------------------------------------------------------ report
def ci(m: dict) -> str:
    return f"{m['value']:.3f} [{m['ci_low']:.3f}, {m['ci_high']:.3f}]"


def report(results: Path) -> Path:
    out = out_dir(results)
    load = lambda name: json.loads((out / name).read_text(encoding="utf-8")) if (out / name).exists() else None  # noqa: E731
    gen, det, pol, app, size = (load(n) for n in ("generate.json", "metrics.json", "policy_change.json",
                                                  "application.json", "size.json"))
    lines = [f"# The huge ledger (`{NAME}`)", "",
             "Produced by `python -m evaluation.huge`. 500,000 invoices from 15,000 vendors at the anomaly rate of the "
             "large ledger; generated from its seed into a work folder (not committed) and checked against the file "
             f"hashes in `results/{NAME}/manifest.json`. No language model is used.", ""]
    if gen:
        c = gen["counts"]
        lines += ["## Data", "",
                  f"{c['invoices']:,} invoices ({c['anomalous']:,} anomalous, {c['anomalous'] / c['invoices']:.1%}; "
                  f"{c['hard_negative']:,} hard negatives), {c['vendors']:,} vendors, {c['ledger_records']:,} records in "
                  f"the five tables. Files: {gen['files']}, {gen['status']}."
                  + (f" Generation and validation took {gen['seconds']:,.0f} s of processor time." if gen.get("seconds") else "")
                  + (f" {gen['note']}" if gen.get("note") else ""), ""]
    if det:
        names = {"C1": "Controls (C1)", "C0-IF": "Isolation forest", "C0-SVM": "One-class SVM"}
        rows = [("Recall", "detection_recall"), ("Precision", "detection_precision"), ("F1", "detection_f1"),
                ("False-positive rate, hard negatives", "fpr_hard_negative"),
                ("False-positive rate, ordinary invoices", "fpr_ordinary")]
        lines += ["## Detection on every invoice", "",
                  f"Bootstrap intervals over invoices, {det['bootstrap_resamples']} resamples. Thresholds of the "
                  "classical detectors by five-fold cross-fitting, as on the benchmark ledgers.", "",
                  "| Measure | " + " | ".join(names[s] for s in names) + " |", "|---|---|---|---|"]
        lines += [f"| {label} | " + " | ".join(ci(det["metrics"][s][key]) for s in names) + " |" for label, key in rows]
        lines += ["", "| Comparison | Only the controls correct | Only the detector correct | Holm-adjusted p |",
                  "|---|---|---|---|"]
        lines += [f"| {k} | {v['only_a_correct']:,} | {v['only_b_correct']:,} | {v['p_holm']:.3g} |"
                  for k, v in det["mcnemar_detection"].items()]
        lines += ["", f"The step took {det['seconds']:,.0f} s.", ""]
    if pol:
        n = pol["invoices"]
        lines += ["## Policy change", "",
                  f"The fourteen policy documents of the policy-change experiment, read from their PDFs, applied to "
                  f"{n:,} invoices each ({pol['audits']:,} audits; the controls took {pol['audit_seconds']:,.0f} s). "
                  f"Under version 2.5 the controls agree with the ground truth on {pol['reference_check']['exact']:,} "
                  f"of {n:,} invoices.", "",
                  "| Policy | Decisions moved | Adherence, policy-driven | Adherence, frozen | Missed exceptions | "
                  "Missed escalations | Unsupported findings | Needless escalations |", "|---|---|---|---|---|---|---|---|"]
        for v in pol["variants"]:
            d, f = v["driven"], v["frozen"]
            lines.append(f"| {v['name']} | {v['affected']:,} ({v['affected'] / n:.1%}) | {d['exact'] / n:.4f} | "
                         f"{f['exact'] / n:.4f} | {f['missed_exceptions']:,} | {f['missed_escalations']:,} | "
                         f"{f['stale_findings']:,} | {f['needless_escalations']:,} |")
        lines.append("")
    if app:
        b, a = app["before"], app["after"]
        lines += ["## The deployed path", "",
                  f"The ledger loaded into a new SQLite store in {app['seconds']['load']:,.0f} s; every invoice audited "
                  f"with the controls, with every result, finding and trail entry stored, in "
                  f"{app['seconds']['audit_before']:,.0f} s; the strict policy document adopted in "
                  f"{app['seconds']['adopt']:.2f} s; every invoice audited again in {app['seconds']['audit_after']:,.0f} s.",
                  "", "| | Before (v2.5) | After (strict policy) |", "|---|---|---|",
                  f"| Invoices audited | {b['invoices']:,} | {a['invoices']:,} |",
                  f"| Findings | {b['findings']:,} | {a['findings']:,} |",
                  f"| Waiting for review | {b['states'].get('PENDING_REVIEW', 0):,} | {a['states'].get('PENDING_REVIEW', 0):,} |",
                  f"| Approved automatically | {b['states'].get('AUTO_APPROVED', 0):,} | {a['states'].get('AUTO_APPROVED', 0):,} |",
                  ""]
    if size:
        lines += ["## The control stage over the whole ledger", "",
                  f"{size['invoices']:,} invoices in {size['seconds']:.1f} s in one process: "
                  f"{size['microseconds_per_invoice']} µs per invoice ({size['invoices_per_second']:,} invoices per "
                  f"second), {size['findings']:,} findings. On 5,000 to 40,000 invoices the same stage took 17.8 to 19.4 "
                  "µs per invoice (`results/scalability.md`).", ""]
    stamps = [x["machine"] for x in (gen, det, pol, app, size) if x and x.get("machine")]
    if stamps:
        lines += [f"Machine: {stamps[0]}."]
    path = out / "huge.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


# ------------------------------------------------------------------ main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--steps", nargs="+", choices=STEPS, default=STEPS)
    ap.add_argument("--work", type=Path, default=PROJECT_ROOT / "data_huge", help="folder for the ledger and stores")
    ap.add_argument("--dataset", type=Path, help="another ledger instead of the huge one (for tests)")
    ap.add_argument("--results", type=Path, default=RESULTS)
    ap.add_argument("--resamples", type=int, default=200, help="bootstrap resamples of the detection step")
    ap.add_argument("--step", choices=STEPS, help=argparse.SUPPRESS)        # internal: run one step in this process
    args = ap.parse_args(argv)
    dataset = args.dataset or args.work / NAME

    if args.step:
        if args.step == "generate":
            step_generate(dataset, args.results)
        elif args.step == "detection":
            step_detection(dataset, args.results, args.work, args.resamples)
        elif args.step == "policy":
            step_policy(dataset, args.results)
        elif args.step == "application":
            step_application(dataset, args.results, args.work)
        elif args.step == "size":
            step_size(dataset, args.results)
        else:
            print(f"wrote {report(args.results)}")
        return 0

    for step in args.steps:
        began = time.time()
        command = [sys.executable, "-m", "evaluation.huge", "--step", step, "--work", str(args.work),
                   "--results", str(args.results), "--resamples", str(args.resamples)]
        if args.dataset:
            command += ["--dataset", str(args.dataset)]
        code = subprocess.run(command, cwd=PROJECT_ROOT).returncode
        print(f"== {step}: exit {code}, {time.time() - began:.0f} s", flush=True)
        if code:
            return code
    return 0


if __name__ == "__main__":
    sys.exit(main())
