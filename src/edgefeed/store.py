"""Persistence (SQLAlchemy Core): SQLite by default, Postgres via EDGEFEED_DB_URL.

The ledger is the point of the project: every scan, every pair's spread, and the full life of
each opportunity (when it opened, how long it lasted, how big it got) so the go/no-go question
is answered with data rather than one lucky snapshot.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Engine,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    event,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Connection

meta = MetaData()


def _ts() -> Column[datetime]:
    return Column("ts", DateTime(timezone=True), nullable=False, index=True)


scans = Table(
    "scans",
    meta,
    Column("id", Integer, primary_key=True),
    Column("started_at", DateTime(timezone=True), nullable=False, index=True),
    Column("seconds", Float, nullable=False),
    Column("pairs", Integer, nullable=False),
    Column("priced", Integer, nullable=False),
    Column("failed", Integer, nullable=False),
    Column("opportunities", Integer, nullable=False),
)

pairs = Table(
    "pairs",
    meta,
    Column("key", String(200), primary_key=True),
    Column("kalshi", String(100), nullable=False),
    Column("polymarket", String(64), nullable=False),
    Column("outcome", String(100), nullable=False),
    Column("relation", String(16), nullable=False),
    Column("label", String(300), nullable=False),
    Column("source", String(16), nullable=False),
    Column("rule_risk", Text, nullable=False, default=""),
    Column("closes_at", DateTime(timezone=True)),
    Column("first_seen", DateTime(timezone=True), nullable=False),
    Column("last_seen", DateTime(timezone=True), nullable=False),
)

quotes = Table(
    "quotes",
    meta,
    Column("id", Integer, primary_key=True),
    Column("scan_id", Integer, ForeignKey("scans.id", ondelete="CASCADE"), nullable=False),
    _ts(),
    Column("pair_key", String(200), nullable=False),
    Column("spread_cents", Float),
    Column("k_yes", Float),
    Column("k_no", Float),
    Column("p_yes", Float),
    Column("p_no", Float),
    Column("k_mid", Float),
    Column("p_mid", Float),
    Index("ix_quotes_pair_ts", "pair_key", "ts"),
)

opportunities = Table(
    "opportunities",
    meta,
    Column("id", Integer, primary_key=True),
    Column("kind", String(16), nullable=False),  # cross
    Column("pair_key", String(200), nullable=False, index=True),
    Column("label", String(300), nullable=False),
    Column("source", String(16), nullable=False),
    Column("direction", String(80), nullable=False),
    Column("opened_at", DateTime(timezone=True), nullable=False, index=True),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("closed_at", DateTime(timezone=True), index=True),
    Column("scans_seen", Integer, nullable=False, default=1),
    Column("first_cents", Float, nullable=False),
    Column("best_cents", Float, nullable=False),
    Column("best_profit", Float, nullable=False),
    Column("best_contracts", Float, nullable=False),
    Column("best_apr", Float, nullable=False),
    Column("lock_days", Float, nullable=False),
    Column("warnings", Text, nullable=False, default="[]"),
    Column("best_snapshot", Text, nullable=False),
)

signals = Table(
    "signals",
    meta,
    Column("id", Integer, primary_key=True),
    _ts(),
    Column("pair_key", String(200), nullable=False, index=True),
    Column("label", String(300), nullable=False),
    Column("leader", String(16), nullable=False),
    Column("laggard", String(16), nullable=False),
    Column("leader_move", Float, nullable=False),
    Column("laggard_move", Float, nullable=False),
    Column("gap", Float, nullable=False),
    Column("leader_mid", Float, nullable=False),
    Column("laggard_mid", Float, nullable=False),
    Column("graded_at", DateTime(timezone=True)),
    Column("laggard_mid_after", Float),
    Column("convergence", Float),
    Column("outcome", String(16)),
)

rules = Table(
    "rules",
    meta,
    Column("market", String(120), primary_key=True),  # "kalshi:TICKER" / "polymarket:ID"
    Column("fingerprint", String(32), nullable=False),
    Column("text", Text, nullable=False),
    Column("first_seen", DateTime(timezone=True), nullable=False),
    Column("last_seen", DateTime(timezone=True), nullable=False),
)

events = Table(
    "events",
    meta,
    Column("id", Integer, primary_key=True),
    _ts(),
    Column("kind", String(32), nullable=False),  # rules_changed | pair_dropped | ...
    Column("subject", String(200), nullable=False),
    Column("detail", Text, nullable=False),
)


def _sqlite_pragmas(dbapi_conn: Any, _: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


def as_utc(v: datetime | None) -> datetime | None:
    """SQLite hands datetimes back naive; everything we store is UTC."""
    if v is None:
        return None
    return v if v.tzinfo else v.replace(tzinfo=UTC)


class Store:
    def __init__(self, url: str = "sqlite:///edgefeed.sqlite") -> None:
        self.engine: Engine = create_engine(url, future=True, pool_pre_ping=True)
        if self.engine.dialect.name == "sqlite":
            event.listen(self.engine, "connect", _sqlite_pragmas)
        meta.create_all(self.engine)

    @contextmanager
    def tx(self) -> Iterator[Connection]:
        with self.engine.begin() as conn:
            yield conn

    # ---- writes ---------------------------------------------------------------------------

    def record_scan(
        self,
        conn: Connection,
        started_at: datetime,
        seconds: float,
        n: int,
        priced: int,
        failed: int,
        opps: int,
    ) -> int:
        res = conn.execute(
            insert(scans).values(
                started_at=started_at,
                seconds=seconds,
                pairs=n,
                priced=priced,
                failed=failed,
                opportunities=opps,
            )
        )
        return int(res.inserted_primary_key[0])  # type: ignore[index]

    def upsert_pair(self, conn: Connection, row: dict[str, Any], now: datetime) -> None:
        existing = conn.execute(select(pairs.c.key).where(pairs.c.key == row["key"])).first()
        if existing:
            conn.execute(update(pairs).where(pairs.c.key == row["key"]).values(**row, last_seen=now))
        else:
            conn.execute(insert(pairs).values(**row, first_seen=now, last_seen=now))

    def record_quotes(self, conn: Connection, rows: list[dict[str, Any]]) -> None:
        if rows:
            conn.execute(insert(quotes), rows)

    def open_opportunity(self, conn: Connection, row: dict[str, Any]) -> int:
        res = conn.execute(insert(opportunities).values(**row))
        return int(res.inserted_primary_key[0])  # type: ignore[index]

    def touch_opportunity(
        self, conn: Connection, opp_id: int, seen_at: datetime, better: dict[str, Any] | None
    ) -> None:
        values: dict[str, Any] = {"last_seen_at": seen_at, "scans_seen": opportunities.c.scans_seen + 1}
        if better:
            values.update(better)
        conn.execute(update(opportunities).where(opportunities.c.id == opp_id).values(**values))

    def close_opportunity(self, conn: Connection, opp_id: int, closed_at: datetime) -> None:
        conn.execute(update(opportunities).where(opportunities.c.id == opp_id).values(closed_at=closed_at))

    def open_ids(self, conn: Connection) -> dict[str, tuple[int, float]]:
        rows = conn.execute(
            select(opportunities.c.pair_key, opportunities.c.id, opportunities.c.best_cents).where(
                opportunities.c.closed_at.is_(None)
            )
        )
        return {r.pair_key: (r.id, r.best_cents) for r in rows}

    def check_rules(self, conn: Connection, market: str, fingerprint: str, text: str, now: datetime) -> str | None:
        """Store a rules fingerprint; return the previous fingerprint if the text changed."""
        row = conn.execute(select(rules.c.fingerprint).where(rules.c.market == market)).first()
        if row is None:
            conn.execute(
                insert(rules).values(market=market, fingerprint=fingerprint, text=text, first_seen=now, last_seen=now)
            )
            return None
        if row.fingerprint == fingerprint:
            conn.execute(update(rules).where(rules.c.market == market).values(last_seen=now))
            return None
        conn.execute(
            update(rules).where(rules.c.market == market).values(fingerprint=fingerprint, text=text, last_seen=now)
        )
        return str(row.fingerprint)

    def add_event(self, conn: Connection, kind: str, subject: str, detail: str, now: datetime) -> None:
        conn.execute(insert(events).values(ts=now, kind=kind, subject=subject, detail=detail))

    def add_signal(self, conn: Connection, row: dict[str, Any]) -> int:
        res = conn.execute(insert(signals).values(**row))
        return int(res.inserted_primary_key[0])  # type: ignore[index]

    def grade_signal(self, conn: Connection, sig_id: int, values: dict[str, Any]) -> None:
        conn.execute(update(signals).where(signals.c.id == sig_id).values(**values))

    def ungraded_signals(self, conn: Connection) -> list[dict[str, Any]]:
        rows = conn.execute(select(signals).where(signals.c.outcome.is_(None)))
        return [dict(r._mapping) for r in rows]

    def prune_quotes(self, conn: Connection, keep_days: int) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=keep_days)
        res = conn.execute(delete(quotes).where(quotes.c.ts < cutoff))
        return int(res.rowcount or 0)

    # ---- reads ----------------------------------------------------------------------------

    def opportunities(
        self, conn: Connection, *, open_only: bool = False, limit: int = 200, since: datetime | None = None
    ) -> list[dict[str, Any]]:
        q = select(opportunities).order_by(opportunities.c.opened_at.desc()).limit(limit)
        if open_only:
            q = q.where(opportunities.c.closed_at.is_(None))
        if since:
            q = q.where(opportunities.c.opened_at >= since)
        out = []
        for r in conn.execute(q):
            d = dict(r._mapping)
            for k in ("opened_at", "last_seen_at", "closed_at"):
                d[k] = as_utc(d[k])
            d["warnings"] = json.loads(d["warnings"] or "[]")
            d["best_snapshot"] = json.loads(d["best_snapshot"] or "{}")
            out.append(d)
        return out

    def latest_quotes(self, conn: Connection) -> list[dict[str, Any]]:
        last = conn.execute(select(func.max(scans.c.id))).scalar()
        if last is None:
            return []
        q = (
            select(quotes, pairs.c.label, pairs.c.source, pairs.c.closes_at, pairs.c.rule_risk)
            .join(pairs, pairs.c.key == quotes.c.pair_key, isouter=True)
            .where(quotes.c.scan_id == last)
            .order_by(quotes.c.spread_cents.desc())
        )
        return [dict(r._mapping) for r in conn.execute(q)]

    def series(self, conn: Connection, pair_key: str, since: datetime) -> list[dict[str, Any]]:
        q = (
            select(quotes.c.ts, quotes.c.spread_cents, quotes.c.k_mid, quotes.c.p_mid)
            .where(quotes.c.pair_key == pair_key, quotes.c.ts >= since)
            .order_by(quotes.c.ts)
        )
        return [dict(r._mapping) for r in conn.execute(q)]

    def recent_scans(self, conn: Connection, limit: int = 100) -> list[dict[str, Any]]:
        q = select(scans).order_by(scans.c.id.desc()).limit(limit)
        return [dict(r._mapping) for r in conn.execute(q)]

    def recent_signals(self, conn: Connection, limit: int = 100) -> list[dict[str, Any]]:
        q = select(signals).order_by(signals.c.ts.desc()).limit(limit)
        return [dict(r._mapping) for r in conn.execute(q)]

    def recent_events(self, conn: Connection, limit: int = 100) -> list[dict[str, Any]]:
        q = select(events).order_by(events.c.ts.desc()).limit(limit)
        return [dict(r._mapping) for r in conn.execute(q)]
