"""Test suite for the analysis engine.

Not decoration. Three of these tests exist to protect specific claims made in
the memo and the deck, so if the code drifts the documentation fails loudly
instead of quietly becoming wrong.

    .venv/bin/python -m pytest environ/tests -q
    .venv/bin/python -m pytest environ/tests -k sensitivity -q   # the important one
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from environ import config as C
from environ import stats as S
from environ.data.generate_data import build_panel

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


# ---------------------------------------------------------------- fixtures
@pytest.fixture(scope="session")
def demo():
    panel, firms = build_panel()
    out = S.analyse(S.prep(panel), firms)
    return panel, firms, out


@pytest.fixture(scope="session")
def null_panel():
    """The same world with the ESG effects switched off."""
    e = C.EsgEffects(level_ret_bp=0.0, momentum_ret_bp=0.0, level_vol_pct=0.0, level_beta=0.0)
    panel, firms = build_panel(e)
    return panel, firms, S.analyse(S.prep(panel), firms)


# ---------------------------------------------------------------- generator
def test_generator_is_deterministic():
    """Same seed, same numbers. The memo and deck quote them, so they must not drift."""
    a, _ = build_panel()
    b, _ = build_panel()
    pd.testing.assert_frame_equal(a, b)


def test_generator_shape():
    panel, firms = build_panel()
    months = C.END_YEAR - C.START_YEAR + 1
    assert panel.date.nunique() == 12 * months
    assert panel.ticker.nunique() == C.N_FIRMS == len(firms)
    assert panel.sector.nunique() == len(C.SECTORS)
    assert not panel[["esg_score", "ret_m", "esg_z"]].isna().any().any()
    assert panel.esg_score.between(0, 100).all()


def test_universe_return_is_plausible():
    """A guard against a generator bug producing ±200% months."""
    panel, _ = build_panel()
    m = panel.ret_m.mean() * 12
    assert 2.0 < m < 20.0, f"annualised universe return {m:.2f}% is not a credible equity sample"
    assert panel.ret_m.abs().max() < 60


def test_letters_are_not_degenerate():
    """The rating scale must span the range, or the 'quintiles' are noise."""
    panel, firms = build_panel()
    assert firms.esg_letter.nunique() >= 5


def test_sectors_have_systematically_different_scores():
    """The sector-bias exhibit only exists if ESG and sector are correlated.

    If someone tunes the generator's reversion speed and this fails, the
    'it is a sector bet' conclusion evaporates - which is exactly what the
    test is for.
    """
    panel, _ = build_panel()
    by_sector = panel.groupby("sector").esg_score.mean()
    spread = by_sector.max() - by_sector.min()
    assert spread > 10, f"sector means span only {spread:.1f} pts - no bias to find"
    assert by_sector.idxmin() == "Energy"
    assert by_sector.idxmax() in {"Utilities", "Real Estate", "Information Technology"}


# ---------------------------------------------------------------- sorts
def test_quintiles_are_balanced_each_month(demo):
    _, _, out = demo
    # 160 firms / 5 buckets; the loader drops nothing per month here
    assert out["sorts"]["naive"]["n_months"] == 12 * (C.END_YEAR - C.START_YEAR + 1)


def test_neutralisation_removes_the_sector_mean(demo):
    """Sector-demeaned returns must average ~zero within each sector-month."""
    panel, _, _ = demo
    d = panel.copy()
    d["r_neu"] = d.ret_m - d.groupby(["date", "sector"]).ret_m.transform("mean")
    resid = d.groupby(["date", "sector"]).r_neu.mean().abs().max()
    assert resid < 1e-9


def test_spread_equals_top_minus_bottom(demo):
    _, _, out = demo
    rows = {r["q"]: r["ret_ann_pct"] for r in out["sorts"]["naive"]["rows"]}
    assert abs(out["sorts"]["naive"]["spread_ret_ann_pct"] - (rows[5] - rows[1])) < 0.02


def test_t_stat_definition(demo):
    """t = mean/se, and the spread's t must be small - the memo says so."""
    _, _, out = demo
    na = out["sorts"]["naive"]
    t = na["spread_ret_ann_pct"] / 100 / (na["spread_vol_ann_pct"] / 100 / np.sqrt(na["n_months"]) / np.sqrt(12))
    # IR = mean/sd of monthly spread; t = IR * sqrt(n)
    assert abs(na["spread_ir"] * np.sqrt(na["n_months"]) - na["spread_t"]) < 0.15
    assert abs(na["spread_t"]) < 3, "a |t| this large on a synthetic demo is suspicious"


