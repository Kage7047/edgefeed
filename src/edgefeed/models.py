"""Venue-neutral market data. Prices are Decimal dollars in [0, 1]; sizes are contracts/shares."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

ONE = Decimal(1)
ZERO = Decimal(0)


class Venue(StrEnum):
    KALSHI = "kalshi"
    POLYMARKET = "polymarket"


class Side(StrEnum):
    YES = "yes"
    NO = "no"


@dataclass(frozen=True, slots=True)
class Level:
    price: Decimal
    size: Decimal


def asks(levels: list[Level]) -> list[Level]:
    """Best (cheapest) ask first, empty and non-tradable levels dropped."""
    return sorted((lv for lv in levels if lv.size > 0 and ZERO < lv.price < ONE), key=lambda lv: lv.price)


@dataclass(frozen=True, slots=True)
class Fee:
    """How a venue charges a taker for one fill.

    kalshi: round_up_to_cent(coeff * multiplier * C * P * (1 - P))
    polymarket: round_5dp(C * rate * (P * (1 - P)) ** exponent)
    """

    venue: Venue
    rate: Decimal
    exponent: int = 1
    multiplier: Decimal = ONE


@dataclass(slots=True)
class Book:
    """Both sides of one binary market, as ask ladders (what a taker can buy)."""

    venue: Venue
    market_id: str
    yes_asks: list[Level]
    no_asks: list[Level]
    fee: Fee
    title: str = ""
    closes_at: datetime | None = None
    rules: str = ""
    min_size: Decimal = ONE
    fetched_at: datetime | None = None
    extra: dict[str, str] = field(default_factory=dict)
    apy: Decimal = ZERO  # yield the venue pays on this position while it is held (interest, rewards)

    def ladder(self, side: Side) -> list[Level]:
        return self.yes_asks if side is Side.YES else self.no_asks

    def best(self, side: Side) -> Level | None:
        lad = self.ladder(side)
        return lad[0] if lad else None

    def mid(self) -> Decimal | None:
        """YES mid: between the best YES ask and the YES bid implied by the best NO ask."""
        y, n = self.best(Side.YES), self.best(Side.NO)
        if not (y and n):
            return None
        return (y.price + (ONE - n.price)) / 2
