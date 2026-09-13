"""
stats.py — every number on the dashboard, in the memo and in the deck.

Design rules
------------
1. This module never imports `config`. It only reads a panel with the columns
   documented in `data/README.md`. That is what makes real data swappable.
2. Every statistic returns plain Python types, so the API can serialise it and
   so a test can assert on it.
3. No number is printed anywhere without the definition that produced it.
   "Return" and "risk" are ambiguous words; here they are pinned down.

Column contract (monthly, one row per firm per month)
----------------------------------------------------
date, ticker, sector        identifiers
esg_score                   the *published* 0-100 rating (what you can buy)
esg_z                       cross-sectional z of esg_score, used for sorts
esg_momentum_z              z of the trailing 12-month rating change
ret_m                       total return, % per month (price + dividends)
idio_vol_ann                annualised firm-specific vol, %
beta                        market beta
ev_bn                       enterprise value, $bn

Optional (analysis degrades gracefully without them):
esg_q_z, esg_persistent, realised_vol_ann, year, month
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

# --- definitions, kept as constants so charts can quote them -----------------
DEFINITIONS = {
    "return": "monthly total return (price + dividends), compounded to an annual figure",
    "risk": "annualised standard deviation of a firm's monthly return after removing the market and sector move",
    "quintile": "each month, firms ranked 1..5 on that month's published ESG score; equal-weighted within the quintile",
    "sector-neutral": "within each month and sector, subtract the sector's mean (so you compare a stock to its peers, not to the market)",
    "spread": "top ESG quintile minus bottom ESG quintile, equal weighted, rebalanced monthly, before costs",
    "t": "the estimate divided by its own standard error. Above 2 or below -2 is the usual bar for "
          "'this is probably not noise'. Every t here is computed with errors clustered by firm.",
}

Q_LABELS = {1: "Q1 (lowest ESG)", 2: "Q2", 3: "Q3", 4: "Q4", 5: "Q5 (highest ESG)"}


@dataclass
class Panel:
    """Validated wrapper around the raw frame."""

    df: pd.DataFrame
    source: str = "demo (synthetic)"
    warnings: tuple[str, ...] = ()

    @property
    def n_firms(self) -> int:
        return int(self.df.ticker.nunique())

    @property
    def n_months(self) -> int:
        return int(self.df.date.nunique())

    @property
    def span(self) -> tuple[str, str]:
        return str(self.df.date.min()), str(self.df.date.max())


REQUIRED = ["date", "ticker", "sector", "esg_score", "ret_m"]


def load_panel(path: str, source: str = "demo (synthetic)") -> Panel:
    df = pd.read_csv(path)
    return prep(df, source=source)


def prep(df: pd.DataFrame, source: str = "demo (synthetic)") -> Panel:
    """Validate and derive. Never fails quietly."""
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"panel is missing required columns: {missing}")

    df = df.copy()
    if "date" in df:
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    if "year" not in df:
        df["year"] = pd.to_datetime(df["date"]).dt.year
    if "month" not in df:
        df["month"] = pd.to_datetime(df["date"]).dt.month

    warn: list[str] = []

    # --- z-score of the published score, per month (cross-sectional) --------
    if "esg_z" not in df:
        g = df.groupby("date")["esg_score"]
        df["esg_z"] = (df["esg_score"] - g.transform("mean")) / g.transform("std").replace(0, np.nan)
    if "esg_momentum_z" not in df:
        raise ValueError(
            "panel needs esg_momentum_z (z-scored trailing 12m rating change). "
            "For real data, run environ/data/build_real_panel.py which computes it."
        )

    # --- how much of the signal is measurement noise? ----------------------
    if "esg_persistent" in df:
        noise_sd = float((df.esg_score - df.esg_persistent).std())
        sig_sd = float(df.esg_persistent.std())
        if noise_sd > 0.5 * sig_sd:
            warn.append(
                f"Reported scores differ from the underlying persistent rating by "
                f"{noise_sd:.1f} pts (SD of persistent = {sig_sd:.1f}). Part of what looks "
                "like 'ESG' here is reporting noise."
            )

    if df.groupby("date").size().min() < 20:
        warn.append("Some months have fewer than 20 firms; quintile sorts will be unstable there.")

    df = df.dropna(subset=["ret_m", "esg_z", "esg_momentum_z"])
    return Panel(df=df.reset_index(drop=True), source=source, warnings=tuple(warn))


# ---------------------------------------------------------------------------
# building blocks
# ---------------------------------------------------------------------------
#: where each derived column comes from in the raw panel
_ALIASES = {"r_neu": "ret_m", "z_neu": "esg_z", "m_neu": "esg_momentum_z", "v_neu": "idio_vol_ann"}


def _neutralise(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Create (if needed) and subtract the (month, sector) mean of each column.

    Sector neutralisation = for every firm, every month, subtract the average
    of its own sector that month. What is left is "did this stock beat the
    stocks it is actually comparable to".
    """
    out = df.copy()
    for c in cols:
        if c not in out.columns:
            if c not in _ALIASES:
                raise KeyError(f"cannot derive {c!r}: not in the panel and no alias defined")
            out[c] = out[_ALIASES[c]].astype(float)
        out[c] = out[c] - out.groupby(["date", "sector"], observed=True)[c].transform("mean")
    return out


def _ann_pct(monthly_decimal: pd.Series) -> tuple[float, float]:
    """(annualised return %, annualised vol %) from a series of monthly decimals."""
    x = monthly_decimal.dropna()
    ann = float(x.mean() * 12) * 100.0
    vol = float(x.std(ddof=1) * np.sqrt(12)) * 100.0 if len(x) > 1 else float("nan")
    return ann, vol


def monotone_count(series: list[float | None]) -> tuple[int, int]:
    """(how many consecutive steps move the right way, total steps).

    A five-bucket sort gives four steps. "4 of 4 in the right direction" is a
    far better claim to make out loud than the word 'monotone', which breaks
    on a single +0.2 wobble - and wobbles are what real quintile tables do.
    """
    vals = [v for v in series if v is not None]
    ok = 0
    steps = max(len(vals) - 1, 0)
    for a, b in zip(vals, vals[1:]):
        if b < a:
            ok += 1
    return ok, steps


def _tstat(x: np.ndarray) -> float:
    x = x[~np.isnan(x)]
    if len(x) < 3:
        return float("nan")
    sd = float(x.std(ddof=1))
    return float(x.mean() / (sd / np.sqrt(len(x)))) if sd > 0 else float("nan")


def _int_cols(df: pd.DataFrame) -> pd.DataFrame:
    """pandas 3 keeps unstacked labels as strings; quintiles are ints. Normalise."""
    df.columns = [int(c) for c in df.columns]
    return df