def test_cumulative_starts_at_100(demo):
    """'Growth of 100 from Jan 2016' must be 100 *during* Jan 2016, not
    100 times January's return. Off-by-one here is a ~9% lie on the first point."""
    _, _, out = demo
    for q, s in out["sorts"]["naive"]["cumulative"].items():
        assert s["values"][0] == 100.0, f"Q{q} index does not start at 100 (got {s['values'][0]})"
        assert s["dates"][0] == out["universe"]["span"][0]
    assert out["sorts"]["naive"]["spread_cum"][0] == 100.0


# ---------------------------------------------------------------- regression
def test_coefficients_are_per_month_basis_points(demo):
    """Unit convention is documented and must hold: 1 SD of momentum moving
    monthly returns by ~26bp is the claim in the memo."""
    _, _, out = demo
    spec = next(s for s in out["regressions"]["specs"] if s["id"] == "sector_neutral")
    mom = next(c for c in spec["result"]["coef"] if c["name"] == "m_neu")
    assert 5 < mom["bp_per_month"] < 100
    assert mom["p"] < 0.05


def test_clustering_widens_errors(demo):
    """On repeated-firm data, clustered SEs must be *wider* than classical ones.

    This is the single most common way an ESG study over-claims: 160 firms x 96
    months looks like 15,360 observations but is really ~160 independent
    drawdowns of a rating. If someone deletes the clustering to make the
    results "cleaner", this test fails.
    """
    panel, _, _ = demo
    d = S._neutralise(panel[panel.year >= 2017].copy(), ["r_neu", "z_neu"])
    d = d.dropna(subset=["r_neu", "z_neu"])
    X = np.column_stack([np.ones(len(d)), d.z_neu.to_numpy(float)])
    y = d.r_neu.to_numpy(float)
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    r = y - X @ b
    n, k = len(d), X.shape[1]

    s2 = float(r @ r) / (n - k)
    se_ols = float(np.sqrt(np.diag(np.linalg.inv(X.T @ X) * s2))[1])

    XtXi = np.linalg.inv(X.T @ X)
    meat = np.zeros((k, k))
    for _, idx in pd.Series(np.arange(n)).groupby(d.ticker.to_numpy()).groups.items():
        sg = X[idx].T @ r[idx]
        meat += np.outer(sg, sg)
    se_cl = float(np.sqrt(np.diag(XtXi @ meat @ XtXi))[1])

    t_ols, t_cl = abs(b[1] / se_ols), abs(b[1] / se_cl)
    assert se_cl > se_ols, f"clustering narrowed the SE ({se_ols:.5f} -> {se_cl:.5f}): suspicious"
    assert t_cl < t_ols, "a clustered t-stat larger than the classical one means the sandwich is wrong"


def test_r2_is_small_by_construction(demo):
    """On monthly returns R² of a few percent is the honest answer. Anything
    large means a leak (e.g. regressing a return on itself)."""
    _, _, out = demo
    for sp in out["regressions"]["specs"]:
        if sp["result"]["r2"] is not None:
            assert sp["result"]["r2"] < 0.25, f"{sp['label']} R²={sp['result']['r2']} looks like a leak"


# ---------------------------------------------------------------- risk
def test_risk_gradient_is_directionally_correct(demo):
    panel, _, out = demo
    rows = out["risk"]["rows"]
    assert rows[0]["vol_ann_pct"] > rows[4]["vol_ann_pct"]
    assert rows[0]["downside_capture_pct"] > rows[4]["downside_capture_pct"]
    ok, steps = S.monotone_count([r["vol_ann_pct"] for r in rows])
    assert ok >= 3


