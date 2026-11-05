"""edgefeed: find, price and track cross-venue prediction-market edges. Analytics only."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from decimal import Decimal

from edgefeed import pairs as pairs_mod
from edgefeed.config import Settings
from edgefeed.scanner import Scan, Scanner
from edgefeed.venues.kalshi import KalshiClient
from edgefeed.venues.polymarket import PolymarketClient


def _cents(x: Decimal | None) -> str:
    return "   -  " if x is None else f"{float(x) * 100:+6.2f}c"


def print_scan(scan: Scan, top: int) -> None:
    rows = sorted(scan.results, key=lambda r: r.spread if r.spread is not None else Decimal(-9), reverse=True)[:top]
    print(f"{'edge':>8}  {'size':>7}  {'profit':>9}  {'APR':>8}  {'w/carry':>7}  {'lock':>6}  pair")
    for r in rows:
        name = r.pair.label or r.pair.key
        if r.error:
            print(f"{'ERR':>8}  {'':>7}  {'':>9}  {'':>8}  {'':>7}  {'':>6}  {name}: {r.error[:70]}")
            continue
        o = r.opportunity
        if o is None:
            print(f"{_cents(r.spread):>8}  {'-':>7}  {'-':>9}  {'-':>8}  {'-':>7}  {'-':>6}  {name}")
            continue
        print(
            f"{_cents(r.spread):>8}  {o.contracts:7.0f}  ${o.profit:8.2f}  {float(o.apr) * 100:7.1f}%  "
            f"{float(o.total_apr) * 100:6.1f}%  "
            f"{o.lock_days:5.1f}d  {name}"
        )
    print(
        f"\n{len(scan.priced)} priced, {len(scan.failed)} failed, "
        f"{sum(1 for r in scan.results if r.opportunity)} with a locked edge, {scan.seconds:.1f}s",
        file=sys.stderr,
    )


async def _pairs_for(args: argparse.Namespace, k: KalshiClient, p: PolymarketClient) -> list[pairs_mod.Pair]:
    from edgefeed.discovery import sports

    out: list[pairs_mod.Pair] = []
    if not args.sports_only:
        out += pairs_mod.load(args.pairs)
    if args.sports or args.sports_only:
        found, cov = await sports.discover(k, p, args.leagues or None, days_ahead=args.days)
        for c in cov:
            print(f"  {c.league:<11} {c.matched_games:>3}/{c.kalshi_games:<3} games matched", file=sys.stderr)
        out += found
    return out


async def cmd_scan(args: argparse.Namespace) -> int:
    k, p = KalshiClient(), PolymarketClient()
    try:
        pairs = await _pairs_for(args, k, p)
        st = Settings()
        scan = await Scanner(k, p, kalshi_apy=st.kalshi_apy, poly_holding_apy=st.poly_holding_apy).scan(pairs)
    finally:
        await k.aclose()
        await p.aclose()
    if args.json:
        payload = [
            {
                "pair": r.pair.key,
                "label": r.pair.label,
                "spread_cents": None if r.spread is None else float(r.spread * 100),
                "opportunity": r.opportunity.as_dict() if r.opportunity else None,
                "error": r.error,
            }
            for r in scan.results
        ]
        json.dump(payload, sys.stdout, indent=2)
        print()
    else:
        print_scan(scan, args.top)
    return 0


async def cmd_discover(args: argparse.Namespace) -> int:
    from edgefeed.discovery import sports

    k, p = KalshiClient(), PolymarketClient()
    try:
        found, cov = await sports.discover(k, p, args.leagues or None, days_ahead=args.days)
    finally:
        await k.aclose()
        await p.aclose()
    for c in cov:
        print(
            f"{c.league:<11} {c.matched_games:>3}/{c.kalshi_games:<3} games  {c.pairs:>3} pairs",
            file=sys.stderr,
        )
    for pr in found:
        print(f"{pr.kalshi:<36} {pr.polymarket:>9}  {pr.outcome:<22} {pr.label}")
    return 0


async def cmd_collect(args: argparse.Namespace) -> int:
    from edgefeed.collector import Collector

    await Collector(Settings()).run(once=args.once)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from edgefeed.report import build, render
    from edgefeed.store import Store

    rep = build(Store(Settings().db_url), days=args.days)
    print(json.dumps(rep, indent=2, default=str) if args.json else render(rep))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("edgefeed.api:app", host=args.host, port=args.port, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ap = argparse.ArgumentParser(prog="edgefeed", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="price pairs once and print the table")
    s.add_argument("--pairs", default="config/pairs.yaml")
    s.add_argument("--sports", action="store_true", help="also match today's games across venues")
    s.add_argument("--sports-only", action="store_true")
    s.add_argument("--leagues", nargs="*", default=[])
    s.add_argument("--days", type=int, default=2)
    s.add_argument("--top", type=int, default=40)
    s.add_argument("--json", action="store_true")

    d = sub.add_parser("discover", help="list game pairs matched across venues")
    d.add_argument("--leagues", nargs="*", default=[])
    d.add_argument("--days", type=int, default=2)

    c = sub.add_parser("collect", help="run the collector loop (settings from EDGEFEED_* env)")
    c.add_argument("--once", action="store_true")

    r = sub.add_parser("report", help="go / no-go summary from the ledger")
    r.add_argument("--days", type=int, default=7)
    r.add_argument("--json", action="store_true")

    v = sub.add_parser("serve", help="HTTP API, dashboard and /metrics")
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--port", type=int, default=8090)

    args = ap.parse_args(argv)
    if args.cmd == "scan":
        return asyncio.run(cmd_scan(args))
    if args.cmd == "discover":
        return asyncio.run(cmd_discover(args))
    if args.cmd == "collect":
        return asyncio.run(cmd_collect(args))
    if args.cmd == "report":
        return cmd_report(args)
    if args.cmd == "serve":
        return cmd_serve(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
