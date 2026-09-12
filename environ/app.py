"""
app.py — FastAPI server.

Layout
------
  GET  /                     the dashboard (static HTML, no build step, no CDN)
  GET  /api/health           readiness + which panel is loaded
  GET  /api/meta             universe, definitions, data provenance
  GET  /api/analysis         the whole payload (one call; ~60 KB of JSON)
  GET  /api/section/{name}   one slice of it, for the deck exporter
  GET  /api/firms            firm-level table, as JSON
  GET  /data/panel.csv       the raw panel, download
  POST /api/upload           your own panel.csv -> same analysis, no re-deploy

Everything is computed at start-up and cached; a request never recomputes
unless you upload a new panel. That is the whole performance story and it is
worth being able to say: ~2 s of maths on boot, then instant.
"""

from __future__ import annotations

import io
import os
from functools import lru_cache
from typing import Any

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from environ import stats as S
from environ import config as C

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
PANEL = os.path.join(HERE, "data", "panel.csv")
FIRMS = os.path.join(HERE, "data", "firms.csv")


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------
class State:
    """Mutable holder for the active analysis. Swapped on upload."""

    payload: dict[str, Any] | None = None
    firms: pd.DataFrame | None = None
    demo_firms: pd.DataFrame | None = None   # kept aside so an upload cannot destroy it
    source: str = "demo (synthetic panel)"
    build_ms: float = 0.0

    @classmethod
    def build(cls, panel: pd.DataFrame, firms: pd.DataFrame | None, source: str) -> None:
        import time

        t0 = time.perf_counter()
        p = S.prep(panel, source=source)
        cls.payload = S.analyse(p, firms)
        cls.payload["provenance"] = provenance(source)
        cls.payload["config_effects"] = {
            "level_ret_bp": C.EFFECTS.level_ret_bp,
            "momentum_ret_bp": C.EFFECTS.momentum_ret_bp,
            "level_vol_pct": C.EFFECTS.level_vol_pct,
            "note": (
                "These are the ASSUMPTIONS used to build the demo panel (environ/config.py). "
                "They are not results. If you load your own data this block still describes the "
                "demo, so the app labels the demo explicitly everywhere."
            ),
            "is_demo": source.startswith("demo"),
        }
        cls.firms = firms
        cls.source = source
        cls.build_ms = (time.perf_counter() - t0) * 1000.0


def provenance(source: str) -> dict[str, Any]:
    return {
        "source": source,
        "is_synthetic": source.startswith("demo"),
        "how_to_get_real": (
            "python -m environ.data.build_real_panel   # public ESG-Book ratings + price history, "
            "writes the same two CSVs; then restart the app."
        ),
        "swap_in_your_own": "POST /api/upload with a CSV following the column contract in data/README.md",
        "generator": "environ/data/generate_data.py (seed 20240912, deterministic)",
    }


@lru_cache(maxsize=1)
def _boot() -> None:
    if not os.path.exists(PANEL):
        from environ.data.generate_data import build_panel

        panel, firms = build_panel()
        os.makedirs(os.path.dirname(PANEL), exist_ok=True)
        panel.to_csv(PANEL, index=False)
        firms.to_csv(FIRMS, index=False)
    panel = pd.read_csv(PANEL)
    firms = pd.read_csv(FIRMS) if os.path.exists(FIRMS) else None
    State.demo_firms = firms
    State.build(panel, firms, "demo (synthetic panel)")


# FastAPI owns /docs (Swagger) and /redoc by default. That collides with the
# written memo we serve at /docs, so the interactive API reference moves to
# /api/docs and /docs is ours.
app = FastAPI(
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/openapi.json",
    title="environ — does a high ESG score pay?",
    version="1.0.0",
    description="""
Quintile-sort analysis of ESG ratings vs stock returns and risk.

The whole app is generated from two CSVs (`data/panel.csv`, `data/firms.csv`), and the
demo panel is **synthetic** - see `/api/meta` for provenance and `data/README.md` for
the column contract.

* `/` - the dashboard (7 tabs, interactive, no CDN, no build step)
* `/docs` - the 2-page written memo
* `/deck` - the 12-slide presentation
* `/api/upload` - drop in real data; every number and every sentence rebuilds
""",
    openapi_tags=[
        {"name": "analysis", "description": "the numbers behind every exhibit"},
        {"name": "exhibits", "description": "charts as standalone SVG"},
        {"name": "data", "description": "the panel itself, in and out"},
    ],
)


@app.on_event("startup")
def _startup() -> None:
    _boot()


# ---------------------------------------------------------------------------
@app.get("/api/health", tags=["analysis"])
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "source": State.source,
        "built_in_ms": round(State.build_ms, 1),
        "rows": State.payload["universe"]["n_obs"] if State.payload else None,
    }


