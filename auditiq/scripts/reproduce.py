"""Reproduce every result that needs no language model, in a temporary folder, and compare it with the
committed one.

    python scripts/reproduce.py                    # every step (about an hour on a laptop)
    python scripts/reproduce.py --steps datasets robustness history
    python scripts/reproduce.py --keep out/        # keep the regenerated files

Nothing in the working copy is written. The datasets are generated again from their seeds and compared byte
for byte with `data/`; each evaluation is run again on the committed datasets with its output in the temporary
folder, and every file it writes is compared with the committed file of the same name. In a comparison,
dates, the machine description and measured durations are ignored: they change from run to run. Every other
number, count, decision and interval must be identical. Binary files (figures, PDFs) are not compared.

The steps that need a model (retrieval, model-assisted policies, the LLM pilot and sample) are not run here;
their replies are cached on the machine that made them (`docs/OPERATIONS.md`).

Exit status 0 when every step ran and every compared file is identical.
"""
from __future__ import annotations

import argparse
import filecmp
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RESULTS = ROOT / "results"

# Keys whose values are dates, the machine or measured durations.
VOLATILE_KEYS = re.compile(r"(produced|machine|seconds|second|_ms$|latency|elapsed|duration|throughput|"
                           r"timing|per_invoice_us|microseconds|^us$|speed)", re.IGNORECASE)
DATE = re.compile(r"\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?")
# A measured duration or rate written in a sentence: "0.04 s", "51 s", "3.2 minutes", "172,226 invoices per second".
DURATION = re.compile(r"\d[\d,]*(\.\d+)?\s?(s|ms|µs|seconds?|minutes?|hours?)\b|\d[\d,]*(\.\d+)?\s?invoices per second",
                      re.IGNORECASE)
# A table column whose header names a time unit or a rate holds measurements.
VOLATILE_COLUMN = re.compile(r"(\(s\)|\(ms\)|\(µs\)|seconds|minutes|per second|/s\b|µs|throughput|speed-up|time)",
                             re.IGNORECASE)
# A line that describes the machine.
VOLATILE_LINE = re.compile(r"(Machine:|logical CPUs|GenuineIntel|Python \d)", re.IGNORECASE)
BINARY = {".png", ".pdf", ".jpg", ".svg", ".db", ".sqlite"}


def steps(tmp: Path) -> dict[str, list[list[str]]]:
    """The commands of each step; every output goes into ``tmp``."""
    py = sys.executable
    out = tmp / "results"
    return {
        "datasets": [[py, "-m", "auditiq_bench", "--out", str(tmp / "data")]],
        "manifests": [[py, "-m", "auditiq_bench.overview", "--verify"]],
        "baselines": [[py, "-m", "evaluation.run_all", "--out", str(out)]],
        "policy_change": [[py, "-m", "evaluation.policy_change", "--out", str(out), "--pdfs", str(tmp / "variants")]],
        "heldout": [[py, "-m", "evaluation.policy_heldout", "--out", str(out), "--pdfs", str(tmp / "variants_heldout")]],
        "robustness": [[py, "-m", "evaluation.policy_robustness", "--out", str(out), "--pdfs", str(tmp / "robustness")]],
        "application": [[py, "-m", "evaluation.application_demo", "--store", str(tmp / "application_demo.db"),
                         "--out", str(out)]],
        "history": [[py, "-m", "evaluation.history_cap", "--out", str(out / "history_cap.md")]],
        "ledgers": [[py, "-m", "evaluation.ledger_runs", "--out", str(out)]],
    }


def mask(line: str) -> str:
    return DATE.sub("<date>", line)


def compare_json(a, b, path: str = "") -> tuple[list[str], list[str]]:
    """(differences, ignored differences) between two JSON values; ignored ones are under a volatile key."""
    diffs: list[str] = []
    ignored: list[str] = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            p = f"{path}.{k}"
            if k not in a or k not in b:
                (ignored if VOLATILE_KEYS.search(str(k)) else diffs).append(f"{p}: only in one file")
                continue
            if VOLATILE_KEYS.search(str(k)):
                if a[k] != b[k]:
                    ignored.append(p)
                continue
            d, i = compare_json(a[k], b[k], p)
            diffs += d
            ignored += i
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            diffs.append(f"{path}: {len(a)} items against {len(b)}")
        for n, (x, y) in enumerate(zip(a, b)):
            d, i = compare_json(x, y, f"{path}[{n}]")
            diffs += d
            ignored += i
    elif isinstance(a, str) and isinstance(b, str):
        if mask(a) != mask(b):
            diffs.append(f"{path}: {a[:60]!r} against {b[:60]!r}")
    elif a != b:
        diffs.append(f"{path}: {a!r} against {b!r}")
    return diffs, ignored


def masked_lines(text: str) -> list[str]:
    """The lines of a text with dates and durations replaced, and the cells of time columns in tables blanked."""
    out: list[str] = []
    header: list[str] = []
    for line in text.splitlines():
        line = DURATION.sub("<duration>", mask(line))
        if line.startswith("|"):
            cells = line.strip().strip("|").split("|")
            if not header or (out and not out[-1].startswith("|")):
                header = cells                       # first row of a table
            elif all(set(c.strip()) <= set("-: ") for c in cells):
                pass                                 # the separator row
            else:
                cells = ["<time>" if i < len(header) and VOLATILE_COLUMN.search(header[i]) else c
                         for i, c in enumerate(cells)]
                line = "|" + "|".join(cells) + "|"
        else:
            header = [] if not line.strip() else header
        out.append(line)
    return out


