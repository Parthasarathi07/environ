"""
generate_data.py — builds the demo panel used by the dashboard.

READ THIS BEFORE YOU DEFEND THE PROJECT
---------------------------------------
This is **synthetic data**. No MSCI licence, no Bloomberg terminal, no price
feed was used. It is generated from an explicit, fully readable set of
assumptions in `environ/config.py`, and it is *deterministic* (fixed seed),
so the numbers in the memo and the deck always match the app.

It is synthetic but not arbitrary: the generator is calibrated so that the
sector composition of high-ESG stocks, the 2021 energy rally and the 2022
rate shock behave the way the published literature describes them. The demo
exists so you can practise the *method* — quintile sorts, sector
neutralisation, risk metrics, clustered regressions — on a panel that
behaves like a real one.

The one design choice worth being able to explain
-------------------------------------------------
An ESG score is modelled as

    esg_score[i,t] = persistent_quality[i,t] + transitory_noise[i,t]

because real ratings are sticky with occasional step changes (agencies update
methodologies, not minds). The transitory part is pure noise: it makes firms
look like they are improving when nothing has happened. Attaching the return
and risk effects to the **persistent** part only is what keeps the generator
honest - if you let a firm's volatility follow its noisy score, you are
accidentally modelling the noise as if it were information.

Swapping in real data
---------------------
    python -m environ.data.build_real_panel
writes the same two CSVs from public sources. Nothing downstream changes:
stats.py only ever reads whatever panel it is handed.

Run:
    python -m environ.data.generate_data
    python -m environ.data.generate_data --momentum-bp 0 --level-bp 0 --level-vol-pct 0
        ^ a world in which ESG means nothing. Open the dashboard afterwards and
          watch every verdict collapse. That is the sensitivity test, and it is
          the strongest thing in the portfolio.
"""

from __future__ import annotations

import argparse
import os

import numpy as np
import pandas as pd

from environ import config as C

RNG_SEED = 20240912

# letter buckets target this shape over the rated universe:
# AAA 10% | AA 18% | A 22% | BBB 22% | BB 17% | B 8% | CCC 3%


def _letter_from_z(z: float) -> str:
    """MSCI-style letter scale, read off the *cross-sectional* z-score.

    MSCI forces a bell curve over its rated universe, so the honest analogue
    is a cut on the z-score, not on the raw 0-100 number.
    """
    if z >= 1.28:
        return "AAA"
    if z >= 0.71:
        return "AA"
    if z >= 0.25:
        return "A"
    if z >= -0.25:
        return "BBB"
    if z >= -0.71:
        return "BB"
    if z >= -1.28:
        return "B"
    return "CCC"


def _months(start: int, end: int) -> pd.DatetimeIndex:
    """Month-end dates for every month from Jan `start` to Dec `end`."""
    return pd.date_range(start=f"{start}-01-01", end=f"{end}-12-31", freq="ME")


def _z(a: np.ndarray) -> np.ndarray:
    """Standardise one row/column (cross-section) without touching zeros."""
    mu = a.mean(axis=-1, keepdims=True)
    sd = a.std(axis=-1, keepdims=True)
    return (a - mu) / np.where(sd > 1e-12, sd, 1.0)


