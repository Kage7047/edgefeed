"""Prometheus metrics. Scraped from the API's /metrics endpoint."""

from prometheus_client import Counter, Gauge, Histogram

http_requests = Counter("edgefeed_http_requests_total", "Venue API requests", ["venue", "status"])
http_latency = Histogram(
    "edgefeed_http_latency_seconds",
    "Venue API latency",
    ["venue"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)
scan_seconds = Histogram("edgefeed_scan_seconds", "Wall time of one full scan", buckets=(0.5, 1, 2, 5, 10, 20, 40, 80))
scans = Counter("edgefeed_scans_total", "Completed scans", ["outcome"])
pairs_priced = Gauge("edgefeed_pairs_priced", "Pairs priced in the last scan")
pairs_failed = Gauge("edgefeed_pairs_failed", "Pairs that could not be priced in the last scan")
open_opportunities = Gauge("edgefeed_open_opportunities", "Opportunities open right now", ["kind"])
best_edge_cents = Gauge("edgefeed_best_edge_cents", "Best top-of-book net edge per pair (cents)", ["pair"])
opportunities_opened = Counter("edgefeed_opportunities_opened_total", "Opportunities opened", ["kind"])
signals_fired = Counter("edgefeed_latency_signals_total", "Lead-lag signals fired", ["leader"])
alerts_sent = Counter("edgefeed_alerts_sent_total", "Alerts delivered", ["channel", "outcome"])
last_scan_ts = Gauge("edgefeed_last_scan_timestamp", "Unix time of the last completed scan")
