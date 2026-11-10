"""Generate report figures from tools/backtest/data/rows_all.jsonl."""

import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
rows = [json.loads(line) for line in (ROOT / "tools/backtest/data/rows_all.jsonl").read_text().splitlines()]
OUT = Path(__file__).parent / "fig"
OUT.mkdir(exist_ok=True)

INK, MUTED, A, B = "#1f2328", "#6e7781", "#cf4a3c", "#3b6fb6"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
                     "xtick.color": INK, "ytick.color": INK, "axes.spines.top": False, "axes.spines.right": False})


def wilson(k, n, z=1.645):
    if n == 0:
        return 0, 0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0, c - m), c + m


# Figure 1: event rate by CI state at merge, per split
fig, ax = plt.subplots(figsize=(6.2, 3.2))
groups = [("Tuning", "tuning"), ("Holdout", "holdout"), ("Pooled", None)]
w = 0.36
for i, (label, split) in enumerate(groups):
    rs = [r for r in rows if split is None or r["split"] == split]
    for j, (name, cond, col) in enumerate(
        [("CI passing", lambda r: r["ci"] == "success", B), ("CI not passing", lambda r: r["ci"] != "success", A)]
    ):
        g = [r for r in rs if cond(r)]
        k = sum(r["event"] for r in g)
        rate = k / len(g)
        lo, hi = wilson(k, len(g))
        x = i + (j - 0.5) * w
        ax.bar(x, rate * 100, w * 0.92, color=col, label=name if i == 0 else None)
        ax.errorbar(x, rate * 100, yerr=[[(rate - lo) * 100], [(hi - rate) * 100]], color=INK, capsize=3, lw=1)
        ax.text(x, hi * 100 + 0.25, f"{k}/{len(g)}", ha="center", fontsize=8, color=MUTED)
ax.set_xticks(range(len(groups)), [g[0] for g in groups])
ax.set_ylim(0, 8.2)
ax.set_ylabel("Revert or fix within 14 days (%)")
ax.legend(frameon=False, loc="upper right")
ax.set_title("Agent PRs merged while CI was not passing", loc="left", fontsize=11, color=INK)
fig.tight_layout()
fig.savefig(OUT / "fig1_ci_effect.png", dpi=200)

# Figure 2: what agent PRs look like
labels = ["No linked issue", "Source w/o tests", "Touches critical paths", "CI not passing at merge", "Fast-path eligible (T1)"]
fns = [
    lambda r: "Agent PR without a linked issue/ticket" in r["missing"],
    lambda r: "Source changes without test changes" in r["missing"],
    lambda r: "critical_paths" in r["reasons"],
    lambda r: r["ci"] != "success",
    lambda r: r["tier"] == "T1",
]
vals = [100 * sum(map(fn, rows)) / len(rows) for fn in fns]
fig, ax = plt.subplots(figsize=(6.2, 2.8))
ax.barh(range(len(labels))[::-1], vals, color=[B, B, B, A, MUTED])
for y, v in zip(range(len(labels))[::-1], vals):
    ax.text(v + 1, y, f"{v:.0f}%", va="center", fontsize=9)
ax.set_yticks(range(len(labels))[::-1], labels)
ax.set_xlim(0, 65)
ax.set_xlabel(f"Share of {len(rows):,} merged agent PRs")
ax.set_title("Profile of agent-authored PRs in active open source", loc="left", fontsize=11, color=INK)
fig.tight_layout()
fig.savefig(OUT / "fig2_profile.png", dpi=200)
print("figures written to", OUT)