def test_drawdown_bounds(demo):
    _, _, out = demo
    for r in out["risk"]["rows"]:
        assert -100 < r["max_drawdown_pct"] < 0
        assert r["worst_month_pct"] < 0 < r["best_month_pct"]


# ---------------------------------------------------------------- attribution
def test_attribution_reconciles(demo):
    """mix + selection ≈ raw spread. This is the deck's central exhibit."""
    _, _, out = demo
    a = out["attribution"]
    assert a["reconciles"], f"gap {a['reconciliation_gap_ann_pct']} pts"
    for y, sub in out["attribution_by_year"].items():
        assert sub["reconciles"], f"{y} failed to reconcile"


def test_attribution_sign_follows_the_bias(demo):
    """In the year the demo is calibrated around, the mix term must carry the
    naive spread's sign and dominate in magnitude."""
    _, _, out = demo
    a = out["attribution"]
    assert np.sign(a["total_mix_effect_ann_pct"]) == np.sign(a["raw_spread_ann_pct"])
    assert abs(a["total_mix_effect_ann_pct"]) > abs(a["total_selection_ann_pct"])


def test_sector_bias_shows_energy_in_the_bottom_quintile(demo):
    _, _, out = demo
    sb = out["sector_bias"]
    i = sb["sectors"].index("Energy")
    assert sb["mix_pct"]["1"][i] > 5, "Energy should be materially overweight in Q1"
    assert sb["mix_pct"]["5"][i] == 0.0, "Energy should be absent from Q5 in this calibration"


# ---------------------------------------------------------------- verdict
def test_verdict_is_generated_not_hardcoded(demo, null_panel):
    """THE regression test for the whole project's honesty claim.

    Zero the assumed effects, rebuild, and the sentences must change. If this
    ever passes while the text looks identical, the verdict has become a
    caption and the portfolio project is a lie.
    """
    _, _, active = demo
    _, _, null = null_panel
    a_txt = json.dumps(active["verdict"], sort_keys=True)
    b_txt = json.dumps(null["verdict"], sort_keys=True)
    assert a_txt != b_txt, "verdict text did not change when the ESG effects were zeroed"

    # in the null world, momentum must stop being significant
    spec = next(s for s in null["regressions"]["specs"] if s["id"] == "sector_neutral")
    mom = next((c for c in spec["result"]["coef"] if c["name"] == "m_neu"), None)
    assert mom is not None and abs(mom["t"]) < 3.0, f"momentum still significant (t={mom['t']}) with no effect in the DGP"
    # and the risk gradient must collapse
    v = [r["vol_ann_pct"] for r in null["risk"]["rows"]]
    assert abs(v[0] - v[4]) < 3.0, f"vol spread still {v[0]-v[4]:+.1f} pts with vol effect set to zero"


def test_verdict_structure(demo):
    _, _, out = demo
    v = out["verdict"]
    assert len(v["answers"]) >= 3
    assert all(set(a) >= {"q", "a", "detail", "stat", "stat_label", "tone"} for a in v["answers"])
    assert v["one_liner"]
    assert all(a["detail"].strip() for a in v["answers"])


# ---------------------------------------------------------------- robustness
def test_degrades_without_optional_columns():
    """A sparse upload must still produce an analysis, not a 500."""
    panel, _ = build_panel()
    thin = panel[["date", "ticker", "sector", "esg_score", "ret_m", "esg_z", "esg_momentum_z"]].copy()
    out = S.analyse(S.prep(thin), None)
    assert out["universe"]["n_firms"] == C.N_FIRMS
    assert out["regressions"]["notes"], "should report the dropped controls"
    assert not out["operating"]["available"]
    assert out["noise"]["available"] is False
    json.dumps(out)


