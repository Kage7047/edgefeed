"""Kalshi public REST (no key needed for reads).

The order book lists *bids only*, for YES and for NO, best price last. A YES bid at p is a NO ask
at 1 - p for the same size, so the ask ladders we need come from the opposite side's bids.
Prices are ``*_dollars`` strings and sizes ``*_fp`` fixed-point strings (renamed in 2025-26).
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from edgefeed import fees
from edgefeed.models import ONE, Book, Level, Venue, asks
from edgefeed.venues.http import VenueHTTP

BASE = "https://api.elections.kalshi.com/trade-api/v2"
BATCH = 100  # /markets?tickers=a,b,... and /markets/orderbooks?tickers=a&tickers=b
COMBO_MARKERS = ("MVE", "CROSSCATEGORY")


def parse_time(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def book_from(raw_orderbook: dict[str, Any]) -> tuple[list[Level], list[Level]]:
    """(yes_asks, no_asks) from a ``/orderbook`` response."""
    ob = raw_orderbook.get("orderbook_fp") or {}
    yes_bids = ob.get("yes_dollars") or []
    no_bids = ob.get("no_dollars") or []
    yes_asks = asks([Level(ONE - Decimal(p), Decimal(s)) for p, s in no_bids])
    no_asks = asks([Level(ONE - Decimal(p), Decimal(s)) for p, s in yes_bids])
    return yes_asks, no_asks


@dataclass(slots=True)
class KalshiMeta:
    ticker: str
    title: str
    status: str
    closes_at: datetime | None
    rules: str
    series: str
    yes_ask: Decimal | None
    no_ask: Decimal | None


def meta_from(raw_market: dict[str, Any]) -> KalshiMeta:
    m = raw_market.get("market", raw_market)
    title = f"{m.get('title') or ''} {m.get('yes_sub_title') or ''}".strip()
    rules = "\n".join(x for x in (m.get("rules_primary"), m.get("rules_secondary")) if x)
    event = m.get("event_ticker") or m.get("ticker", "")
    closes = parse_time(m.get("expected_expiration_time")) or parse_time(m.get("close_time"))

    def price(k: str) -> Decimal | None:
        v = m.get(k)
        d = Decimal(str(v)) if v not in (None, "") else None
        return d if d is not None and 0 < d < 1 else None

    return KalshiMeta(
        ticker=m.get("ticker", ""),
        title=title,
        status=m.get("status", ""),
        closes_at=closes,
        rules=rules,
        series=str(event).split("-")[0],
        yes_ask=price("yes_ask_dollars"),
        no_ask=price("no_ask_dollars"),
    )


class KalshiClient:
    venue = Venue.KALSHI

    def __init__(self, http: VenueHTTP | None = None, *, meta_ttl: float = 600.0) -> None:
        self.http = http or VenueHTTP("kalshi", BASE, rate=8.0)
        self.meta_ttl = meta_ttl
        self._meta: dict[str, tuple[float, KalshiMeta]] = {}
        self._fee_mult: dict[str, Decimal] = {}

    async def aclose(self) -> None:
        await self.http.aclose()

    async def meta(self, ticker: str) -> KalshiMeta:
        hit = self._meta.get(ticker)
        if hit and time.monotonic() - hit[0] < self.meta_ttl:
            return hit[1]
        m = meta_from(await self.http.get(f"/markets/{ticker}"))
        self._meta[ticker] = (time.monotonic(), m)
        return m

    async def fee_multiplier(self, series: str) -> Decimal:
        if series not in self._fee_mult:
            data = await self.http.get(f"/series/{series}")
            s = data.get("series", {})
            self._fee_mult[series] = Decimal(str(s.get("fee_multiplier", 1) or 1))
        return self._fee_mult[series]

    async def metas(self, tickers: list[str]) -> dict[str, KalshiMeta]:
        """Metadata for many markets: cached ones reused, the rest fetched in batches."""
        now = time.monotonic()
        stale = [t for t in dict.fromkeys(tickers) if not (h := self._meta.get(t)) or now - h[0] >= self.meta_ttl]
        for i in range(0, len(stale), BATCH):
            chunk = stale[i : i + BATCH]
            data = await self.http.get("/markets", tickers=",".join(chunk), limit=len(chunk))
            for raw in data.get("markets", []):
                m = meta_from(raw)
                self._meta[m.ticker] = (now, m)
        return {t: self._meta[t][1] for t in tickers if t in self._meta}

    async def books(self, tickers: list[str], depth: int = 32) -> dict[str, Book]:
        """Books for many markets in a handful of requests. Missing tickers are left out."""
        metas = await self.metas(tickers)
        for series in {m.series for m in metas.values()}:
            await self.fee_multiplier(series)
        ladders: dict[str, tuple[list[Level], list[Level]]] = {}
        wanted = list(metas)
        for i in range(0, len(wanted), BATCH):
            chunk = wanted[i : i + BATCH]
            params = [("tickers", t) for t in chunk] + [("depth", str(depth))]
            data = await self.http.request("GET", "/markets/orderbooks", params=params)
            for ob in data.get("orderbooks", []):
                ladders[ob.get("ticker", "")] = book_from(ob)
        return {t: self._book(metas[t], *ladders[t]) for t in wanted if t in ladders}

    def _book(self, m: KalshiMeta, yes_asks: list[Level], no_asks: list[Level]) -> Book:
        return Book(
            venue=Venue.KALSHI,
            market_id=m.ticker,
            yes_asks=yes_asks,
            no_asks=no_asks,
            fee=fees.kalshi(self._fee_mult.get(m.series, ONE)),
            title=m.title,
            closes_at=m.closes_at,
            rules=m.rules,
            min_size=ONE,
            fetched_at=datetime.now(UTC),
            extra={"status": m.status, "series": m.series},
        )

    async def book(self, ticker: str, depth: int = 32) -> Book:
        m = await self.meta(ticker)
        mult = await self.fee_multiplier(m.series)
        raw = await self.http.get(f"/markets/{ticker}/orderbook", depth=depth)
        yes_asks, no_asks = book_from(raw)
        return Book(
            venue=Venue.KALSHI,
            market_id=ticker,
            yes_asks=yes_asks,
            no_asks=no_asks,
            fee=fees.kalshi(mult),
            title=m.title,
            closes_at=m.closes_at,
            rules=m.rules,
            min_size=ONE,
            fetched_at=datetime.now(UTC),
            extra={"status": m.status, "series": m.series},
        )

    async def events(
        self, *, status: str = "open", max_pages: int = 20, page_size: int = 200
    ) -> AsyncIterator[dict[str, Any]]:
        """Open events with their markets nested; parlay combos skipped."""
        cursor: str | None = None
        for _ in range(max_pages):
            params: dict[str, Any] = {"status": status, "with_nested_markets": "true", "limit": page_size}
            if cursor:
                params["cursor"] = cursor
            data = await self.http.get("/events", **params)
            for ev in data.get("events", []):
                ev["markets"] = [
                    m for m in ev.get("markets") or [] if not any(x in m.get("ticker", "") for x in COMBO_MARKERS)
                ]
                if ev["markets"]:
                    yield ev
            cursor = data.get("cursor")
            if not cursor:
                return
