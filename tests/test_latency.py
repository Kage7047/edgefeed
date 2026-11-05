from edgefeed.latency import Detector, LatencyConfig, grade

CFG = LatencyConfig(window=240, move=2, lag=1, gap=2, cooldown=180)


def feed(d, ks, ps, step=30.0):
    out = None
    for i, (k, p) in enumerate(zip(ks, ps, strict=True)):
        out = d.observe("x", i * step, k, p) or out
    return out


def test_fires_when_one_venue_moves_alone():
    sig = feed(Detector(CFG), [40, 42, 44, 48], [40.2] * 4)
    assert sig and sig.leader == "kalshi" and sig.laggard == "polymarket"
    assert sig.leader_move >= 2 and sig.gap >= 2 and abs(sig.laggard_move) <= 1


def test_quiet_when_both_move_together():
    assert feed(Detector(CFG), [40, 44, 48], [40, 44, 48]) is None


def test_cooldown():
    d = Detector(CFG)
    assert feed(d, [40, 48], [40, 40])
    assert d.observe("x", 90, 49, 40) is None


def test_grade():
    # leader at 50, laggard at 40
    assert grade(50, 40, 50, 46, 0.4) == (0.6, "hit")  # laggard caught up
    assert grade(50, 40, 50, 41, 0.4) == (0.1, "partial")
    assert grade(50, 40, 50, 38, 0.4)[1] == "miss"
    assert grade(50, 40, 42, 40, 0.4) == (0.0, "revert")  # the leader came back: noise
    assert grade(30, 40, 30, 35, 0.4) == (0.5, "hit")  # works downward too
    assert grade(40, 40, 40, 40, 0.4) == (0.0, "miss")


def test_wide_books_are_ignored():
    # same moves as the firing case, but Polymarket's book is 10c wide: its mid is not evidence
    d = Detector(CFG)
    out = None
    for i, k in enumerate([40, 42, 44, 48]):
        out = d.observe("x", i * 30.0, k, 40.2, k_width=1, p_width=10) or out
    assert out is None
    assert d.latest("x", "polymarket") is None


def test_tight_books_still_fire():
    d = Detector(CFG)
    out = None
    for i, k in enumerate([40, 42, 44, 48]):
        out = d.observe("x", i * 30.0, k, 40.2, k_width=1, p_width=2) or out
    assert out and out.leader == "kalshi"
