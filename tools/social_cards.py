"""Generate social-preview card candidates (1280x640) from the dataset.

Three designs on one shared dark design system:
  card2          Constituent lifespan (Gantt of Nifty 50 tenures)
  social-preview Index churn river (Nifty 500 add/remove per year) <- CHOSEN
  card4          Membership heatmap (Nifty 50 month-by-month "fabric")

`social-preview.png` is the card uploaded to GitHub Settings -> Social preview.
card2/card4 are kept candidates (not tracked).

Run: ./venv/bin/python -m tools.social_cards
Out: docs/social/{social-preview,card2,card4}.png
"""
from __future__ import annotations
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib import font_manager
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
INDEX_CSV = ROOT / "index_history" / "data" / "index_membership_history.csv"
OUTDIR = ROOT / "docs" / "social"
OUTDIR.mkdir(parents=True, exist_ok=True)

# ---- design system -------------------------------------------------------
BG      = "#0B1220"   # deep navy canvas
PANEL   = "#111B2E"   # slightly lighter panel
INK     = "#E8EEF6"   # primary text
MUTE    = "#8A97A8"   # secondary text
FAINT   = "#5A6678"   # footer / gridlines
ACCENT  = "#38BDF8"   # sky — "in index"
GOOD    = "#3FB950"   # add (GitHub green)
BAD     = "#F85149"   # remove (GitHub red)
AMBER   = "#F0B429"   # highlight

SANS = "DejaVu Sans"
MONO = "DejaVu Sans Mono"

W, H, DPI = 1280, 640, 160
FIGSIZE = (W / DPI, H / DPI)

LEFT, RIGHT = 0.055, 0.945
URL = "github.com/aditya-jha/nse-historical-membership"


def _new_fig():
    fig = plt.figure(figsize=FIGSIZE, dpi=DPI)
    fig.patch.set_facecolor(BG)
    return fig


def _frame(fig, kicker, title_lines, tagline, chips=None):
    """Shared title block + footer. Returns nothing; caller adds the axes."""
    # accent kicker (uppercase, tracked)
    fig.text(LEFT, 0.935, kicker, color=ACCENT, fontfamily=MONO, fontsize=10.5,
             fontweight="bold")
    # title (bold, up to 2 lines)
    y = 0.815
    for ln in title_lines:
        fig.text(LEFT, y, ln, color=INK, fontfamily=SANS, fontsize=28,
                 fontweight="bold")
        y -= 0.078
    # tagline
    fig.text(LEFT, y + 0.005, tagline, color=MUTE, fontfamily=SANS, fontsize=12.5)
    # footer rule + url
    fig.add_artist(plt.Line2D([LEFT, RIGHT], [0.085, 0.085], color="#1E2A40",
                              lw=1.0, transform=fig.transFigure))
    fig.text(LEFT, 0.045, URL, color=FAINT, fontfamily=MONO, fontsize=10.5)
    fig.text(RIGHT, 0.045, "MIT · CC BY 4.0", color=FAINT, fontfamily=MONO,
             fontsize=10.5, ha="right")
    # optional stat chips on the right of the footer-ish area
    if chips:
        x = RIGHT
        for label in reversed(chips):
            fig.text(x, 0.905, label, color=MUTE, fontfamily=MONO, fontsize=10.5,
                     ha="right", fontweight="bold")
            x -= 0.005  # chips stack via the label text itself


def _style_ax(ax):
    ax.set_facecolor("none")
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(colors=MUTE, labelsize=9.5, length=0)


def load():
    return pd.read_csv(INDEX_CSV, parse_dates=["valid_from", "valid_to"])


# ---- card 2: constituent lifespan (Gantt) --------------------------------
def card2(df):
    n50 = df[df.index_name == "Nifty 50"].copy()
    now = pd.Timestamp("2026-06-01")
    n50["end"] = n50.valid_to.fillna(now)
    n50["open"] = n50.valid_to.isna()
    # one row per symbol: take its widest interval span for a clean cascade
    g = (n50.groupby("symbol")
             .agg(start=("valid_from", "min"), end=("end", "max"),
                  open=("open", "max"))
             .reset_index())
    g = g.sort_values("start").reset_index(drop=True)
    g = g[g.start >= pd.Timestamp("2013-06-01")]  # keep the visible window tidy
    n = len(g)

    fig = _new_fig()
    ax = fig.add_axes([LEFT, 0.115, RIGHT - LEFT, 0.495])
    _style_ax(ax)
    d2n = matplotlib.dates.date2num
    x0 = d2n(pd.Timestamp("2014-01-01"))
    for i, r in g.iterrows():
        s, e = d2n(r.start), d2n(r.end)
        color = ACCENT if r.open else BAD
        alpha = 0.92 if r.open else 0.55
        ax.broken_barh([(s, e - s)], (i - 0.40, 0.80),
                       facecolors=color, alpha=alpha, edgecolor="none")
    # iconic exits as clean right-gutter callouts (no clipping)
    iconic = {"HDFC": "HDFC — merged 2023", "LTM": "MINDTREE → LTM",
              "INDUSINDBK": "INDUSINDBK — exit 2025"}
    gutter = d2n(pd.Timestamp("2030-02-01"))
    for i, r in g.iterrows():
        if r.symbol in iconic:
            e = d2n(r.end)
            ax.plot([e, gutter], [i, i], color=FAINT, lw=0.7, alpha=0.55, zorder=1)
            ax.scatter([e], [i], s=10, color=INK, zorder=2)
            ax.annotate(iconic[r.symbol], (gutter, i), color=INK, fontsize=8.5,
                        fontfamily=MONO, va="center", ha="right")
    ax.set_xlim(x0, d2n(pd.Timestamp("2030-06-01")))
    ax.set_ylim(-1, n)
    ax.invert_yaxis()
    ax.set_yticks([])
    ax.xaxis_date()
    ax.xaxis.set_major_locator(matplotlib.dates.YearLocator(2))
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%Y"))
    ax.set_xticks([d2n(pd.Timestamp(f"{y}-01-01")) for y in range(2014, 2027, 2)])
    ax.grid(axis="x", color="#1A2740", lw=0.8, alpha=0.7)
    ax.set_axisbelow(True)

    _frame(fig,
           "NSE · POINT-IN-TIME",
           ["Every constituent. Every date."],
           "Nifty 50 membership tenure, 2014 → today")
    fig.legend(handles=[mpatches.Patch(color=ACCENT, label="currently in index"),
                        mpatches.Patch(color=BAD, label="since removed")],
               loc="lower left", bbox_to_anchor=(LEFT, 0.645), ncol=2,
               frameon=False, labelcolor=MUTE, fontsize=10,
               handlelength=1.1, columnspacing=1.4)
    out = OUTDIR / "card2.png"
    fig.savefig(out, dpi=DPI, facecolor=BG)
    plt.close(fig)
    return out


