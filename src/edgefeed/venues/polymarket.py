"""Polymarket public data: Gamma for market metadata, the CLOB for order books (both no-auth).

Each binary market has two CLOB tokens (YES and NO) with separate books; the asks of each token
are the ladder for buying that side. Fee parameters come per market from Gamma's
``feeSchedule``; ``feesEnabled: false`` means no taker fee.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from edgefeed import fees
from edgefeed.models import Book, Fee, Level, Venue, asks
from edgefeed.venues.http import ClientError, VenueHTTP
from edgefeed.venues.kalshi import parse_time

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
BOOKS_BATCH = 50


def _json_list(v: Any) -> list[Any]:
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            out = json.loads(v)
        except ValueError:
            return []
        return out if isinstance(out, list) else []
    return []


@dataclass(slots=True)
class PolyMeta:
    market_id: str
    question: str
    yes_token: str
    no_token: str
    closes_at: datetime | None
    rules: str
    fee: Fee
    min_size: Decimal
    neg_risk: bool
    active: bool
    category: str
    holding_rewards: bool = False


def meta_from(m: dict[str, Any], outcome: str = "Yes") -> PolyMeta | None:
    """None unless the market has exactly two outcomes, both with CLOB tokens, one named ``outcome``.

    ``outcome`` becomes our YES side: "Yes" for a Yes/No market, a team name for a moneyline.
    """
    outcomes = [str(o).strip().lower() for o in _json_list(m.get("outcomes"))]
    tokens = [str(t) for t in _json_list(m.get("clobTokenIds"))]
    if len(outcomes) != 2 or len(tokens) != 2 or outcome.strip().lower() not in outcomes:
        return None
    yi = outcomes.index(outcome.strip().lower())
    category = str(m.get("feeType") or m.get("category") or "").replace("_fees", "")
    sched = m.get("feeSchedule") or {}
    if m.get("feesEnabled") is False:
        fee = fees.polymarket(0)
    elif sched.get("rate") is not None:
        fee = fees.polymarket(sched["rate"], int(sched.get("exponent", 1) or 1))
    else:
        fee = fees.polymarket(None, category=category)
    return PolyMeta(
        market_id=str(m.get("id", "")),
        question=str(m.get("question") or ""),
        yes_token=tokens[yi],
        no_token=tokens[1 - yi],
        closes_at=parse_time(m.get("endDate")),
        rules=str(m.get("description") or ""),
        fee=fee,
        min_size=Decimal(str(m.get("orderMinSize") or 1)),
        neg_risk=bool(m.get("negRisk")),
        active=bool(m.get("active")) and not bool(m.get("closed")),
        category=category,
        holding_rewards=bool(m.get("holdingRewardsEnabled")),
    )


def result_from(m: dict[str, Any], outcome: str = "Yes") -> Decimal | None:
    """What one share of ``outcome`` paid out, once the market is resolved; None while it is open."""
    if not m.get("closed") or str(m.get("umaResolutionStatus") or "").lower() != "resolved":
        return None
    outcomes = [str(o).strip().lower() for o in _json_list(m.get("outcomes"))]
    prices = _json_list(m.get("outcomePrices"))
    if outcome.strip().lower() not in outcomes or len(prices) != len(outcomes):
        return None
    try:
        return Decimal(str(prices[outcomes.index(outcome.strip().lower())]))
    except ArithmeticError:
        return None


def ladder_from(raw_book: dict[str, Any]) -> list[Level]:
    return asks([Level(Decimal(str(a["price"])), Decimal(str(a["size"]))) for a in raw_book.get("asks") or []])


class PolymarketClient:
    venue = Venue.POLYMARKET

    def __init__(
        self, gamma: VenueHTTP | None = None, clob: VenueHTTP | None = None, *, meta_ttl: float = 600.0
    ) -> None:
        self.gamma = gamma or VenueHTTP("polymarket", GAMMA, rate=6.0)
        self.clob = clob or VenueHTTP("polymarket", CLOB, rate=10.0)
        self.meta_ttl = meta_ttl
        self._meta: dict[tuple[str, str], tuple[float, PolyMeta]] = {}

    async def aclose(self) -> None:
        await self.gamma.aclose()
        await self.clob.aclose()

    async def meta(self, market_id: str, outcome: str = "Yes") -> PolyMeta:
        hit = self._meta.get((market_id, outcome))
        if hit and time.monotonic() - hit[0] < self.meta_ttl:
            return hit[1]
        raw = await self.gamma.get(f"/markets/{market_id}")
        m = meta_from(raw[0] if isinstance(raw, list) else raw, outcome)
        if m is None:
            raise ValueError(f"polymarket {market_id} has no two-outcome book with outcome {outcome!r}")
        self._meta[(market_id, outcome)] = (time.monotonic(), m)
        return m

    async def metas(self, wanted: list[tuple[str, str]]) -> dict[tuple[str, str], PolyMeta]:
        """Metadata for many (market_id, outcome) pairs, fetched ``?id=a&id=b`` in batches."""
        now = time.monotonic()
        stale_ids = list(
            dict.fromkeys(
                mid for mid, oc in wanted if not (h := self._meta.get((mid, oc))) or now - h[0] >= self.meta_ttl
            )
        )
        raw_by_id: dict[str, dict[str, Any]] = {}
        for i in range(0, len(stale_ids), BOOKS_BATCH):
            chunk = stale_ids[i : i + BOOKS_BATCH]
            params = [("id", x) for x in chunk] + [("limit", str(len(chunk)))]
            for raw in await self.gamma.request("GET", "/markets", params=params) or []:
                raw_by_id[str(raw.get("id"))] = raw
        for mid, oc in wanted:
            if mid in raw_by_id and (m := meta_from(raw_by_id[mid], oc)) is not None:
                self._meta[(mid, oc)] = (now, m)
        return {k: self._meta[k][1] for k in wanted if k in self._meta}

    async def event_by_slug(self, slug: str) -> dict[str, Any] | None:
        data = await self.gamma.get("/events", slug=slug)
        return data[0] if data else None

    async def ladders(self, tokens: list[str]) -> dict[str, list[Level]]:
        """Ask ladders for many tokens, batched through ``POST /books``."""
        out: dict[str, list[Level]] = {}
        for i in range(0, len(tokens), BOOKS_BATCH):
            chunk = tokens[i : i + BOOKS_BATCH]
            data = await self.clob.post("/books", [{"token_id": t} for t in chunk])
            for b in data or []:
                out[str(b.get("asset_id"))] = ladder_from(b)
        return out

    def book_from(self, m: PolyMeta, ladders: dict[str, list[Level]]) -> Book:
        return Book(
            venue=Venue.POLYMARKET,
            market_id=m.market_id,
            yes_asks=ladders.get(m.yes_token, []),
            no_asks=ladders.get(m.no_token, []),
            fee=m.fee,
            title=m.question,
            closes_at=m.closes_at,
            rules=m.rules,
            min_size=m.min_size,
            fetched_at=datetime.now(UTC),
            extra={
                "yes_token": m.yes_token,
                "neg_risk": str(m.neg_risk).lower(),
                "category": m.category,
                "holding_rewards": str(m.holding_rewards).lower(),
            },
        )

    async def result(self, market_id: str, outcome: str = "Yes") -> Decimal | None:
        raw = await self.gamma.get(f"/markets/{market_id}")
        return result_from(raw[0] if isinstance(raw, list) else raw, outcome)

    async def book(self, market_id: str, outcome: str = "Yes") -> Book:
        m = await self.meta(market_id, outcome)
        return self.book_from(m, await self.ladders([m.yes_token, m.no_token]))

    async def events(self, *, max_pages: int = 20, page_size: int = 100) -> AsyncIterator[dict[str, Any]]:
        """Open events, most liquid first, with their markets. Gamma refuses offsets past ~2000."""
        for page in range(max_pages):
            try:
                data = await self._events_page(page, page_size)
            except ClientError:
                return
            if not data:
                return
            for ev in data:
                yield ev

    async def _events_page(self, page: int, page_size: int) -> Any:
        return await self.gamma.get(
            "/events",
            closed="false",
            active="true",
            limit=page_size,
            offset=page * page_size,
            order="volume",
            ascending="false",
        )
