"""
make_figures.py — PNG exhibits for the memo, the deck and a portfolio site.

The dashboard's charts are live SVG (see environ/charts.py). These are the
same numbers rendered with matplotlib, for when you need an image you can
paste into a slide or a Word doc. Single source of truth: both call
environ.stats.analyse().

    .venv/bin/python -m environ.scripts.make_figures            # -> environ/docs/figures
    .venv/bin/python -m environ.scripts.make_figures --year 2020
"""

from __future__ import annotations

import argparse
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from environ import stats as S  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DEFAULT = os.path.join(HERE, "docs", "figures")

INK = "#16181d"
MUTED = "#6b7280"
GREEN = "#1f5c46"
WARN = "#b4453c"
SEQ = ["#8c9bab", "#5f8fb3", "#3f7fa6", "#2f6f74", "#1f5c46"]
GREY = "#e5e7eb"


def style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10.5,
            "axes.edgecolor": "#c3c8d1",
            "axes.labelcolor": INK,
            "text.color": INK,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.color": GREY,
            "grid.linewidth": 0.8,
            "axes.axisbelow": True,
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
            "savefig.bbox": "tight",
            "savefig.dpi": 170,
        }
    )


def save(fig, outdir: str, name: str) -> str:
    os.makedirs(outdir, exist_ok=True)
    p = os.path.join(outdir, name)
    fig.savefig(p)
    plt.close(fig)
    print(f"  wrote {os.path.relpath(p, HERE)}")
    return p


# ---------------------------------------------------------------------------
def fig_quintiles(out, outdir):
    naive, neu = out["sorts"]["naive"], out["sorts"]["sector_neutral"]
    # Separate y-axes on purpose: the entire point is that the neutral panel's
    # full range is ~1pt while the naive one spans 2. Shared axes would draw
    # the interesting panel as a flat line and read as "nothing plotted".
    fig, axes = plt.subplots(1, 2, figsize=(9.6, 3.9))
    for ax, sort, head, cap in (
        (axes[0], naive, "As published", "what a headline reports"),
        (axes[1], neu, "Sector-neutral", "the honest comparison"),
    ):
        rows = sort["rows"]
        vals = [r["ret_ann_pct"] for r in rows]
        bars = ax.bar([r["q"] for r in rows], vals, color=SEQ, width=0.66)
        for b, v in zip(bars, vals):
            if abs(v) < 0.05:
                continue   # never print "-0.0"
            ax.annotate(
                f"{v:+.1f}",
                (b.get_x() + b.get_width() / 2, v),
                ha="center",
                va="bottom" if v >= 0 else "top",
                fontsize=9.5,
                fontweight="bold",
            )
        ax.axhline(0, color="#aeb4be", lw=1)
        rng = (max(vals) - min(vals)) or 1.0
        ax.set_ylim(min(vals) - 0.28 * rng, max(vals) + 0.30 * rng)
        ax.set_title(f"{head} — {cap}", fontsize=10.5, fontweight="bold", loc="left", color=MUTED)
        ax.set_xticks([1, 2, 3, 4, 5])
        ax.set_xticklabels([f"Q{i}" for i in range(1, 6)])
        ax.set_ylabel("annualised return, %" if ax is axes[0] else "")
        spread = sort["spread_ret_ann_pct"]
        t = sort["spread_t"]
        ax.text(
            0.02, 1.02, f"Q5−Q1 = {spread:+.1f}%/yr   t = {t:+.1f}",
            transform=ax.transAxes, fontsize=9.5, va="bottom",
            color=GREEN if abs(t) >= 2 else MUTED, fontweight="bold",
        )
    fig.suptitle(
        "Higher ESG score does not buy you return",
        x=0.02, y=1.04, ha="left", fontsize=13.5, fontweight="bold",
    )
    fig.text(
        0.02, -0.06,
        f"Equal-weighted quintile portfolios on the published ESG score, {naive['n_months']} months, "
        f"{out['universe']['n_firms']} firms. Demo panel (synthetic).",
        fontsize=8.5, color=MUTED, ha="left",
    )
    return save(fig, outdir, "01_quintile_returns.png")


