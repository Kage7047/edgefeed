from datetime import timedelta
from decimal import Decimal as D

from hypothesis import given, settings
from hypothesis import strategies as st

from edgefeed import arb, fees
from edgefeed.models import Level, Side
from tests.conftest import NOW, kbook, lv, pbook


def test_no_edge_when_books_cross_at_par():
    k = kbook(lv(("0.55", 100)), lv(("0.46", 100)))
    p = pbook(lv(("0.55", 100)), lv(("0.46", 100)))
    assert arb.price_pair("x", k, p, now=NOW) is None


def test_edge_walks_until_it_stops_paying():
    # buy K YES + P NO: 0.40 + 0.50 = 0.90 at the top, then 0.40 + 0.58 = 0.98 (fees eat it)
    k = kbook(lv(("0.40", 100)), lv(("0.62", 10)))
    p = pbook(lv(("0.70", 10)), lv(("0.50", 60), ("0.58", 500)))
    o = arb.price_pair("x", k, p, now=NOW)
    assert o is not None
    assert o.direction == "kalshi:yes+polymarket:no"
    assert o.contracts == 60
    assert o.legs[0].side is Side.YES and o.legs[1].side is Side.NO
    # 60 * (1 - 0.9) = 6.00 gross, minus fees
    assert o.profit == D(60) - o.cost - o.fees
    assert D("4") < o.profit < D("6")


def test_inverse_relation_buys_yes_on_both():
    k = kbook(lv(("0.40", 50)), lv(("0.65", 50)))
    p = pbook(lv(("0.50", 50)), lv(("0.55", 50)))
    o = arb.price_pair("x", k, p, arb.Relation.INVERSE, now=NOW)
    assert o is not None and o.direction == "kalshi:yes+polymarket:yes"


def test_apr_uses_the_later_resolution_and_flags_mismatch():
    k = kbook(lv(("0.40", 100)), lv(("0.65", 1)), days=10)
    p = pbook(lv(("0.70", 1)), lv(("0.50", 100)), days=30)
    o = arb.price_pair("x", k, p, now=NOW)
    assert o is not None
    assert abs(o.lock_days - 30) < D("0.01")
    assert o.apr == o.roi * 365 / o.lock_days
    assert any("resolution dates differ" in w for w in o.warnings)


def test_min_order_size_warning():
    k = kbook(lv(("0.40", 3)), lv(("0.65", 1)))
    p = pbook(lv(("0.70", 1)), lv(("0.50", 3)), min_size="5")
    o = arb.price_pair("x", k, p, now=NOW)
    assert o is not None and any("minimum order" in w for w in o.warnings)


def test_max_contracts_caps_size():
    k = kbook(lv(("0.40", 1000)), lv(("0.65", 1)))
    p = pbook(lv(("0.70", 1)), lv(("0.50", 1000)))
    o = arb.price_pair("x", k, p, now=NOW, max_contracts=D(25))
    assert o is not None and o.contracts == 25


def test_spread_reports_negative_distance():
    k = kbook(lv(("0.55", 1)), lv(("0.47", 1)))
    p = pbook(lv(("0.56", 1)), lv(("0.46", 1)))
    s = arb.spread(k, p)
    assert s is not None and s < 0


def _brute(asks_a, asks_b, fa, fb, max_n):
    """Profit of every whole size by explicit fills; the walk must match the best one."""
    best = D(0)

    def take(ladder, n):
        out, left = [], n
        for lvl in ladder:
            q = min(lvl.size, left)
            if q > 0:
                out.append(Level(lvl.price, q))
                left -= q
        return out if left == 0 else None

    for n in range(1, max_n + 1):
        a, b = take(asks_a, D(n)), take(asks_b, D(n))
        if a is None or b is None:
            break
        cost = sum(x.price * x.size for x in a + b)
        profit = D(n) - cost - fees.fills_fee(fa, a) - fees.fills_fee(fb, b)
        best = max(best, profit)
    return best


ladder = st.lists(st.tuples(st.decimals("0.05", "0.95", places=2), st.integers(1, 12)), min_size=1, max_size=4).map(
    lambda xs: sorted((Level(p, D(s)) for p, s in xs), key=lambda lv: lv.price)
)


@settings(max_examples=300, deadline=None)
@given(a=ladder, b=ladder)
def test_walk_matches_brute_force(a, b):
    fa, fb = fees.kalshi(1), fees.polymarket("0.05")
    w = arb.walk_books(a, b, fa, fb)
    total = min(sum(x.size for x in a), sum(x.size for x in b))
    best = _brute(a, b, fa, fb, int(total))
    # The walk evaluates each step's end. Kalshi rounds each fill's fee up to the cent, so an interior
    # size can beat it by under a cent per fill: that is the documented bound, nothing more.
    bound = D("0.01") * (len(a) + 1)
    found = w.profit if w else D(0)
    assert w is None or w.profit > 0
    assert best - found <= bound


def test_unknown_close_date_counts_as_a_year():
    k = kbook(lv(("0.40", 10)), lv(("0.65", 1)))
    p = pbook(lv(("0.70", 1)), lv(("0.50", 10)))
    k.closes_at = p.closes_at = None
    o = arb.price_pair("x", k, p, now=NOW + timedelta(0))
    assert o is not None and o.lock_days == 365