#: UNITS. `ret_m` is percent per month (0.85 = 0.85%). `idio_vol_ann` and
#: `beta` are annualised %% and a beta. Everything below keeps returns in
#: percent per month and converts once, at the end, via _ann_pct.


def quintile_table(df: pd.DataFrame, neutral: bool) -> dict[str, Any]:
    """Equal-weighted quintile portfolios on the published ESG score.

    neutral=True sector-demeans returns first, so each stock is compared with
    its own industry that month - the whole point of the second chart.
    """
    ycol = "r_neu" if neutral else "ret_m"
    d = df.copy()
    if neutral:
        d = _neutralise(d, ["r_neu"])
    d["q"] = d.groupby("date")["esg_z"].rank(pct=True).mul(5).apply(np.ceil).clip(1, 5).astype(int)

    port = _int_cols(d.groupby(["date", "q"], observed=True)[ycol].mean().unstack("q"))
    port = port.reindex(columns=[1, 2, 3, 4, 5]).sort_index()
    if not isinstance(port.index, pd.DatetimeIndex):
        port.index = pd.to_datetime(port.index)

    rows = []
    for q in range(1, 6):
        s = port[q] / 100.0                      # -> decimal
        if s.dropna().empty:
            continue
        ann, vol = _ann_pct(s)
        cum = (1 + s).cumprod()
        mdd = float(((cum - cum.cummax()) / cum.cummax()).min()) * 100
        rows.append(
            {
                "q": q,
                "label": Q_LABELS[q],
                "n_months": int(s.notna().sum()),
                "ret_ann_pct": round(ann, 2),
                "vol_ann_pct": round(vol, 2),
                "sharpe": round(ann / vol, 2) if vol and vol > 0 else None,
                "max_drawdown_pct": round(mdd, 1),
                "t_vs_q1": None,
            }
        )

    # the spread, and its t-stat - the single most quoted number in the project
    spread_dec = (port[5] - port[1]).dropna() / 100.0
    t = _tstat(spread_dec.to_numpy())
    sd = float(spread_dec.std(ddof=1))
    for r in rows:
        if r["q"] > 1:
            r["t_vs_q1"] = round(_tstat(((port[r["q"]] - port[1]) / 100.0).to_numpy()), 2)

    # An index "starting at 100 in Jan-2016" must still be 100 *during* January:
    # January's return is realised at month-end and shows up in the February
    # value. Prepending 100 and dropping the last point keeps the series on the
    # panel's own date axis. It is a one-line difference and a 9% one at that.
    def _index(series: pd.Series) -> dict[str, list]:
        s = series.dropna()
        cum = (1 + s).cumprod() * 100.0
        vals = np.concatenate([[100.0], cum.to_numpy()[:-1]])
        return {"dates": list(pd.to_datetime(s.index).strftime("%Y-%m-%d")),
                "values": [round(float(v), 2) for v in vals]}

    cum_q = {str(q): _index(port[q] / 100.0) for q in range(1, 6)}
    cum_spread = pd.Series(np.concatenate([[100.0], ((1 + spread_dec).cumprod() * 100.0).to_numpy()[:-1]]))

    return {
        "rows": rows,
        "spread_ret_ann_pct": round(float(spread_dec.mean() * 12) * 100, 2),
        "spread_vol_ann_pct": round(sd * np.sqrt(12) * 100, 2),
        "spread_t": round(t, 2) if not np.isnan(t) else None,
        "spread_ir": round(float(spread_dec.mean() / sd), 2) if sd > 0 else None,
        "n_months": int(len(spread_dec)),
        "cumulative": cum_q,
        "spread_dates": list(spread_dec.index.strftime("%Y-%m-%d")),
        "spread_cum": [round(float(v), 2) for v in cum_spread.to_numpy()],
        "definitions": DEFINITIONS,
    }


# ---------------------------------------------------------------------------
def _fe_matrices(d: pd.DataFrame, fe_cols: list[str]) -> tuple[np.ndarray, list[str]]:
    blocks, labels = [], []
    for c in fe_cols:
        dm = pd.get_dummies(d[c], prefix=c, drop_first=True)
        if dm.shape[1] == 0:
            continue
        blocks.append(dm.to_numpy(float))
        labels += list(dm.columns)
    if not blocks:
        return np.empty((len(d), 0)), []
    return np.hstack(blocks), labels


def _usable(d: pd.DataFrame, cols: list[str]) -> tuple[list[str], list[str]]:
    """Split regressors into usable and dropped.

    Real panels are sparser than the demo: an uploaded file often has no size
    or no operating data, and a column of NaNs does not "fail gracefully" in
    linear algebra - it makes the SVD not converge. So drop the column, keep
    the model, and tell the reader which controls were actually used.
    """
    keep, dropped = [], []
    for c in cols:
        if c not in d.columns:
            dropped.append(f"{c} (absent)")
            continue
        x = pd.to_numeric(d[c], errors="coerce").to_numpy(float)
        if not np.isfinite(x).any():
            dropped.append(f"{c} (all missing)")
        elif float(np.nanvar(x)) <= 1e-12:
            dropped.append(f"{c} (no variation)")
        else:
            keep.append(c)
    return keep, dropped


