"""The always-on loop: discover pairs, scan, keep the ledger, alert.

``Ledger.apply`` is the whole bookkeeping step for one scan and has no I/O besides the store,
so it is what the tests drive. ``Collector`` adds the clock, discovery and the venue clients.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy.engine import Connection

from edgefeed import metrics
from edgefeed import pairs as pairs_mod
from edgefeed.alerts import Notifier, format_opportunity, notifier
from edgefeed.config import Settings
from edgefeed.discovery import sports
from edgefeed.latency import Detector, grade
from edgefeed.models import ONE, Book, Side
from edgefeed.pairs import Pair, fingerprint
from edgefeed.scanner import PairResult, Scan, Scanner
from edgefeed.store import Store, as_utc
from edgefeed.venues.kalshi import KalshiClient
from edgefeed.venues.polymarket import PolymarketClient

log = logging.getLogger("edgefeed.collector")


def _f(x: Decimal | None) -> float | None:
    return None if x is None else float(x)


def _yes_mid_cents(book: Book) -> float | None:
    m = book.mid()
    return None if m is None else float(m * 100)


def _poly_yes_mid_cents(book: Book, relation_inverse: bool) -> float | None:
    m = book.mid()
    if m is None:
        return None
    return float((ONE - m) * 100) if relation_inverse else float(m * 100)


@dataclass(slots=True)
class Outcome:
    opened: list[int] = field(default_factory=list)
    closed: list[int] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    signals: list[int] = field(default_factory=list)
    rule_changes: list[str] = field(default_factory=list)


class Ledger:
    def __init__(self, store: Store, settings: Settings, detector: Detector | None = None) -> None:
        self.store = store
        self.s = settings
        self.detector = detector or Detector()

    def qualifies(self, r: PairResult) -> bool:
        o = r.opportunity
        return bool(o and o.per_contract * 100 >= self.s.min_edge_cents and o.profit >= self.s.min_profit)

    def alertable(self, r: PairResult) -> bool:
        o = r.opportunity
        return bool(o and o.apr >= self.s.alert_min_apr and o.profit >= self.s.alert_min_profit)

    def apply(self, scan: Scan, *, clock: float | None = None) -> Outcome:
        out = Outcome()
        now = scan.started_at
        ts = clock if clock is not None else time.time()
        with self.store.tx() as conn:
            winners = [r for r in scan.results if self.qualifies(r)]
            scan_id = self.store.record_scan(
                conn, now, scan.seconds, len(scan.results), len(scan.priced), len(scan.failed), len(winners)
            )
            quote_rows = []
            for r in scan.results:
                p = r.pair
                closes = None
                if r.kalshi and r.poly:
                    closes = max((c for c in (r.kalshi.closes_at, r.poly.closes_at) if c), default=None)
                self.store.upsert_pair(
                    conn,
                    {
                        "key": p.key,
                        "kalshi": p.kalshi,
                        "polymarket": p.polymarket,
                        "outcome": p.outcome,
                        "relation": p.relation.value,
                        "label": p.label or p.key,
                        "source": p.source,
                        "rule_risk": p.rule_risk,
                        "closes_at": closes,
                    },
                    now,
                )
                if r.kalshi is None or r.poly is None:
                    continue
                inverse = p.relation.value == "inverse"
                k_mid, p_mid = _yes_mid_cents(r.kalshi), _poly_yes_mid_cents(r.poly, inverse)
                quote_rows.append(
                    {
                        "scan_id": scan_id,
                        "ts": now,
                        "pair_key": p.key,
                        "spread_cents": None if r.spread is None else float(r.spread * 100),
                        "k_yes": _f(b.price) if (b := r.kalshi.best(Side.YES)) else None,
                        "k_no": _f(b.price) if (b := r.kalshi.best(Side.NO)) else None,
                        "p_yes": _f(b.price) if (b := r.poly.best(Side.YES)) else None,
                        "p_no": _f(b.price) if (b := r.poly.best(Side.NO)) else None,
                        "k_mid": k_mid,
                        "p_mid": p_mid,
                    }
                )
                if r.spread is not None:
                    metrics.best_edge_cents.labels(p.key).set(float(r.spread * 100))
                for book in (r.kalshi, r.poly):
                    if book.rules:
                        market = f"{book.venue.value}:{book.market_id}"
                        old = self.store.check_rules(conn, market, fingerprint(book.rules), book.rules, now)
                        if old:
                            msg = f"rules changed for {market} ({p.label or p.key}); re-verify the pair"
                            self.store.add_event(conn, "rules_changed", market, msg, now)
                            out.rule_changes.append(market)
                            out.alerts.append(f"RULES CHANGED\n{msg}")
                sig = self.detector.observe(p.key, ts, k_mid, p_mid)
                if sig:
                    sid = self.store.add_signal(
                        conn,
                        {
                            "ts": now,
                            "pair_key": p.key,
                            "label": p.label or p.key,
                            "leader": sig.leader,
                            "laggard": sig.laggard,
                            "leader_move": sig.leader_move,
                            "laggard_move": sig.laggard_move,
                            "gap": sig.gap,
                            "leader_mid": sig.leader_mid,
                            "laggard_mid": sig.laggard_mid,
                        },
                    )
                    out.signals.append(sid)
                    metrics.signals_fired.labels(sig.leader).inc()
                    if self.s.latency_alerts:
                        out.alerts.append(
                            f"LEAD-LAG {p.label or p.key}\n{sig.leader} moved {sig.leader_move:+.1f}c, "
                            f"{sig.laggard} still {sig.gap:.1f}c away"
                        )
            self.store.record_quotes(conn, quote_rows)
            self._grade(conn, now)

            open_now = self.store.open_ids(conn)
            seen: set[str] = set()
            for r in winners:
                o = r.opportunity
                assert o is not None
                key = r.pair.key
                seen.add(key)
                cents = float(o.per_contract * 100)
                snap = o.as_dict()
                if key in open_now:
                    opp_id, best = open_now[key]
                    better = None
                    if cents > best:
                        better = {
                            "best_cents": cents,
                            "best_profit": float(o.profit),
                            "best_contracts": float(o.contracts),
                            "best_apr": float(o.apr),
                            "best_snapshot": json.dumps(snap),
                        }
                    self.store.touch_opportunity(conn, opp_id, now, better)
                else:
                    opp_id = self.store.open_opportunity(
                        conn,
                        {
                            "kind": "cross",
                            "pair_key": key,
                            "label": r.pair.label or key,
                            "source": r.pair.source,
                            "direction": o.direction,
                            "opened_at": now,
                            "last_seen_at": now,
                            "scans_seen": 1,
                            "first_cents": cents,
                            "best_cents": cents,
                            "best_profit": float(o.profit),
                            "best_contracts": float(o.contracts),
                            "best_apr": float(o.apr),
                            "lock_days": float(o.lock_days),
                            "warnings": json.dumps(o.warnings),
                            "best_snapshot": json.dumps(snap),
                        },
                    )
                    out.opened.append(opp_id)
                    metrics.opportunities_opened.labels("cross").inc()
                    if self.alertable(r):
                        out.alerts.append(format_opportunity(snap, r.pair.label or key))
            failed = {r.pair.key for r in scan.failed}
            for key, (opp_id, _) in open_now.items():
                # a pair that failed to fetch this round is unknown, not closed
                if key not in seen and key not in failed:
                    self.store.close_opportunity(conn, opp_id, now)
                    out.closed.append(opp_id)
            metrics.open_opportunities.labels("cross").set(len(open_now) - len(out.closed) + len(out.opened))
        return out

    def _grade(self, conn: Connection, now: datetime) -> None:
        for sig in self.store.ungraded_signals(conn):
            fired = as_utc(sig["ts"])
            if fired is None or (now - fired).total_seconds() < self.detector.cfg.followup:
                continue
            lag_now = self.detector.latest(sig["pair_key"], sig["laggard"])
            if lag_now is None:
                continue
            frac, outcome = grade(sig["leader_mid"], sig["laggard_mid"], lag_now, self.detector.cfg.hit_frac)
            self.store.grade_signal(
                conn,
                sig["id"],
                {
                    "graded_at": now,
                    "laggard_mid_after": lag_now,
                    "convergence": frac,
                    "outcome": outcome,
                },
            )


class Collector:
    def __init__(self, settings: Settings | None = None) -> None:
        self.s = settings or Settings()
        self.store = Store(self.s.db_url)
        self.kalshi = KalshiClient()
        self.poly = PolymarketClient()
        self.scanner = Scanner(self.kalshi, self.poly, max_contracts=self.s.max_contracts)
        self.ledger = Ledger(self.store, self.s)
        self.notify: Notifier = notifier(self.s.telegram_token, self.s.telegram_chat)
        self._curated: list[Pair] = []
        self._curated_mtime = 0.0
        self._sports: list[Pair] = []
        self._last_discovery = 0.0
        self._last_prune = 0.0

    def curated(self) -> list[Pair]:
        path = Path(self.s.pairs_file)
        if path.exists() and path.stat().st_mtime != self._curated_mtime:
            try:
                self._curated = pairs_mod.load(path)
                self._curated_mtime = path.stat().st_mtime
                log.info("loaded %d curated pairs from %s", len(self._curated), path)
            except (ValueError, OSError) as e:  # keep the last good list on a bad edit
                log.error("pairs file rejected, keeping previous list: %s", e)
        return self._curated

    async def refresh_sports(self) -> None:
        if not self.s.sports or time.monotonic() - self._last_discovery < self.s.discovery_every:
            return
        self._last_discovery = time.monotonic()
        try:
            found, cov = await sports.discover(
                self.kalshi, self.poly, self.s.sports, days_ahead=self.s.sports_days_ahead
            )
        except Exception as e:
            log.warning("sports discovery failed, keeping %d pairs: %s", len(self._sports), e)
            return
        self._sports = found
        log.info("sports discovery: %s", ", ".join(f"{c.league} {c.matched_games}/{c.kalshi_games}" for c in cov))

    async def tick(self) -> Outcome:
        await self.refresh_sports()
        pairs = self.curated() + self._sports
        t0 = time.perf_counter()
        scan = await self.scanner.scan(pairs)
        metrics.scan_seconds.observe(time.perf_counter() - t0)
        metrics.pairs_priced.set(len(scan.priced))
        metrics.pairs_failed.set(len(scan.failed))
        out = self.ledger.apply(scan)
        metrics.scans.labels("ok").inc()
        metrics.last_scan_ts.set(time.time())
        for text in out.alerts:
            await self.notify.send(text)
        if time.monotonic() - self._last_prune > 3600:
            self._last_prune = time.monotonic()
            with self.store.tx() as conn:
                self.store.prune_quotes(conn, self.s.keep_quotes_days)
        log.info(
            "scan: %d pairs, %d priced, %d failed, %d opened, %d closed, %d signals, %.1fs",
            len(scan.results),
            len(scan.priced),
            len(scan.failed),
            len(out.opened),
            len(out.closed),
            len(out.signals),
            scan.seconds,
        )
        return out

    async def run(self, *, once: bool = False, stop: asyncio.Event | None = None) -> None:
        stop = stop or asyncio.Event()
        if self.s.metrics_port and not once:
            from prometheus_client import start_http_server

            start_http_server(self.s.metrics_port)
            log.info("metrics on :%d/metrics", self.s.metrics_port)
        try:
            while not stop.is_set():
                started = time.monotonic()
                try:
                    await self.tick()
                except Exception:
                    metrics.scans.labels("error").inc()
                    log.exception("scan failed")
                if once:
                    return
                delay = max(1.0, self.s.interval - (time.monotonic() - started))
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=delay)
        finally:
            await self.kalshi.aclose()
            await self.poly.aclose()
