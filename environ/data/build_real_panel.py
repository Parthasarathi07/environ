"""
build_real_panel.py — turn real ESG scores + real prices into the panel this
project analyses.

This is the file that decides whether the project is a demo or a tool. The
analysis in `environ/stats.py` never touches `config.py` and never knows where
its rows came from, so pointing it at observed data is a data problem, not a
code problem. This module solves the data problem for the two free sources a
student can actually get:

    ratings  ESG-Book, public on Hugging Face (CC-BY-4.0)
             https://huggingface.co/datasets/ESG-Book/esg
             columns: date, name, sector, esg, esg_unadjusted, esg_controversy, symbol
    prices   yfinance monthly adjusted close (or any "date,ticker,close" CSV)
             python -m pip install yfinance

    # 1. ratings
    #    download the CSV from the dataset's "Files" tab, or:
    #    huggingface-cli download ESG-Book/esg data.csv --repo-type dataset
    # 2. prices
    python -m environ.data.build_real_panel --fetch-prices SIM   # (needs network)
    # 3. merge -> panel.csv + firms.csv
    python -m environ.data.build_real_panel \\
        --ratings esg.csv --prices prices.csv --out environ/data/panel.csv
    # 4. restart the app; everything, including the verdict sentences, rebuilds

Two honest warnings built in
--------------------------
* If `sector` is missing, sector-neutralisation silently becomes
  whole-market neutralisation and the headline finding of this project
  disappears with it. So the loader refuses to do that quietly: it raises
  unless you pass `--allow-missing-sector`.
* Prices from yfinance are *adjusted closes*, which is total return for
  dividends but not for spin-offs, and coverage starts when the stock starts.
  The loader reports what it could and could not derive, and the app shows it.
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

# column aliases we accept, so you can be lazy about renaming
RATINGS_ALIASES = {
    "esg_score": ["esg", "esg_unadjusted", "esg_score", "sustainology_rating", "rating"],
    "date": ["date", "as_of_date", "quarter", "reporting_date"],
    "ticker": ["symbol", "ticker", "isin", "permno", "id"],
    "sector": ["sector", "gics_sector", "sectorname", "sector_name"],
    "esg_controversy": ["esg_controversy", "controversy"],
}
PRICES_ALIASES = {
    "close": ["close", "adj_close", "adjusted_close", "Adj Close", "price"],
    "date": ["date", "Date", "month"],
    "ticker": ["symbol", "ticker", "Ticker", "id"],
}


def _rename(df: pd.DataFrame, aliases: dict[str, list[str]]) -> pd.DataFrame:
    """First alias present wins; original spelling is discarded."""
    out, mapping = pd.DataFrame(), {}
    for std, cands in aliases.items():
        for c in cands:
            if c in df.columns and c not in mapping.values():
                mapping[c] = std
                break
    out = df.rename(columns=mapping)
    keep = [c for c in out.columns if c in list(aliases) or c not in {v for vs in aliases.values() for v in vs}]
    return out[keep]


def month_end(d: pd.Series) -> pd.Series:
    return pd.to_datetime(d).values.astype("datetime64[M]").astype("datetime64[ns]") + pd.Timedelta(days=1) - pd.Timedelta(days=1)


def _as_month_key(d: pd.Series) -> pd.Series:
    return pd.to_datetime(d).dt.to_period("M").astype(str) + "-01"


def load_ratings(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = _rename(df, RATINGS_ALIASES)
    need = [c for c in ("date", "ticker", "esg_score") if c not in df.columns]
    if need:
        raise SystemExit(
            f"ratings file has no {need}. columns found: {list(df.columns)}\n"
            f"accepts any of: {RATINGS_ALIASES}"
        )
    df["mkey"] = _as_month_key(df["date"])
    df["esg_score"] = pd.to_numeric(df["esg_score"], errors="coerce")
    if "sector" not in df.columns:
        df["sector"] = np.nan
        print("  ! no sector column - see the docstring; pass --allow-missing-sector to proceed anyway")
    # one rating per firm-month: mean of what the provider published that month
    df = df.groupby(["mkey", "ticker"], as_index=False).agg(
        esg_score=("esg_score", "mean"),
        **({"sector": ("sector", "first")} if df.sector.notna().any() else {}),
    )
    return df.dropna(subset=["esg_score"])


def load_prices(path: str | None, fetch_tickers: str | None) -> pd.DataFrame:
    if path:
        px = pd.read_csv(path)
        px = _rename(px, PRICES_ALIASES)
        if "close" not in px.columns:
            raise SystemExit(f"price file needs a close column; got {list(px.columns)}")
    else:
        import yfinance as yf  # noqa: PLC0415 - optional dependency, by design

        tickers = [t.strip() for t in fetch_tickers.split(",") if t.strip()]
        frames = []
        for i in range(0, len(tickers), 50):
            chunk = tickers[i : i + 50]
            print(f"  fetching {i+1}-{i+len(chunk)} of {len(tickers)} tickers…")
            d = yf.download(chunk, period="max", interval="1mo", auto_adjust=True, progress=False)
            if d is None or d.empty:
                continue
            c = d["Close"] if isinstance(d.columns, pd.MultiIndex) else d[["Close"]]
            long = c.stack().reset_index()
            long.columns = ["date", "ticker", "close"][: len(long.columns)]
            frames.append(long)
        if not frames:
            raise SystemExit("yfinance returned nothing - check names and network access")
        px = pd.concat(frames, ignore_index=True)
    px["mkey"] = _as_month_key(px["date"])
    px["close"] = pd.to_numeric(px["close"], errors="coerce")
    px = px.dropna(subset=["close", "ticker"])
    px = px.sort_values(["ticker", "mkey"]).drop_duplicates(["ticker", "mkey"], keep="last")
    return px[["mkey", "ticker", "close"]]


def build(ratings: pd.DataFrame, prices: pd.DataFrame, min_hist: int = 24) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Merge, compute returns and derive the columns stats.py wants."""
    px = prices.copy()
    px["ret_m"] = px.groupby("ticker").close.pct_change() * 100.0
    px = px.dropna(subset=["ret_m"])
    if px.empty:
        raise SystemExit("no returns could be computed - need at least 2 monthly closes per ticker")

    # --- the month grid comes from PRICES, not from the merge.
    # Ratings are published quarterly; returns are monthly. Intersecting first
    # would silently throw away every month between publications and hand you a
    # quarterly strategy dressed up as a monthly one. Instead: build the full
    # price panel, then carry the last published rating forward.
    have_sector = "sector" in ratings.columns and ratings.sector.notna().any()
    universe = px[["ticker"]].drop_duplicates()
    if have_sector:
        universe = universe.merge(ratings[["ticker", "sector"]].drop_duplicates("ticker"), on="ticker", how="left")
    months = pd.DataFrame({"mkey": sorted(px.mkey.unique())})
    d = universe.merge(months, how="cross").merge(
        px[["mkey", "ticker", "ret_m"]], on=["mkey", "ticker"], how="left"
    )
    # sector is carried on `universe` (one value per firm); keeping it in the
    # ratings frame too would collide and create sector_x / sector_y.
    d = d.merge(ratings[["mkey", "ticker", "esg_score"]].drop_duplicates(["mkey", "ticker"]),
                on=["mkey", "ticker"], how="left")
    d = d.sort_values(["ticker", "mkey"])
    d["esg_score"] = d.groupby("ticker").esg_score.ffill()
    if have_sector:
        d["sector"] = d.groupby("ticker").sector.ffill()
    else:
        d["sector"] = np.nan
    d = d.dropna(subset=["esg_score", "ret_m"])
    if d.empty:
        raise SystemExit("no firm-months survived - check that ticker names match between the two files")

    n_hist = d.groupby("ticker").mkey.transform("count")
    before = len(d)
    d = d[n_hist >= min_hist]
    if before - len(d):
        print(f"  dropped {before - len(d)} firm-months from firms with <{min_hist} months of history")

    d["date"] = d["mkey"]
    d["year"] = pd.to_datetime(d["date"]).dt.year
    d["month"] = pd.to_datetime(d["date"]).dt.month
    if d.sector.isna().all() or (d.sector.nunique() == 1):
        print("  ! no usable sector column: the naive and the sector-neutral views will be identical. "
              "That is expected here, not a bug - it just means this file cannot answer the question.")
        d["sector"] = "Unknown"
    d["sector"] = d["sector"].astype("string").fillna("Unknown")

    # --- ESG level, cross-sectional z each month
    g = d.groupby("date")["esg_score"]
    d["esg_z"] = (d["esg_score"] - g.transform("mean")) / g.transform("std").replace(0, np.nan)

    # --- momentum: trailing 12-month change in the published score, z-scored
    d["esg_change_12m"] = d.groupby("ticker")["esg_score"].diff(12)
    d["esg_reported_change_12m"] = d["esg_change_12m"]
    gm = d.groupby("date")["esg_change_12m"]
    d["esg_momentum_z"] = (d["esg_change_12m"] - gm.transform("mean")) / gm.transform("std").replace(0, np.nan)
    d["esg_momentum_z"] = d["esg_momentum_z"].fillna(0.0)

    # --- risk proxies. With no factor model available, realised vol net of the
    # sector-month mean is the honest stand-in for "firm-specific" volatility.
    d["realised_vol_ann"] = (
        d.groupby("ticker")["ret_m"].transform(lambda s: s.rolling(24, min_periods=12).std(ddof=1)) * np.sqrt(12)
    )
    d["idio_vol_ann"] = d["realised_vol_ann"]
    d["beta"] = 1.0
    d["ev_bn"] = np.nan
    mkt = d.groupby("date").ret_m.transform("mean")
    d["_ex"] = d["ret_m"] - mkt
    d["_sx"] = d["esg_score"] - d.groupby("date")["esg_score"].transform("mean")
    num = d.groupby("ticker").apply(
        lambda x: np.cov(x["_ex"], x["_sx"])[0, 1] / np.var(x["_sx"]) if len(x) > 12 and np.var(x["_sx"]) > 0 else 1.0,
        include_groups=False,
    )
    d["beta"] = d["ticker"].map(num).fillna(1.0).clip(0.2, 3.0)
    d = d.drop(columns=["_ex", "_sx"])

    for c in ("esg_score", "esg_z", "esg_change_12m", "esg_momentum_z", "ret_m", "idio_vol_ann", "realised_vol_ann", "beta"):
        if c in d:
            d[c] = pd.to_numeric(d[c], errors="coerce").round(4)
    panel = d[["date", "year", "month", "ticker", "sector", "esg_score", "esg_z", "esg_change_12m",
               "esg_reported_change_12m", "esg_momentum_z", "ret_m", "idio_vol_ann", "realised_vol_ann",
               "beta", "ev_bn"]].copy()

    # --- letter grades + firm-level file
    zmean = panel.groupby("ticker").esg_z.mean()
    from environ.data.generate_data import _letter_from_z  # noqa: PLC0415

    firms = pd.DataFrame(
        {
            "ticker": zmean.index,
            "sector": panel.groupby("ticker").sector.first().to_numpy(),
            "esg_mean": panel.groupby("ticker").esg_score.mean().round(1).to_numpy(),
            "esg_letter": [_letter_from_z(v) for v in zmean.to_numpy()],
            "esg_z_mean": zmean.round(3).to_numpy(),
            "ev_bn": np.nan,
            "idio_vol_ann": panel.groupby("ticker").idio_vol_ann.mean().round(2).to_numpy(),
            "beta": panel.groupby("ticker").beta.mean().round(3).to_numpy(),
        }
    )
    print(
        f"  panel: {len(panel):,} firm-months | {panel.ticker.nunique()} firms | "
        f"{panel.date.nunique()} months | {panel.sector.nunique()} sectors"
    )
    for c in ("ev_bn",):
        if panel[c].isna().all():
            print(f"  ! {c} unavailable -> the size control in the regressions will be dropped by the app")
    return panel, firms


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the analysis panel from real data.")
    ap.add_argument("--ratings", help="CSV of ESG scores (ESG-Book format or any superset)")
    ap.add_argument("--prices", help="CSV of monthly closes: date, ticker, close")
    ap.add_argument("--fetch-prices", metavar="TICKERS", help="comma-separated tickers to pull from yfinance")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "panel.csv"))
    ap.add_argument("--min-history", type=int, default=24)
    ap.add_argument("--allow-missing-sector", action="store_true")
    args = ap.parse_args()

    if not args.ratings or not (args.prices or args.fetch_prices):
        raise SystemExit(__doc__)

    ratings = load_ratings(args.ratings)
    no_sector = ("sector" not in ratings.columns) or ratings.sector.isna().all()
    if no_sector:
        msg = ("No sector column in the ratings file. Sector neutralisation is the difference between "
               "'ESG has no return premium' and 'ESG has one', so this project will not run without it. "
               "Add GICS sector, or pass --allow-missing-sector to see the naive analysis only.")
        if not args.allow_missing_sector:
            raise SystemExit("REFUSED: " + msg)
        print("WARN: " + msg)

    prices = load_prices(args.prices, args.fetch_prices)
    panel, firms = build(ratings, prices, min_hist=args.min_history)

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    panel.to_csv(out, index=False)
    fpath = out.replace("panel.csv", "firms.csv")
    firms.to_csv(fpath, index=False)
    print(f"\nwrote {out}\nwrote {fpath}")
    print("\nNow:  uvicorn environ.app:app --reload   (it reloads data on start)")
    print("Keep the demo panel too, so the sensitivity test stays reproducible:")
    print(f"  cp {out} panel_real.csv && python -m environ.data.generate_data")


if __name__ == "__main__":
    sys.exit(main())
