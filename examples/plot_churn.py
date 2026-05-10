"""Plot annual Nifty 500 churn (additions + removals) — produces docs/churn.png.

Used by the top-level README. Re-run after each data refresh.
"""
from __future__ import annotations
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
INDEX_CSV = ROOT / "index_history" / "data" / "index_membership_history.csv"
OUT = ROOT / "docs" / "churn.png"


def members_on(df: pd.DataFrame, index_name: str, on: pd.Timestamp) -> set[str]:
    sub = df[df.index_name == index_name]
    mask = (sub.valid_from <= on) & (sub.valid_to.isna() | (sub.valid_to > on))
    return set(sub.loc[mask, "symbol"])


def main() -> None:
    df = pd.read_csv(INDEX_CSV, parse_dates=["valid_from", "valid_to"])
    fig, axes = plt.subplots(2, 1, figsize=(10, 6.5), sharex=True)

    for ax, idx_name in zip(axes, ["Nifty 50", "Nifty 500"]):
        years = list(range(2015, 2027))
        added, removed = [], []
        for yr in years:
            a = members_on(df, idx_name, pd.Timestamp(yr - 1, 12, 31))
            b = members_on(df, idx_name, pd.Timestamp(yr, 12, 31))
            added.append(len(b - a))
            removed.append(-len(a - b))
        ax.bar(years, added,   color="#2ca02c", label="added")
        ax.bar(years, removed, color="#d62728", label="removed")
        ax.axhline(0, color="black", lw=0.6)
        ax.set_title(f"{idx_name} — annual churn")
        ax.set_ylabel("symbols")
        ax.legend(loc="upper left", frameon=False)
        ax.grid(axis="y", alpha=0.3)

    axes[-1].set_xlabel("year-end")
    plt.suptitle("NSE index churn — derived from nse-historical-membership", y=1.00)
    plt.tight_layout()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUT, dpi=120, bbox_inches="tight")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
