"""Figures of the measured results, for the results document and the paper.

    python -m evaluation.figures

Reads the JSON and Markdown files that the evaluation scripts wrote under
results/ and draws PNG figures in results/figures/. Nothing is measured here:
every value in a figure is read from those files, which are named in the
docstring of each function. A figure whose source file is missing is skipped.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from auditiq.policy import PROJECT_ROOT  # noqa: E402

RESULTS = PROJECT_ROOT / "results"
OUT = RESULTS / "figures"
# Categorical slots 1 to 3 of the validated reference palette (all pairs pass the colour-vision checks);
# every bar carries its value as a label, because the third slot is below 3:1 contrast on white.
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, MUTED, GRID, SURFACE = "#1f2328", "#52514e", "#e3e2de", "#ffffff"


def style(ax) -> None:
    ax.tick_params(axis="both", labelsize=7, length=0, colors=MUTED)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#b5b4ae")
    ax.set_axisbelow(True)


def save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(OUT / name, dpi=200, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    print(f"wrote {OUT / name}")


def detection() -> None:
    """Controls against the two classical detectors, mean of the three benchmark ledgers.
    Source: results/bench_seed_*/metrics.json (python -m evaluation.run_all)."""
    files = sorted(RESULTS.glob("bench_seed_*/metrics.json"))
    if not files:
        return
    measures = [("detection_recall", "Recall"), ("detection_precision", "Precision"), ("detection_f1", "F1"),
                ("fpr_hard_negative", "False positives,\nhard negatives")]
    systems = [("C1", "Policy-driven controls", BLUE), ("C0-IF", "Isolation forest", ORANGE),
               ("C0-SVM", "One-class SVM", AQUA)]
    metrics = [json.loads(f.read_text(encoding="utf-8"))["metrics"] for f in files]
    mean = {s: [sum(m[s][k]["value"] for m in metrics) / len(metrics) for k, _ in measures] for s, _, _ in systems}
    fig, ax = plt.subplots(figsize=(6.2, 2.9))
    width = 0.26
    for i, (key, label, colour) in enumerate(systems):
        xs = [j + (i - 1) * width for j in range(len(measures))]
        bars = ax.bar(xs, mean[key], width, color=colour, edgecolor=SURFACE, linewidth=1.5, label=label)
        for bar, value in zip(bars, mean[key]):
            ax.text(bar.get_x() + bar.get_width() / 2, value + 0.015, f"{value:.3f}", ha="center", va="bottom",
                    fontsize=6, color=INK)
    ax.set_xticks(range(len(measures)), [m[1] for m in measures])
    ax.set_ylim(0, 1.12)
    ax.yaxis.grid(True, color=GRID, linewidth=0.6)
    ax.set_ylabel("Share (mean of three ledgers)", fontsize=7, color=MUTED)
    ax.legend(fontsize=7, frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.13))
    style(ax)
    save(fig, "detection.png")


def scalability() -> None:
    """Throughput of the control stage against worker processes. Source: results/scalability.json."""
    path = RESULTS / "scalability.json"
    if not path.exists():
        return
    rows = json.loads(path.read_text(encoding="utf-8"))["by_workers"]
    xs = [r["workers"] for r in rows]
    ys = [r["invoices_per_second"] / 1000 for r in rows]
    fig, ax = plt.subplots(figsize=(3.6, 2.5))
    ax.plot(xs, ys, color=BLUE, linewidth=2, marker="o", markersize=5, markeredgecolor=SURFACE, markeredgewidth=1.5)
    for x, y in zip(xs, ys):
        ax.text(x, y + 6, f"{y:.0f}k", ha="center", va="bottom", fontsize=6.5, color=INK)
    ax.set_xticks(xs)
    ax.set_xlim(0.5, max(xs) + 0.5)
    ax.set_ylim(0, max(ys) * 1.25)
    ax.set_xlabel("Worker processes", fontsize=7, color=MUTED)
    ax.set_ylabel("Invoices per second (thousands)", fontsize=7, color=MUTED)
    ax.yaxis.grid(True, color=GRID, linewidth=0.6)
    style(ax)
    save(fig, "scalability.png")


def frozen_error() -> None:
    """Share of invoices a system frozen at version 2.5 decides against the policy in force, for the 14
    hand-written and the 20 held-out policy documents. The policy-driven controls decide none against it.
    Source: results/policy_change.json and results/policy_heldout.json."""
    change, held = RESULTS / "policy_change.json", RESULTS / "policy_heldout.json"
    if not change.exists() or not held.exists():
        return
    rows = []
    for path, group in ((change, "hand-written"), (held, "held-out")):
        r = json.loads(path.read_text(encoding="utf-8"))
        n = r["invoices"]
        for v in r["variants"]:
            name = v.get("name") or f"v{v['version']} (random)"
            rows.append((name, 100 * (n - v["frozen"]["exact"]) / n, group))
    rows.sort(key=lambda row: row[1])
    fig, ax = plt.subplots(figsize=(4.6, 6.4))
    colours = [BLUE if g == "hand-written" else ORANGE for _, _, g in rows]
    bars = ax.barh([r[0] for r in rows], [r[1] for r in rows], color=colours, height=0.72, edgecolor=SURFACE,
                   linewidth=1)
    for bar, (_, share, _) in zip(bars, rows):
        ax.text(bar.get_width() + 0.4, bar.get_y() + bar.get_height() / 2, f"{share:.1f}%", va="center",
                fontsize=5.5, color=INK)
    ax.set_xlim(0, max(r[1] for r in rows) * 1.18)
    ax.set_xlabel("Invoices decided against the policy in force (%)", fontsize=7, color=MUTED)
    ax.xaxis.grid(True, color=GRID, linewidth=0.6)
    ax.tick_params(axis="y", labelsize=5.5)
    handles = [plt.Rectangle((0, 0), 1, 1, color=BLUE), plt.Rectangle((0, 0), 1, 1, color=ORANGE)]
    ax.legend(handles, ["Hand-written documents (14)", "Held-out random documents (20)"], fontsize=6.5,
              frameon=False, loc="lower right")
    style(ax)
    save(fig, "frozen_error.png")


def model_stages() -> None:
    """Invoice-level recall and precision of each configuration, on the 20-invoice pilot (development ledger)
    and on the 34-invoice sample of benchmark ledger 101. Source: the tables of
    results/pilot_seed_909/pilot20.md and results/bench_seed_101/sample34.md (python -m evaluation.run_pilot)."""
    sources = [(RESULTS / "pilot_seed_909" / "pilot20.md", "Pilot, 20 invoices"),
               (RESULTS / "bench_seed_101" / "sample34.md", "Benchmark sample, 34 invoices")]
    panels = [(read_table(path), title) for path, title in sources if path.exists()]
    if not panels:
        return
    fig, axes = plt.subplots(1, len(panels), figsize=(3.3 * len(panels), 2.6), sharey=True, squeeze=False)
    for ax, (table, title) in zip(axes[0], panels):
        configs = [c for c in ("C1", "C2", "C3", "C4", "C5") if c in table["Invoice-level recall"]]
        width = 0.36
        for i, (measure, colour) in enumerate((("Invoice-level recall", BLUE), ("Invoice-level precision", ORANGE))):
            # A configuration that flags no invoice has no precision ("n/a" in the report): no bar, a label.
            values = [table[measure].get(c) for c in configs]
            xs = [j + (i - 0.5) * width for j in range(len(configs))]
            bars = ax.bar(xs, [v or 0 for v in values], width, color=colour, edgecolor=SURFACE, linewidth=1.5,
                          label=measure.replace("Invoice-level ", "").capitalize())
            for bar, value in zip(bars, values):
                ax.text(bar.get_x() + bar.get_width() / 2, (value or 0) + 0.015,
                        "n/a" if value is None else f"{value:.2f}", ha="center", va="bottom", fontsize=5.5, color=INK)
        ax.set_xticks(range(len(configs)), configs)
        ax.set_ylim(0, 1.15)
        ax.set_title(title, fontsize=7.5, color=INK)
        ax.yaxis.grid(True, color=GRID, linewidth=0.6)
        style(ax)
    # Above the panels: inside them the legend would cover the bars of C1.
    fig.legend(*axes[0][0].get_legend_handles_labels(), fontsize=6.5, frameon=False, loc="lower center",
               ncol=2, bbox_to_anchor=(0.5, 1.0))
    save(fig, "model_stages.png")


def read_table(path: Path) -> dict[str, dict[str, float]]:
    """The metric table of a run_pilot report: {metric: {configuration: value}}."""
    lines = path.read_text(encoding="utf-8").splitlines()
    header = next(line for line in lines if line.startswith("| Metric |"))
    names = [re.sub(r"-.*$", "", c.strip()) for c in header.strip("|").split("|")[1:]]
    table = {}
    for line in lines[lines.index(header) + 2:]:
        if not line.startswith("|"):
            break
        cells = [c.strip() for c in line.strip("|").split("|")]
        values = {}
        for name, cell in zip(names, cells[1:]):
            number = re.match(r"[\d.]+", cell)
            if number:
                values[name] = float(number.group())
        table[cells[0]] = values
    return table


def main() -> None:
    detection()
    scalability()
    frozen_error()
    model_stages()


if __name__ == "__main__":
    main()