def compare_text(a: str, b: str) -> tuple[list[str], list[str]]:
    la, lb = masked_lines(a), masked_lines(b)
    raw_b = b.splitlines()
    diffs: list[str] = []
    ignored: list[str] = []
    if len(la) != len(lb):
        diffs.append(f"{len(la)} lines against {len(lb)}")
    for n, (x, y) in enumerate(zip(la, lb), 1):
        if x == y:
            continue
        (ignored if VOLATILE_LINE.search(x) or VOLATILE_LINE.search(y) else diffs).append(f"line {n}: {raw_b[n - 1][:100]!r}")
    ignored += [f"masked: {n}" for n, (x, y) in enumerate(zip(a.splitlines(), raw_b), 1) if x != y and la[n - 1] == lb[n - 1]]
    return diffs, ignored


def compare_file(committed: Path, fresh: Path) -> tuple[str, list[str], list[str]]:
    """'same', 'different', 'missing' or 'binary', with the differences and the ignored ones."""
    if not committed.exists():
        return "missing", [f"{committed.name} is not committed"], []
    if fresh.suffix.lower() in BINARY:
        return "binary", [], []
    if fresh.suffix == ".json":
        diffs, ignored = compare_json(json.loads(committed.read_text(encoding="utf-8")),
                                      json.loads(fresh.read_text(encoding="utf-8")))
    elif fresh.suffix == ".jsonl":
        diffs, ignored = compare_json([json.loads(x) for x in committed.read_text(encoding="utf-8").splitlines() if x],
                                      [json.loads(x) for x in fresh.read_text(encoding="utf-8").splitlines() if x])
    else:
        diffs, ignored = compare_text(committed.read_text(encoding="utf-8"), fresh.read_text(encoding="utf-8"))
    return ("same" if not diffs else "different"), diffs, ignored


def compare_datasets(fresh: Path) -> tuple[int, int, list[str]]:
    names = sorted(p.relative_to(DATA) for p in DATA.rglob("*") if p.is_file())
    new = sorted(p.relative_to(fresh) for p in fresh.rglob("*") if p.is_file())
    bad = [f"different: {n}" for n in names if (fresh / n).exists()
           and not filecmp.cmp(DATA / n, fresh / n, shallow=False)]
    bad += [f"not regenerated: {n}" for n in names if not (fresh / n).exists()]
    bad += [f"only regenerated: {n}" for n in new if n not in names]
    return len(names) - sum(1 for b in bad if not b.startswith("only")), len(names), bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--steps", nargs="+", help="run only these steps (default: all)")
    ap.add_argument("--keep", type=Path, help="write the regenerated files here and keep them")
    ap.add_argument("--list", action="store_true", help="list the steps and exit")
    args = ap.parse_args()

    tmp = args.keep.resolve() if args.keep else Path(tempfile.mkdtemp(prefix="auditiq-reproduce-"))
    tmp.mkdir(parents=True, exist_ok=True)
    plan = steps(tmp)
    if args.list:
        for name, commands in plan.items():
            print(f"{name:14s} " + " && ".join(" ".join(c[1:]) for c in commands))
        return 0
    chosen = args.steps or list(plan)
    unknown = [s for s in chosen if s not in plan]
    if unknown:
        ap.error(f"unknown steps {unknown}; choose from {list(plan)}")

    failed = False
    (tmp / "logs").mkdir(exist_ok=True)
    for name in chosen:
        began = time.time()
        code = 0
        for command in plan[name]:
            with open(tmp / "logs" / f"{name}.log", "a", encoding="utf-8") as log:
                code = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT).returncode
            if code:
                break
        print(f"{name:14s} exit {code}  {time.time() - began:6.0f} s")
        if code:
            failed = True
            print(f"               see {tmp / 'logs' / (name + '.log')}")
            continue
        if name == "datasets":
            same, total, bad = compare_datasets(tmp / "data")
            print(f"               {same} of {total} dataset files identical byte for byte")
            for b in bad[:20]:
                print("              ", b)
            failed |= bool(bad)

    produced = sorted(p for p in (tmp / "results").rglob("*") if p.is_file()) if (tmp / "results").exists() else []
    counts = {"same": 0, "different": 0, "missing": 0, "binary": 0}
    ignored_total = 0
    for fresh in produced:
        rel = fresh.relative_to(tmp / "results")
        status, diffs, ignored = compare_file(RESULTS / rel, fresh)
        counts[status] += 1
        ignored_total += len(ignored)
        if status in ("different", "missing"):
            failed = True
            print(f"{status}: results/{rel.as_posix()}")
            for d in diffs[:8]:
                print("    ", d)
    if produced:
        print(f"result files: {counts['same']} identical, {counts['different']} different, {counts['missing']} "
              f"not committed, {counts['binary']} binary (not compared); {ignored_total} differences in dates, "
              f"machine or durations ignored")
    print("reproduced" if not failed else "NOT reproduced", "" if args.keep else f"(temporary folder: {tmp})")
    if not args.keep and not failed:
        shutil.rmtree(tmp, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
