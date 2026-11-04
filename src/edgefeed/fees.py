"""Taker fees, exactly as the venues publish them (checked 2026-11).

Kalshi (fee schedule PDF): fees = round_up(0.07 x C x P x (1 - P)) to the next cent, per trade,
scaled by the series' ``fee_multiplier`` (from ``GET /series/{ticker}``). Rounding is applied per
fill here, so an order that walks several price levels is charged a little more than a single
fill would be — the conservative side.

Polymarket (docs.polymarket.com/trading/fees, Fee Structure V2): fee = C x feeRate x p x (1 - p),
taker only, in USDC, rounded to 5 decimals. Each market carries its own ``feeSchedule``
(``rate``, ``exponent``) in Gamma; geopolitics markets have rate 0. ``exponent`` generalises the
curve as (p(1-p))**exponent; every live market uses 1.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from edgefeed.models import ONE, ZERO, Fee, Level, Venue

CENT = Decimal("0.01")
FIVE_DP = Decimal("0.00001")
KALSHI_COEFF = Decimal("0.07")

# Fallbacks when a Polymarket market has no feeSchedule (published V2 taker rates).
POLY_CATEGORY_RATE: dict[str, Decimal] = {
    "crypto": Decimal("0.07"),
    "sports": Decimal("0.05"),
    "economics": Decimal("0.05"),
    "culture": Decimal("0.05"),
    "weather": Decimal("0.05"),
    "other": Decimal("0.05"),
    "finance": Decimal("0.04"),
    "politics": Decimal("0.04"),
    "mentions": Decimal("0.04"),
    "tech": Decimal("0.04"),
    "geopolitics": Decimal("0"),
}
POLY_DEFAULT_RATE = Decimal("0.07")  # unknown category: assume the most expensive


def kalshi_fee(contracts: Decimal, price: Decimal, multiplier: Decimal = ONE) -> Decimal:
    raw = KALSHI_COEFF * multiplier * contracts * price * (ONE - price)
    return raw.quantize(CENT, rounding=ROUND_CEILING)


def polymarket_fee(shares: Decimal, price: Decimal, rate: Decimal, exponent: int = 1) -> Decimal:
    raw = shares * rate * (price * (ONE - price)) ** exponent
    return raw.quantize(FIVE_DP, rounding=ROUND_HALF_UP)


def fill_fee(fee: Fee, contracts: Decimal, price: Decimal) -> Decimal:
    if contracts <= 0:
        return ZERO
    if fee.venue is Venue.KALSHI:
        return kalshi_fee(contracts, price, fee.multiplier)
    return polymarket_fee(contracts, price, fee.rate, fee.exponent)


def fills_fee(fee: Fee, fills: list[Level]) -> Decimal:
    return sum((fill_fee(fee, f.size, f.price) for f in fills), ZERO)


def kalshi(multiplier: Decimal | int | str = 1) -> Fee:
    return Fee(Venue.KALSHI, KALSHI_COEFF, 1, Decimal(str(multiplier)))


def polymarket(rate: Decimal | str | float | None, exponent: int = 1, category: str | None = None) -> Fee:
    r = POLY_CATEGORY_RATE.get((category or "").lower(), POLY_DEFAULT_RATE) if rate is None else Decimal(str(rate))
    return Fee(Venue.POLYMARKET, r, int(exponent))