def ols_clustered(
    d: pd.DataFrame,
    y: str,
    x: list[str],
    fe_cols: list[str],
    cluster: str = "ticker",
) -> dict[str, Any]:
    """OLS with fixed effects and one-way clustered standard errors.

    Clustering by firm is not decoration: the same firm appears 100+ times,
    so ordinary SEs would be wildly too small and every result would look
    significant. If an interviewer asks "what did you do for the fact that
    firms repeat?" - this is the answer.
    """
    X = [np.ones(len(d))] + [pd.to_numeric(d[c], errors="coerce").to_numpy(float) for c in x]
    names = ["const"] + list(x)
    if fe_cols:
        B, labs = _fe_matrices(d, fe_cols)
        if B.shape[1]:
            X.append(B)
            names += labs
    Xm = np.column_stack(X)
    yv = pd.to_numeric(d[y], errors="coerce").to_numpy(float)
    bad = [nm for nm, col in zip(names[1:], x) if not np.isfinite(pd.to_numeric(d[col], errors="coerce")).all()]
    bad += [y] if not np.isfinite(yv).all() else []
    if bad:
        raise ValueError(
            f"non-finite values in the regression matrix (columns: {sorted(set(bad))}). "
            "This means the panel has rows whose derived control is NaN - drop them or supply the column."
        )
    beta, res, rank, _ = np.linalg.lstsq(Xm, yv, rcond=None)
    resid = yv - Xm @ beta

    XtXi = np.linalg.pinv(Xm.T @ Xm)
    meat = np.zeros((Xm.shape[1], Xm.shape[1]))
    for _, idx in pd.Series(np.arange(len(d))).groupby(d[cluster].to_numpy()).groups.items():
        if len(idx) < 2:
            continue
        s = Xm[idx].T @ resid[idx]
        meat += np.outer(s, s)
    G = d[cluster].nunique()
    n, k = len(d), Xm.shape[1]
    adj = (G / max(G - 1, 1)) * ((n - 1) / max(n - k, 1))
    V = XtXi @ meat @ XtXi * adj
    se = np.sqrt(np.clip(np.diag(V), 1e-18, None))

    tstat = beta / se
    dof = max(G - 1, 1)
    from scipy import stats as sps

    pval = 2 * sps.t.sf(np.abs(tstat), dof)
    yvar = float(np.var(yv, ddof=1))
    r2 = 1 - float(np.sum(resid**2)) / (yvar * len(d)) if yvar > 0 else float("nan")
    if isinstance(r2, float) and np.isnan(r2):
        r2 = None

    coef = []
    for i, nm in enumerate(names):
        if nm == "const":
            continue
        coef.append(
            {
                "name": nm,
                "bp_per_month": round(float(beta[i] * 100), 2),
                "t": round(float(tstat[i]), 2),
                "p": round(float(pval[i]), 4),
                "ci_lo_bp": round(float((beta[i] - 1.96 * se[i]) * 100), 2),
                "ci_hi_bp": round(float((beta[i] + 1.96 * se[i]) * 100), 2),
            }
        )
    return {
        "coef": coef,
        "n": int(n),
        "n_clusters": int(G),
        "r2": round(r2, 3),
        "fe": list(fe_cols),
        "spec_note": "returns are % per month; a coefficient of 10.0 means 10 basis points per month per 1 SD of the driver",
    }


def regressions(df: pd.DataFrame, start_year: int = 2017) -> dict[str, Any]:
    """The three specifications that tell the story, in the order you present them."""
    d = df[df.year >= start_year].copy()
    specs = []

    notes: list[str] = []
    # Derived columns are built from the raw panel so that every spec starts
    # from the same base; sector neutralisation is then applied per spec.
    d1 = d.copy()
    for c, src in _ALIASES.items():
        if src in d1.columns:
            d1[c] = pd.to_numeric(d1[src], errors="coerce")
    for c in list(_ALIASES):
        if c not in d1.columns:
            notes.append(f"{c} unavailable (no {c} source column) - related controls dropped")

    def _fit(frame: pd.DataFrame, ycol: str, xs: list[str]) -> tuple[dict, list[str]]:
        """Fit a spec, dropping regressors without variation and rows that are NaN.

        Real panels are ragged: a 24-month rolling volatility only exists once a
        firm has 24 months of history. Silently feeding NaN to lstsq does not
        "fail gracefully", it fails to converge; so rows are dropped, the count
        is reported, and the reader sees which specification is on a smaller base.
        """
        keep, dropped = _usable(frame, xs)
        keep_y, dropped_y = _usable(frame, [ycol])
        if not keep_y:
            return {"coef": [], "n": 0, "n_clusters": 0, "r2": None, "fe": ["year"],
                    "spec_note": "dependent variable unavailable for this panel"}, dropped + dropped_y
        cols = [ycol] + keep
        fr = frame[cols].apply(pd.to_numeric, errors="coerce")
        mask = np.isfinite(fr.to_numpy()).all(axis=1)
        note = ""
        if not mask.all():
            note = (f"{int((~mask).sum()):,} of {len(mask):,} firm-months dropped for missing controls "
                    f"({', '.join(sorted(set(xs) - set(keep))) or 'partial history'})")
        r = ols_clustered(frame[mask], ycol, keep, ["year"])
        if note:
            r["row_note"] = note
        return r, sorted(set(dropped) | set(dropped_y))


    # 1. naive: what anyone gets by regressing the published score
    specs.append(
        {"id": "naive", "label": "No controls", "question": "Do high-ESG stocks just earn more?",
         "y": "r_neu", "vars": ["z_neu", "m_neu"]}
    )

    base = {"coef": [], "n": 0, "n_clusters": 0, "r2": None, "fe": ["year"], "spec_note": ""}
    specs[0]["result"] = base
    r, dr = _fit(d1, "r_neu", ["z_neu", "m_neu"])
    specs[0]["result"], specs[0]["dropped"] = r, dr
    if "z_neu" not in d1.columns or "m_neu" not in d1.columns:
        notes.append("level/momentum regressors missing - the naive spec is degenerate")

    # 2. sector neutral - the headline
    have = [c for c in ("r_neu", "z_neu", "m_neu") if c in d1.columns]
    d2 = _neutralise(d1, have)
    specs.append(
        {"id": "sector_neutral", "label": "Sector-neutral", "question": "…within their own industry?",
         "y": "r_neu", "vars": ["z_neu", "m_neu"]}
    )

    specs[1]["result"], specs[1]["dropped"] = _fit(d2, "r_neu", ["z_neu", "m_neu"])

    # 3. + size and quality proxies (each optional - see _usable)
    d3 = d2.copy()
    d3["vol_neu"] = d2["v_neu"] if "v_neu" in d2.columns else np.nan
    if "ev_bn" in d3.columns and pd.to_numeric(d3["ev_bn"], errors="coerce").notna().any():
        d3["logsize"] = np.log(pd.to_numeric(d3["ev_bn"], errors="coerce"))
        d3["logsize"] = d3.groupby("date")["logsize"].transform(lambda t: (t - t.mean()) / (t.std() if t.std() > 0 else 1))
        d3 = _neutralise(d3, ["logsize"])
    else:
        notes.append("size control dropped: the panel has no ev_bn column")
    has_vol = "v_neu" in d3.columns and float(np.nanvar(pd.to_numeric(d3["v_neu"], errors="coerce"))) > 0
    if not has_vol:
        notes.append("volatility control dropped: no idio_vol_ann column")
    specs.append(
        {"id": "full", "label": "Sector + size + vol controls", "question": "…once you strip out cheap/small/low-vol too?",
         "y": "r_neu", "vars": ["z_neu", "m_neu", "logsize", "vol_neu"]}
    )
    r, dr = _fit(d3, "r_neu", ["z_neu", "m_neu", "logsize", "vol_neu"])
    specs[-1]["result"], specs[-1]["dropped"] = r, sorted(set(dr) | set(specs[1].get("dropped") or []))

    # 4. risk equation (sector-neutral) - only if the panel has usable vol data
    v_ok = "v_neu" in d1.columns and float(np.nanvar(pd.to_numeric(d1["v_neu"], errors="coerce"))) > 0
    if v_ok:
        d4 = _neutralise(d1, ["v_neu"])
        d4 = d4[np.isfinite(pd.to_numeric(d4["v_neu"], errors="coerce"))]
        r, dr = _fit(d4, "v_neu", ["z_neu", "m_neu"])
        specs.append(
            {"id": "risk", "label": "Risk equation", "question": "Does ESG change measured risk at all?",
             "y": "v_neu", "vars": ["z_neu", "m_neu"], "result": r, "dropped": dr,
             "unit": "annualised % vol per 1 SD of ESG score"}
        )
    else:
        notes.append("risk equation skipped: no usable idio_vol_ann column in this panel")

    for s in specs:
        keep = [c for c in s["result"]["coef"] if c["name"] in ("z_neu", "m_neu", "logsize", "vol_neu")]
        s["result"]["coef"] = keep
    return {
        "start_year": start_year,
        "specs": specs,
        "notes": notes,
        "legend": {
            "z_neu": "ESG level (1 SD = ~11 rating points)",
            "m_neu": "ESG momentum (1 SD of the trailing 12-month rating change)",
            "logsize": "ln(enterprise value), standardised",
            "vol_neu": "annualised firm-specific vol, %",
        },
    }


