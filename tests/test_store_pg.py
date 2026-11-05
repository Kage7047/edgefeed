"""The ledger flow again, on Postgres. CI sets EDGEFEED_TEST_PG_URL; locally it is skipped."""

import os

import pytest

from edgefeed.collector import Ledger
from edgefeed.config import Settings
from edgefeed.report import build
from edgefeed.store import Store, meta
from tests.conftest import NOW
from tests.test_ledger import result, scan_at

URL = os.environ.get("EDGEFEED_TEST_PG_URL")
pytestmark = [pytest.mark.pg, pytest.mark.skipif(not URL, reason="EDGEFEED_TEST_PG_URL not set")]


@pytest.fixture
def pg():
    s = Store(URL)
    yield s
    meta.drop_all(s.engine)


def test_ledger_on_postgres(pg):
    led = Ledger(pg, Settings())
    led.apply(scan_at(0, result()))
    led.apply(scan_at(1, result(p_no="0.45")))
    out = led.apply(scan_at(2, result(k_yes="0.55", p_no="0.46")))
    assert out.closed
    with pg.tx() as conn:
        (row,) = pg.opportunities(conn)
        assert row["closed_at"].tzinfo is not None and row["scans_seen"] == 2
        assert pg.latest_quotes(conn, now=NOW)
    assert build(pg, now=NOW)["opportunities"]["total"] == 1