def build_panel(
    effects: C.EsgEffects | None = None,
    seed: int = RNG_SEED,
    n_firms: int = C.N_FIRMS,
    start: int = C.START_YEAR,
    end: int = C.END_YEAR,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (firm_month_panel, firm_static). A pure function of the config."""
    e = effects or C.EFFECTS
    rng = np.random.default_rng(seed)

    months = _months(start, end)
    n_t, n = len(months), n_firms
    years = months.year.to_numpy()

    # ---------------------------------------------------------------- 1. firms
    names = list(C.SECTORS)
    weights = np.array([C.SECTORS[s][0] for s in names], dtype=float)
    weights /= weights.sum()
    esg_mu = np.array([C.SECTORS[s][1] for s in names], dtype=float)
    vol_mult = 1.0 + np.array([C.SECTORS[s][2] for s in names], dtype=float)   # sector vol tilt

    s_idx = rng.choice(len(names), size=n, p=weights)
    sector = np.array(names)[s_idx]

    log_size = rng.normal(C.LOG_SIZE_MU, C.LOG_SIZE_SIGMA, n)
    size_bn = np.exp(log_size)
    size_z = (log_size - log_size.mean()) / log_size.std(ddof=0)

    # ------------------------------------------------- 2. persistent ESG level
    # Quality is a *stationary* AR(1) around the firm's sector mean. The
    # reversion speed is the knob that keeps the sector/ESG correlation
    # intact over a decade, which is the single most important thing this
    # generator has to get right (see the sector-bias chart in the app).
    kappa = C.ESG_REVERSION_ANNUAL / 12.0
    drift_sd = C.ESG_DRIFT_SIGMA_ANNUAL / np.sqrt(12.0)
    reversion_target = esg_mu[s_idx]

    # transitory score noise: analyst disagreement, restatements, data gaps
    esg_noise_sd = C.ESG_VOL_ANNUAL / np.sqrt(12.0)

    # rare discrete rating actions (MSCI moves in letter steps, not smoothly)
    action_prob = 0.020                                     # per firm-month
    action_size = 6.5

    quality = np.empty((n_t, n))
    score = np.empty((n_t, n))
    level = reversion_target + rng.normal(0.0, 9.5, n)      # reputation endowment
    for t in range(n_t):
        level = level - kappa * (level - reversion_target) + rng.normal(0.0, drift_sd, n)
        jump = np.where(
            rng.random(n) < action_prob,
            rng.choice([-1.0, 1.0], n) * action_size,
            0.0,
        )
        level = np.clip(level + jump, 1.0, 98.0)
        quality[t] = level
        score[t] = np.clip(level + rng.normal(0.0, esg_noise_sd, n), 0.5, 99.0)

    # ------------------------------------------------------ 3. common factors
    mkt = rng.normal(C.MARKET_MEAN_M, C.MARKET_VOL_M, n_t)
    for y, adj in C.MARKET_SHOCKS.items():
        mkt[years == y] += adj

    sector_factor = np.zeros((n_t, len(names)))
    for i, s in enumerate(names):
        tilt = np.zeros(n_t)
        for y, val in C.SECTOR_YEAR_TILT.get(s, {}).items():
            tilt[years == y] += val
        # AR(1) sector noise so sector effects are persistent (they are in real life)
        noise = np.empty(n_t)
        noise[0] = rng.normal(0.0, 0.8)
        for t in range(1, n_t):
            noise[t] = 0.72 * noise[t - 1] + rng.normal(0.0, 0.8 * np.sqrt(1 - 0.72**2))
        sector_factor[:, i] = noise + tilt

    # --------------------------------------------- 4. risk: vol + beta on q_z
    # q_z = persistent quality, standardised cross-sectionally each month.
    # Everything the analysis calls "ESG" is measured on this scale, which is
    # how a factor paper would state it and how you would read a coefficient.
    q_z = _z(quality)
    s_z = _z(score)                       # what a naive user would sort on

    # Idiosyncratic vol is ADDITIVE in the ESG z-score, not multiplicative.
    # Multiplying by (1 + adj) lets the sector/size baseline sneak into the
    # size of the ESG effect, which made the risk channel hard to read.
    # Additive means: "one SD of ESG score changes annual vol by exactly
    # config.EFFECTS.level_vol_pct percentage points, everywhere". Easy to
    # explain, easy to audit.
    base_idio = 20.0 * vol_mult[s_idx] * (1.0 - 0.10 * size_z)          # annual %
    v_state = np.zeros(n)
    vol_panel = np.empty((n_t, n))
    for t in range(n_t):
        v_state = 0.90 * v_state + rng.normal(0.0, 0.16, n)
        vol_panel[t] = np.maximum(3.0, base_idio * (1.0 + v_state) + e.level_vol_pct * q_z[t])

    beta = C.BETA_BASE + e.level_beta * q_z

    # ------------------------------------------------------------ 5. momentum
    # trailing-12m change in the *persistent* quality, z-scored by month
    mom_raw = np.full((n_t, n), np.nan)
    mom_raw[12:] = quality[12:] - quality[:-12]
    mom_raw[:, :] = np.where(np.isnan(mom_raw), 0.0, mom_raw)
    mom_z = _z(mom_raw)

    # what an investor holding the *published* scores would actually see:
    # reported change = persistent change + noise in both endpoints. The gap
    # between these two columns is the measurement error you are paid for.
    rep_change = np.full((n_t, n), np.nan)
    rep_change[12:] = score[12:] - score[:-12]
    rep_change[:, :] = np.where(np.isnan(rep_change), 0.0, rep_change)

    # ---------------------------------------------------------------- 6. returns
    alpha_firm = rng.normal(0.0, 0.05, n)          # per month %
    ret = np.empty((n_t, n))
    for t in range(n_t):
        eps = rng.normal(0.0, 1.0, n) * (vol_panel[t] / np.sqrt(12.0))
        mu_esg = (e.level_ret_bp / 100.0) * q_z[t] + (e.momentum_ret_bp / 100.0) * mom_z[t]
        ret[t] = beta[t] * mkt[t] + sector_factor[t][s_idx] + mu_esg + alpha_firm + eps

    # ------------------------------------------------------- 7. long-form frame
    tickers = [f"SIM{i:03d}" for i in range(1, n + 1)]
    idio_m = vol_panel / np.sqrt(12.0)
    realised_vol = np.full((n_t, n), np.nan)
    for t in range(12, n_t):
        realised_vol[t] = ret[t - 12 : t].std(axis=0, ddof=1) * np.sqrt(12.0)

    panel = pd.DataFrame(
        {
            "date": np.repeat(months.strftime("%Y-%m-%d"), n),
            "year": np.repeat(years, n),
            "month": np.repeat(months.month.to_numpy(), n),
            "ticker": np.tile(tickers, n_t),
            "sector": np.tile(sector, n_t),
            "esg_score": score.reshape(-1).round(2),
            "esg_persistent": quality.reshape(-1).round(2),
            "esg_z": s_z.reshape(-1).round(4),
            "esg_q_z": q_z.reshape(-1).round(4),
            "esg_change_12m": mom_raw.reshape(-1).round(3),
            "esg_momentum_z": mom_z.reshape(-1).round(4),
            "esg_reported_change_12m": rep_change.reshape(-1).round(3),
            "ret_m": ret.reshape(-1).round(4),
            "idio_vol_ann": vol_panel.reshape(-1).round(2),
            "realised_vol_ann": np.round(realised_vol.reshape(-1), 2),
            "beta": beta.reshape(-1).round(3),
            "ev_bn": np.tile(size_bn, n_t).round(2),
        }
    )
    panel["esg_letter"] = [_letter_from_z(v) for v in panel["esg_z"]]

    if panel[["esg_score", "ret_m", "idio_vol_ann", "esg_q_z"]].isna().any().any():
        raise RuntimeError("NaNs in the panel - check the generator")

    # ------------------------------------------------ 8. firm-static "why" file
    mean_q_z = q_z.mean(axis=0)
    growth = C.GROWTH_MU + (e.level_growth_bp / 100.0) * mean_q_z * 4.0 + rng.normal(0, C.GROWTH_SIGMA * 0.5, n)
    margin = C.MARGIN_MU + (e.level_margin_bp / 100.0) * mean_q_z * 3.0 + rng.normal(0, C.MARGIN_SIGMA * 0.5, n)
    capex = 5.5 + 0.30 * mean_q_z + rng.normal(0.0, 1.0, n)   # greener firms invest a bit more
    coe = C.COST_OF_EQUITY_BASE + (vol_panel.mean(axis=0) - 20.0) * 0.135 - 0.12 * mean_q_z

    firms = pd.DataFrame(
        {
            "ticker": tickers,
            "sector": sector,
            "esg_mean": score.mean(axis=0).round(1),
            "esg_letter": [_letter_from_z(v) for v in mean_q_z],
            "esg_z_mean": mean_q_z.round(3),
            "ev_bn": size_bn.round(2),
            "idio_vol_ann": vol_panel.mean(axis=0).round(2),
            "beta": beta.mean(axis=0).round(3),
            "revenue_growth_pct": growth.round(2),
            "ebitda_margin_pct": margin.round(2),
            "capex_intensity_pct": capex.round(2),
            "cost_of_equity_pct": coe.round(2),
        }
    )
    return panel, firms


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Generate the demo ESG / returns panel.")
    ap.add_argument("--level-bp", type=float, default=C.EFFECTS.level_ret_bp,
                    help="monthly return premium per SD of ESG level (basis points)")
    ap.add_argument("--momentum-bp", type=float, default=C.EFFECTS.momentum_ret_bp,
                    help="monthly return premium per SD of trailing 12m rating change")
    ap.add_argument("--level-vol-pct", type=float, default=C.EFFECTS.level_vol_pct,
                    help="change in annual idiosyncratic vol (%%) per SD of ESG level")
    ap.add_argument("--firms", type=int, default=C.N_FIRMS)
    ap.add_argument("--seed", type=int, default=RNG_SEED)
    ap.add_argument("--out", default=C.PATHS.panel)
    args = ap.parse_args()

    eff = C.EsgEffects(
        level_ret_bp=args.level_bp,
        momentum_ret_bp=args.momentum_bp,
        level_vol_pct=args.level_vol_pct,
    )
    panel, firms = build_panel(eff, seed=args.seed, n_firms=args.firms)

    out_panel = os.path.abspath(args.out)
    out_firms = out_panel.replace("panel.csv", "firms.csv")
    os.makedirs(os.path.dirname(out_panel), exist_ok=True)
    panel.to_csv(out_panel, index=False)
    firms.to_csv(out_firms, index=False)

    print(f"panel  -> {out_panel}")
    print(f"         {len(panel):,} rows | {panel.ticker.nunique()} firms | "
          f"{panel.date.nunique()} months ({panel.date.min()} .. {panel.date.max()})")
    print(f"firms  -> {out_firms}")
    print("assumed effects: "
          f"level={args.level_bp}bp/mo/SD  momentum={args.momentum_bp}bp/mo/SD  "
          f"vol={args.level_vol_pct}pct/SD")


if __name__ == "__main__":
    main()