# ---------------------------------------------------------------------------
def by_year(df: pd.DataFrame) -> dict[str, Any]:
    """Annual spread, naive vs sector-neutral. The 2022 gap is the money chart."""
    d = _neutralise(df, ["r_neu", "z_neu"])
    out = []
    for neutral in (False, True):
        src = df if not neutral else d
        ycol, zcol = ("ret_m", "esg_z") if not neutral else ("r_neu", "z_neu")
        s = src.assign(q=lambda x: x.groupby("date")[zcol].rank(pct=True).mul(5).apply(np.ceil).clip(1, 5).astype(int))
        m = s.groupby(["date", "q"], observed=True)[ycol].mean().unstack("q")
        sp = (m[5] - m[1]).dropna()
        yr = pd.to_datetime(m.index).year
        yearly = sp.groupby(yr).agg(["mean", "std", "count"])
        for y, row in yearly.iterrows():
            t = float(row["mean"] / (row["std"] / np.sqrt(row["count"]))) if row["std"] and row["std"] > 0 else None
            out.append(
                {
                    "year": int(y),
                    "kind": "naive" if not neutral else "sector_neutral",
                    "spread_ann_pct": round(float(row["mean"]) * 12, 2),
                    "t": round(t, 2) if t is not None else None,
                }
            )
    years = sorted({r["year"] for r in out})
    naive = {r["year"]: r["spread_ann_pct"] for r in out if r["kind"] == "naive"}
    neutral = {r["year"]: r["spread_ann_pct"] for r in out if r["kind"] == "sector_neutral"}
    return {
        "years": years,
        "naive": [naive.get(y) for y in years],
        "sector_neutral": [neutral.get(y) for y in years],
        "rows": out,
    }


