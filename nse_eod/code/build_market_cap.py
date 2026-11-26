"""Point-in-time shares outstanding and market cap for every row of `_daily_ohlc.parquet`.

Sources, in order of preference for each (symbol, date):
  nse_mcap     NSE's daily `mcap` file (PR zip, from mid-2024): issue size that day. Exact.
  shareholding `shareholding_history` quarterly `total_shares`, usable from the day after the
               filing's broadcast date. Renames are followed through NSE's symbolchange.csv.
  backfill     the symbol's first `mcap` issue size carried back through bonuses and face-value
               splits (`bc` corporate-action files). Misses fresh issues (IPOs, QIPs,
               preferential allotments); stops at any capital reduction or consolidation.

Output `data/_market_cap.parquet`: symbol, date, series, shares, mcap_inr, shares_source.
Needs `fetch_bhavcopy --dataset pr` and `build_daily_ohlc` first.

Run:  python -m nse_eod.code.build_market_cap
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PR_DIR = ROOT / "data" / "pr"
OHLC = ROOT / "data" / "_daily_ohlc.parquet"
OUT = ROOT / "data" / "_market_cap.parquet"
SYMCHG = ROOT / "data" / "symbolchange.csv"
SYMCHG_URL = "https://nsearchives.nseindia.com/content/equities/symbolchange.csv"
SHP = ROOT.parent / "shareholding_history" / "data"


# ------------------------------------------------------------------ corporate-action factors

_BONUS = re.compile(r"BONUS\s*(\d+)\s*:\s*(\d+)")
_SPLIT = re.compile(r"F\s*V\s*SPL\w*\s*FRM\s*R[SE]\.?\s*([\d.]+)\s*(?:/-)?\s*TO\s*R[SE]\.?\s*([\d.]+)")
_UNKNOWN = re.compile(r"CAPITAL REDUCTION|CONSOLIDAT")


def share_factor(purpose: str) -> float | None:
    """Multiplier on shares outstanding at the ex-date; 1.0 = no change, None = unknown change."""
    p = " ".join(purpose.upper().split())
    f = 1.0
    if (m := _BONUS.search(p)):
        a, b = int(m.group(1)), int(m.group(2))
        f *= (a + b) / b                       # a new shares for every b held
    if (m := _SPLIT.search(p)):
        f *= float(m.group(1)) / float(m.group(2))
    if _UNKNOWN.search(p):
        return None
    return f


assert share_factor("BONUS 1:1") == 2.0
assert share_factor("BONUS 1:2 /DIV-RS 0.50") == 1.5
assert share_factor("BONUS 3:1") == 4.0
assert share_factor("FVSPLT FRM RS 10 TO RE 1") == 10.0
assert share_factor("FV SPLT FRM RS 5 TO RS 2") == 2.5
assert share_factor("AGM/DIV-RS 21.1 PER SH") == 1.0
assert share_factor("CAPITAL REDUCTION") is None


_DATE = re.compile(r"^\s*(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})\s*$")


def _bc_row(f: list[str]) -> list[tuple[str, str, str]]:
    """SERIES,SYMBOL,SECURITY,RECORD_DT,BC_STRT_DT,BC_END_DT,EX_DT,ND_STRT_DT,ND_END_DT,PURPOSE.

    SECURITY and PURPOSE may hold unquoted commas, so the four date-ish fields before
    PURPOSE are found as the first run of date-or-blank fields after SECURITY."""
    if len(f) < 10:
        return []
    for i in range(3, len(f) - 6):
        block = f[i:i + 6]
        if all(_DATE.match(x) or not x.strip() for x in block) and _DATE.match(f[i + 3] or "x"):
            return [(f[1].strip(), f[i + 3].strip(), ",".join(f[i + 6:]).strip())]
    return []


assert _bc_row("EQ,ABC,ABC LTD, ,01/07/2024,05/07/2024,05/07/2024, , ,BONUS 1:1".split(",")) == \
    [("ABC", "05/07/2024", "BONUS 1:1")]
assert _bc_row("EQ,XYZ,X, Y AND Z LTD,26/07/2024, , ,26/07/2024, , ,DIV - RS 3, SPL DIV".split(",")) == \
    [("XYZ", "26/07/2024", "DIV - RS 3, SPL DIV")]


def load_actions() -> pd.DataFrame:
    """De-duplicated (symbol, ex_date, factor) for actions that change the share count."""
    rows = []
    for p in sorted(PR_DIR.glob("bc_*.csv")):
        if p.stat().st_size == 0:
            continue
        lines = list(csv.reader(p.read_text(encoding="latin-1").splitlines()))
        for f in lines[1:]:
            rows.extend(_bc_row(f))
    a = pd.DataFrame(rows, columns=["SYMBOL", "EX_DT", "PURPOSE"]).dropna()
    a = a.assign(symbol=a.SYMBOL.str.strip(), purpose=a.PURPOSE.str.strip(),
                 ex_date=pd.to_datetime(a.EX_DT.str.strip(), dayfirst=True, errors="coerce",
                                        format="mixed"))
    a = a.dropna(subset=["ex_date"]).drop_duplicates(["symbol", "ex_date", "purpose"])
    a["ex_date"] = a.ex_date.astype("datetime64[ns]")
    a["factor"] = a.purpose.map(share_factor)
    a = a[a.factor.isna() | (a.factor != 1.0)]
    # one row per symbol-day; an unknown action on a day makes the day unknown
    return (a.groupby(["symbol", "ex_date"]).factor
            .apply(lambda s: np.nan if s.isna().any() else float(np.prod(s))).reset_index())


# ------------------------------------------------------------------ sources

def load_nse_mcap() -> pd.DataFrame:
    frames = []
    for p in sorted(PR_DIR.glob("mcap_*.csv")):
        m = pd.read_csv(p, dtype=str, encoding="latin-1", skipinitialspace=True)
        m.columns = [c.strip() for c in m.columns]
        frames.append(pd.DataFrame({
            "date": pd.to_datetime(m["Trade Date"].str.strip(), format="%d %b %Y").astype("datetime64[ns]"),
            "symbol": m["Symbol"].str.strip(), "series": m["Series"].str.strip(),
            "shares": pd.to_numeric(m["Issue Size"].str.strip(), errors="coerce")}))
    return pd.concat(frames).dropna().drop_duplicates(["date", "symbol", "series"])


def final_symbol_map() -> dict[str, str]:
    """old symbol -> latest symbol, following chains (A->B, B->C gives A->C)."""
    if not SYMCHG.exists():
        import requests  # rebuild-side only; keeps the module importable with pandas alone
        r = requests.get(SYMCHG_URL, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        SYMCHG.write_bytes(r.content)
    s = pd.read_csv(SYMCHG, dtype=str, encoding="latin-1")
    s.columns = [c.strip() for c in s.columns]
    s["d"] = pd.to_datetime(s["EFFECTIVE DATE"].str.strip(), format="%d-%b-%Y", errors="coerce")
    nxt = {o.strip(): n.strip() for o, n in
           s.sort_values("d")[["OLD SYMBOL", "NEW SYMBOL"]].dropna().itertuples(index=False)}
    out = {}
    for o in nxt:
        cur, seen = o, {o}
        while cur in nxt and nxt[cur] not in seen:
            cur = nxt[cur]
            seen.add(cur)
        out[o] = cur
    return out


def load_shareholding() -> pd.DataFrame:
    w = pd.read_csv(SHP / "parsed" / "_wide.csv", usecols=["ticker", "period", "total_shares"]).dropna()
    rows = []
    for f in (SHP / "filings_index").glob("*.json"):
        d = json.loads(f.read_text())
        for x in d.get("filings", []):
            if x.get("broadcast_date") and x.get("date"):
                rows.append((d["ticker"], x["date"], x["broadcast_date"][:11]))
    b = pd.DataFrame(rows, columns=["ticker", "qend", "bdate"])
    b["period"] = pd.to_datetime(b.qend, format="%d-%b-%Y").dt.strftime("%Y-%m")
    b["bdate"] = pd.to_datetime(b.bdate, format="%d-%b-%Y")
    b = b.groupby(["ticker", "period"], as_index=False).bdate.min()      # first broadcast
    s = w.merge(b, on=["ticker", "period"])
    return pd.DataFrame({"key": s.ticker, "avail_date": (s.bdate + pd.Timedelta(days=1)).astype("datetime64[ns]"),
                         "shares": s.total_shares})


# ------------------------------------------------------------------ build

def backfill(panel: pd.DataFrame, nse: pd.DataFrame, actions: pd.DataFrame) -> pd.Series:
    """Shares before each symbol's first nse_mcap date, carried back through known actions."""
    first = (nse.sort_values("date").groupby("symbol").first()[["date", "shares"]]
             .rename(columns={"date": "t0", "shares": "s0"}))
    p = panel[["symbol", "date"]].join(first, on="symbol")
    p = p[p.date < p.t0]
    # cumulative product of factors from the far future backwards: shares(d) = s0 / prod(f, d < ex <= t0)
    act = actions.join(first, on="symbol").dropna(subset=["t0"])
    act = act[act.ex_date <= act.t0].sort_values(["symbol", "ex_date"])
    act["unknown"] = act.factor.isna()
    g = act.iloc[::-1].groupby("symbol")
    act["prod_after"] = g.factor.transform(lambda x: x.fillna(1.0).cumprod())  # ex >= this one
    act["unknown_after"] = g.unknown.transform("cummax")
    # for row date d, the relevant set is ex > d: the first action strictly after d
    p = p.sort_values("date")
    act = act.sort_values("ex_date")
    m = pd.merge_asof(p.reset_index(), act[["symbol", "ex_date", "prod_after", "unknown_after"]],
                      left_on="date", right_on="ex_date", by="symbol",
                      direction="forward", allow_exact_matches=False).set_index("index")
    shares = m.s0 / m.prod_after.fillna(1.0)
    return shares.where(~m.unknown_after.fillna(False).astype(bool))


