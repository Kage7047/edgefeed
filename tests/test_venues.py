from decimal import Decimal as D

import httpx
import pytest
import respx

from edgefeed.models import Side, Venue
from edgefeed.venues import kalshi as K
from edgefeed.venues import polymarket as P
from edgefeed.venues.http import ClientError, NotFound, VenueError, VenueHTTP
from tests.conftest import fixture


def test_kalshi_asks_come_from_the_opposite_bids():
    yes, no = K.book_from(fixture("kalshi_orderbook.json"))
    # best NO bid 0.86 -> YES ask 0.14; best YES bid 0.13 -> NO ask 0.87
    assert yes[0].price == D("0.14") and yes[0].size == D("325565.37")
    assert no[0].price == D("0.87")
    assert [x.price for x in yes] == sorted(x.price for x in yes)


def test_kalshi_meta_from_fixture():
    m = K.meta_from(fixture("kalshi_market.json"))
    assert m.ticker == "KXPRESNOMD-28-AOC" and m.series == "KXPRESNOMD"
    assert m.closes_at is not None and m.closes_at.year == 2028
    assert "Ocasio-Cortez" in m.rules


def test_polymarket_meta_uses_the_markets_own_fee_schedule():
    m = P.meta_from(fixture("poly_market.json"))
    assert m is not None
    assert m.fee.venue is Venue.POLYMARKET and m.fee.rate == D("0.04")
    assert m.min_size == D(5) and m.neg_risk


def test_polymarket_named_outcome_becomes_yes():
    raw = {
        "id": "9",
        "outcomes": '["Hawks", "Wizards"]',
        "clobTokenIds": '["a", "b"]',
        "feeSchedule": {"rate": 0.05},
    }
    m = P.meta_from(raw, "Wizards")
    assert m is not None and m.yes_token == "b" and m.no_token == "a"
    assert P.meta_from(raw, "Lakers") is None


def test_polymarket_fees_disabled_means_zero():
    raw = {
        "id": "9",
        "outcomes": '["Yes", "No"]',
        "clobTokenIds": '["a", "b"]',
        "feesEnabled": False,
        "feeSchedule": {"rate": 0.04},
    }
    m = P.meta_from(raw)
    assert m is not None and m.fee.rate == 0


def test_polymarket_ladder_sorted_best_first():
    lad = P.ladder_from(fixture("poly_book_no.json"))
    assert lad[0].price == min(x.price for x in lad)


@respx.mock
async def test_kalshi_books_batches_requests():
    route_m = respx.get(f"{K.BASE}/markets").mock(
        return_value=httpx.Response(200, json={"markets": [fixture("kalshi_market.json")["market"]]})
    )
    respx.get(f"{K.BASE}/series/KXPRESNOMD").mock(return_value=httpx.Response(200, json=fixture("kalshi_series.json")))
    ob = fixture("kalshi_orderbook.json") | {"ticker": "KXPRESNOMD-28-AOC"}
    route_ob = respx.get(f"{K.BASE}/markets/orderbooks").mock(
        return_value=httpx.Response(200, json={"orderbooks": [ob]})
    )
    c = K.KalshiClient(K.VenueHTTP("kalshi", K.BASE, rate=1000))
    books = await c.books(["KXPRESNOMD-28-AOC"])
    books = await c.books(["KXPRESNOMD-28-AOC"])  # metadata now cached
    await c.aclose()
    b = books["KXPRESNOMD-28-AOC"]
    assert b.best(Side.YES).price == D("0.14")
    assert route_m.call_count == 1 and route_ob.call_count == 2


@respx.mock
async def test_polymarket_metas_and_ladders():
    respx.get(f"{P.GAMMA}/markets").mock(return_value=httpx.Response(200, json=[fixture("poly_market.json")]))
    book = fixture("poly_book_no.json")
    respx.post(f"{P.CLOB}/books").mock(return_value=httpx.Response(200, json=[book]))
    c = P.PolymarketClient(VenueHTTP("polymarket", P.GAMMA, rate=1000), VenueHTTP("polymarket", P.CLOB, rate=1000))
    metas = await c.metas([("559653", "Yes")])
    m = metas[("559653", "Yes")]
    lad = await c.ladders([m.no_token])
    await c.aclose()
    assert m.no_token == book["asset_id"] and lad[m.no_token]


@respx.mock
async def test_http_retries_then_succeeds():
    route = respx.get("https://x.test/a").mock(side_effect=[httpx.Response(503), httpx.Response(200, json={"ok": 1})])
    h = VenueHTTP("t", "https://x.test", rate=1000)
    assert await h.get("/a") == {"ok": 1}
    assert route.call_count == 2
    await h.aclose()


@respx.mock
async def test_http_honours_retry_after():
    respx.get("https://x.test/a").mock(
        side_effect=[httpx.Response(429, headers={"retry-after": "0"}), httpx.Response(200, json=[])]
    )
    h = VenueHTTP("t", "https://x.test", rate=1000)
    assert await h.get("/a") == []
    await h.aclose()


@respx.mock
async def test_http_does_not_retry_client_errors():
    route = respx.get("https://x.test/a").mock(return_value=httpx.Response(422))
    h = VenueHTTP("t", "https://x.test", rate=1000)
    with pytest.raises(ClientError):
        await h.get("/a")
    assert route.call_count == 1
    respx.get("https://x.test/b").mock(return_value=httpx.Response(404))
    with pytest.raises(NotFound):
        await h.get("/b")
    await h.aclose()


@respx.mock
async def test_http_gives_up():
    respx.get("https://x.test/a").mock(return_value=httpx.Response(500))
    h = VenueHTTP("t", "https://x.test", rate=1000, retries=1)
    with pytest.raises(VenueError):
        await h.get("/a")
    await h.aclose()
