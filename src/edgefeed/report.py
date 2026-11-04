"""Go / no-go summary from the ledger.

The question the project exists to answer: do edges that survive real fees and depth show up
often enough, last long enough to act on, and pay enough per dollar locked to be worth it?
"""

from __future__ import annotations

import statistics
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from edgefeed.store import Store, as_utc, scans, signals

# An edge is "actionable" if it was still there on a second scan, and "worth it" if it beats a
# 10% annualised return on the capital it locks (well above a T-bill) with at least $5 of profit.
WORTH_APR = 0.10
WORTH_PROFIT = 5.0
GO_PER_DAY = 3.0


def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * (len(xs) - 1) + 0.5))]


def build(store: Store, days: int = 7, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    since = now - timedelta(days=days)
    with store.tx() as conn:
        n_scans, first, last, avg_s = conn.execute(
            select(
                func.count(),
                func.min(scans.c.started_at),
                func.max(scans.c.started_at),
                func.avg(scans.c.seconds),
            ).where(scans.c.started_at >= since)
        ).one()
        opps = store.opportunities(conn, since=since, limit=100_000)
        sig_rows = [dict(r._mapping) for r in conn.execute(select(signals).where(signals.c.ts >= since))]

    first, last = as_utc(first), as_utc(last)
    observed_days = max(((last - first).total_seconds() / 86400) if first and last else 0.0, 1 / 24)

    def duration(o: dict[str, Any]) -> float:
        end = o["closed_at"] or o["last_seen_at"]
        return float((end - o["opened_at"]).total_seconds())

    actionable = [o for o in opps if o["scans_seen"] >= 2]
    worth = [o for o in actionable if o["best_apr"] >= WORTH_APR and o["best_profit"] >= WORTH_PROFIT]
    by_source: dict[str, int] = {}
    for o in opps:
        by_source[o["source"]] = by_source.get(o["source"], 0) + 1
    durations = [duration(o) for o in opps if o["closed_at"]]

    graded = [s for s in sig_rows if s["outcome"]]
    hits = [s for s in graded if s["outcome"] == "hit"]
    worth_per_day = len(worth) / observed_days

    if n_scans == 0:
        verdict = "NO DATA: run `edgefeed collect` first."
    elif observed_days < 3:
        verdict = f"TOO EARLY: {observed_days:.1f} days observed; the gate needs at least 3, ideally 7."
    elif worth_per_day >= GO_PER_DAY:
        verdict = f"GO: {worth_per_day:.1f} worth-it, actionable edges per day."
    elif worth:
        verdict = f"MARGINAL: {worth_per_day:.1f} worth-it edges per day (gate is {GO_PER_DAY:.0f})."
    else:
        verdict = "NO-GO for arb: no edge was both actionable and worth the capital it locks."

    return {
        "window_days": days,
        "observed_days": round(observed_days, 2),
        "scans": n_scans,
        "avg_scan_seconds": round(float(avg_s or 0), 2),
        "opportunities": {
            "total": len(opps),
            "open_now": sum(1 for o in opps if o["closed_at"] is None),
            "actionable": len(actionable),
            "worth_it": len(worth),
            "worth_it_per_day": round(worth_per_day, 2),
            "by_source": by_source,
            "median_duration_s": statistics.median(durations) if durations else None,
            "p90_duration_s": _pct(durations, 0.9),
            "best_cents_p50": _pct([o["best_cents"] for o in opps], 0.5),
            "best_cents_max": max((o["best_cents"] for o in opps), default=None),
            "profit_sum_at_best": round(sum(o["best_profit"] for o in worth), 2),
        },
        "top": sorted(worth or actionable or opps, key=lambda o: -o["best_profit"])[:10],
        "latency": {
            "signals": len(sig_rows),
            "graded": len(graded),
            "hit_rate": round(len(hits) / len(graded), 3) if graded else None,
        },
        "verdict": verdict,
    }


def render(rep: dict[str, Any]) -> str:
    o, lat = rep["opportunities"], rep["latency"]
    lines = [
        f"EdgeFeed report, last {rep['window_days']}d ({rep['observed_days']}d observed, {rep['scans']} scans,"
        f" {rep['avg_scan_seconds']}s/scan)",
        "",
        f"  opportunities      {o['total']}  (open now {o['open_now']}, by source {o['by_source']})",
        f"  actionable (2+ scans)  {o['actionable']}",
        f"  worth it (>= {WORTH_APR:.0%} APR, >= ${WORTH_PROFIT:.0f})  {o['worth_it']}  ({o['worth_it_per_day']}/day)",
        f"  duration median / p90  {o['median_duration_s']} / {o['p90_duration_s']} s",
        f"  best edge p50 / max    {o['best_cents_p50']} / {o['best_cents_max']} c per contract",
        f"  profit at best size (worth-it only)  ${o['profit_sum_at_best']}",
        "",
        f"  lead-lag signals   {lat['signals']} fired, {lat['graded']} graded, hit rate {lat['hit_rate']}",
        "",
    ]
    for t in rep["top"][:5]:
        lines.append(
            f"  {t['best_cents']:6.2f}c  ${t['best_profit']:8.2f}  {t['best_apr'] * 100:7.1f}% APR"
            f"  {t['scans_seen']:>4} scans  {t['label'][:60]}"
        )
    lines += ["", f"VERDICT: {rep['verdict']}", "Analytics only, not financial advice."]
    return "\n".join(lines)
