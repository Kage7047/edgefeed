from datetime import timedelta
from decimal import Decimal as D

from edgefeed import arb
from edgefeed.collector import Ledger
from edgefeed.config import Settings
from edgefeed.latency import Detector, LatencyConfig
from edgefeed.pairs import Pair
from edgefeed.scanner import PairResult, Scan
from tests.conftest import NOW, kbook, lv, pbook

PAIR = Pair("K1", "P1", label="Test pair", source="sports", rule_risk="cancelled games differ")


def settings(**kw) -> Settings:
    base = dict(min_edge_cents=D("0.25"), min_profit=D("1"), alert_min_apr=D("0.10"), alert_min_profit=D("5"))
    return Settings(**(base | kw))


def result(k_yes="0.40", p_no="0.50", size=100, rules="rule v1", pair=PAIR) -> PairResult:
    k = kbook(lv((k_yes, size)), lv(("0.65", 1)), rules=rules)
    p = pbook(lv(("0.70", 1)), lv((p_no, size)), rules="poly rules")
    r = PairResult(pair=pair, kalshi=k, poly=p)
    r.spread = arb.spread(k, p)
    r.opportunity = arb.price_pair(pair.key, k, p, now=NOW)
    if r.opportunity and pair.rule_risk:
        r.opportunity.warnings.append(pair.rule_risk)
    return r


def scan_at(minutes: float, *results: PairResult) -> Scan:
    return Scan(started_at=NOW + timedelta(minutes=minutes), seconds=1.0, results=list(results))


def test_open_touch_improve_close(store):
    led = Ledger(store, settings())
    o1 = led.apply(scan_at(0, result()))
    assert len(o1.opened) == 1 and o1.alerts  # $9+ on a 1-day lock: alertable
    assert "cancelled games differ" in o1.alerts[0]
    o2 = led.apply(scan_at(1, result(p_no="0.45")))  # wider edge, same opportunity
    assert not o2.opened and not o2.closed
    o3 = led.apply(scan_at(2, result(k_yes="0.55", p_no="0.46")))  # gone
    assert o3.closed == o1.opened
    with store.tx() as conn:
        (row,) = store.opportunities(conn)
    assert row["scans_seen"] == 2 and row["best_cents"] > row["first_cents"]
    assert row["closed_at"] == NOW + timedelta(minutes=2)
    assert row["warnings"] == ["cancelled games differ"]


def test_failed_fetch_does_not_close_an_open_opportunity(store):
    led = Ledger(store, settings())
    led.apply(scan_at(0, result()))
    out = led.apply(scan_at(1, PairResult(pair=PAIR, error="kalshi: timeout")))
    assert not out.closed


def test_small_edges_are_not_recorded(store):
    led = Ledger(store, settings(min_profit=D("1000")))
    assert not led.apply(scan_at(0, result())).opened


def test_long_lock_is_recorded_but_not_alerted(store):
    led = Ledger(store, settings())
    r = result()
    r.kalshi.closes_at = r.poly.closes_at = NOW + timedelta(days=700)
    r.opportunity = arb.price_pair(PAIR.key, r.kalshi, r.poly, now=NOW)
    out = led.apply(scan_at(0, r))
    assert out.opened and not out.alerts


def test_rule_change_raises_an_event(store):
    led = Ledger(store, settings())
    led.apply(scan_at(0, result(rules="rule v1")))
    led.apply(scan_at(1, result(rules="rule   V1")))  # whitespace/case only: same rule
    out = led.apply(scan_at(2, result(rules="rule v2: now includes overtime")))
    assert out.rule_changes == ["kalshi:K1"]
    with store.tx() as conn:
        assert store.recent_events(conn)[0]["kind"] == "rules_changed"


def test_quotes_and_pairs_are_written(store):
    Ledger(store, settings()).apply(scan_at(0, result()))
    with store.tx() as conn:
        (q,) = store.latest_quotes(conn)
    assert q["label"] == "Test pair" and q["k_yes"] == 0.40 and q["spread_cents"] > 0


def test_latency_signal_is_recorded_and_graded(store):
    cfg = LatencyConfig(window=600, move=2, lag=1, gap=2, cooldown=0, followup=60, hit_frac=0.4)
    led = Ledger(store, settings(min_profit=D("1e9")), Detector(cfg))
    for i, k_yes in enumerate(["0.40", "0.43", "0.46"]):  # Kalshi climbs, Polymarket flat
        r = result(k_yes=k_yes, p_no="0.62")
        led.apply(scan_at(i * 0.5, r), clock=i * 30.0)
    with store.tx() as conn:
        sigs = store.recent_signals(conn)
    assert sigs and sigs[0]["leader"] == "kalshi"
    # Kalshi's mid is 40.5c, Polymarket's 54c. Later Polymarket comes down to 45c: most of the gap closed.
    led.apply(scan_at(3, result(k_yes="0.46", p_no="0.80")), clock=200.0)
    with store.tx() as conn:
        graded = [s for s in store.recent_signals(conn) if s["outcome"]]
    assert graded and graded[0]["outcome"] == "hit" and graded[0]["convergence"] > 0.5
