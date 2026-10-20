"""Run the language-model configurations on the whole evaluation subset of the benchmark ledgers (plan item B10).

    python -m evaluation.run_full                                   # ledgers 101, 202, 303; C1, C3, C4, C5, C2
    python -m evaluation.run_full --ledgers bench_seed_101 --configs C1 C3
    python -m evaluation.run_full --n 25                            # a stratified 25 per ledger, to try an endpoint
    python -m evaluation.run_full --report-only
    python -m evaluation.run_full --ledgers swap_seed_404 --policy 2.6 --tag full-v2.6   # the policy swap

This needs a chat model (AUDITIQ_LLM_BASE_URL and AUDITIQ_LLM_MODEL; docs/OPERATIONS.md, Section 5), and a
fast one: each ledger has 1,200 invoices in its evaluation subset and an invoice needs three to five calls, so
on a laptop CPU the run takes weeks. Use a GPU or a hosted endpoint. Each configuration audits the subset with
the whole ledger as vendor history; the response cache lets an interrupted run continue where it stopped and
lets C3, C4 and C5 share their agent calls.

The prompts must be the ones frozen for the benchmark sample: a run is refused when the prompt hash differs
from the one recorded in results/bench_seed_101/C3-sample34.meta.json, unless --allow-new-prompts is given (and
then the full run is not comparable with the sample).

Writes results/<ledger>/<config>-full.jsonl (with a .meta.json beside each) and results/<ledger>/full.md, the
comparison with intervals and McNemar's tests. `python -m evaluation.collect_results` and
`python -m evaluation.full_report` include every full.md they find.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from auditiq import prompts
from auditiq.llm import LLMSettings
from auditiq.policy import PROJECT_ROOT

from .metrics import read_subset
from .run_pilot import ORDER, RESULTS, audit, write_report

LEDGERS = ["bench_seed_101", "bench_seed_202", "bench_seed_303"]
FROZEN = RESULTS / "bench_seed_101" / "C3-sample34.meta.json"
TAG = "full"


def frozen_prompt_hash() -> str | None:
    return json.loads(FROZEN.read_text(encoding="utf-8"))["prompt_hash"] if FROZEN.exists() else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledgers", nargs="+", default=LEDGERS, help="dataset folders under --data")
    ap.add_argument("--configs", nargs="+", default=ORDER, choices=ORDER)
    ap.add_argument("--data", type=Path, default=PROJECT_ROOT / "data")
    ap.add_argument("--results", type=Path, default=RESULTS)
    ap.add_argument("--n", type=int, help="audit a stratified sample of about this many invoices per ledger")
    ap.add_argument("--workers", type=int, default=4, help="invoices audited at the same time")
    ap.add_argument("--tag", default=TAG)
    ap.add_argument("--policy", default="2.5", help="the policy version the configurations apply")
    ap.add_argument("--allow-new-prompts", action="store_true")
    ap.add_argument("--no-cache", action="store_true", help="neither read nor write the response cache")
    ap.add_argument("--report-only", action="store_true", help="audit nothing; write the reports")
    args = ap.parse_args(argv)

    if not args.report_only:
        if any(c != "C1" for c in args.configs):
            try:
                settings = LLMSettings.from_env()
            except RuntimeError as err:
                print(err, file=sys.stderr)
                return 2
            print(f"model: {settings.model} at {settings.base_url}")
        frozen, now = frozen_prompt_hash(), prompts.prompt_hash()
        if frozen and frozen != now and not args.allow_new_prompts:
            print(f"the prompts changed since the benchmark sample (hash {now}, frozen {frozen}); "
                  "restore them or pass --allow-new-prompts", file=sys.stderr)
            return 2

    for name in args.ledgers:
        dataset = args.data / name
        size = len(read_subset(dataset))
        if args.n:
            selection = ["--stratified", str(args.n), "--subset-seed", "0"]
            scope = (f"Invoices: {args.n} requested per configuration, stratified over the classes and hard-negative "
                     f"types (seed 0), from the evaluation subset of {size:,} invoices")
            notice = ("**A stratified sample of the evaluation subset, not the full run.** It checks the endpoint and "
                      "the cost of an invoice; compare configurations only on the full subset.")
        else:
            selection = []
            scope = (f"Invoices: the evaluation subset of the ledger, {size:,} invoices (every anomalous invoice, "
                     "every hard negative and a weighted sample of the clean ones), with the whole ledger as vendor "
                     "history")
            notice = ("**The full run.** Rates are estimates for the whole ledger: the clean invoices of the subset "
                      "carry weights. The prompts are those frozen for the benchmark sample (hash "
                      f"{prompts.prompt_hash()}).")
        if not args.report_only:
            print(f"== {name}: {', '.join(args.configs)}", flush=True)
            audit(dataset, args.configs, selection, args.tag, args.policy, args.workers, args.results,
                  extra=("--no-cache",) if args.no_cache else ())
        elif not list((args.results / name).glob(f"*-{args.tag}.jsonl")):
            print(f"{name}: no prediction file of tag '{args.tag}' yet")
            continue
        out = write_report(dataset, args.tag, "Full run" if not args.n else "Sample of the evaluation subset",
                           scope, notice, args.policy, args.results)
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
