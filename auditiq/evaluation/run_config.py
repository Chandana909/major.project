"""Run one pipeline configuration (C1 to C5) over a dataset.

    python -m evaluation.run_config --dataset data/bench_seed_101 --config C3
    python -m evaluation.run_config --dataset data/pilot_seed_909 --config C5 --stratified 50 --tag pilot

A configuration with an LLM audits the evaluation subset of the ledger
(eval_subset.csv: every anomalous invoice, every hard negative and a weighted
sample of the clean ones), with the whole ledger as vendor history; C1 audits
every invoice. --stratified N draws a smaller sample from the subset.

Writes results/<dataset>/<config>[-<tag>].jsonl, one prediction per invoice, and
a .meta.json beside it with the model, the temperatures and the prompt hash.
A run that was interrupted continues where it stopped; --fresh starts again.
The labels are read only to draw a stratified sample; no label reaches the
pipeline.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from auditiq import __version__, prompts
from auditiq.extraction import extract
from auditiq.graph import PRESETS, PipelineConfig, build_graph, to_result
from auditiq.llm import ChatClient, LLMSettings, OpenAIChatClient, ResponseCache
from auditiq.policy import PROJECT_ROOT, Policy, load_policy

from .metrics import read_labels, read_subset


def stratified_ids(labels: pd.DataFrame, n: int, seed: int = 0, within: set[str] | None = None) -> list[str]:
    """About ``n`` invoices with every class and hard-negative type represented.

    Each of the 14 classes and 5 hard-negative types contributes n // 25
    invoices (at least one); ordinary clean invoices fill the rest. ``within``
    restricts the choice, for example to the evaluation subset of the ledger.
    """
    if within is not None:
        labels = labels[labels.index.isin(within)]
    per_stratum = max(1, n // 25)
    strata = labels["class_id"].where(labels["class_id"] != "", labels["hard_negative_type"])
    chosen: list[str] = []
    for i, (_, group) in enumerate(sorted(labels[strata != ""].groupby(strata[strata != ""]))):
        chosen += list(group.sample(min(per_stratum, len(group)), random_state=seed + i).index)
    clean = labels[strata == ""]
    chosen += list(clean.sample(min(max(n - len(chosen), 0), len(clean)), random_state=seed).index)
    return sorted(chosen)


def run(transactions: list[dict], config: PipelineConfig, policy: Policy, client: ChatClient | None,
        out: Path, workers: int = 4, fresh: bool = False, progress: bool = True) -> list[dict]:
    """Audit every transaction and append one prediction per invoice to ``out``."""
    out.parent.mkdir(parents=True, exist_ok=True)
    if fresh and out.exists():
        out.unlink()
    done: dict[str, dict] = {}
    if out.exists():
        with out.open(encoding="utf-8") as f:
            done = {r["invoice_id"]: r for r in map(json.loads, filter(str.strip, f))}
    todo = [t for t in transactions if t["invoice"]["invoice_id"] not in done]
    graph = build_graph(config, policy, client)
    model = getattr(client, "model", None)
    lock, started = threading.Lock(), time.time()

    with out.open("a", encoding="utf-8", newline="\n") as f:
        def one(txn: dict) -> dict:
            result = to_result(graph.invoke({"txn": txn}), config, policy, model)
            with lock:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
                f.flush()
                done[result["invoice_id"]] = result
                if progress and (len(done) % 25 == 0 or len(done) == len(transactions)):
                    print(f"  {config.name}: {len(done)}/{len(transactions)} invoices, "
                          f"{time.time() - started:.0f} s", flush=True)
            return result

        if workers <= 1:
            for txn in todo:
                one(txn)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(one, todo))
    return [done[t["invoice"]["invoice_id"]] for t in transactions]


def summarize(results: list[dict]) -> dict:
    total = lambda path: sum(r[path[0]][path[1]] for r in results)  # noqa: E731
    routes: dict[str, int] = {}
    for r in results:
        routes[r["route"]] = routes.get(r["route"], 0) + 1
    return {
        "invoices": len(results),
        "invoices_flagged": sum(r["anomalous"] for r in results),
        "agent_flags": sum(f["source"] == "L" for r in results for f in r["flags"]),
        "flags_removed_by_challenger": sum(len(r["removed_flags"]) for r in results),
        "routes": routes,
        "llm_calls": total(("cost", "llm_calls")),
        "cache_hits": total(("cost", "cache_hits")),
        "prompt_tokens": total(("cost", "prompt_tokens")),
        "completion_tokens": total(("cost", "completion_tokens")),
        "model_time_s": round(total(("cost", "latency_ms")) / 1000, 1),
        "failed_stages": total(("issues", "failed_stages")),
        "repaired_replies": total(("issues", "repaired_replies")),
        "out_of_remit_flags": total(("issues", "out_of_remit_flags")),
        "malformed_flags": total(("issues", "malformed_flags")),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--config", choices=list(PRESETS), required=True)
    ap.add_argument("--policy", default="2.5")
    ap.add_argument("--stratified", type=int, help="audit a stratified subset of about this many invoices")
    ap.add_argument("--ids-file", type=Path, help="audit the invoice ids listed in this file, one per line")
    ap.add_argument("--subset-seed", type=int, default=0)
    ap.add_argument("--scope", choices=["subset", "all"], help="the evaluation subset (default with an LLM) or "
                                                               "every invoice of the ledger (default for C1)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--tag", default="", help="suffix of the output file, e.g. 'pilot'")
    ap.add_argument("--out", type=Path, help="default: results/<dataset>/<config>[-<tag>].jsonl")
    ap.add_argument("--fresh", action="store_true", help="discard an existing output file")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    config, policy = PRESETS[args.config], load_policy(args.policy)
    transactions = extract(args.dataset)
    # Configurations with an LLM audit the evaluation subset of the ledger; the controls audit everything.
    scope = args.scope or ("all" if config.agents == "none" else "subset")
    within = None
    if scope == "subset" and (args.dataset / "eval_subset.csv").exists():
        within = set(read_subset(args.dataset).index)
    if args.ids_file:
        wanted = set(args.ids_file.read_text(encoding="utf-8").split())
    elif args.stratified:
        wanted = set(stratified_ids(read_labels(args.dataset), args.stratified, args.subset_seed, within))
    else:
        wanted = within
    if wanted is not None:
        transactions = [t for t in transactions if t["invoice"]["invoice_id"] in wanted]

    client, settings = None, None
    if config.agents != "none":
        settings = LLMSettings.from_env()
        client = OpenAIChatClient(settings, None if args.no_cache else ResponseCache())
    name = args.config + (f"-{args.tag}" if args.tag else "")
    out = args.out or PROJECT_ROOT / "results" / args.dataset.name / f"{name}.jsonl"

    began = time.strftime("%Y-%m-%d %H:%M:%S")
    results = run(transactions, config, policy, client, out, args.workers, args.fresh)
    summary = summarize(results)
    meta = {
        "dataset": args.dataset.name, "configuration": asdict(config), "policy_version": policy.version,
        "model": settings.model if settings else None, "base_url": settings.base_url if settings else None,
        "prompt_hash": prompts.prompt_hash(), "auditiq_version": __version__,
        "scope": scope,
        "subset": {"stratified": args.stratified, "seed": args.subset_seed, "ids_file": str(args.ids_file or "")},
        "started": began, "finished": time.strftime("%Y-%m-%d %H:%M:%S"), "summary": summary,
    }
    out.with_suffix(".meta.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
