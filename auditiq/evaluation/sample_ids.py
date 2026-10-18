"""Draw a reproducible sample of invoice ids from the labels of a ledger.

    python -m evaluation.sample_ids --dataset data/bench_seed_101 --classes J1 J2 J3 J4 --per-class 5 \
        --per-hard-negative 2 --ordinary 4 --out evaluation/bench101_sample_ids.txt

The invoices come from the evaluation subset of the ledger and are drawn with a
fixed seed, so the same command always gives the same sample. The output lists
one invoice id per line and nothing else, as evaluation.run_pilot and
evaluation.run_config expect. The labels are read only to choose the sample.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .metrics import read_labels, read_subset


def sample_ids(labels: pd.DataFrame, subset: pd.DataFrame | None, classes: list[str], per_class: int,
               per_hard_negative: int, ordinary: int, seed: int = 0) -> list[str]:
    """``per_class`` invoices of each listed class, ``per_hard_negative`` of each hard-negative
    type and ``ordinary`` ordinary clean invoices, all from the evaluation subset."""
    pool = labels if subset is None else labels[labels.index.isin(subset.index)]
    chosen: list[str] = []
    for i, k in enumerate(classes):
        group = pool[pool["class_id"] == k]
        chosen += list(group.sample(min(per_class, len(group)), random_state=seed + i).index)
    hard = pool[pool["label"] == "hard_negative"]
    for j, (_, group) in enumerate(sorted(hard.groupby("hard_negative_type"))):
        chosen += list(group.sample(min(per_hard_negative, len(group)), random_state=seed + 100 + j).index)
    clean = pool[pool["label"] == "clean"]
    if subset is not None:                       # ordinary invoices, not originals of duplicates
        clean = clean[clean.index.isin(subset.index[subset["stratum"] == "ordinary"])]
    chosen += list(clean.sample(min(ordinary, len(clean)), random_state=seed + 200).index)
    return sorted(chosen)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--classes", nargs="+", default=["J1", "J2", "J3", "J4"])
    ap.add_argument("--per-class", type=int, default=5)
    ap.add_argument("--per-hard-negative", type=int, default=2)
    ap.add_argument("--ordinary", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    subset = read_subset(args.dataset) if (args.dataset / "eval_subset.csv").exists() else None
    ids = sample_ids(read_labels(args.dataset), subset, args.classes, args.per_class, args.per_hard_negative,
                     args.ordinary, args.seed)
    args.out.write_text("\n".join(ids) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {len(ids)} invoice ids to {args.out}")


if __name__ == "__main__":
    main()
