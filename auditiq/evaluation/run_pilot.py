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
stopped.
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
    args = ap.parse_args()

    folder = PROJECT_ROOT / "results" / args.dataset.name
    if args.ids_file:
        chosen = ["--ids-file", str(args.ids_file.resolve())]
        sample = f"the {len(args.ids_file.read_text(encoding='utf-8').split())} invoices listed in `{args.ids_file.name}`"
    else:
        chosen = ["--stratified", str(args.n), "--subset-seed", str(args.seed)]
        sample = (f"{args.n} invoices requested, stratified over the classes and hard-negative types "
                  f"(seed {args.seed})")
    for config in args.configs:
        began = time.time()
        subprocess.run([sys.executable, "-m", "evaluation.run_config", "--dataset", str(args.dataset),
                        "--config", config, "--policy", args.policy, "--scope", "subset",
                        *chosen, "--workers", str(args.workers), "--tag", args.tag], check=True, cwd=PROJECT_ROOT)
        print(f"{config}: {time.time() - began:.0f} s", flush=True)

    files = [folder / f"{c}-{args.tag}.jsonl" for c in ORDER if (folder / f"{c}-{args.tag}.jsonl").exists()]
    names = {f.stem for f in files}
    pairs = [f"{a}-{args.tag}:{b}-{args.tag}" for a, b in (p.split(":") for p in PAIRS)
             if {f"{a}-{args.tag}", f"{b}-{args.tag}"} <= names]
    table = report.build(args.dataset, files, args.policy, resamples=1000, comparisons=pairs)

    meta = {f.stem: json.loads(f.with_suffix(".meta.json").read_text(encoding="utf-8")) for f in files}
    models = sorted({m["model"] for m in meta.values() if m["model"]})
    lines = [f"# Pilot on `{args.dataset.name}`", "",
             f"Model: {', '.join(models) or 'none'}. Sample: {sample}.", "",
             "**This is a pilot.** It shows that the pipeline runs end to end against this model and what an "
             "invoice costs. The sample is far too small to compare configurations: the intervals are wide "
             "and no difference between configurations can be claimed from it.", "", table, "",
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
    out = folder / f"{args.tag}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
