from datetime import timedelta
from decimal import Decimal as D

import sqlalchemy as sa

from edgefeed import arb
from edgefeed.collector import Collector, Ledger
from edgefeed.config import Settings
from edgefeed.discovery.sports import game_start
from edgefeed.pairs import Pair
from edgefeed.paper import Paper, payout
from edgefeed.scanner import PairResult, Scan
from edgefeed.store import Store
from edgefeed.venues import kalshi, polymarket
from tests.conftest import NOW, kbook, lv, pbook

PAIR = Pair("K1", "P1", label="Game", source="sports")


def settings(tmp_path, **kw) -> Settings:
    base = dict(db_url=f"sqlite:///{tmp_path}/t.sqlite", min_edge_cents=D("0.25"), min_profit=D("1"))
    base.update(kw)
    return Settings(**base)


def result(k_yes="0.40", p_no="0.50", size=100, pair=PAIR) -> PairResult:
    k = kbook(lv((k_yes, size)), lv(("0.65", 1)))
    p = pbook(lv(("0.70", 1)), lv((p_no, size)))
    r = PairResult(pair=pair, kalshi=k, poly=p)
    r.spread = arb.spread(k, p)
    r.opportunity = arb.price_pair(pair.key, k, p, now=NOW)
    return r


class FakeScanner:
    def __init__(self, *results: PairResult) -> None:
        self.results = list(results)

    async def scan(self, pairs):
        return Scan(started_at=NOW, seconds=0.1, results=[self.results.pop(0)])


class FakeVenue:
    def __init__(self, value):
        self.value = value

    async def result(self, *_):
        return self.value


# ---- pricing: carry ---------------------------------------------------------------------------


def test_carry_adds_holding_yield_on_the_locked_leg():
    k = kbook(lv(("0.14", 100)), lv(("0.90", 100)), days=730)
    p = pbook(lv(("0.20", 100)), lv(("0.84", 100)), days=730, rate="0")
    p.apy = D("0.04")
    o = arb.price_pair("x", k, p, now=NOW)
    assert o is not None
    poly_cost = sum(f.size * f.price for f in o.legs[1].fills)
    assert o.carry_apr == poly_cost * D("0.04") / o.capital
    assert o.total_apr == o.apr + o.carry_apr
    assert 0.03 < float(o.carry_apr) < 0.04  # most of the capital sits on Polymarket


# ---- paper fills and settlement ---------------------------------------------------------------


def test_payout_of_a_locked_pair_is_the_contract_count():
    legs = [
        {"venue": "kalshi", "side": "yes", "contracts": 10},
        {"venue": "polymarket", "side": "no", "contracts": 10},
    ]
    assert payout(legs, D(1), D(1)) == 10  # Kalshi YES won, Polymarket NO lost
    assert payout(legs, D(0), D(0)) == 10
    assert payout(legs, D("0.5"), D(1)) == 5  # Kalshi voided at a fair price: the hedge broke


async def test_take_fills_when_the_edge_survives_the_recheck(tmp_path):
    s = settings(tmp_path, paper_contracts=D("50"))
    store = Store(s.db_url)
    seen = result()
    paper = Paper(store, FakeScanner(result()), FakeVenue(None), FakeVenue(None), s)  # type: ignore[arg-type]
    with store.tx() as conn:
        opp_id = store.open_opportunity(conn, _opp_row())
    row = await paper.take(opp_id, seen)
    assert row and row["status"] == "open" and row["contracts"] == 50
    with store.tx() as conn:
        (opp,) = store.opportunities(conn)
    assert opp["confirmed"] == 1 and opp["confirm_ms"] is not None


async def test_take_records_a_miss_when_the_edge_is_gone(tmp_path):
    s = settings(tmp_path)
    store = Store(s.db_url)
    paper = Paper(store, FakeScanner(result(k_yes="0.55", p_no="0.50")), None, None, s)  # type: ignore[arg-type]
    with store.tx() as conn:
        opp_id = store.open_opportunity(conn, _opp_row())
    row = await paper.take(opp_id, result())
    assert row and row["status"] == "missed" and row["fill_cents"] is None


async def test_long_lockups_are_not_paper_traded(tmp_path):
    s = settings(tmp_path, paper_max_lock_days=D("14"))
    store = Store(s.db_url)
    k = kbook(lv(("0.40", 100)), lv(("0.65", 1)), days=700)
    p = pbook(lv(("0.70", 1)), lv(("0.50", 100)), days=700)
    r = PairResult(pair=PAIR, kalshi=k, poly=p, opportunity=arb.price_pair("x", k, p, now=NOW))
    assert await Paper(store, FakeScanner(), None, None, s).take(1, r) is None  # type: ignore[arg-type]


async def test_settle_books_pnl_and_flags_a_broken_hedge(tmp_path):
    s = settings(tmp_path)
    store = Store(s.db_url)
    paper = Paper(store, FakeScanner(result()), FakeVenue(D("0.5")), FakeVenue(D(1)), s)  # type: ignore[arg-type]
    with store.tx() as conn:
        opp_id = store.open_opportunity(conn, _opp_row())
    row = await paper.take(opp_id, result())
    assert row and row["status"] == "open"
    (done,) = await paper.settle()
    assert done["note"].startswith("legs did not offset")
    # Kalshi YES paid 0.5, Polymarket NO paid 0: half the contracts came back
    assert abs(done["payout"] - row["contracts"] / 2) < 1e-9
    with store.tx() as conn:
        assert store.recent_events(conn)[0]["kind"] == "settlement_mismatch"
        assert store.paper(conn)[0]["status"] == "settled"
    assert await paper.settle() == []  # nothing left open


