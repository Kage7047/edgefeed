"""One scan: fetch both books for every pair concurrently and price them."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from edgefeed import arb
from edgefeed.models import Book
from edgefeed.pairs import Pair
from edgefeed.venues.kalshi import KalshiClient
from edgefeed.venues.polymarket import PolymarketClient, PolyMeta


@dataclass(slots=True)
class PairResult:
    pair: Pair
    kalshi: Book | None = None
    poly: Book | None = None
    spread: Decimal | None = None  # best top-of-book net edge per contract (can be negative)
    opportunity: arb.Opportunity | None = None
    error: str | None = None


@dataclass(slots=True)
class Scan:
    started_at: datetime
    seconds: float
    results: list[PairResult] = field(default_factory=list)
    kind: str = "full"  # full | hot

    @property
    def priced(self) -> list[PairResult]:
        return [r for r in self.results if r.error is None and r.spread is not None]

    @property
    def failed(self) -> list[PairResult]:
        return [r for r in self.results if r.error is not None]


class Scanner:
    def __init__(
        self,
        kalshi: KalshiClient,
        poly: PolymarketClient,
        *,
        max_contracts: Decimal | None = None,
        kalshi_apy: Decimal = Decimal(0),
        poly_holding_apy: Decimal = Decimal(0),
    ) -> None:
        self.kalshi = kalshi
        self.poly = poly
        self.max_contracts = max_contracts
        self.kalshi_apy = kalshi_apy
        self.poly_holding_apy = poly_holding_apy

    async def scan(self, pairs: list[Pair]) -> Scan:
        """Price every pair. Requests are batched per venue, so cost grows with pairs / 100."""
        t0 = time.perf_counter()
        started = datetime.now(UTC)
        kres, pres = await asyncio.gather(
            self.kalshi.books([p.kalshi for p in pairs]),
            self.poly.metas([(p.polymarket, p.outcome) for p in pairs]),
            return_exceptions=True,
        )
        kbooks: dict[str, Book] = {} if isinstance(kres, BaseException) else kres
        pmetas: dict[tuple[str, str], PolyMeta] = {} if isinstance(pres, BaseException) else pres
        venue_err = {
            "kalshi": f"kalshi: {kres}" if isinstance(kres, BaseException) else None,
            "polymarket": f"polymarket: {pres}" if isinstance(pres, BaseException) else None,
        }
        tokens = [t for m in pmetas.values() for t in (m.yes_token, m.no_token)]
        try:
            ladders = await self.poly.ladders(list(dict.fromkeys(tokens)))
        except Exception as e:
            ladders, venue_err["polymarket"] = {}, f"polymarket books: {e}"

        out = Scan(started_at=started, seconds=0.0)
        for p in pairs:
            r = PairResult(pair=p)
            kb, pm = kbooks.get(p.kalshi), pmetas.get((p.polymarket, p.outcome))
            if venue_err["kalshi"] or venue_err["polymarket"]:
                r.error = venue_err["kalshi"] or venue_err["polymarket"]
            elif kb is None:
                r.error = f"kalshi: market {p.kalshi} not found"
            elif pm is None:
                r.error = f"polymarket: market {p.polymarket} has no outcome {p.outcome!r}"
            else:
                r.kalshi, r.poly = kb, self.poly.book_from(pm, ladders)
                r.kalshi.apy = self.kalshi_apy
                if pm.holding_rewards:
                    r.poly.apy = self.poly_holding_apy
                r.spread = arb.spread(r.kalshi, r.poly, p.relation)
                r.opportunity = arb.price_pair(
                    p.key, r.kalshi, r.poly, p.relation, now=started, max_contracts=self.max_contracts
                )
                if r.opportunity and p.rule_risk:
                    r.opportunity.warnings.append(p.rule_risk)
            out.results.append(r)
        out.seconds = time.perf_counter() - t0
        return out