def fig_year(out, outdir):
    by = out["by_year"]
    yrs = by["years"]
    x = np.arange(len(yrs))
    w = 0.38
    fig, ax = plt.subplots(figsize=(9.6, 4.1))
    b1 = ax.bar(x - w / 2, by["naive"], w, color="#98a4b1", label="as published")
    b2 = ax.bar(x + w / 2, by["sector_neutral"], w, color=GREEN, label="sector-neutral")
    for bars, vals in ((b1, by["naive"]), (b2, by["sector_neutral"])):
        for b, v in zip(bars, vals):
            if v is None:
                continue
            ax.annotate(f"{v:+.0f}", (b.get_x() + b.get_width() / 2, v),
                        ha="center", va="bottom" if v >= 0 else "top", fontsize=8.5, color=MUTED)
    ax.axhline(0, color="#aeb4be", lw=1)
    ax.set_xticks(x)
    ax.set_xticklabels(yrs)
    ax.set_ylabel("Q5 − Q1 spread, % per year")
    ax.legend(frameon=False, loc="lower left", fontsize=9.5)
    ax.set_title(
        "One year carries the whole ESG debate — and it is a sector story",
        loc="left", fontsize=13.5, fontweight="bold",
    )
    i = int(np.argmin([v if v is not None else 9e9 for v in by["naive"]]))
    ax.annotate(
        f"{yrs[i]}: naive {by['naive'][i]:+.1f}% vs\nsector-neutral {by['sector_neutral'][i]:+.1f}%",
        xy=(x[i] - w / 2, by["naive"][i]),
        xytext=(x[i] + 0.5, by["naive"][i] * 0.42),
        fontsize=9.5, color=WARN, fontweight="bold",
        arrowprops=dict(arrowstyle="->", color=WARN, lw=1.2),
    )
    fig.text(0.02, -0.07,
             "Same portfolios, same months. The only difference is whether the sector's own move is subtracted.",
             fontsize=8.5, color=MUTED, ha="left")
    return save(fig, outdir, "02_year_gap.png")


def fig_risk(out, outdir):
    rows = out["risk"]["rows"]
    q = [r["q"] for r in rows]
    fig, axes = plt.subplots(1, 3, figsize=(10.6, 3.5))
    panels = [
        ("vol_ann_pct", "annualised volatility, %"),
        ("downside_capture_pct", "downside capture, % of market"),
        ("max_drawdown_pct", "worst drawdown, %"),
    ]
    for ax, (key, lab) in zip(axes, panels):
        vals = [r[key] for r in rows]
        ax.plot(q, vals, "o-", color=GREEN, lw=2.2, ms=6)
        for xx, vv in zip(q, vals):
            ax.annotate(f"{vv:.0f}" if abs(vv) >= 10 else f"{vv:.1f}", (xx, vv),
                        textcoords="offset points", xytext=(0, 8), ha="center", fontsize=9)
        ax.axhline(100, color="#c9ccd2", lw=1, ls="--") if key == "downside_capture_pct" else None
        ax.set_title(lab, fontsize=10.5, fontweight="bold", loc="left")
        ax.set_xticks(q)
        ax.set_xticklabels([f"Q{i}" for i in q])
    fig.suptitle("What the score does move: risk", x=0.02, y=1.05, ha="left",
                 fontsize=13.5, fontweight="bold")
    sh = out.get("verdict", {}).get("risk_shape", {}) or {}
    fig.text(0.02, -0.08,
             "Bottom to top ESG quintile. Gradient: {} on volatility, {} on downside capture, {} on drawdown "
             "depth. Not a perfectly clean line, and saying so is part of the result.".format(
                 sh.get("vol", "n/a"), sh.get("capture", "n/a"), sh.get("drawdown", "n/a")),
             fontsize=8.5, color=MUTED, ha="left")
    return save(fig, outdir, "03_risk.png")


def fig_attribution(out, outdir, year=None):
    if year is None or year == out["attribution"]["year"]:
        a = out["attribution"]
    else:
        raw = pd.read_csv(os.path.join(HERE, "data", "panel.csv"))
        raw["year"] = pd.to_datetime(raw["date"]).dt.year
        a = S.sector_contribution(raw, year=year)
    rows = [r for r in a["rows"] if abs(r["contribution_ann_pct"]) > 0.02]
    names = [r["sector"] for r in rows]
    mix = [r["mix_ann_pct"] for r in rows]
    sel = [r["selection_ann_pct"] for r in rows]
    y = np.arange(len(rows))
    fig, ax = plt.subplots(figsize=(9.6, 5.0))
    h = 0.36
    ax.barh(y + h / 2, mix, h, color=WARN, label="sector mix (what each book holds)")
    ax.barh(y - h / 2, sel, h, color="#5f8fb3", label="within-sector selection (stock-picking)")
    ax.axvline(0, color="#aeb4be", lw=1)
    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=9.5)
    ax.invert_yaxis()
    ax.set_xlabel(f"contribution to the Q5−Q1 spread, % per year ({a['year']})")
    # legend above the plot: one of the bars runs to the far right and would
    # sit under a lower-right legend
    ax.legend(frameon=False, fontsize=9.5, loc="upper left", bbox_to_anchor=(0.0, 1.02))
    ax.grid(axis="y", visible=False)
    ax.set_title(
        f"Why the {a['year']} spread was {a['raw_spread_ann_pct']:+.1f}%/yr: it is a sector bet",
        loc="left", fontsize=13.5, fontweight="bold",
    )
    tot = a["total_mix_effect_ann_pct"] + a["total_selection_ann_pct"]
    fig.text(0.02, -0.06,
             f"Sector mix {a['total_mix_effect_ann_pct']:+.1f} pts + selection {a['total_selection_ann_pct']:+.1f} pts "
             f"= {tot:+.1f} pts vs a raw spread of {a['raw_spread_ann_pct']:+.1f} pts "
             f"(gap {a['reconciliation_gap_ann_pct']:+.2f} pts; weights drift monthly). Exact identity, built per month.",
             fontsize=8.5, color=MUTED, ha="left")
    return save(fig, outdir, "04_attribution.png")


