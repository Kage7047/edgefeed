"""Cross-venue arbitrage on one matched pair, priced against real order-book depth.

A locked edge buys two legs that together pay $1 whatever happens: YES on one venue and NO on
the other (or YES+YES when the pair is defined as inverse). Profit per contract is
``1 - (ask_a + ask_b) - fees``. Asks get worse as you walk the books, so profit as a function of
size is concave; we walk both ladders together, stop at the first step that loses money, and
keep the size with the best *total* profit at each step's end. Kalshi rounds every fill's fee up to
the cent, so a size inside a step can occasionally beat that by less than a cent per fill; the
property test pins that bound against brute force.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_FLOOR, Decimal
from enum import StrEnum

from edgefeed.fees import fills_fee
from edgefeed.models import ONE, ZERO, Book, Fee, Level, Side, Venue

DAYS_PER_YEAR = Decimal(365)
MIN_LOCK_DAYS = Decimal(1)


class Relation(StrEnum):
    SAME = "same"  # YES on A means YES on B
    INVERSE = "inverse"  # YES on A means NO on B


@dataclass(slots=True)
class Leg:
    venue: str
    market_id: str
    side: Side
    fills: list[Level]
    fee: Decimal

    @property
    def contracts(self) -> Decimal:
        return sum((f.size for f in self.fills), ZERO)

    @property
    def cost(self) -> Decimal:
        return sum((f.size * f.price for f in self.fills), ZERO)

    @property
    def avg_price(self) -> Decimal:
        n = self.contracts
        return self.cost / n if n else ZERO


@dataclass(slots=True)
class Walk:
    contracts: Decimal
    a: list[Level]
    b: list[Level]
    fee_a: Decimal
    fee_b: Decimal

    @property
    def cost(self) -> Decimal:
        return sum((f.size * f.price for f in self.a + self.b), ZERO)

    @property
    def fees(self) -> Decimal:
        return self.fee_a + self.fee_b

    @property
    def profit(self) -> Decimal:
        return self.contracts - self.cost - self.fees


def _add(fills: list[Level], price: Decimal, size: Decimal) -> None:
    """Append a fill, merging it into the last one at the same price (one fill per price level)."""
    if fills and fills[-1].price == price:
        fills[-1] = Level(price, fills[-1].size + size)
    else:
        fills.append(Level(price, size))


def _floor(x: Decimal) -> Decimal:
    return x.to_integral_value(rounding=ROUND_FLOOR)


def walk_books(
    asks_a: list[Level],
    asks_b: list[Level],
    fee_a: Fee,
    fee_b: Fee,
    *,
    max_contracts: Decimal | None = None,
) -> Walk | None:
    """Best whole-contract size buying ``asks_a`` and ``asks_b`` together. None if nothing pays."""
    i = j = 0
    rem_a = asks_a[0].size if asks_a else ZERO
    rem_b = asks_b[0].size if asks_b else ZERO
    fills_a: list[Level] = []
    fills_b: list[Level] = []
    total = ZERO
    best: Walk | None = None
    carry = ZERO  # fractional size left over at a level boundary, folded into the next step

    while i < len(asks_a) and j < len(asks_b):
        pa, pb = asks_a[i].price, asks_b[j].price
        # net per contract at this step, before fee rounding: once it is <= 0, no deeper level pays
        marginal = ONE - pa - pb - _unrounded_fee(fee_a, pa) - _unrounded_fee(fee_b, pb)
        if marginal <= 0:
            break
        q = min(rem_a, rem_b)
        if max_contracts is not None:
            q = min(q, max_contracts - total)
        take = _floor(q + carry)
        carry = q + carry - take
        if take > 0:
            _add(fills_a, pa, take)
            _add(fills_b, pb, take)
            total += take
            cand = Walk(total, list(fills_a), list(fills_b), fills_fee(fee_a, fills_a), fills_fee(fee_b, fills_b))
            if cand.profit > 0 and (best is None or cand.profit > best.profit):
                best = cand
        if max_contracts is not None and total >= max_contracts:
            break
        rem_a -= q
        rem_b -= q
        if rem_a <= 0:
            i += 1
            rem_a = asks_a[i].size if i < len(asks_a) else ZERO
        if rem_b <= 0:
            j += 1
            rem_b = asks_b[j].size if j < len(asks_b) else ZERO
    return best


def _unrounded_fee(fee: Fee, price: Decimal) -> Decimal:
    p = price * (ONE - price)
    if fee.venue is Venue.KALSHI:
        return fee.rate * fee.multiplier * p
    return fee.rate * p**fee.exponent


@dataclass(slots=True)
class Opportunity:
    pair_key: str
    direction: str
    legs: tuple[Leg, Leg]
    contracts: Decimal
    cost: Decimal
    fees: Decimal
    profit: Decimal
    top_edge: Decimal  # net per contract at the best level only (what a 1-lot would make)
    lock_days: Decimal
    resolution_gap_days: Decimal | None
    warnings: list[str] = field(default_factory=list)

    @property
    def capital(self) -> Decimal:
        return self.cost + self.fees

    @property
    def per_contract(self) -> Decimal:
        return self.profit / self.contracts if self.contracts else ZERO

    @property
    def roi(self) -> Decimal:
        return self.profit / self.capital if self.capital else ZERO

    @property
    def apr(self) -> Decimal:
        return self.roi * DAYS_PER_YEAR / max(self.lock_days, MIN_LOCK_DAYS)

    def as_dict(self) -> dict[str, object]:
        return {
            "pair_key": self.pair_key,
            "direction": self.direction,
            "contracts": float(self.contracts),
            "cost": float(self.cost),
            "fees": float(self.fees),
            "profit": float(self.profit),
            "per_contract_cents": float(self.per_contract * 100),
            "top_edge_cents": float(self.top_edge * 100),
            "roi": float(self.roi),
            "apr": float(self.apr),
            "lock_days": float(self.lock_days),
            "resolution_gap_days": None if self.resolution_gap_days is None else float(self.resolution_gap_days),
            "warnings": list(self.warnings),
            "legs": [
                {
                    "venue": leg.venue,
                    "market_id": leg.market_id,
                    "side": leg.side.value,
                    "contracts": float(leg.contracts),
                    "avg_price": float(leg.avg_price),
                    "worst_price": float(leg.fills[-1].price) if leg.fills else None,
                    "fee": float(leg.fee),
                }
                for leg in self.legs
            ],
        }


def _days(a: datetime, b: datetime) -> Decimal:
    return Decimal(str((a - b).total_seconds() / 86400))


def price_pair(
    key: str,
    a: Book,
    b: Book,
    relation: Relation = Relation.SAME,
    *,
    now: datetime | None = None,
    max_contracts: Decimal | None = None,
    max_resolution_gap_days: Decimal = Decimal(3),
) -> Opportunity | None:
    """Best locked edge on the pair across both directions, or None if neither direction pays."""
    now = now or datetime.now(UTC)
    if relation is Relation.SAME:
        directions = [(Side.YES, Side.NO), (Side.NO, Side.YES)]
    else:
        directions = [(Side.YES, Side.YES), (Side.NO, Side.NO)]

    closes = [c for c in (a.closes_at, b.closes_at) if c is not None]
    # capital is locked until the later of the two markets resolves; unknown dates count as a year
    lock_days = _days(max(closes), now) if closes else DAYS_PER_YEAR
    gap = abs(_days(a.closes_at, b.closes_at)) if a.closes_at and b.closes_at else None

    best: Opportunity | None = None
    for sa, sb in directions:
        la, lb = a.ladder(sa), b.ladder(sb)
        w = walk_books(la, lb, a.fee, b.fee, max_contracts=max_contracts)
        if w is None:
            continue
        top = ONE - la[0].price - lb[0].price - _unrounded_fee(a.fee, la[0].price) - _unrounded_fee(b.fee, lb[0].price)
        warnings: list[str] = []
        if gap is not None and gap > max_resolution_gap_days:
            warnings.append(f"resolution dates differ by {gap:.0f} days")
        for book in (a, b):
            if w.contracts < book.min_size:
                warnings.append(f"{book.venue.value} minimum order is {book.min_size} contracts")
        opp = Opportunity(
            pair_key=key,
            direction=f"{a.venue.value}:{sa.value}+{b.venue.value}:{sb.value}",
            legs=(
                Leg(a.venue.value, a.market_id, sa, w.a, w.fee_a),
                Leg(b.venue.value, b.market_id, sb, w.b, w.fee_b),
            ),
            contracts=w.contracts,
            cost=w.cost,
            fees=w.fees,
            profit=w.profit,
            top_edge=top,
            lock_days=max(lock_days, ZERO),
            resolution_gap_days=gap,
            warnings=warnings,
        )
        if best is None or opp.profit > best.profit:
            best = opp
    return best


def spread(a: Book, b: Book, relation: Relation = Relation.SAME) -> Decimal | None:
    """Best top-of-book net edge per contract over both directions, even when negative.

    This is the number the collector charts: how far the pair is from a locked edge.
    """
    if relation is Relation.SAME:
        directions = [(Side.YES, Side.NO), (Side.NO, Side.YES)]
    else:
        directions = [(Side.YES, Side.YES), (Side.NO, Side.NO)]
    out: Decimal | None = None
    for sa, sb in directions:
        x, y = a.best(sa), b.best(sb)
        if not (x and y):
            continue
        v = ONE - x.price - y.price - _unrounded_fee(a.fee, x.price) - _unrounded_fee(b.fee, y.price)
        out = v if out is None else max(out, v)
    return out