@app.get("/api/analysis", tags=["analysis"])
def analysis() -> JSONResponse:
    if State.payload is None:
        raise HTTPException(503, "analysis not built yet")
    return JSONResponse(State.payload)


@app.get("/api/section/{name}", tags=["analysis"])
def section(name: str) -> JSONResponse:
    if State.payload is None or name not in State.payload:
        raise HTTPException(404, f"no section {name!r}. try: {sorted(State.payload or {})}")
    return JSONResponse({name: State.payload[name]})


@app.get("/api/meta", tags=["analysis"])
def meta() -> dict[str, Any]:
    return {
        "universe": State.payload["universe"] if State.payload else {},
        "provenance": provenance(State.source),
        "config_effects": State.payload.get("config_effects", {}),
        "definitions": S.DEFINITIONS,
        "sections": sorted(State.payload or {}),
    }


@app.get("/api/firms", tags=["data"])
def firms() -> JSONResponse:
    if State.firms is None:
        raise HTTPException(404, "no firm-level file loaded")
    return JSONResponse(State.firms.to_dict(orient="records"))


@app.post("/api/upload", tags=["data"])
async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    """Accept a firm-month panel CSV and rebuild the whole analysis from it.

    This is the feature that makes the project not-a-toy: the demo panel is a
    stand-in, and anyone with real data can drop it in without touching code.
    """
    raw = await file.read()
    if len(raw) > 80 * 1024 * 1024:
        raise HTTPException(413, "file too large (80 MB cap)")
    try:
        panel = pd.read_csv(io.BytesIO(raw))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"could not parse CSV: {exc}") from exc

    # A firm-level table is only usable if it came with the upload (operating
    # columns live there). Otherwise fall back to the demo one and SAY so,
    # rather than silently pairing someone's real returns with synthetic margins.
    has_own_firms = "revenue_growth_pct" in panel.columns
    try:
        State.build(panel, State.firms if has_own_firms else State.demo_firms,
                    source=f"uploaded: {file.filename}")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"analysis failed on that file: {type(exc).__name__}: {exc}") from exc
    warns = list(State.payload["universe"]["warnings"])
    if not has_own_firms:
        warns.append(
            "No firm-level operating columns in this upload, so the operating-characteristics table "
            "is showing the DEMO firms file and does not correspond to your panel. Add firms.csv "
            "columns (revenue_growth_pct, ebitda_margin_pct, …) to make it meaningful."
        )
    return {
        "ok": True,
        "rows": len(panel),
        "firms": State.payload["universe"]["n_firms"],
        "months": State.payload["universe"]["n_months"],
        "warnings": warns,
        "build_ms": round(State.build_ms, 1),
    }


@app.get("/data/panel.csv", tags=["data"])
def download_panel() -> FileResponse:
    if not os.path.exists(PANEL):
        raise HTTPException(404, "no panel on disk")
    return FileResponse(PANEL, media_type="text/csv", filename="panel.csv")


@app.get("/data/firms.csv", tags=["data"])
def download_firms() -> FileResponse:
    if not os.path.exists(FIRMS):
        raise HTTPException(404, "no firms file on disk")
    return FileResponse(FIRMS, media_type="text/csv", filename="firms.csv")


@app.get("/api/svg/{name}", tags=["exhibits"])
def svg(name: str) -> HTMLResponse:
    """Server-rendered SVG, used by the deck exporter. Same maths, static art."""
    from environ.charts import render

    out = render(name, State.payload)
    if out is None:
        raise HTTPException(404, f"no chart named {name!r}. try: {sorted(render_names())}")
    return HTMLResponse(out, media_type="image/svg+xml")


def render_names() -> list[str]:
    from environ.charts import CHART_NAMES

    return CHART_NAMES


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(os.path.join(WEB, "index.html"))


@app.get("/docs", include_in_schema=False)
@app.get("/docs/", include_in_schema=False)
def docs() -> FileResponse:
    """The written memo, served next to the app so one link is enough."""
    memo = os.path.join(HERE, "docs", "memo.html")
    if os.path.exists(memo):
        return FileResponse(memo, media_type="text/html")
    raise HTTPException(404, "run: python -m environ.scripts.build_docs")


@app.get("/deck", include_in_schema=False)
def deck() -> FileResponse:
    d = os.path.join(HERE, "docs", "deck.html")
    if os.path.exists(d):
        return FileResponse(d, media_type="text/html")
    raise HTTPException(404, "run: python -m environ.scripts.build_deck")


app.mount("/static", StaticFiles(directory=os.path.join(WEB, "static")), name="static")


def run(host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:
    """`environ` on the PATH = uvicorn environ.app:app, without the boilerplate."""
    import uvicorn

    uvicorn.run("environ.app:app", host=host, port=port, reload=reload)