def fig_cum(out, outdir):
    cu = out["sorts"]["naive"]["cumulative"]
    fig, ax = plt.subplots(figsize=(9.6, 4.0))
    for q in ("1", "5"):
        s = pd.Series(cu[q]["values"], index=pd.to_datetime(cu[q]["dates"]))
        ax.plot(s.index, s.values, lw=2.4, color=SEQ[int(q) - 1], label=f"Q{q} ({'highest' if q=='5' else 'lowest'} ESG)")
    s1 = pd.Series(cu["1"]["values"], index=pd.to_datetime(cu["1"]["dates"]))
    s5 = pd.Series(cu["5"]["values"], index=pd.to_datetime(cu["5"]["dates"]))
    ax.annotate(f"{s5.iloc[-1]:.0f}", xy=(s5.index[-1], s5.iloc[-1]), xytext=(-4, 6),
                textcoords="offset points", ha="right", color=SEQ[4], fontweight="bold")
    ax.annotate(f"{s1.iloc[-1]:.0f}", xy=(s1.index[-1], s1.iloc[-1]), xytext=(-4, -14),
                textcoords="offset points", ha="right", color=SEQ[0], fontweight="bold")
    ax.set_ylabel("value of 100")
    ax.legend(frameon=False, fontsize=9.5, loc="upper left")
    ax.set_title("Growth of 100 — top vs bottom ESG quintile", loc="left", fontsize=13.5, fontweight="bold")
    fig.text(0.02, -0.06, "Monthly rebalanced, equal weighted, before transaction costs.",
             fontsize=8.5, color=MUTED, ha="left")
    return save(fig, outdir, "05_growth_of_100.png")


def fig_forest(out, outdir):
    specs = out["regressions"]["specs"]
    items = [
        (sp["label"], c)
        for sp in specs
        for c in sp["result"]["coef"]
        if c["name"] == "z_neu"
    ]
    fig, ax = plt.subplots(figsize=(9.6, 3.4))
    y = np.arange(len(items))
    ax.errorbar([c["bp_per_month"] for _, c in items], y,
                xerr=[[c["bp_per_month"] - c["ci_lo_bp"] for _, c in items],
                      [c["ci_hi_bp"] - c["bp_per_month"] for _, c in items]],
                fmt="o", color=GREEN, ecolor=INK, elinewidth=1.5, capsize=3, ms=7)
    ax.axvline(0, color=WARN, ls="--", lw=1.2)
    ax.set_yticks(y)
    ax.set_yticklabels([n for n, _ in items], fontsize=9.5)
    ax.invert_yaxis()
    ax.set_xlabel("ESG-level coefficient, basis points per month per 1 SD of score")
    ax.set_title("The ESG 'premium' depends on what you control for", loc="left", fontsize=13.5, fontweight="bold")
    for yy, (_, c) in zip(y, items):
        ax.annotate(f"t={c['t']:+.1f}", xy=(c["ci_hi_bp"] + 2, yy), fontsize=9,
                    color=INK if abs(c["t"]) >= 2 else MUTED, va="center",
                    fontweight="bold" if abs(c["t"]) >= 2 else "normal")
    ax.grid(axis="y", visible=False)
    fig.text(0.02, -0.1, "95% intervals from standard errors clustered by firm; year fixed effects included.",
             fontsize=8.5, color=MUTED, ha="left")
    return save(fig, outdir, "06_forest.png")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default=os.path.join(HERE, "data", "panel.csv"))
    ap.add_argument("--firms", default=os.path.join(HERE, "data", "firms.csv"))
    ap.add_argument("--outdir", default=OUT_DEFAULT)
    ap.add_argument("--year", type=int, default=None)
    args = ap.parse_args()

    style()
    panel = S.prep(pd.read_csv(args.panel))
    firms = pd.read_csv(args.firms) if os.path.exists(args.firms) else None
    out = S.analyse(panel, firms)
    print("figures:")
    fig_quintiles(out, args.outdir)
    fig_year(out, args.outdir)
    fig_risk(out, args.outdir)
    fig_attribution(out, args.outdir, args.year)
    fig_cum(out, args.outdir)
    fig_forest(out, args.outdir)


if __name__ == "__main__":
    main()