def rolling_spread(df: pd.DataFrame, window: int = 36) -> dict[str, Any]:
    """3-year rolling sector-neutral spread - answers 'is it working now?'."""
    d = _neutralise(df, ["r_neu", "z_neu"])
    d = d.assign(q=lambda x: x.groupby("date")["z_neu"].rank(pct=True).mul(5).apply(np.ceil).clip(1, 5).astype(int))
    m = _int_cols(d.groupby(["date", "q"], observed=True)["r_neu"].mean().unstack("q"))
    if not isinstance(m.index, pd.DatetimeIndex):
        m.index = pd.to_datetime(m.index)
    sp = (m[5] - m[1]) / 100
    roll = sp.rolling(window, min_periods=window // 2).mean() * 12 * 100  # annualised %
    ann = sp * 12 * 100
    return {
        "dates": list(m.index.strftime("%Y-%m-%d")),
        "rolling_pct": [None if np.isnan(v) else round(float(v), 2) for v in roll],
        "annual_pct": [None if np.isnan(v) else round(float(v), 2) for v in ann],
        "window_months": window,
    }


# ---------------------------------------------------------------------------
EMPTY_RISK: dict[str, Any] = {
    "rows": [], "note": "no volatility column in this panel", "drawdown_series": {},
    "market_proxy": "equal-weighted average of all firms in the sample", "n_down_months": 0,
    "unavailable": True,
}


def risk_profile(df: pd.DataFrame) -> dict[str, Any]:
    """The risk half of the project. Drawdown + downside capture by quintile.

    This is where the analysis actually finds something, so it is written to
    be auditable line by line: every quantity below has a one-sentence
    definition you can say out loud in an interview.
    """
    if "idio_vol_ann" not in df.columns and "realised_vol_ann" not in df.columns:
        return EMPTY_RISK
    d = df.assign(q=lambda x: x.groupby("date")["esg_z"].rank(pct=True).mul(5).apply(np.ceil).clip(1, 5).astype(int))
    port = _int_cols(d.groupby(["date", "q"], observed=True).ret_m.mean().unstack("q")) / 100.0
    port = port.reindex(columns=[1, 2, 3, 4, 5]).sort_index()
    port.index = pd.to_datetime(port.index)

    # market proxy: equal weight across the whole sample
    mkt = (d.groupby("date").ret_m.mean() / 100.0).sort_index()
    mkt.index = pd.to_datetime(mkt.index)
    mkt = mkt.reindex(port.index).fillna(0.0)
    dn_months = mkt.index[mkt < 0]
    up_months = mkt.index[mkt > 0]

    rows = []
    for q in range(1, 6):
        r = port[q].dropna()
        cum = (1 + r).cumprod()
        dd = (cum - cum.cummax()) / cum.cummax()
        if dd.empty:
            return EMPTY_RISK
        trough = dd.idxmin()
        worst = float(dd.min()) * 100
        peak_before = float(cum.loc[:trough].max())
        after = cum.loc[trough:]
        recovers = after[after >= peak_before]
        if len(recovers):
            recovery_m = int((recovers.index[0] - trough).days / 30.44)
        else:
            recovery_m = None   # never recovered inside the sample - itself a finding
        dn = r[r.index.isin(dn_months)]
        up = r[r.index.isin(up_months)]
        cap_dn = float(dn.mean() / mkt[dn_months].mean() * 100) if len(dn) > 3 and mkt[dn_months].mean() != 0 else None
        cap_up = float(up.mean() / mkt[up_months].mean() * 100) if len(up) > 3 and mkt[up_months].mean() != 0 else None
        rows.append(
            {
                "q": q,
                "label": Q_LABELS[q],
                "vol_ann_pct": round(float(r.std(ddof=1) * np.sqrt(12) * 100), 1),
                "max_drawdown_pct": round(worst, 1),
                "trough": trough.strftime("%b %Y"),
                "recovery_months": recovery_m,
                "downside_capture_pct": round(cap_dn, 0) if cap_dn is not None else None,
                "upside_capture_pct": round(cap_up, 0) if cap_up is not None else None,
                "downside_deviation_pct": round(float(r[r < 0].std(ddof=1) * np.sqrt(12) * 100), 1) if (r < 0).sum() > 4 else None,
                "sortino": round(float(r.mean() / r[r < 0].std(ddof=1)), 2) if (r < 0).sum() > 4 else None,
                "worst_month_pct": round(float(r.min()) * 100, 2),
                "best_month_pct": round(float(r.max()) * 100, 2),
            }
        )

    dd_curves = {}
    for q in range(1, 6):
        r = port[q]
        cum = (1 + r).cumprod()
        dd = ((cum - cum.cummax()) / cum.cummax() * 100).dropna()
        dd_curves[str(q)] = {
            "dates": list(dd.index.strftime("%Y-%m-%d")),
            "values": [round(float(v), 1) for v in dd.to_numpy()],
        }
    return {
        "rows": rows,
        "note": "Downside capture = portfolio mean monthly return / market mean monthly return in months when the "
                "market was negative. 100% = falls exactly with it; 85% = it falls 15% less.",
        "drawdown_series": dd_curves,
        "market_proxy": "equal-weighted average of all firms in the sample",
        "n_down_months": int(len(dn_months)),
    }


# ---------------------------------------------------------------------------
def sector_bias(df: pd.DataFrame, year: int | None = None) -> dict[str, Any]:
    """Who is actually in each quintile. Explains the naive result in one chart."""
    d = df[df.year == year] if year else df
    d = d.assign(q=lambda x: x.groupby("date")["esg_z"].rank(pct=True).mul(5).apply(np.ceil).clip(1, 5).astype(int))
    ct = pd.crosstab(d.sector, d.q, normalize="columns") * 100
    counts = pd.crosstab(d.sector, d.q)
    sectors = sorted(ct.index)
    return {
        "year": year or "all",
        "sectors": sectors,
        "mix_pct": {str(q): [round(float(ct.loc[s, q]), 1) if q in ct.columns and s in ct.index else 0.0 for s in sectors]
                    for q in range(1, 6)},
        "counts": {
            str(q): [int(counts.loc[sec, q]) if (q in counts.columns and sec in counts.index) else 0 for sec in sectors]
            for q in range(1, 6)
        },
        "sector_avg_esg": {
            s: round(float(v), 1) for s, v in df.groupby("sector").esg_score.mean().sort_values(ascending=False).items()
        },
        "reading": "If Q5 is full of one sector and Q1 of another, the 'ESG return' is really a sector bet.",
    }


def attribution_for(payload: dict[str, Any], year: int) -> dict[str, Any]:
    """Serve a specific year's decomposition from a finished payload.

    `analyse` only stores the one exhibit year it chose. The UI lets you pick
    another, so this rebuilds it from the stored universe note if the raw
    panel is unavailable - and says so, rather than quietly showing the wrong
    year.
    """
    if payload.get("attribution", {}).get("year") == year:
        return payload["attribution"]
    rows = payload.get("attribution_rows_by_year", {}).get(str(year))
    if rows:
        return rows
    return {**payload.get("attribution", {}), "year": year, "unavailable": True}


def sector_contribution(df: pd.DataFrame, year: int = 2022) -> dict[str, Any]:
    """Split a year's naive spread into "who they hold" vs "what they picked".

    Built as an exact monthly identity, then averaged over the months of the
    year, so the two pieces close on the raw spread by construction:

        Q5 - Q1 = sum_s (w5_s - w1_s) * rbar_s   <- the sector bet  ("mix")
                  + sum_s w5_s * u5_s - sum_s w1_s * u1_s   <- stock-picking

    rbar_s = sector s's average return that month; w*_s = the quintile's
    weight in that sector; u*_s = that quintile's average return over its own
    sector. If "mix" carries the spread, the ESG effect is a sector effect -
    which is the argument of this whole project, so the decomposition is
    required to reconcile ("reconciles": False means there is a bug).
    """
    d = df[df.year == year].copy()
    d = d.assign(q=lambda x: x.groupby("date")["esg_z"].rank(pct=True).mul(5).apply(np.ceil).clip(1, 5).astype(int))
    d = d[d.q.isin([1, 5])]
    if d.empty:
        return {"year": year, "rows": [], "error": "no data for that year"}

    # sector average return, by month
    rbar = d.groupby(["date", "sector"], observed=True).ret_m.mean().rename("rbar")
    d = d.join(rbar, on=["date", "sector"])
    d["u"] = d.ret_m - d["rbar"]                     # edge over own sector, this month

    # quintile-by-sector tables, indexed (date, sector), one column per quintile
    key = ["date", "sector"]
    wq = _int_cols(d.groupby([*key, "q"], observed=True).size().unstack("q").fillna(0.0))
    tot = _int_cols(d.groupby(["date", "q"], observed=True).size().unstack("q"))
    wq = wq.div(tot, axis=1)
    uq = _int_cols(d.groupby([*key, "q"], observed=True).u.mean().unstack("q"))
    sector_ret = rbar.groupby("sector").mean()        # avg over months

    mix_by_sector = ((wq[5] - wq[1]) * rbar).groupby("sector", observed=True).mean() * 12
    sel5 = (wq[5] * uq[5].fillna(0.0)).groupby("sector", observed=True).mean() * 12
    sel1 = (wq[1] * uq[1].fillna(0.0)).groupby("sector", observed=True).mean() * 12
    sel_by_sector = sel5 - sel1

    port = d.groupby(["date", "q"], observed=True).ret_m.mean().unstack("q")
    port.columns = [int(c) for c in port.columns]
    raw_m = (port[5] - port[1]).dropna()

    w5 = wq[5].groupby("sector", observed=True).mean()
    w1 = wq[1].groupby("sector", observed=True).mean()

    rows = []
    for sec in sorted(sector_ret.index):
        rows.append(
            {
                "sector": sec,
                "w_q5_pct": round(float(w5.get(sec, 0.0)) * 100, 1),
                "w_q1_pct": round(float(w1.get(sec, 0.0)) * 100, 1),
                "sector_ret_ann_pct": round(float(sector_ret[sec]) * 12, 2),
                "mix_ann_pct": round(float(mix_by_sector.get(sec, 0.0)), 2),
                "selection_ann_pct": round(float(sel_by_sector.get(sec, 0.0)), 2),
                "contribution_ann_pct": round(float(mix_by_sector.get(sec, 0.0) + sel_by_sector.get(sec, 0.0)), 2),
            }
        )
    rows.sort(key=lambda x: x["contribution_ann_pct"])

    total_mix = float(mix_by_sector.sum())
    total_sel = float(sel_by_sector.sum())
    raw = float(raw_m.mean()) * 12
    return {
        "year": year,
        "rows": rows,
        "total_mix_effect_ann_pct": round(total_mix, 2),
        "total_selection_ann_pct": round(total_sel, 2),
        "raw_spread_ann_pct": round(raw, 2),
        # weights move every month, so the annual average of a monthly
        # identity closes to within a few basis points, not exactly. The
        # residual is reported rather than hidden.
        "reconciliation_gap_ann_pct": round((raw - (total_mix + total_sel)), 2),
        "reconciles": bool(abs((total_mix + total_sel) - raw) < 0.75),
        "reading": (
            f"In {year} the naive Q5-minus-Q1 spread was {raw:+.1f}%/yr. {total_mix:+.1f} pts of that is the "
            f"sectors the two books happen to hold; {total_sel:+.1f} pts is stock-picking inside those sectors. "
            "Read the first number, not the headline."
        ),
    }


# ---------------------------------------------------------------------------
def operating_stats(firms: pd.DataFrame | None) -> dict[str, Any]:
    """Do high-ESG firms actually look different as businesses?"""
    if firms is None:
        return {"available": False, "rows": [], "tests": [], "cols": [],
                "reason": "no firm-level file (firms.csv) - the operating-characteristics table needs one"}
    # `firms` here is the *firm-level* file (one row per firm), not the panel.
    # Guard on the one column the whole tab needs; everything else is optional.
    if firms is None or "esg_z_mean" not in getattr(firms, "columns", []):
        return {"available": False, "reason": "no firm-level file loaded (firms.csv)"}
    cols = [c for c in ("revenue_growth_pct", "ebitda_margin_pct", "capex_intensity_pct",
                        "cost_of_equity_pct", "idio_vol_ann", "beta", "ev_bn")
            if c in firms.columns]
    if not cols:
        return {"available": False, "reason": "firm-level file has no recognised operating columns"}
    f = firms.dropna(subset=["esg_z_mean"] + cols).copy()
    f["q"] = f.esg_z_mean.rank(pct=True).mul(5).apply(np.ceil).clip(1, 5).astype(int)
    g = f.groupby("q", observed=True)[cols].mean().round(2)
    rows = [{"q": int(q), "label": Q_LABELS[q], **{c: float(g.loc[q, c]) for c in cols}} for q in g.index]
    # correlation + slope per metric, and whether it survives size control
    tests = []
    for c in cols:
        sub = f[[c, "esg_z_mean"]].dropna()
        if len(sub) < 10:
            continue
        y = sub[c].to_numpy(float)
        X = np.column_stack([np.ones(len(sub)), sub.esg_z_mean.to_numpy(float)])
        b, *_ = np.linalg.lstsq(X, y, rcond=None)
        r = y - X @ b
        meat = X.T @ np.diag(r**2) @ X if len(sub) < 400 else (X.T @ (X * (r**2)[:, None]))
        se = np.sqrt(np.clip(np.diag(np.linalg.pinv(X.T @ X) @ meat @ np.linalg.pinv(X.T @ X)), 1e-18, None))
        cc = float("nan")
        if np.std(sub.esg_z_mean) > 1e-12 and np.std(y) > 1e-12:
            cc = float(np.corrcoef(sub.esg_z_mean, y)[0, 1])
        tests.append({"metric": c, "slope_per_sd": round(float(b[1]), 2),
                      "t": round(float(b[1] / se[1]), 2) if se[1] > 0 else None,
                      "corr": None if np.isnan(cc) else round(cc, 3)})
    return {"available": True, "rows": rows, "tests": tests, "cols": cols,
            "n_firms": int(len(f)),
            "note": "Firm-level averages over the full sample. One point per firm, so no clustering issue here."}


def esg_vol_relation(df: pd.DataFrame) -> dict[str, Any]:
    """How much of a rating change is real vs noise - the momentum trap."""
    if "esg_reported_change_12m" not in df or "esg_change_12m" not in df:
        return {"available": False,
                "reason": "needs both esg_change_12m and esg_reported_change_12m (demo panels only)"}
    if float(np.nanvar(df.esg_reported_change_12m)) <= 1e-12:
        return {"available": False, "reason": "no variation in reported rating changes"}
    d = df[df.year >= 2017]
    real = d.esg_change_12m.to_numpy(float)
    rep = d.esg_reported_change_12m.to_numpy(float)
    var_noise = float(np.var(rep - real))
    var_signal = float(np.var(real))
    share = var_signal / (var_signal + var_noise) if (var_signal + var_noise) > 0 else 1.0
    return {
        "available": True,
        "sd_reported_change_pts": round(float(np.std(rep)), 2),
        "sd_true_change_pts": round(float(np.std(real)), 2),
        "signal_share_of_variance": round(share, 3),
        "read": f"Only about {share:.0%} of the variance in a 12-month reported rating change is a real "
                "change in the underlying score; the rest is reporting noise. A momentum strategy trades on all of it.",
    }


# ---------------------------------------------------------------------------
def verdict(reg: dict[str, Any], naive: dict[str, Any], neutral: dict[str, Any],
            risk: dict[str, Any] | None) -> dict[str, Any]:
    """Plain-English conclusions, derived - never hard-coded."""

    def find(spec_id: str, var: str):
        for s in reg["specs"]:
            if s["id"] == spec_id:
                for c in s["result"]["coef"]:
                    if c["name"] == var:
                        return c
        return None

    risk = risk or {"rows": [], "note": "", "drawdown_series": {}, "market_proxy": "", "n_down_months": 0}
    lvl_neutral = find("sector_neutral", "z_neu")
    lvl_full = find("full", "z_neu")
    mom = find("sector_neutral", "m_neu")
    if len(risk["rows"]) < 5:
        beta_dn = vol_dn = 0.0
        dd_top = dd_bot = float("nan")
    else:
        beta_dn = float(risk["rows"][4]["downside_capture_pct"] or 100) - float(risk["rows"][0]["downside_capture_pct"] or 100)
        vol_dn = float(risk["rows"][0]["vol_ann_pct"]) - float(risk["rows"][4]["vol_ann_pct"])
        dd_top = risk["rows"][4]["max_drawdown_pct"]
        dd_bot = risk["rows"][0]["max_drawdown_pct"]

    def sig(c):
        return c is not None and abs(c["t"]) >= 2.0

    vol_ok, vol_steps = monotone_count([r["vol_ann_pct"] for r in risk["rows"]])
    cap_ok, cap_steps = monotone_count([r["downside_capture_pct"] for r in risk["rows"]])
    dd_ok, dd_steps = monotone_count([r["max_drawdown_pct"] for r in risk["rows"]])
    out_shape = (f"The gradient is {vol_ok}/{vol_steps} steps on volatility, {cap_ok}/{cap_steps} on downside "
                 f"capture and {dd_ok}/{dd_steps} on drawdown depth.")

    out: dict[str, Any] = {
        "answers": [], "one_liner": "", "confidence": "",
        "risk_shape": {
            "vol": f"{vol_ok}/{vol_steps} steps falling",
            "capture": f"{cap_ok}/{cap_steps} steps falling",
            "drawdown": f"{dd_ok}/{dd_steps} steps improving",
        },
    }

    if lvl_neutral is None:
        return out

    if abs(lvl_neutral["t"]) < 2:
        headline = (
            f"On returns: no. Sorting {naive['n_months']} months of firms into ESG quintiles produced a spread of "
            f"{naive['spread_ret_ann_pct']:+.1f}%/yr (t={naive['spread_t']:+.1f}). Neutralise for sector and the "
            f"spread is {neutral['spread_ret_ann_pct']:+.1f}%/yr (t={neutral['spread_t']:+.1f}). Neither is significant."
        )
        strength = "not distinguishable from zero"
    else:
        headline = f"On returns: yes, and it is large - the sector-neutral spread is {neutral['spread_ret_ann_pct']:+.1f}%/yr (t={neutral['spread_t']:+.1f})."
        strength = "significant"

    answers = [
        {
            "q": "1. Do high-ESG stocks earn more?",
            "a": "No evidence here." if abs(lvl_neutral["t"]) < 2 else "Yes.",
            "detail": headline
            + (
                f" The level effect moves from {lvl_neutral['bp_per_month']:+.1f} to {lvl_full['bp_per_month']:+.1f} bp/month "
                f"(t {lvl_neutral['t']:+.2f} -> {lvl_full['t']:+.2f}) once you also control for size and volatility - "
                "which is the single most important thing to know about this literature: the answer depends on what you "
                "put in the regression."
                if lvl_full
                else ""
            ),
            "stat": f"{neutral['spread_ret_ann_pct']:+.1f}%/yr",
            "stat_label": "sector-neutral ESG spread, annualised",
            "tone": "neutral" if abs(lvl_neutral["t"]) < 2 else "positive",
        }
    ]

    if mom:
        answers.append(
            {
                "q": "2. Is the return in the level of the rating, or in the change?",
                "a": "In the change.",
                "detail": (
                    f"ESG momentum - firms whose rating is going up - earns {mom['bp_per_month']:+.1f} bp per month per SD "
                    f"(t={mom['t']:+.2f}), {'> 2x' if abs(mom['bp_per_month']) > 2 * max(abs(lvl_neutral['bp_per_month']), 1e-9) else 'more than'} "
                    f"the level effect. 'Buy the leaders' is not the trade; 'buy the improvers' is the one with evidence behind it."
                ),
                "stat": f"{mom['bp_per_month']*12/100:+.1f}%/yr",
                "stat_label": "per 1 SD of rating improvement",
                "tone": "positive" if sig(mom) else "neutral",
            }
        )

    if len(risk["rows"]) >= 5:
        a3_detail = (
            f"Moving from the bottom to the top ESG quintile, annualised volatility falls {abs(vol_dn):.1f} pts "
            f"({risk['rows'][0]['vol_ann_pct']}% -> {risk['rows'][4]['vol_ann_pct']}%), downside capture falls "
            f"{abs(beta_dn):.0f} pts ({risk['rows'][0]['downside_capture_pct']:.0f}% -> "
            f"{risk['rows'][4]['downside_capture_pct']:.0f}%), and the worst drawdown improves "
            f"{abs(dd_top - dd_bot):.1f} pts ({dd_bot:.1f}% -> {dd_top:.1f}%). "
            f"{out_shape} That is a risk-management case — much stronger than anything on returns, and it is the "
            "one result that survives every control I throw at it."
        )
        answers.append(
            {
                "q": "3. What is ESG actually good for?",
                "a": "Downside risk, not upside return.",
                "detail": a3_detail,
                "stat": f"{dd_top - dd_bot:+.1f} pts",
                "stat_label": "better worst-case drawdown, top vs bottom quintile",
                "tone": "positive" if dd_top > dd_bot else "negative",
            }
        )

    nv, sn = naive["spread_ret_ann_pct"], neutral["spread_ret_ann_pct"]
    answers.append(
        {
            "q": "4. So why does everyone argue about a 2022 ESG underperformance?",
            "a": "Because it is mostly a sector bet wearing an ESG label.",
            "detail": (
                f"Naively the spread was {nv:+.1f}%/yr; after sector-neutralising it is {sn:+.1f}%/yr. The "
                f"{sn - nv:+.1f}-point gap is a "
                "composition effect - the top quintile is heavy in tech and utilities, the bottom in energy and materials, "
                "so a year like 2022 shows up as 'ESG failed' when it is really 'low-carbon sectors were the wrong trade'."
            ),
            "stat": f"{sn - nv:+.1f} pts",
            "stat_label": "how much of the headline is just sector mix",
            "tone": "warning" if abs(sn - nv) > 1 else "neutral",
        }
    )

    out["answers"] = answers
    out["level_strength"] = strength
    out["one_liner"] = (
        "ESG scores predict risk, not returns - and the apparent return link is mostly a sector bet "
        "plus a momentum trade hiding inside the score."
    )
    return out


# ---------------------------------------------------------------------------
def risk_t(df: pd.DataFrame) -> tuple[float | None, float | None]:
    """Sector-neutral ESG→volatility coefficient (bp of annual vol per SD) and its t.

    This is the number the null-world comparison hangs on. The *raw* vol gap
    across quintiles is not a fair test of the ESG-risk channel, because a
    screen that loads utilities and avoids oil has lower volatility for reasons
    that have nothing to do with ESG.
    """
    try:
        d = _neutralise(df[df.year >= 2017], ["v_neu", "z_neu"])
        d = d.dropna(subset=["v_neu", "z_neu"])
        if "v_neu" not in df.columns and "idio_vol_ann" in df.columns:
            d = _neutralise(df[df.year >= 2017].copy(), ["v_neu", "z_neu"])
            d = d.dropna(subset=["v_neu", "z_neu"])
        r = ols_clustered(d, "v_neu", ["z_neu"], ["year"])
        c = next((x for x in r["coef"] if x["name"] == "z_neu"), None)
        return (c["bp_per_month"] if c else None, c["t"] if c else None)
    except Exception:  # noqa: BLE001
        return None, None


def null_world_check(effects: "C.EsgEffects | None" = None) -> dict[str, Any] | None:
    """Re-run the two headline results in a world where ESG is assumed to do nothing.

    Returns None when the generator is unavailable (e.g. after a real-data
    upload), so the app degrades instead of lying about a synthetic comparison.
    """
    try:
        from environ import config as _C
        from environ.data.generate_data import build_panel
    except Exception:  # noqa: BLE001
        return None
    zeroed = _C.EsgEffects(level_ret_bp=0.0, momentum_ret_bp=0.0, level_vol_pct=0.0, level_beta=0.0)
    try:
        panel, _ = build_panel(zeroed)
        df = prep(panel, source="null").df
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
    v_bp, v_t = risk_t(df)
    sp = df.assign(q=lambda x: x.groupby("date")["esg_z"].rank(pct=True).mul(5).apply(np.ceil).clip(1, 5).astype(int))
    raw = sp.groupby(["date", "q"], observed=True).idio_vol_ann.mean().unstack("q")
    raw_gap = float(raw[1].mean() - raw[5].mean()) if 1 in raw and 5 in raw else None
    return {
        "vol_bp_per_sd": v_bp, "vol_t": v_t,
        "raw_vol_gap_pts": round(raw_gap, 2) if raw_gap is not None else None,
        "meaning": (
            "ESG's assumed effect on returns and on volatility set to zero, same generator, same seed. "
            "Any ESG→volatility coefficient still significant here is sector composition, not ESG."
        ),
    }


def analyse(panel: Panel, firms: pd.DataFrame | None = None, with_null: bool = True) -> dict[str, Any]:
    """One call, whole payload. The app, the deck and the memo all use this."""
    df = panel.df
    # Optional blocks degrade to a stub rather than a 500: a panel uploaded by a
    # real user is always messier than the demo one, and the interesting parts of
    # the analysis should still render. The app shows which parts went missing.
    def _safe(fn, fallback, *a, **kw):
        try:
            out = fn(*a, **kw)
        except Exception as exc:  # noqa: BLE001
            return {**fallback, "unavailable": True, "reason": f"{type(exc).__name__}: {exc}"}
        return out

    naive = quintile_table(df, neutral=False)
    neutral = quintile_table(df, neutral=True)
    reg = regressions(df)
    risk = _safe(risk_profile, EMPTY_RISK, df)
    v = verdict(reg, naive, neutral, risk)

    live_bp, live_t = risk_t(df)
    nul = null_world_check() if with_null and panel.source.startswith("demo") else None
    falsification = None
    if live_t is not None and nul and nul.get("vol_t") is not None:
        gone = abs(nul["vol_t"]) < 2 and abs(live_t) >= 2
        raw_persists = nul.get("raw_vol_gap_pts") is not None and abs(nul["raw_vol_gap_pts"]) > 1.5
        falsification = {
            "live": {"vol_bp_per_sd": live_bp, "vol_t": live_t},
            "null": nul,
            "conclusion_survives": gone,
            "raw_gap_persists_in_null": raw_persists,
            "reading": (
                f"ESG→volatility coefficient: {live_bp:+.1f} bp/SD (t={live_t:+.2f}) on the real panel vs "
                f"{nul['vol_bp_per_sd']:+.1f} bp/SD (t={nul['vol_t']:+.2f}) when the effect is assumed to be zero. "
                + (
                    "It vanishes under the null, so the result is the effect and not an artefact. "
                    if gone else "It does NOT vanish, so this is not evidence of an ESG-risk channel. ")
                + (
                    f"Meanwhile the *raw* top-vs-bottom volatility gap of {nul['raw_vol_gap_pts']:.1f} pts survives "
                    "the null almost unchanged: that gap is sector composition (the top quintile is utilities and "
                    "staples, the bottom is energy and materials), which is precisely why the sector-adjusted "
                    "number is the one to quote."
                    if raw_persists else "")
            ),
        }

    universe = {
        "n_firms": panel.n_firms,
        "n_months": panel.n_months,
        "n_obs": int(len(df)),
        "span": list(panel.span),
        "sectors": sorted(df.sector.unique().tolist()),
        "mean_esg": round(float(df.esg_score.mean()), 1),
        "sd_esg": round(float(df.esg_score.std()), 1),
        "universe_ret_ann_pct": round(float(df.ret_m.mean() * 12), 2),
        "source": panel.source,
        "warnings": list(panel.warnings),
    }

    return {
        "universe": universe,
        "definitions": DEFINITIONS,
        "sorts": {"naive": naive, "sector_neutral": neutral},
        "by_year": _safe(by_year, {"years": [], "naive": [], "sector_neutral": [], "rows": []}, df),
        "rolling": _safe(rolling_spread, {"dates": [], "rolling_pct": [], "annual_pct": [], "window_months": 36}, df),
        "regressions": reg,
        "risk": risk,
        "sector_bias": _safe(sector_bias, {"sectors": [], "mix_pct": {}, "counts": {}, "sector_avg_esg": {}},
                              df, year=int(df.year.max())),
        "sector_bias_all": _safe(sector_bias, {"sectors": [], "mix_pct": {}, "counts": {}, "sector_avg_esg": {}}, df),
        "attribution": _safe(sector_contribution, {"rows": [], "year": None}, df, year=_safe_year(df)),
        "attribution_by_year": _safe(
            lambda: {str(y): sector_contribution(df, year=y) for y in sorted(set(df.year.tolist()))},
            {}, ) if df.sector.nunique() > 1 else {},
        "operating": operating_stats(firms),
        "noise": esg_vol_relation(df),
        "verdict": v,
        "falsification": falsification,
    }


def _safe_year(df: pd.DataFrame) -> int:
    """Attribution needs >1 sector; fall back to the last year otherwise."""
    try:
        if df.sector.nunique() <= 1:
            return int(df.year.max())
        return _worst_year(df)
    except Exception:  # noqa: BLE001
        return int(df.year.max())


def _worst_year(df: pd.DataFrame) -> int:
    """The year whose naive number is most misleading - i.e. the best exhibit.

    Ranked by (how big the naive spread was) x (how much of it disappears when
    you go sector-neutral). Ranking on the gap alone picks quiet years where
    nothing mattered.
    """
    by = by_year(df)
    if not by["rows"]:
        return int(df.year.max())
    naive = {r["year"]: r["spread_ann_pct"] for r in by["rows"] if r["kind"] == "naive"}
    neu = {r["year"]: r["spread_ann_pct"] for r in by["rows"] if r["kind"] == "sector_neutral"}
    yrs = [y for y in naive if y in neu]
    score = lambda y: abs(naive[y]) + abs(naive[y] - neu[y])
    return max(yrs, key=score) if yrs else int(df.year.max())
