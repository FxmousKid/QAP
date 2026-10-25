"""House style for QA pass charts (matplotlib). Import it, draw, then save().

Run without installing anything:
    uv run --no-project --with matplotlib python my_chart.py

    import sys; sys.path.insert(0, "<skill>/scripts")
    from chart_style import plt, style, save, VERDICT, NEUTRAL
    style()
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    ...
    save(fig, "img/my-chart.png", title="What the reader should conclude", ax=ax)

Rules the style encodes:
- The title states the conclusion ("SaT is two thirds of the time"), not the variable name.
- Colour encodes a verdict (good / bad / neutral), not a value. Use VERDICT for pass/fail and
  better/worse, NEUTRAL for context series.
- Label the axes with units, annotate the bars or points that carry the argument, and draw
  limits and gates as dashed lines with a text label.
- The legend goes below the plot when it would hide data.
- Save at 200 dpi on a white background, so charts stay sharp on Retina (2x) screens and on wide
  layouts; the page shows them inside a bordered figure, in light and dark mode.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

VERDICT = {"good": "#2e7d32", "bad": "#c62828", "warn": "#b4700e", "info": "#2e5a86"}
NEUTRAL = ["#9aa5b1", "#5b6b7a", "#c9ced6"]
SERIES = ["#2878d6", "#e8673c", "#1aae7a", "#f0a30a", "#8a63d2", "#a7a29a"]


def style() -> None:
    plt.rcParams.update({
        "figure.dpi": 200,
        "savefig.dpi": 200,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.titlesize": 12,
        "axes.titlelocation": "left",
        "axes.labelsize": 10,
        "xtick.labelsize": 9.5,
        "ytick.labelsize": 9.5,
        "legend.frameon": False,
        "legend.fontsize": 9,
        "axes.grid": True,
        "grid.color": "#e6e6e6",
        "grid.linewidth": 0.8,
        "axes.axisbelow": True,
        "axes.prop_cycle": matplotlib.cycler(color=SERIES),
    })


def gate(ax, y: float, label: str, *, axis: str = "y") -> None:
    """Draw a limit or gate as a dashed line with its label."""
    if axis == "y":
        ax.axhline(y, color="#333", linestyle="--", linewidth=1)
        ax.text(ax.get_xlim()[1], y, f" {label}", va="bottom", ha="right", fontsize=9, color="#333")
    else:
        ax.axvline(y, color="#333", linestyle="--", linewidth=1)
        ax.text(y, ax.get_ylim()[1], f" {label}", va="top", ha="left", fontsize=9, color="#333", rotation=90)


def save(fig, path: str, *, title: str | None = None, ax=None, legend_below: bool = False) -> None:
    if title and ax is not None:
        ax.set_title(title)
    if legend_below and ax is not None:
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=3)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    print(path)
