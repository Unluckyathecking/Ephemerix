"""Before/after plot of per-epoch residuals from the published track (parallax removed).

    uv run --with matplotlib python probes/astro/plot_residuals.py before.json after.json out.png

The JSON files are written by residuals.py --json. Written with Claude Code.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

BANDS = {"W2": ("o", "tab:blue"), "W1": ("^", "tab:green"), "spx-b6": ("s", "tab:red")}


def panel(ax, rows: list[dict], title: str) -> None:
    for band, (marker, color) in BANDS.items():
        pts = [(r["mjd"], r["res_en"]) for r in rows if r["band"] == band and r["res_en"]]
        if not pts:
            continue
        yr = [2000 + (m - 51544.5) / 365.25 for m, _ in pts]
        ax.plot(yr, [p[0] for _, p in pts], marker, color=color, ms=4, label=f"{band} E")
        ax.plot(yr, [p[1] for _, p in pts], marker, color=color, ms=4, mfc="none",
                label=f"{band} N")
    ax.axhline(0, color="grey", lw=0.5)
    ax.set_ylim(-3, 3)
    ax.set_title(title, fontsize=9)
    ax.set_ylabel("measured - Gaia (arcsec)", fontsize=8)


def main(before: Path, after: Path, out: Path) -> None:
    b, a = json.loads(before.read_text()), json.loads(after.read_text())
    fig, axes = plt.subplots(len(a), 2, figsize=(11, 2.6 * len(a)), sharex=True)
    for i, (rb, ra) in enumerate(zip(b, a)):
        panel(axes[i][0], rb["rows"], f"{rb['slug']}: before")
        panel(axes[i][1], ra["rows"], f"{ra['slug']}: after")
    axes[0][1].legend(fontsize=7, ncol=3, loc="upper right")
    fig.tight_layout()
    fig.savefig(out, dpi=90)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