# ---- card 3: churn river -------------------------------------------------
def members_on(df, name, on):
    sub = df[df.index_name == name]
    m = (sub.valid_from <= on) & (sub.valid_to.isna() | (sub.valid_to > on))
    return set(sub.loc[m, "symbol"])


def card3(df):
    name = "Nifty 500"
    years = list(range(2015, 2027))
    added, removed = [], []
    for yr in years:
        a = members_on(df, name, pd.Timestamp(yr - 1, 12, 31))
        b = members_on(df, name, pd.Timestamp(yr, 12, 31))
        added.append(len(b - a))
        removed.append(-len(a - b))

    fig = _new_fig()
    ax = fig.add_axes([LEFT, 0.135, RIGHT - LEFT, 0.46])
    _style_ax(ax)
    ax.bar(years, added, color=GOOD, width=0.62, label="added", zorder=3)
    ax.bar(years, removed, color=BAD, width=0.62, label="removed", zorder=3)
    ax.axhline(0, color=FAINT, lw=1.0)
    # value labels
    for x, v in zip(years, added):
        if v:
            ax.text(x, v + 2, str(v), color=GOOD, fontsize=8.5, ha="center",
                    fontfamily=MONO, fontweight="bold")
    for x, v in zip(years, removed):
        if v:
            ax.text(x, v - 2, str(-v), color=BAD, fontsize=8.5, ha="center",
                    va="top", fontfamily=MONO, fontweight="bold")
    ax.set_xticks(years)
    ax.set_yticks([])
    ax.set_xlim(years[0] - 0.7, years[-1] + 0.7)
    mx = max(max(added), -min(removed)) + 12
    ax.set_ylim(-mx, mx)

    _frame(fig,
           "NSE · POINT-IN-TIME",
           ["Indices aren't static."],
           "Constituents added & removed from the Nifty 500, every year")
    fig.legend(handles=[mpatches.Patch(color=GOOD, label="added"),
                        mpatches.Patch(color=BAD, label="removed")],
               loc="lower left", bbox_to_anchor=(LEFT, 0.645), ncol=2,
               frameon=False, labelcolor=MUTE, fontsize=10,
               handlelength=1.1, columnspacing=1.4)
    out = OUTDIR / "social-preview.png"   # <- the chosen GitHub social card
    fig.savefig(out, dpi=DPI, facecolor=BG)
    plt.close(fig)
    return out


# ---- card 4: membership heatmap (fabric) ---------------------------------
def card4(df):
    name = "Nifty 50"
    months = pd.date_range("2014-01-01", "2026-06-01", freq="MS")
    n50 = df[df.index_name == name]
    syms = sorted(n50.symbol.unique())
    M = np.zeros((len(syms), len(months)))
    idx = {s: i for i, s in enumerate(syms)}
    for _, r in n50.iterrows():
        lo = r.valid_from
        hi = r.valid_to if pd.notna(r.valid_to) else months[-1] + pd.Timedelta(days=1)
        for j, m in enumerate(months):
            if lo <= m < hi:
                M[idx[r.symbol], j] = 1
    # sort rows by first month present -> diagonal texture
    first = [np.argmax(row) if row.any() else len(months) for row in M]
    order = np.argsort(first)
    M = M[order]

    from matplotlib.colors import ListedColormap
    cmap = ListedColormap([PANEL, ACCENT])

    fig = _new_fig()
    ax = fig.add_axes([LEFT, 0.115, RIGHT - LEFT, 0.50])
    _style_ax(ax)
    ax.imshow(M, aspect="auto", cmap=cmap, interpolation="nearest",
              extent=[matplotlib.dates.date2num(months[0]),
                      matplotlib.dates.date2num(months[-1]), len(syms), 0])
    ax.set_yticks([])
    ax.xaxis_date()
    ax.xaxis.set_major_locator(matplotlib.dates.YearLocator(2))
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%Y"))
    ax.tick_params(colors=MUTE, labelsize=9.5, length=0)

    _frame(fig,
           "NSE · POINT-IN-TIME",
           ["12 years, reconstructed."],
           f"Who was in the {name}, month by month — {len(syms)} symbols")
    fig.text(RIGHT, 0.645, "each row = one stock", color=FAINT, fontfamily=MONO,
             fontsize=9.5, ha="right")
    out = OUTDIR / "card4.png"
    fig.savefig(out, dpi=DPI, facecolor=BG)
    plt.close(fig)
    return out


def main():
    df = load()
    for fn in (card2, card3, card4):
        print("wrote", fn(df))


if __name__ == "__main__":
    main()
