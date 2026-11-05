"""Paper trading: would we really have got the edge, and did it pay out?

A scan sees an edge on books that are already a moment old. ``Paper.take`` re-fetches both books
straight away, prices a fixed size on them, and records what a fast bot would have filled (or that
the edge was gone: a "missed" trade). ``Paper.settle`` later asks both venues how each market
resolved and books the real payout, so settlement-rule differences show up as money, not prose.

Nothing here places an order. It is a measurement of execution and settlement risk.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from edgefeed import arb
from edgefeed.config import Settings
from edgefeed.models import ONE, ZERO
from edgefeed.scanner import PairResult, Scanner
from edgefeed.store import Store
from edgefeed.venues.kalshi import KalshiClient
from edgefeed.venues.polymarket import PolymarketClient

log = logging.getLogger("edgefeed.paper")


def payout(legs: list[dict[str, Any]], kalshi_yes: Decimal, poly_yes: Decimal) -> Decimal:
    """What the legs pay at settlement, given what one YES share of each market paid."""
    total = ZERO
    for leg in legs:
        yes = kalshi_yes if leg["venue"] == "kalshi" else poly_yes
        pays = yes if leg["side"] == "yes" else ONE - yes
        total += Decimal(str(leg["contracts"])) * pays
    return total


class Paper:
    def __init__(
        self,
        store: Store,
        scanner: Scanner,
        kalshi: KalshiClient,
        poly: PolymarketClient,
        settings: Settings,
    ) -> None:
        self.store = store
        self.scanner = scanner
        self.kalshi = kalshi
        self.poly = poly
        self.s = settings

    async def take(self, opp_id: int, seen: PairResult) -> dict[str, Any] | None:
        """Re-check a freshly opened edge and paper-fill it. None when it is out of scope."""
        o = seen.opportunity
        if o is None or o.lock_days > self.s.paper_max_lock_days:
            return None
        t0 = time.perf_counter()
        fresh = (await self.scanner.scan([seen.pair])).results[0]
        ms = (time.perf_counter() - t0) * 1000
        fill: arb.Opportunity | None = None
        if fresh.kalshi and fresh.poly:
            fill = arb.price_pair(
                seen.pair.key,
                fresh.kalshi,
                fresh.poly,
                seen.pair.relation,
                max_contracts=self.s.paper_contracts,
            )
        ok = bool(fill and fill.per_contract * 100 >= self.s.min_edge_cents)
        full_depth = fresh.opportunity
        confirm_cents = float(full_depth.per_contract * 100) if full_depth else None
        row: dict[str, Any] = {
            "opportunity_id": opp_id,
            "pair_key": seen.pair.key,
            "label": seen.pair.label or seen.pair.key,
            "source": seen.pair.source,
            "outcome": seen.pair.outcome,
            "opened_at": datetime.now(UTC),
            "latency_ms": round(ms, 1),
            "seen_cents": float(o.per_contract * 100),
            "fill_cents": float(fill.per_contract * 100) if fill else None,
            "status": "open" if ok else "missed",
            "note": "" if ok else (fresh.error or "edge gone on the re-fetched books"),
        }
        if ok and fill:
            snap = fill.as_dict()
            row.update(
                contracts=float(fill.contracts),
                cost=float(fill.cost),
                fees=float(fill.fees),
                expected_profit=float(fill.profit),
                legs=json.dumps(snap["legs"]),
            )
        with self.store.tx() as conn:
            self.store.confirm_opportunity(conn, opp_id, ok, confirm_cents, round(ms, 1))
            row["id"] = self.store.add_paper(conn, row)
        return row

    async def settle(self) -> list[dict[str, Any]]:
        """Settle every open paper trade whose two markets have both resolved."""
        with self.store.tx() as conn:
            trades = self.store.open_papers(conn)
        done: list[dict[str, Any]] = []
        for t in trades:
            legs = t["legs"]
            k = next((leg for leg in legs if leg["venue"] == "kalshi"), None)
            p = next((leg for leg in legs if leg["venue"] == "polymarket"), None)
            if not (k and p):
                continue
            try:
                ky = await self.kalshi.result(k["market_id"])
                py = await self.poly.result(p["market_id"], t["outcome"])
            except Exception as e:  # a venue hiccup only delays settlement
                log.warning("settle %s: %s", t["pair_key"], e)
                continue
            if ky is None or py is None:
                continue
            paid = payout(legs, ky, py)
            pnl = paid - Decimal(str(t["cost"])) - Decimal(str(t["fees"]))
            locked = abs(paid - Decimal(str(t["contracts"]))) < Decimal("0.0001")
            note = "" if locked else f"legs did not offset: kalshi YES paid {ky}, polymarket YES paid {py}"
            at = datetime.now(UTC)
            values: dict[str, Any] = {"settled_at": at, "payout": float(paid), "pnl": float(pnl), "note": note}
            with self.store.tx() as conn:
                self.store.settle_paper(conn, t["id"], values)
                if not locked:
                    self.store.add_event(conn, "settlement_mismatch", t["pair_key"], note, at)
            done.append({**t, **values, "status": "settled"})
        return done


def format_fill(row: dict[str, Any]) -> str:
    if row["status"] == "missed":
        return (
            f"PAPER MISSED {row['label']}\nsaw {row['seen_cents']:.2f}c, gone after {row['latency_ms']:.0f}ms"
            f" ({row['note']})"
        )
    return (
        f"PAPER FILL {row['label']}\n{row['contracts']:.0f} contracts at {row['fill_cents']:.2f}c each"
        f" (saw {row['seen_cents']:.2f}c), expect ${row['expected_profit']:.2f}, re-check {row['latency_ms']:.0f}ms"
    )


def format_settled(row: dict[str, Any]) -> str:
    warn = f"\n! {row['note']}" if row.get("note") else ""
    return f"PAPER SETTLED {row['label']}\npnl ${row['pnl']:+.2f} (expected ${row['expected_profit']:+.2f}){warn}"
