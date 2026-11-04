from decimal import Decimal as D

from hypothesis import given
from hypothesis import strategies as st

from edgefeed import fees
from edgefeed.models import Level


def test_kalshi_rounds_up_per_fill_not_per_contract():
    assert fees.kalshi_fee(D(1), D("0.50")) == D("0.02")  # 1.75c -> 2c
    assert fees.kalshi_fee(D(100), D("0.50")) == D("1.75")  # not 100 x 2c
    assert fees.kalshi_fee(D(10), D("0.14")) == D("0.09")  # 0.07*10*.14*.86 = 0.08428 -> 0.09


def test_kalshi_series_multiplier():
    assert fees.kalshi_fee(D(100), D("0.50"), D("0.5")) == D("0.88")


def test_polymarket_formula_and_rounding():
    assert fees.polymarket_fee(D(100), D("0.50"), D("0.07")) == D("1.75")  # docs worked example
    assert fees.polymarket_fee(D(100), D("0.50"), D("0.04")) == D("1.00")
    assert fees.polymarket_fee(D(1), D("0.001"), D("0.04")) == D("0.00004")  # 5 dp
    assert fees.polymarket_fee(D(1000), D("0.3"), D("0")) == D("0")  # geopolitics


def test_polymarket_fee_is_symmetric_around_half():
    assert fees.polymarket_fee(D(50), D("0.3"), D("0.05")) == fees.polymarket_fee(D(50), D("0.7"), D("0.05"))


def test_polymarket_category_fallback_is_conservative():
    assert fees.polymarket(None, category="geopolitics").rate == D(0)
    assert fees.polymarket(None, category="nope").rate == fees.POLY_DEFAULT_RATE


def test_fills_fee_sums_each_fill():
    f = fees.kalshi(1)
    assert fees.fills_fee(f, [Level(D("0.5"), D(1)), Level(D("0.5"), D(1))]) == D("0.04")


@given(c=st.integers(1, 10_000), p=st.decimals("0.01", "0.99", places=2))
def test_kalshi_fee_bounds(c, p):
    exact = D("0.07") * c * p * (1 - p)
    fee = fees.kalshi_fee(D(c), p)
    assert exact <= fee < exact + D("0.01")
