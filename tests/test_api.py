from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from edgefeed.api import create_app
from edgefeed.collector import Ledger
from edgefeed.config import Settings
from edgefeed.scanner import Scan
from tests.test_ledger import result


def test_health_is_503_until_a_fresh_scan(store):
    c = TestClient(create_app(store))
    assert c.get("/healthz").status_code == 503
    Ledger(store, Settings()).apply(Scan(datetime.now(UTC), 1.0, [result()]))
    assert c.get("/healthz").json()["status"] == "ok"


def test_endpoints(store):
    Ledger(store, Settings()).apply(Scan(datetime.now(UTC) - timedelta(minutes=1), 1.0, [result()]))
    c = TestClient(create_app(store))
    pairs = c.get("/api/pairs").json()
    assert pairs[0]["pair_key"] == "K1<>P1"
    assert c.get("/api/pairs/K1<>P1/series", params={"hours": 1}).json()
    opps = c.get("/api/opportunities", params={"status": "open"}).json()
    assert opps[0]["best_snapshot"]["legs"]
    assert c.get("/api/scans").json()[0]["priced"] == 1
    assert c.get("/api/report").json()["verdict"].startswith("TOO EARLY")
    assert c.get("/api/opportunities", params={"status": "bogus"}).status_code == 422
    assert c.get("/metrics").status_code == 200