def main() -> None:
    panel = pd.read_parquet(OHLC, columns=["symbol", "date", "series", "close"])
    panel["date"] = pd.to_datetime(panel.date).astype("datetime64[ns]")
    nse = load_nse_mcap()
    nse["date"] = nse.date.astype("datetime64[ns]")
    print(f"nse_mcap: {nse.date.nunique()} days, {nse.date.min().date()} → {nse.date.max().date()}")

    out = panel.merge(nse.rename(columns={"shares": "s_nse"}), on=["date", "symbol", "series"], how="left")

    fmap = final_symbol_map()
    shp = load_shareholding()
    shp["key"] = shp.key.map(lambda t: fmap.get(t, t))
    shp["avail_date"] = shp.avail_date.astype("datetime64[ns]")
    out["key"] = out.symbol.map(lambda t: fmap.get(t, t))
    out = pd.merge_asof(out.sort_values("date"), shp.sort_values("avail_date").rename(columns={"shares": "s_shp"}),
                        left_on="date", right_on="avail_date", by="key", direction="backward")
    out = out.drop(columns=["avail_date"]).sort_values(["symbol", "date", "series"]).reset_index(drop=True)

    actions = load_actions()
    out["s_back"] = backfill(out, nse, actions).reindex(out.index)

    out["shares"] = out.s_nse.fillna(out.s_shp).fillna(out.s_back)
    out["shares_source"] = np.select([out.s_nse.notna(), out.s_shp.notna(), out.s_back.notna()],
                                     ["nse_mcap", "shareholding", "backfill"], "none")
    out["mcap_inr"] = out.shares * out.close

    # agreement checks where two sources overlap
    both = out.dropna(subset=["s_nse", "s_shp"])
    r1 = (both.s_shp / both.s_nse - 1).abs()
    print(f"shareholding vs nse_mcap: {len(both):,} rows, median |diff| {r1.median():.2%}, "
          f"within 5%: {(r1 < 0.05).mean():.1%}")
    bb = out.dropna(subset=["s_back", "s_shp"])
    r2 = (bb.s_back / bb.s_shp - 1).abs()
    print(f"backfill vs shareholding: {len(bb):,} rows, median |diff| {r2.median():.2%}, "
          f"within 10%: {(r2 < 0.10).mean():.1%}")
    cov = out.assign(y=out.date.dt.year).groupby(["y", out.series.isin(["SM", "ST"]).map({True: "SME", False: "main"})]
                                                 ).shares_source.value_counts(normalize=True).unstack().round(3)
    print("share-count source by year (row share):")
    print(cov.to_string())

    out[["symbol", "date", "series", "shares", "mcap_inr", "shares_source"]].to_parquet(OUT, index=False)
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
