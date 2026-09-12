"""
config.py — the single place where every assumption lives.

Why this file exists
--------------------
In a finance project, the numbers that matter most are usually not in the
code, they are in the *assumptions*. So they get their own file, with
comments explaining what each one means in plain English. If someone asks
"what did you assume?", you open this file and read it out loud.

Everything here feeds the demo data generator (data/generate_data.py).
The analysis code in stats.py never uses these constants — it only reads
whatever panel it is given. That separation is deliberate: the conclusions
are produced by the statistics, not hard-coded.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 1. Time and universe
# ---------------------------------------------------------------------------
START_YEAR = 2016
END_YEAR = 2024          # inclusive -> 108 monthly observations
N_FIRMS = 160

# ---------------------------------------------------------------------------
# 2. The sector table
# ---------------------------------------------------------------------------
# name            universe weight   avg ESG score   sector vol tilt (x, 1.0 = none)
#
# `weight` is how common the sector is in the simulated universe.
# `esg_mu` is the average MSCI-style 0-100 ESG score of firms in that sector.
# `vol_tilt` nudges how volatile that sector's stocks are. It is kept *small
# on purpose*: if sector volatility were large, the sector mix of the ESG
# quintiles would swamp the ESG-risk channel and you could not see either one.
#   Real-world pattern: tech / utilities / real estate score well, oil and
#   gas and airlines score badly, because the score is *sector relative*.
SECTORS: dict[str, tuple[float, float, float]] = {
    "Information Technology": (0.20, 42.0, 0.14),
    "Industrials":            (0.14, 33.0, 0.05),
    "Financial Services":     (0.13, 30.0, -0.05),
    "Health Care":            (0.12, 31.0, -0.03),
    "Consumer Discretionary": (0.11, 29.0, 0.10),
    "Consumer Staples":       (0.09, 34.0, -0.14),
    "Utilities":              (0.08, 40.0, -0.10),
    "Communication Services": (0.07, 37.0, 0.08),
    "Materials":              (0.05, 27.0, 0.06),
    "Real Estate":            (0.04, 44.0, -0.06),
    "Energy":                 (0.04, 15.0, 0.22),
}

# ---------------------------------------------------------------------------
# 3. Sector x year tilts (monthly, in %)
# ---------------------------------------------------------------------------
# This is the honest reason the ESG debate flips year to year. Energy boomed
# in 2021-22; long-duration tech got hit when rates rose. The ESG-relevant
# point is only this: the sectors that ESG screens *out* are the ones that
# happened to boom in 2021-22, and the sectors it screens *in* are the ones
# that got hit.
#
# Rows = sector, columns = year. Values are ADDED to that sector's expected
# monthly return for that year. 1.0 means "+1 percentage point per month".
SECTOR_YEAR_TILT: dict[str, dict[int, float]] = {
    "Energy":                 {2020: -3.0, 2021: 2.1, 2022: 2.4, 2023: -0.6},
    "Materials":              {2020: -1.2, 2021: 0.7, 2022: -0.5},
    "Industrials":            {2020: -1.3, 2021: 0.6, 2022: -0.3},
    "Communication Services": {2021: 0.6, 2022: -1.1, 2023: 0.8, 2024: 0.5},
    "Information Technology": {2020: 1.1, 2021: 0.9, 2022: -1.4, 2023: 1.2, 2024: 0.8},
    "Utilities":              {2021: 0.4, 2022: -0.7, 2023: -0.4, 2024: 0.4},
    "Health Care":            {2020: -0.6, 2021: 0.4, 2022: 0.6, 2023: -0.3},
    "Financial Services":     {2020: -1.6, 2022: 0.5, 2023: -0.4},
    "Consumer Discretionary": {2020: 0.4, 2021: 0.5, 2022: -1.2, 2023: 0.3, 2024: 0.3},
    "Consumer Staples":       {2022: 0.4, 2023: -0.2, 2024: 0.2},
    "Real Estate":            {2020: -1.8, 2021: 1.0, 2022: -1.5, 2023: -0.5, 2024: 0.3},
}

# ---------------------------------------------------------------------------
# 4. The market factor
# ---------------------------------------------------------------------------
MARKET_MEAN_M = 0.62      # % per month  (~5.4% p.a. before the shocks below)
MARKET_VOL_M = 4.2        # % per month
MARKET_SHOCKS: dict[int, float] = {2020: -0.55, 2022: -0.35, 2023: -0.05, 2024: 0.25}


# ---------------------------------------------------------------------------
# 5. THE THREE ESG CHANNELS  <-- this is the heart of the whole project
# ---------------------------------------------------------------------------
@dataclass
class EsgEffects:
    """How much ESG is allowed to matter in the simulated world.

    Flipping these numbers is the project's built-in honesty test: change a
    coefficient, re-run generate_data.py, and watch the dashboard's verdict
    change. That is exactly how you should read anyone else's ESG study.
    """

    # (a) LEVEL -> return. Sector-neutral premium per 1 SD of ESG score.
    #     Set small on purpose. Most careful studies find something near zero
    #     once you strip out sector, size and momentum.
    level_ret_bp: float = 0.5          # 5 bp per month per SD -> ~0.6% p.a., i.e. noise

    # (b) MOMENTUM -> return. Premium for firms whose rating is *improving*.
    #     Literature is much firmer here than on levels. The unit is a
    #     standardised 12-month rating change, so this says: a firm whose
    #     score jumped into the top decile of improvers earns ~3.6%/yr more,
    #     for a while. That is an aggressive-but-published number.
    momentum_ret_bp: float = 30.0      # 30 bp per month per SD of rating change

    # (c) LEVEL -> risk. Better-rated firms carry less firm-specific risk and
    #     slightly less market sensitivity. This is the "downside protection"
    #     story and it is the strongest result the dashboard finds.
    level_vol_pct: float = -2.6        # each SD of ESG cuts annual idio vol by 260 bp
    level_beta: float = -0.09          # each SD of ESG cuts market beta by 0.09

    # (d) LEVEL -> earnings growth / margin. The "ESG costs money" channel
    #     that short-sellers cite. Only used for the operating-stats tab.
    level_growth_bp: float = -1.5      # per SD per year
    level_margin_bp: float = -3.0      # per SD per year


EFFECTS = EsgEffects()

# ---------------------------------------------------------------------------
# 6. Rating-dynamics knobs
# ---------------------------------------------------------------------------
ESG_VOL_ANNUAL = 5.5        # how noisy a firm's *reported* score is, points/yr
ESG_SECTOR_DRIFT_ANNUAL = 0.55   # sectors slowly converge toward their sector mean
# mean reversion of a firm's persistent quality toward its sector mean.
# Keep this firm: if it is too loose, firms drift across sectors over ten
# years and the ESG-score/sector correlation that drives the whole
# "sector bias" story disappears. 0.10/yr = 90% of a firm's sector-relative
# position survives a year.
ESG_REVERSION_ANNUAL = 0.10
# how much a firm's own standing genuinely moves per year (points).
# This, not the reporting noise, is what an ESG-momentum signal can trade.
ESG_DRIFT_SIGMA_ANNUAL = 3.4

# ---------------------------------------------------------------------------
# 7. Size / operating stats
# ---------------------------------------------------------------------------
LOG_SIZE_MU = 4.0           # ln($bn); median firm ~ $55bn
LOG_SIZE_SIGMA = 1.15
BETA_BASE = 1.0
GROWTH_MU = 6.0             # revenue growth %, annual
GROWTH_SIGMA = 6.0
MARGIN_MU = 13.0            # EBITDA margin %
MARGIN_SIGMA = 6.0
COST_OF_EQUITY_BASE = 8.4   # % - used only to draw the COE panel


@dataclass
class Paths:
    """Where files live, so nothing depends on the current working directory."""

    root: str = "."
    panel: str = "environ/data/panel.csv"
    firms: str = "environ/data/firms.csv"
    outputs: str = "environ/data/outputs"


PATHS = Paths()
