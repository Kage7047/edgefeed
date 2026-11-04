"""Read-only HTTP API over the ledger, the dashboard, and Prometheus /metrics.

The collector writes; the API only reads, so either can restart without the other.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from edgefeed import __version__, report
from edgefeed.config import Settings
from edgefeed.store import Store, as_utc

STATIC = Path(__file__).parent / "static"
STALE_AFTER = timedelta(minutes=5)


def create_app(store: Store | None = None) -> FastAPI:
    app = FastAPI(title="EdgeFeed", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.store = store

    def db() -> Store:
        if app.state.store is None:
            app.state.store = Store(Settings().db_url)
        s: Store = app.state.store
        return s

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        with db().tx() as conn:
            last = db().recent_scans(conn, 1)
        ts = as_utc(last[0]["started_at"]) if last else None
        fresh = bool(ts and datetime.now(UTC) - ts < STALE_AFTER)
        if not fresh:
            raise HTTPException(503, detail={"status": "stale", "last_scan": ts.isoformat() if ts else None})
        return {"status": "ok", "last_scan": ts.isoformat() if ts else None, "version": __version__}

    @app.get("/metrics")
    def prom() -> PlainTextResponse:
        return PlainTextResponse(generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/api/pairs")
    def pairs() -> list[dict[str, Any]]:
        with db().tx() as conn:
            return db().latest_quotes(conn)

    @app.get("/api/pairs/{pair_key:path}/series")
    def series(pair_key: str, hours: float = Query(6, gt=0, le=24 * 30)) -> list[dict[str, Any]]:
        since = datetime.now(UTC) - timedelta(hours=hours)
        with db().tx() as conn:
            return db().series(conn, pair_key, since)

    @app.get("/api/opportunities")
    def opportunities(
        status: str = Query("all", pattern="^(all|open)$"), limit: int = Query(200, ge=1, le=5000)
    ) -> list[dict[str, Any]]:
        with db().tx() as conn:
            return db().opportunities(conn, open_only=status == "open", limit=limit)

    @app.get("/api/signals")
    def signals(limit: int = Query(100, ge=1, le=2000)) -> list[dict[str, Any]]:
        with db().tx() as conn:
            return db().recent_signals(conn, limit)

    @app.get("/api/scans")
    def scans(limit: int = Query(120, ge=1, le=5000)) -> list[dict[str, Any]]:
        with db().tx() as conn:
            return db().recent_scans(conn, limit)

    @app.get("/api/events")
    def events(limit: int = Query(100, ge=1, le=2000)) -> list[dict[str, Any]]:
        with db().tx() as conn:
            return db().recent_events(conn, limit)

    @app.get("/api/report")
    def get_report(days: int = Query(7, ge=1, le=90)) -> dict[str, Any]:
        return report.build(db(), days=days)

    if (STATIC / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(STATIC / "index.html")

    return app


app = create_app()