def _opp_row() -> dict:
    return {
        "kind": "cross",
        "pair_key": PAIR.key,
        "label": "Game",
        "source": "sports",
        "direction": "kalshi:yes+polymarket:no",
        "opened_at": NOW,
        "last_seen_at": NOW,
        "scans_seen": 1,
        "first_cents": 1.0,
        "best_cents": 1.0,
        "best_profit": 1.0,
        "best_contracts": 1.0,
        "best_apr": 1.0,
        "lock_days": 1.0,
        "warnings": "[]",
        "best_snapshot": "{}",
    }


# ---- hot scans --------------------------------------------------------------------------------


def test_hot_scan_does_not_close_edges_it_did_not_look_at(tmp_path):
    s = settings(tmp_path)
    store = Store(s.db_url)
    led = Ledger(store, s)
    other = Pair("K2", "P2", label="Other")
    led.apply(Scan(NOW, 1.0, [result(), result(pair=other)]))
    hot = Scan(NOW + timedelta(seconds=3), 0.2, [result(k_yes="0.60")], kind="hot")  # only PAIR, edge gone
    out = led.apply(hot)
    assert len(out.closed) == 1
    with store.tx() as conn:
        open_keys = set(store.open_ids(conn))
    assert open_keys == {other.key}


def test_unchanged_quotes_are_not_rewritten(tmp_path):
    s = settings(tmp_path)
    store = Store(s.db_url)
    led = Ledger(store, s)
    for i in range(5):
        led.apply(Scan(NOW + timedelta(seconds=3 * i), 0.2, [result()], kind="hot"), clock=3.0 * i)
    led.apply(Scan(NOW + timedelta(seconds=20), 0.2, [result(p_no="0.49")]), clock=20.0)
    with store.engine.connect() as conn:
        assert conn.execute(sa.text("select count(*) from quotes")).scalar() == 2


def test_hot_set_is_live_games_and_open_edges(tmp_path):
    c = Collector(settings(tmp_path))
    live = Pair("K1", "P1", starts_at=NOW - timedelta(hours=1))
    soon = Pair("K2", "P2", starts_at=NOW + timedelta(minutes=10))
    later = Pair("K3", "P3", starts_at=NOW + timedelta(hours=5))
    done = Pair("K4", "P4", starts_at=NOW - timedelta(hours=6))
    curated = Pair("K5", "P5")
    assert c.hot([live, soon, later, done, curated], now=NOW) == [live, soon]


# ---- schema migration, venue parsing -----------------------------------------------------------


V02_SCANS = (
    "create table scans (id integer primary key, started_at timestamp not null, seconds float not null,"
    " pairs integer not null, priced integer not null, failed integer not null, opportunities integer not null)"
)


def test_v02_database_gains_new_columns(tmp_path):
    url = f"sqlite:///{tmp_path}/old.sqlite"
    with sa.create_engine(url).begin() as conn:
        conn.execute(sa.text(V02_SCANS))
        conn.execute(sa.text("insert into scans values (1, '2026-11-04', 1.0, 1, 1, 0, 0)"))
    store = Store(url)  # create_all skips the existing table, migrate() adds the missing column
    with store.engine.connect() as conn:
        assert conn.execute(sa.text("select id, kind from scans")).all() == [(1, None)]
    assert store.migrate() == []  # idempotent


def test_migration_refuses_a_required_column(tmp_path):
    url = f"sqlite:///{tmp_path}/odd.sqlite"
    with sa.create_engine(url).begin() as conn:
        conn.execute(sa.text("create table scans (id integer primary key, started_at timestamp not null)"))
    try:
        Store(url)
    except RuntimeError as e:
        assert "scans.seconds" in str(e)
    else:
        raise AssertionError("expected a refusal")


def test_results_parse_from_both_venues():
    assert kalshi.result_from({"market": {"status": "finalized", "settlement_value_dollars": "1.0000"}}) == 1
    assert kalshi.result_from({"status": "settled", "result": "no"}) == 0
    assert kalshi.result_from({"status": "active", "result": ""}) is None
    m = {
        "closed": True,
        "umaResolutionStatus": "resolved",
        "outcomes": '["Heat", "Clippers"]',
        "outcomePrices": '["1", "0"]',
    }
    assert polymarket.result_from(m, "Heat") == 1 and polymarket.result_from(m, "Clippers") == 0
    assert polymarket.result_from({**m, "umaResolutionStatus": "proposed"}, "Heat") is None


def test_game_start_prefers_the_market_time():
    t = game_start({"gameStartTime": "2026-11-06 02:00:00+00"}, {"startTime": "2026-11-07T00:00:00Z"})
    assert t is not None and t.isoformat() == "2026-11-06T02:00:00+00:00"
    assert game_start({}, {"startTime": "2026-11-07T00:00:00Z"}) is not None
