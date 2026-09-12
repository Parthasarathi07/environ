"""
charts.py — server-side SVG renderer.

One implementation of every exhibit, used twice:
  * `GET /api/svg/{name}`      -> inline SVG for the slide deck
  * scripts/make_figures.py    -> PNGs for the memo / portfolio site

Kept deliberately small (no plotly, no CDN) because the sandbox has no
internet and a portfolio project that cannot run offline is worthless.
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np

# ----------------------------------------------------------------------------- palette
INK = "#16181d"
MUTED = "#6b7280"
GRID = "#e5e7eb"
BG = "#ffffff"
SEQ = ["#8c9bab", "#5f8fb3", "#3f7fa6", "#2f6f74", "#1f5c46"]   # Q1 -> Q5, grey to green
ACCENT = "#1f5c46"
WARN = "#b4453c"
FONT = "'Inter', 'Helvetica Neue', Arial, sans-serif"


def esc(x: Any) -> str:
    return (
        str(x)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _fmt(v: float | None, nd: int = 1, sign: bool = False) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"{v:+.{nd}f}" if sign else f"{v:.{nd}f}"


class SVG:
    """A tiny drawing surface. Everything is a string; no dependencies."""

    def __init__(self, w: int, h: int, margin: tuple[int, int, int, int] = (52, 28, 58, 62)):
        self.w, self.h = w, h
        self.t, self.r, self.b, self.l = margin
        self.x0, self.y0 = self.l, self.t
        self.x1, self.y1 = w - self.r, h - self.b
        self.pw, self.ph = self.x1 - self.x0, self.y1 - self.y0
        self.body: list[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
            f'width="{w}" height="{h}" font-family="{FONT}">',
            f'<rect width="{w}" height="{h}" fill="{BG}"/>',
        ]

    # ---- scales
    def scale(self, xmin: float, xmax: float, ymin: float, ymax: float) -> None:
        self.xmin, self.xmax, self.ymin, self.ymax = xmin, xmax, ymin, ymax
        pad = (ymax - ymin) * 0.08 or 1.0
        self.ymin, self.ymax = ymin - pad * 0.4, ymax + pad
        if self.xmax == self.xmin:
            self.xmax = self.xmin + 1

    def X(self, i: float) -> float:
        return self.x0 + (i - self.xmin) / (self.xmax - self.xmin) * self.pw

    def Y(self, v: float) -> float:
        return self.y1 - (v - self.ymin) / (self.ymax - self.ymin) * self.ph

    # ---- primitives
    def text(self, x, y, s, size=12, color=INK, anchor="start", weight=None, style=None, rotate=None):
        w = f' font-weight="{weight}"' if weight else ""
        rot = f' transform="rotate({rotate} {x} {y})"' if rotate is not None else ""
        st = f' font-style="{style}"' if style else ""
        self.body.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{color}" '
            f'text-anchor="{anchor}"{w}{st}{rot}>{esc(s)}</text>'
        )

    def line(self, x1, y1, x2, y2, color=GRID, width=1.0, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.body.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                         f'stroke="{color}" stroke-width="{width}"{d}/>')

    def rect(self, x, y, w, h, fill, opacity=1.0, rx=0):
        self.body.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w,0):.1f}" height="{max(h,0):.1f}" '
                         f'fill="{fill}" opacity="{opacity}" rx="{rx}"/>')

    def path(self, pts: list[tuple[float, float]], color: str, width: float = 2.2, fill: str | None = None,
             opacity: float = 1.0):
        if not pts:
            return
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        if fill:
            d += f" L{pts[-1][0]:.1f},{self.y1:.1f} L{pts[0][0]:.1f},{self.y1:.1f} Z"
        self.body.append(f'<path d="{d}" fill="{fill or "none"}" fill-opacity="{0.10 if fill else 0}" '
                         f'stroke="{color}" stroke-width="{width}" stroke-linejoin="round" '
                         f'stroke-linecap="round" opacity="{opacity}"/>')

    def dots(self, pts, color, r=3.4):
        for x, y in pts:
            self.body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{color}"/>')

    def dot(self, x, y, color, r=3.4):
        self.body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{color}"/>')

    # ---- furniture
    def title(self, title: str, sub: str = "", kicker: str = ""):
        if kicker:
            self.text(self.l - 8, 18, kicker.upper(), 10.5, MUTED, weight="600")
        self.text(self.l - 8, 36, title, 16, INK, weight="700")
        if sub:
            self.text(self.l - 8, self.h - 16, sub, 10.5, MUTED)

    def grid_y(self, ticks: list[float], fmt: Callable[[float], str] = lambda v: _fmt(v, 0)):
        for t in ticks:
            y = self.Y(t)
            self.line(self.x0, y, self.x1, y, GRID, 1.0)
            self.text(self.x0 - 8, y + 4, fmt(t), 10.5, MUTED, anchor="end")

    def zero(self):
        if self.ymin < 0 < self.ymax:
            self.line(self.x0, self.Y(0), self.x1, self.Y(0), "#c3c8d1", 1.4)

    def frame(self):
        self.line(self.x0, self.y1, self.x1, self.y1, "#c3c8d1", 1.2)

    def done(self) -> str:
        self.body.append("</svg>")
        return "".join(self.body)


def _ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    if hi == lo:
        return [lo]
    raw = (hi - lo) / n
    mag = 10 ** np.floor(np.log10(abs(raw) or 1))
    step = 10 * mag
    for cand in (1, 2, 2.5, 5, 10):
        if raw / (cand * mag) <= 1.0001:
            step = cand * mag
            break
    start = np.ceil(lo / step) * step
    out = []
    v = start
    while v <= hi + step * 1e-9:
        out.append(round(float(v), 8))
        v += step
    return out


# ----------------------------------------------------------------------------- charts
def chart_quintile_bars(payload: dict) -> str | None:
    """Annualised return by ESG quintile, naive vs sector-neutral, side by side."""
    try:
        naive = payload["sorts"]["naive"]["rows"]
        neu = payload["sorts"]["sector_neutral"]["rows"]
    except KeyError:
        return None
    s = SVG(760, 400)
    s.title(
        "Higher ESG score does not buy you return",
        "Equal-weighted quintile portfolios, annualised total return 2016–2024. "
        "Left: as published. Right: after subtracting each sector's own move.",
        "Quintile sorts",
    )
    half = (s.w - 130) / 2

    def panel(rows, x_off, heading, note):
        vals = [r["ret_ann_pct"] for r in rows]
        lo, hi = min(vals + [0]), max(vals + [0])
        pad = (hi - lo) * 0.15 or 1
        ymin, ymax = lo - pad, hi + pad
        bw = half / 5 * 0.62
        base = s.Y(0) if False else None
        top, bot = s.t + 42, s.y1 - 8
        scale = (bot - top) / (ymax - ymin)
        y0 = bot + ymin * scale          # pixel of value 0
        s.text(x_off + half / 2, s.t + 22, heading, 12.5, INK, anchor="middle", weight="700")
        for t in _ticks(ymin, ymax, 4):
            y = y0 - t * scale
            s.line(x_off, y, x_off + half, y, GRID, 1)
            s.text(x_off - 6, y + 3.5, _fmt(t, 0) + "%", 9.5, MUTED, anchor="end")
        if ymin < 0 < ymax:
            s.line(x_off, y0, x_off + half, y0, "#aeb4be", 1.3)
        for i, r in enumerate(rows):
            cx = x_off + half / 5 * (i + 0.5)
            v = r["ret_ann_pct"]
            h = v * scale
            s.rect(cx - bw / 2, min(y0, y0 - h), bw, abs(h), SEQ[i], rx=2)
            s.text(cx, y0 - h + (-7 if h >= 0 else 15), _fmt(v, 1), 11, INK, anchor="middle", weight="600")
            s.text(cx, s.y1 + 15, f"Q{r['q']}", 11, INK, anchor="middle", weight="600")
        s.text(x_off, s.y1 + 34, note, 10, MUTED)

    spread_n = payload["sorts"]["naive"]["spread_ret_ann_pct"]
    spread_s = payload["sorts"]["sector_neutral"]["spread_ret_ann_pct"]
    panel(neu, s.l, "Sector-neutral (the honest view)",
          f"Q5-Q1 spread {spread_s:+.1f}%/yr, t={payload['sorts']['sector_neutral']['spread_t']:+.1f} — indistinguishable from zero")
    panel(naive, s.l + half + 66, "As published (what a headline reports)",
          f"Q5-Q1 spread {spread_n:+.1f}%/yr, t={payload['sorts']['naive']['spread_t']:+.1f} — same portfolios, same maths")
    return s.done()


def chart_year_gap(payload: dict) -> str | None:
    """The money chart: naive vs sector-neutral spread, by year."""
    by = payload["by_year"]
    if not by["years"]:
        return None
    years = by["years"]
    nv, sn = by["naive"], by["sector_neutral"]
    s = SVG(760, 420)
    s.title(
        "One year carries the whole ESG debate — and it is a sector story",
        "Annualised Q5-minus-Q1 spread. In 2022 the naive spread was the worst of the sample; "
        "sector-neutral, it was slightly positive.",
        "Where the headline comes from",
    )
    allv = [v for v in nv + sn if v is not None]
    lo, hi = min(allv + [0]), max(allv + [0])
    s.scale(0, len(years) - 1, lo, hi)
    s.grid_y(_ticks(lo, hi, 5), lambda v: _fmt(v, 0) + "%")
    s.zero()
    s.frame()
    for i, y in enumerate(years):
        s.X(i)
    slot = s.pw / len(years)
    bw = slot * 0.30
    for i, y in enumerate(years):
        cx = s.x0 + slot * (i + 0.5)
        for off, v, col in ((-bw * 0.62, nv[i], "#8c9bab"), (bw * 0.62, sn[i], ACCENT)):
            if v is None:
                continue
            y0, y1 = s.Y(0), s.Y(v)
            s.rect(cx + off - bw / 2, min(y0, y1), bw, abs(y1 - y0), col, rx=1.5)
        s.text(cx, s.y1 + 17, str(y), 11, INK, anchor="middle", weight="500")
    worst = int(np.argmin([v if v is not None else 9e9 for v in nv]))
    wx = s.x0 + slot * (worst + 1)
    s.rect(wx - slot / 2 + 2, s.t, slot - 4, s.ph, "#b4453c", opacity=0.055)
    s.text(wx, s.t + 16, f"{years[worst]}: naive {nv[worst]:+.1f}%  vs  neutral {sn[worst]:+.1f}%",
           11, WARN, anchor="middle", weight="700")
    for i, v in enumerate(nv):
        if v is not None:
            s.text(s.x0 + slot * (i + 0.5) - bw * 0.62, s.Y(v) + (-8 if v >= 0 else 16), _fmt(v, 0), 9, MUTED, anchor="middle")
    s.text(s.x1, s.t + 4, "■ as published", 10.5, MUTED, anchor="end")
    s.text(s.x1, s.t + 18, "■ sector-neutral", 10.5, ACCENT, anchor="end")
    s.text(s.l - 8, s.h - 16,
           "Q5-Q1 spread per year, equal-weighted monthly rebalance. 2016 & 2017 partly shown for continuity.",
           10.5, MUTED)
    return s.done()


def chart_risk_profile(payload: dict) -> str | None:
    """Vol and downside capture falling monotonically across quintiles."""
    rows = payload["risk"]["rows"]
    s = SVG(760, 400)
    s.title(
        "What the score does move: risk",
        "Annualised volatility and downside capture by ESG quintile. "
        "Downside capture = return in months the market fell, as a % of the market's fall.",
        "The finding that survives every control",
    )
    xs = list(range(5))
    vol = [r["vol_ann_pct"] for r in rows]
    dn = [r["downside_capture_pct"] for r in rows]
    half = (s.w - 130) / 2

    def one(vals, x_off, head, ymin, ymax, unit, fmtnd=1):
        s.text(x_off + half / 2, s.t + 22, head, 12.5, INK, anchor="middle", weight="700")
        top, bot = s.t + 42, s.y1 - 26
        sc = (bot - top) / (ymax - ymin)
        for t in _ticks(ymin, ymax, 4):
            y = bot - (t - ymin) * sc
            s.line(x_off, y, x_off + half, y, GRID, 1)
            s.text(x_off - 6, y + 3.5, _fmt(t, fmtnd) + unit, 9.5, MUTED, anchor="end")
        pts = [(x_off + half / 5 * (i + 0.5), bot - (v - ymin) * sc) for i, v in enumerate(vals)]
        s.path([(a, b) for a, b in pts], ACCENT, 2.6)
        for (a, b), v in zip(pts, vals):
            s.dot(a, b, ACCENT, 4)
            s.text(a, b - 12, _fmt(v, fmtnd) + unit, 10.5, INK, anchor="middle", weight="600")
        for i, (a, _) in enumerate(pts):
            s.text(a, s.y1 - 4, f"Q{i+1}", 11, INK, anchor="middle", weight="600")

    one(vol, s.l, "Annualised volatility", min(vol) - 2, max(vol) + 1.5, "%")
    one([v if v is not None else 100 for v in dn], s.l + half + 66, "Downside capture",
        min([v for v in dn if v] + [100]) - 12, max([v for v in dn if v] + [100]) + 8, "%", 0)
    s.text(s.l - 8, s.h - 16,
           f"Q1 -> Q5: vol {vol[0] - vol[-1]:+.1f} pts lower for the best-rated, downside capture "
           f"{(dn[-1] or 100) - (dn[0] or 100):+.0f} pts. Monotone in both.", 10.5, MUTED)
    return s.done()


def chart_cum(payload: dict) -> str | None:
    """Growth of 100 in each quintile, naive."""
    cu = payload["sorts"]["naive"]["cumulative"]
    if not cu.get("1"):
        return None
    s = SVG(760, 400)
    s.title("Growth of 100, top vs bottom ESG quintile",
            "Monthly rebalanced, equal weighted, no costs. The two lines end within a few points of each other.",
            "Cumulative")
    allv, alld = [], None
    d0 = cu["1"]["dates"]
    for q in ("1", "5"):
        allv += cu[q]["values"]
    lo, hi = min(allv), max(allv)
    n = len(d0)
    s.scale(0, n - 1, lo * 0.96, hi * 1.03)
    s.grid_y(_ticks(lo, hi, 5), lambda v: f"{v:.0f}")
    s.frame()
    for i, d in enumerate(d0):
        if d.endswith("-01-31") or i == 0:
            pass
    # year gridlines
    yrs = {}
    for i, d in enumerate(d0):
        yrs.setdefault(d[:4], i)
    for yr, i in yrs.items():
        if yr == d0[0][:4]:
            continue
        x = s.X(i)
        s.line(x, s.t, x, s.y1, GRID, 1)
        s.text(x, s.y1 + 16, yr, 10, MUTED, anchor="middle")
    s.path([(s.X(i), s.Y(v)) for i, v in enumerate(cu["5"]["values"])], ACCENT, 2.4, fill=ACCENT)
    s.path([(s.X(i), s.Y(v)) for i, v in enumerate(cu["1"]["values"])], "#8c9bab", 2.4)
    s.text(s.x1, s.Y(cu["5"]["values"][-1]) - 9, f"Q5 {cu['5']['values'][-1]:.0f}", 11, ACCENT, anchor="end", weight="700")
    s.text(s.x1, s.Y(cu["1"]["values"][-1]) + 16, f"Q1 {cu['1']['values'][-1]:.0f}", 11, MUTED, anchor="end", weight="700")
    s.text(s.l - 8, s.h - 16, "Both series start at 100 in Jan 2016. Source: demo panel (synthetic).", 10.5, MUTED)
    return s.done()


def chart_drawdown(payload: dict) -> str | None:
    dd = payload["risk"]["drawdown_series"]
    s = SVG(760, 380)
    s.title("Drawdown: the ESG ranking is a ranking of pain, not of gain",
           "% below the running peak, equal-weighted quintile portfolios. Shallower = better.",
           "Risk, over time")
    q5 = dd["5"]
    if not q5["dates"]:
        return None
    n = len(q5["dates"])
    lo = min(min(dd[str(q)]["values"]) for q in dd)
    s.scale(0, n - 1, lo * 1.08, 1)
    s.grid_y(_ticks(lo * 1.08, 0, 5), lambda v: f"{v:.0f}%")
    s.frame()
    yrs: dict[str, int] = {}
    for i, d in enumerate(q5["dates"]):
        yrs.setdefault(d[:4], i)
    for yr, i in yrs.items():
        if i == 0:
            continue
        x = s.X(i)
        s.line(x, s.t, x, s.y1, GRID, 1)
        s.text(x, s.y1 + 16, yr, 10, MUTED, anchor="middle")
    for q in ("1", "2", "3", "4"):
        s.path([(s.X(i), s.Y(v)) for i, v in enumerate(dd[q]["values"])], SEQ[int(q)], 1.5, opacity=0.85)
    s.path([(s.X(i), s.Y(v)) for i, v in enumerate(dd["5"]["values"])], ACCENT, 2.8)
    s.text(s.l - 8, s.h - 16,
           "Q5 worst "
           + f"{min(dd['5']['values']):.1f}%  vs  Q1 worst {min(dd['1']['values']):.1f}%.",
           10.5, MUTED)
    s.text(s.x1, s.t + 4, "── Q5 (highest ESG)", 10.5, ACCENT, anchor="end", weight="700")
    s.text(s.x1, s.t + 18, "── Q1 (lowest ESG)", 10.5, SEQ[0], anchor="end")
    return s.done()


def chart_attribution(payload: dict) -> str | None:
    a = payload.get("attribution") or {}
    rows = a.get("rows") or []
    if not rows:
        return None
    rows = [r for r in rows if abs(r["contribution_ann_pct"]) > 0.05]
    s = SVG(760, 430)
    s.title(
        f"Why the {a['year']} spread was {a['raw_spread_ann_pct']:+.1f}%: it is a sector bet",
        f"Decomposition of the Q5-minus-Q1 return. Left bar = holding different sectors "
        f"({a['total_mix_effect_ann_pct']:+.1f} pts). Right bar = picking within a sector "
        f"({a['total_selection_ann_pct']:+.1f} pts).",
        "Attribution",
    )
    rows = sorted(rows, key=lambda r: r["contribution_ann_pct"])
    n = len(rows)
    rh = (s.ph - 6) / max(n, 1)
    vals = [r["mix_ann_pct"] for r in rows] + [r["selection_ann_pct"] for r in rows]
    lo, hi = min(vals + [0]), max(vals + [0])
    pad = (hi - lo) * 0.10 or 1
    lo, hi = lo - pad, hi + pad
    label_w = 168
    plot_x0, plot_x1 = s.l + label_w, s.x1
    sc = (plot_x1 - plot_x0) / (hi - lo)
    zx = plot_x0 - lo * sc
    s.line(zx, s.t + 30, zx, s.y1, "#aeb4be", 1.2)
    for t in _ticks(lo, hi, 5):
        x = plot_x0 + t * sc
        s.line(x, s.t + 30, x, s.y1, GRID, 1)
        s.text(x, s.y1 + 15, _fmt(t, 0), 9.5, MUTED, anchor="middle")
    for i, r in enumerate(rows):
        y = s.t + 38 + i * rh
        s.text(plot_x0 - 8, y + rh * 0.62, r["sector"], 10.5, INK, anchor="end")
        for j, (v, col) in enumerate([(r["mix_ann_pct"], WARN), (r["selection_ann_pct"], "#5f8fb3")]):
            h = rh * 0.34
            yy = y + rh * 0.14 + j * (h + 2)
            x = plot_x0 + v * sc
            s.rect(min(zx, x), yy, abs(x - zx), h, col, rx=1)
            s.text(x + (4 if v >= 0 else -4), yy + h - 1.5, _fmt(v, 1), 9, MUTED if j else INK,
                   anchor="start" if v >= 0 else "end", weight=None if j else "600")
    s.text(s.l - 8, s.y1 + 34,
           f"■ sector mix (what each book holds)   ■ within-sector selection (stock-picking)   "
           f"both in %/yr contribution to the spread. Gap vs the raw spread: "
           f"{a.get('reconciliation_gap_ann_pct', 0):+.2f} pts (weights drift monthly).",
           10, MUTED)
    return s.done()


def chart_sector_mix(payload: dict, key: str = "sector_bias") -> str | None:
    """Overweight / underweight of each sector in the top vs bottom quintile.

    A plain "share of quintile" chart is unreadable, because every bar sums to
    100%. What matters is the *difference* from the sector's share of the
    universe - that is the bet the screen is actually taking.
    """
    sb = payload.get(key)
    if not sb:
        return None
    # recompute shares vs universe share straight from the payload's mix table
    secs = sb["sectors"]
    c5 = sb["mix_pct"]["5"]
    c1 = sb["mix_pct"]["1"]
    tot = [sb["mix_pct"][str(q)] for q in range(1, 6)]
    uni = [sum(t[i] for t in tot) / 5.0 for i in range(len(secs))]
    over5 = [c5[i] - uni[i] for i in range(len(secs))]
    over1 = [c1[i] - uni[i] for i in range(len(secs))]
    order = sorted(range(len(secs)), key=lambda i: over5[i] - over1[i])
    secs = [secs[i] for i in order]
    over5 = [over5[i] for i in order]
    over1 = [over1[i] for i in order]

    yr = sb.get("year", "latest year")
    s = SVG(760, 64 if len(secs) == 0 else 44 + 27 * len(secs) + 46)
    s.title("What the screen is really betting on",
            f"Over/under-weight of each sector in the extreme ESG quintiles vs the universe, {yr}. "
            "Read one bar: if it is long, the screen is long that sector.",
            "Sector bias")
    rh = 27.0
    top = s.t + 16
    label_w = 176
    x0, x1 = s.l + label_w, s.x1 - 66
    hi = max(4.0, max(abs(v) for v in over5 + over1) * 1.15)
    sc = (x1 - x0) / 2 / hi
    zx = (x0 + x1) / 2
    s.line(zx, top - 6, zx, top + rh * len(secs), "#aeb4be", 1.2)
    for t in (-hi / 2, -hi / 4, 0, hi / 4, hi / 2):
        x = zx + t * sc
        s.line(x, top - 6, x, top + rh * len(secs), GRID, 1)
        s.text(x, top + rh * len(secs) + 14, f"{t:+.0f}%", 9.5, MUTED, anchor="middle")
    for i, sec in enumerate(secs):
        y = top + i * rh
        s.text(x0 - 8, y + rh * 0.6, sec, 10.5, INK, anchor="end")
        for j, (v, col) in enumerate([(over5[i], ACCENT), (over1[i], WARN)]):
            h = rh * 0.32
            yy = y + 3 + j * (h + 2)
            x = zx + v * sc
            s.rect(min(zx, x), yy, abs(x - zx), h, col, rx=1)
            s.text(x + (4 if v >= 0 else -4), yy + h - 1, f"{v:+.1f}", 9, INK if j == 0 else MUTED,
                   anchor="start" if v >= 0 else "end", weight="600" if j == 0 else None)
    s.rect(x0 - 140, s.h - 20, 9, 9, ACCENT, rx=1)
    s.text(x0 - 127, s.h - 12, "Q5 (highest ESG)", 10, INK)
    s.rect(x0 - 30, s.h - 20, 9, 9, WARN, rx=1)
    s.text(x0 - 17, s.h - 12, "Q1 (lowest ESG)", 10, INK)
    s.text(s.x1, s.h - 12, "zero = same as the universe", 10, MUTED, anchor="end")
    return s.done()


def chart_sector_mix_all(payload: dict) -> str | None:
    return chart_sector_mix(payload, key="sector_bias_all")


def chart_forest(payload: dict) -> str | None:
    """Coefficient plot across the four specifications."""
    specs = payload["regressions"]["specs"]
    s = SVG(760, 380)
    s.title(
        "The ESG 'return premium' is an artefact of what you control for",
        "Coefficient on the ESG score (bp per month per 1 SD of score), 95% intervals. "
        "Clustered by firm, year fixed effects.",
        "Robustness",
    )
    rows = []
    for sp in specs:
        for c in sp["result"]["coef"]:
            if c["name"] == "z_neu":
                rows.append((sp["label"], c, sp["result"]["n"]))
    if not rows:
        return None
    vals = [c["bp_per_month"] for _, c, _ in rows]
    lo = min([c["ci_lo_bp"] for _, c, _ in rows] + vals)
    hi = max([c["ci_hi_bp"] for _, c, _ in rows] + vals)
    pad = (hi - lo) * 0.12 or 5
    lo, hi = lo - pad, hi + pad
    x0, x1 = s.l + 210, s.x1 - 30
    sc = (x1 - x0) / (hi - lo)
    zx = x0 - lo * sc
    s.line(zx, s.t + 22, zx, s.y1 - 26, WARN, 1.3, dash="3,3")
    s.text(zx, s.t + 14, "zero effect", 10, WARN, anchor="middle")
    for t in _ticks(lo, hi, 6):
        x = x0 + t * sc
        s.line(x, s.t + 22, x, s.y1 - 26, GRID, 1)
        s.text(x, s.y1 - 8, _fmt(t, 0), 9.5, MUTED, anchor="middle")
    rh = (s.ph - 60) / len(rows)
    for i, (lab, c, nn) in enumerate(rows):
        y = s.t + 40 + i * rh
        s.text(x0 - 10, y + 4, lab, 11, INK, anchor="end", weight="600")
        s.line(x0 + c["ci_lo_bp"] * sc, y, x0 + c["ci_hi_bp"] * sc, y, INK, 1.6)
        s.dot(x0 + c["bp_per_month"] * sc, y, ACCENT if abs(c["t"]) >= 2 else MUTED, 5)
        s.text(x1 + 4, y + 4, f"t={c['t']:+.1f}", 10, INK if abs(c["t"]) >= 2 else MUTED,
               weight="700" if abs(c["t"]) >= 2 else None)
    s.text(s.l - 8, s.h - 16,
           "Green dot = significant at 2 standard errors. n = {:,} firm-months. "
           "The only coefficient that stays put is the one you control for least.".format(rows[0][2]),
           10.5, MUTED)
    return s.done()


CHARTS: dict[str, Callable[[dict], str | None]] = {
    "quintile_bars": chart_quintile_bars,
    "year_gap": chart_year_gap,
    "risk_profile": chart_risk_profile,
    "cumulative": chart_cum,
    "drawdown": chart_drawdown,
    "attribution": chart_attribution,
    "sector_mix": chart_sector_mix,
    "sector_mix_all": chart_sector_mix_all,
    "forest": chart_forest,
}
CHART_NAMES = list(CHARTS)


def render(name: str, payload: dict | None) -> str | None:
    if payload is None or name not in CHARTS:
        return None
    try:
        return CHARTS[name](payload)
    except Exception as exc:  # noqa: BLE001 - a broken exhibit must not kill the page
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="700" height="120"><text x="10" y="40" ' \
               f'font-family="monospace" font-size="13" fill="#b4453c">chart {name!r} failed: {esc(exc)[:180]}</text></svg>'
