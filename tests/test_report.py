from datetime import timedelta

from edgefeed.collector import Ledger
from edgefeed.config import Settings
from edgefeed.report import build, render
from tests.conftest import NOW
from tests.test_ledger import result, scan_at


def test_empty_ledger(store):
    assert build(store, now=NOW)["verdict"].startswith("NO DATA")


def test_verdict_after_enough_days(store):
    led = Ledger(store, Settings())
    for day in range(4):
        for i in range(2):  # the same edge seen on two scans: actionable
            led.apply(scan_at(day * 1440 + i, result()))
        led.apply(scan_at(day * 1440 + 5, result(k_yes="0.55", p_no="0.46")))
    rep = build(store, days=7, now=NOW + timedelta(days=4))
    assert rep["opportunities"]["actionable"] == 4
    assert rep["verdict"].startswith(("GO", "MARGINAL"))
    assert "VERDICT" in render(rep)
