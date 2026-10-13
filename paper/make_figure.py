"""Draw Fig. 1 (AuditIQ architecture) for the paper.

Run:  python make_figure.py
Writes fig_architecture.pdf (for LaTeX) and fig_architecture.png (preview)
next to this script.
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parent

CODE = "#e3e3e3"   # deterministic code stage
LLM = "#ffffff"    # LLM stage
HUMAN = "#bdbdbd"  # human decision
STORE = "#f4f4f4"  # data at rest
EDGE = "#222222"
FS = 6.0

fig, ax = plt.subplots(figsize=(7.16, 2.5))
ax.set_xlim(-0.6, 100.6)
ax.set_ylim(0.2, 38.6)
ax.axis("off")


def box(x, y, w, h, text, fill, dashed=False, fs=FS):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.2,rounding_size=0.8",
        fc=fill, ec=EDGE, lw=0.7, ls="--" if dashed else "-"))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fs, linespacing=1.2)


def arrow(p, q, dashed=False):
    ax.add_patch(FancyArrowPatch(
        p, q, arrowstyle="-|>", mutation_scale=6, lw=0.7, color=EDGE,
        ls="--" if dashed else "-", shrinkA=1.5, shrinkB=1.5))


TOP, H = 24.0, 13.5
MID = TOP + H / 2

# --- pipeline, left to right -------------------------------------------
box(0.0, TOP, 11.0, H, "Source records\n\ninvoices, POs,\nGRNs, vendors,\napprovals", STORE)
box(13.0, TOP, 11.0, H, "1  Evidence\nextraction\n\n(SQL join)", CODE)
box(26.0, TOP, 12.0, H, "2  Deterministic\ncontrols\n\n(code; every\nflag has c = 1)", CODE)

ax.add_patch(FancyBboxPatch((40.0, TOP), 17.0, H, boxstyle="round,pad=0.2,rounding_size=0.8",
                            fc="none", ec=EDGE, lw=0.7))
ax.text(48.5, TOP + H - 1.5, "3  Specialist agents", ha="center", va="center", fontsize=FS)
for i, name in enumerate(["Math & approvals", "Tax & identity", "Vendor intelligence"]):
    box(41.3, TOP + 7.3 - i * 3.3, 14.4, 2.6, name, LLM, fs=FS - 0.4)

box(59.0, TOP, 13.0, H, "4  Challenger /\nverifier\n\n(LLM, then code\ngrounding check)", LLM)
box(74.0, TOP, 12.5, H, "5  Confidence-\nweighted\nrisk scorer\n\n(code)", CODE)
box(88.5, TOP, 11.5, H, "6  Router\n\n(code)", CODE)

for x0, x1 in [(11.0, 13.0), (24.0, 26.0), (38.0, 40.0), (57.0, 59.0), (72.0, 74.0), (86.5, 88.5)]:
    arrow((x0 - 0.2, MID), (x1 + 0.2, MID))

# --- outcomes -----------------------------------------------------------
OY, OH = 9.5, 7.0
box(59.0, OY, 12.0, OH, "Auto-approve", LLM)
box(73.0, OY, 12.5, OH, "Sampled\nreview", HUMAN)
box(87.5, OY, 12.5, OH, "Human review\napprove / reject /\noverride / re-analyse", HUMAN, fs=FS - 0.7)
for xt in (65.0, 79.25, 93.75):
    arrow((94.25, TOP), (xt, OY + OH))

# --- policy store -------------------------------------------------------
box(26.0, OY, 31.0, OH,
    "Policy store (versioned)\nactive policy text and clause thresholds,\nread at run time",
    STORE, dashed=True, fs=FS - 0.3)
arrow((32.0, OY + OH), (32.0, TOP), dashed=True)
arrow((48.5, OY + OH), (48.5, TOP), dashed=True)
arrow((55.0, OY + OH), (61.5, TOP), dashed=True)

# --- audit trail --------------------------------------------------------
box(0.0, 1.0, 100.0, 4.6,
    "Audit trail and audit pack:   rule  ->  evidence  ->  agent  ->  verifier  ->  reviewer  ->  outcome     (one record per stage, per transaction)",
    STORE)
arrow((18.5, TOP), (18.5, 5.6), dashed=True)
for xt in (65.0, 79.25, 93.75):
    arrow((xt, OY), (xt, 5.6), dashed=True)

# --- legend -------------------------------------------------------------
lx, ly = 0.3, 14.6
for i, (fill, label) in enumerate([(CODE, "deterministic code"), (LLM, "LLM stage"), (HUMAN, "human decision")]):
    ax.add_patch(FancyBboxPatch((lx, ly - i * 2.5), 2.4, 1.5, boxstyle="round,pad=0.1,rounding_size=0.4",
                                fc=fill, ec=EDGE, lw=0.6))
    ax.text(lx + 3.6, ly - i * 2.5 + 0.75, label, fontsize=FS - 0.6, va="center")

fig.subplots_adjust(left=0.0, right=1.0, top=1.0, bottom=0.0)
fig.savefig(OUT / "fig_architecture.pdf")
fig.savefig(OUT / "fig_architecture.png", dpi=220)
print("wrote", OUT / "fig_architecture.pdf")