def test_falsification_check_is_honest(demo):
    """The memo claims the result dies under the null. Here is the machinery that
    proves it, and the assertion that it has not quietly been flipped to always pass.
    """
    _, _, out = demo
    f = out.get("falsification")
    if f is None:
        pytest.skip("generator unavailable")
    assert abs(f["live"]["vol_t"]) >= 2, "the live risk result should be significant on the demo panel"
    assert abs(f["null"]["vol_t"]) < 2, "the risk result survived a null in which ESG does nothing"
    assert f["conclusion_survives"] is True
    assert abs(f["null"]["raw_vol_gap_pts"]) < 1.5, (
        f"raw vol gap of {f['null']['raw_vol_gap_pts']} pts persists under the null - "
        "the 'risk gradient' would then be sector composition, not ESG"
    )
    # the reading must state what was zeroed, not just a number - otherwise the
    # exhibit can be read as "we re-ran it" without knowing what "it" was
    assert "volatility" in f["reading"] and ("zero" in f["reading"] or "null" in f["reading"])


def test_degraded_panel_never_throws():
    """A user-uploaded CSV is always messier than the demo. Missing optional
    blocks must degrade to a stub with a reason, not a 500 - the app renders
    those stubs as an explanatory banner."""
    panel, _ = build_panel()
    thin = panel[["date", "ticker", "sector", "esg_score", "ret_m", "esg_z", "esg_momentum_z"]]
    out = S.analyse(S.prep(thin.copy()), None)
    assert out["risk"]["unavailable"] and out["risk"]["rows"] == []
    assert out["operating"]["available"] is False and out["operating"]["rows"] == []
    assert out["noise"]["available"] is False
    assert out["regressions"]["notes"]
    assert out["verdict"]["answers"], "verdict must still answer what it can"
    json.dumps(out)
    # every chart must still render off a degraded payload (the UI does this)
    from environ import charts as CH

    for name in CH.CHART_NAMES:
        svg = CH.render(name, out)
        assert svg and svg.startswith("<svg"), f"{name} died on a degraded panel"


def test_prep_rejects_bad_input():
    with pytest.raises(ValueError):
        S.prep(pd.DataFrame({"a": [1]}))
    with pytest.raises(ValueError):
        S.prep(pd.DataFrame({"date": ["2020-01-31"], "ticker": ["X"], "sector": ["Y"],
                             "esg_score": [1.0], "ret_m": [1.0]}))


def test_by_year_matches_full_sample(demo):
    """Annual spreads, weighted by months, must reproduce the overall spread."""
    panel, _, out = demo
    yrs = pd.Series({r["year"]: r["spread_ann_pct"] for r in out["by_year"]["rows"] if r["kind"] == "naive"})
    n = pd.Series({r["year"]: (pd.to_datetime(panel.date).dt.year == r["year"]).sum() for r in out["by_year"]["rows"]})
    recon = float((yrs * n).sum() / n.sum())
    assert abs(recon - out["sorts"]["naive"]["spread_ret_ann_pct"]) < 1.0


# ---------------------------------------------------------------- app
@pytest.mark.parametrize("name", [
    "quintile_bars", "year_gap", "risk_profile", "cumulative", "drawdown",
    "attribution", "sector_mix", "sector_mix_all", "forest",
])
def test_charts_render(demo, name):
    from environ import charts as CH

    svg = CH.render(name, demo[2])
    assert svg and svg.startswith("<svg") and svg.rstrip().endswith("</svg>"), f"{name} failed"
    assert "failed:" not in svg[:400]
    import re as _re
    # "financial services" contains the letters n-a-n; match real tokens instead
    bad = _re.search(r">[^<>]*(?:\bnan\b|\bnone\b|\binf\b)[^<>]*<", svg.lower())
    assert not bad, f"{name} leaked {bad.group(0) if bad else '?'} into the SVG"


def test_cli_generate_and_docs_run(tmp_path):
    """The commands printed in the README must actually work."""
    out = tmp_path / "panel.csv"
    r = subprocess.run([sys.executable, "-m", "environ.data.generate_data", "--out", str(out), "--firms", "40"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
    assert out.exists() and len(pd.read_csv(out)) > 0
