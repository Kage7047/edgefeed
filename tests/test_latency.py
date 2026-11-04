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
    assert grade(50, 40, 46, 0.4) == (0.6, "hit")
    assert grade(50, 40, 41, 0.4) == (0.1, "partial")
    assert grade(50, 40, 38, 0.4)[1] == "miss"
