"""Run every configuration on one small stratified sample and report them side by side.

    python -m evaluation.run_pilot --dataset data/pilot_seed_909 --n 50
    python -m evaluation.run_pilot --dataset data/pilot_seed_909 --ids-file evaluation/demo_ids.txt --tag demo

A pilot answers two questions before a full run is paid for: does the pipeline
work end to end against the configured model, and how long does an invoice
take. Its sample is too small to compare configurations (about two invoices per
class), and the report says so. The sample is drawn from the evaluation subset
of the ledger and is the same for every configuration.

The runs share the response cache, so C4 pays only for the challenger calls and
C5 only for the re-runs on top of C3. An interrupted pilot continues where it
stopped. The full run on the benchmark ledgers is `evaluation.run_full`.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from auditiq.policy import PROJECT_ROOT

from . import report

ORDER = ["C1", "C3", "C4", "C5", "C2"]          # the paper's main comparison first, the single prompt last
PAIRS = ["C3:C2", "C4:C3", "C5:C4"]
RESULTS = PROJECT_ROOT / "results"


def audit(dataset: Path, configs: list[str], selection: list[str], tag: str, policy: str = "2.5",
          workers: int = 1, results: Path = RESULTS, extra: tuple[str, ...] = ()) -> None:
    """Run each configuration on the evaluation subset of ``dataset`` (narrowed by ``selection``, arguments of
    run_config such as --ids-file or --stratified) into results/<dataset>/<config>-<tag>.jsonl."""
    folder = results / dataset.name
    for config in configs:
        began = time.time()
        subprocess.run([sys.executable, "-m", "evaluation.run_config", "--dataset", str(dataset),
                        "--config", config, "--policy", policy, "--scope", "subset", *selection,
                        "--workers", str(workers), "--tag", tag, "--out", str(folder / f"{config}-{tag}.jsonl"),
                        *extra],
                       check=True, cwd=PROJECT_ROOT)
        print(f"{config}: {time.time() - began:.0f} s", flush=True)


def write_report(dataset: Path, tag: str, title: str, scope: str, notice: str, policy: str = "2.5",
                 results: Path = RESULTS, resamples: int = 1000) -> Path:
    """Compare the prediction files of ``tag`` and write results/<dataset>/<tag>.md."""
    folder = results / dataset.name
    files = [folder / f"{c}-{tag}.jsonl" for c in ORDER if (folder / f"{c}-{tag}.jsonl").exists()]
    if not files:
        raise SystemExit(f"no prediction file of tag '{tag}' in {folder}")
    names = {f.stem for f in files}
    pairs = [f"{a}-{tag}:{b}-{tag}" for a, b in (p.split(":") for p in PAIRS) if {f"{a}-{tag}", f"{b}-{tag}"} <= names]
    table = report.build(dataset, files, policy, resamples=resamples, comparisons=pairs)

    meta = {f.stem: json.loads(f.with_suffix(".meta.json").read_text(encoding="utf-8")) for f in files}
    models = sorted({m["model"] for m in meta.values() if m["model"]})
    lines = [f"# {title} on `{dataset.name}`", "",
             f"Model: {', '.join(models) or 'none'}. {scope}.", "", notice, "", table, "",
             "| Run | Invoices | LLM calls | Cache hits | Prompt tokens | Completion tokens | Model time (s) | "
             "Failed stages | Repaired replies | Out-of-remit flags |", "|---|---|---|---|---|---|---|---|---|---|"]
    for name, m in meta.items():
        s = m["summary"]
        lines.append(f"| {name} | {s['invoices']} | {s['llm_calls']} | {s['cache_hits']} | {s['prompt_tokens']} | "
                     f"{s['completion_tokens']} | {s['model_time_s']} | {s['failed_stages']} | "
                     f"{s['repaired_replies']} | {s['out_of_remit_flags']} |")
    lines += ["", "Model time is the waiting time of every call the configuration needs, summed; a call that came "
                  "from the cache counts with the time it took when it was made. The three agents call the model "
                  "at the same time, so on a server that answers one call at a time each call also waits for the "
                  "others and the sum exceeds the time that passed."]
    out = folder / f"{tag}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--n", type=int, default=50, help="size of the stratified sample")
    ap.add_argument("--ids-file", type=Path, help="audit the invoices listed in this file instead of a sample")
    ap.add_argument("--configs", nargs="+", default=ORDER, choices=ORDER)
    ap.add_argument("--policy", default="2.5")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=1, help="invoices audited at the same time")
    ap.add_argument("--tag", default="pilot")
    ap.add_argument("--report-only", action="store_true",
                    help="audit nothing; write the report from the prediction files of this tag")
    args = ap.parse_args()

    if args.ids_file:
        selection = ["--ids-file", str(args.ids_file.resolve())]
        sample = f"the {len(args.ids_file.read_text(encoding='utf-8').split())} invoices listed in `{args.ids_file.name}`"
    else:
        selection = ["--stratified", str(args.n), "--subset-seed", str(args.seed)]
        sample = (f"{args.n} invoices requested, stratified over the classes and hard-negative types "
                  f"(seed {args.seed})")
    if not args.report_only:
        audit(args.dataset, args.configs, selection, args.tag, args.policy, args.workers)
    out = write_report(args.dataset, args.tag, "Pilot", f"Sample: {sample}",
                       "**This is a pilot.** It shows that the pipeline runs end to end against this model and what an "
                       "invoice costs. The sample is far too small to compare configurations: the intervals are wide "
                       "and no difference between configurations can be claimed from it.", args.policy)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
