"""Contract tests against the real public APIs. Run with ``pytest -m live`` (daily in CI)."""

from decimal import Decimal

import pytest

from edgefeed import pairs
from edgefeed.discovery import sports
from edgefeed.models import ONE, Side
from edgefeed.scanner import Scanner
from edgefeed.venues.kalshi import KalshiClient
from edgefeed.venues.polymarket import PolymarketClient

pytestmark = pytest.mark.live


@pytest.fixture
async def clients():
    k, p = KalshiClient(), PolymarketClient()
    yield k, p
    await k.aclose()
    await p.aclose()


async def test_curated_pairs_still_price(clients):
    k, p = clients
    ps = pairs.load("config/pairs.yaml")
    scan = await Scanner(k, p).scan(ps)
    assert len(scan.priced) >= len(ps) * 0.6, [r.error for r in scan.failed]
    for r in scan.priced:
        for book in (r.kalshi, r.poly):
            assert book is not None
            for side in (Side.YES, Side.NO):
                lad = book.ladder(side)
                assert all(Decimal(0) < lv.price < ONE for lv in lad)
                assert lad == sorted(lad, key=lambda lv: lv.price)
        assert r.kalshi.closes_at is not None and r.kalshi.rules


async def test_fee_fields_present(clients):
    _, p = clients
    m = await p.meta(pairs.load("config/pairs.yaml")[0].polymarket)
    assert m.fee.rate >= 0 and m.fee.exponent >= 1


async def test_sports_discovery_runs(clients):
    k, p = clients
    found, cov = await sports.discover(k, p, ["nba", "nhl", "epl"], days_ahead=3)
    assert {c.league for c in cov} == {"nba", "nhl", "epl"}
    for pr in found:
        assert pr.kalshi.startswith("KX") and pr.polymarket.isdigit()
