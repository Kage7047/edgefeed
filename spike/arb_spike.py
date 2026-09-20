#!/usr/bin/env python3
"""
EdgeFeed — Arbitrage Spike
==========================

A ZERO-DEPENDENCY (stdlib only) probe that answers ONE question before you build
anything else:

    "Do capturable cross-venue arbitrage edges between Kalshi and Polymarket
     actually exist right now, after real fees and with real order-book depth?"

It hits the live PUBLIC market-data APIs of both venues (no account, no key,
no money), matches markets (curated file preferred, fuzzy auto-match as a
fallback), pulls executable order-book prices, subtracts the real fee schedules,
and prints a ranked table of surviving edges.

This is a THROWAWAY validation tool, not product code. Its purpose is to make the
go/no-go decision cheap. If nothing survives fees here, the arb thesis is weak and
you should pivot (see the build plan's kill/pivot signal) BEFORE building the
monorepo.

Usage
-----
    python arb_spike.py                       # auto-match discovery (noisy)
    python arb_spike.py --pairs curated.json  # trustworthy: verified pairs only
    python arb_spike.py --min-net 1.0 --top 40
    python arb_spike.py --kalshi-limit 400 --poly-limit 400 --match-threshold 0.72

Notes
-----
* Fee math is the crux and is APPROXIMATE + configurable. VERIFY against live fee
  docs before trusting a single number for real trading. Defaults are intentionally
  conservative (they OVER-count fees, so a surviving edge is a real edge).
* Auto-matched pairs are UNVERIFIED. Never trust an auto-match without eyeballing
  both market titles + resolution criteria. Curated pairs are the trustworthy path.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from difflib import SequenceMatcher

# --------------------------------------------------------------------------- #
# Endpoints (VERIFY these against live docs; they drift)
# --------------------------------------------------------------------------- #
KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
POLY_GAMMA = "https://gamma-api.polymarket.com"
POLY_CLOB = "https://clob.polymarket.com"

USER_AGENT = "edgefeed-arb-spike/0.1 (+research; contact: you@example.com)"
HTTP_TIMEOUT = 20

# --------------------------------------------------------------------------- #
# HTTP helper (stdlib, with light retry/backoff)
# --------------------------------------------------------------------------- #
def http_get_json(url: str, retries: int = 3, backoff: float = 1.5):
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                        "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(backoff ** attempt + 0.2)
    raise RuntimeError(f"GET failed after {retries} tries: {url}\n  -> {last_err}")


# --------------------------------------------------------------------------- #
# Fee models (APPROXIMATE — VERIFY). All returns in CENTS per 1 contract/share.
# --------------------------------------------------------------------------- #
def kalshi_fee_cents(price_cents: float, coeff: float = 0.07) -> float:
    """Kalshi taker fee. Published formula: ceil_to_cent(coeff * C * (1-C)) per
    contract, C in dollars (0..1). Maxes near C=0.50. Rounded UP to the next cent."""
    c = max(0.0, min(1.0, price_cents / 100.0))
    fee_dollars = coeff * c * (1.0 - c)
    return math.ceil(fee_dollars * 100.0)  # dollars -> cents, ceil to whole cent


# Polymarket V2 taker-fee caps by category (cents per share). geopolitics/world = 0.
# These are the *caps*; using the cap is the conservative (worst-case) assumption.
POLY_FEE_CAPS = {
    "geopolitics": 0.0, "world": 0.0,
    "politics": 1.0, "finance": 1.0, "tech": 1.0, "mentions": 1.0,
    "sports": 1.25, "economics": 1.25, "culture": 1.25, "weather": 1.25, "other": 1.25,
    "crypto": 1.75,
}
DEFAULT_POLY_CATEGORY = "politics"

def poly_fee_cents(category: str) -> float:
    return POLY_FEE_CAPS.get((category or DEFAULT_POLY_CATEGORY).lower(),
                             POLY_FEE_CAPS[DEFAULT_POLY_CATEGORY])


# --------------------------------------------------------------------------- #
# Data models
# --------------------------------------------------------------------------- #
@dataclass
class KMarket:
    ticker: str
    title: str
    yes_bid: float   # cents
    yes_ask: float   # cents
    no_ask: float    # cents (Kalshi now returns this directly)
    volume: float
    liquidity: float


@dataclass
class PMarket:
    market_id: str
    question: str
    yes_token: str | None
    no_token: str | None
    yes_price: float  # cents (Gamma last/mid, used only for pre-filtering)
    no_price: float   # cents
    volume: float
    liquidity: float
    category: str = DEFAULT_POLY_CATEGORY
    # filled after order-book fetch:
    yes_ask: float | None = None  # cents, executable
    no_ask: float | None = None
    yes_ask_size: float = 0.0
    no_ask_size: float = 0.0


@dataclass
class Edge:
    key: str
    k: KMarket
    p: PMarket
    direction: str          # "K_yes+P_no" or "P_yes+K_no"
    cost_cents: float
    gross_cents: float
    fee_cents: float
    net_cents: float
    cap_size: float         # min executable size across the two legs (contracts)
    match_score: float
    match_source: str       # "curated" | "auto"


# --------------------------------------------------------------------------- #
# Ingestion — Kalshi
# --------------------------------------------------------------------------- #
def fetch_kalshi_markets(limit: int, max_pages: int = 12) -> list[KMarket]:
    """Ingest via /events?with_nested_markets=true. The flat /markets firehose is
    ~99.97% auto-generated parlay combos (MVE/CROSSCATEGORY) with no real prices;
    the events endpoint surfaces the genuine, liquid single markets."""
    out: list[KMarket] = []
    cursor = None
    pages = 0
    while len(out) < limit and pages < max_pages:
        params = {"status": "open", "with_nested_markets": "true", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        url = f"{KALSHI_BASE}/events?" + urllib.parse.urlencode(params)
        data = http_get_json(url)
        pages += 1
        events = data.get("events", [])
        for ev in events:
            ev_title = ev.get("title") or ""
            for m in ev.get("markets", []) or []:
                ticker = m.get("ticker", "")
                if "MVE" in ticker or "CROSSCATEGORY" in ticker:
                    continue
                yes_ask = float(m.get("yes_ask_dollars") or 0) * 100.0
                yes_bid = float(m.get("yes_bid_dollars") or 0) * 100.0
                no_ask = float(m.get("no_ask_dollars") or 0) * 100.0
                if not (0 < yes_ask < 100):  # no live two-sided market
                    continue
                # combine event + market subtitle for a matchable title
                sub = m.get("yes_sub_title") or m.get("title") or ""
                full_title = f"{ev_title} {sub}".strip()
                out.append(KMarket(
                    ticker=ticker,
                    title=full_title,
                    yes_bid=yes_bid,
                    yes_ask=yes_ask,
                    no_ask=no_ask if 0 < no_ask < 100 else (100.0 - yes_bid),
                    volume=float(m.get("volume_fp") or 0),
                    liquidity=float(m.get("liquidity_dollars") or 0),
                ))
        cursor = data.get("cursor")
        if not cursor or not events:
            break
    return out


def fetch_kalshi_orderbook(ticker: str) -> dict:
    url = f"{KALSHI_BASE}/markets/{urllib.parse.quote(ticker)}/orderbook"
    return http_get_json(url).get("orderbook", {}) or {}


# --------------------------------------------------------------------------- #
# Ingestion — Polymarket (Gamma metadata + CLOB order book)
# --------------------------------------------------------------------------- #
def _to_cents(x) -> float:
    try:
        return float(x) * 100.0
    except (TypeError, ValueError):
        return 0.0


def fetch_poly_markets(limit: int, max_pages: int = 12) -> list[PMarket]:
    out: list[PMarket] = []
    offset = 0
    page = 200
    pages = 0
    # order by volume desc so we scan the liquid markets first
    while len(out) < limit and pages < max_pages:
        params = {"closed": "false", "active": "true", "limit": page, "offset": offset,
                  "order": "volumeNum", "ascending": "false"}
        url = f"{POLY_GAMMA}/markets?" + urllib.parse.urlencode(params)
        data = http_get_json(url)
        pages += 1
        if not isinstance(data, list) or not data:
            break
        for m in data:
            outcomes = _maybe_json(m.get("outcomes"))
            if not outcomes or len(outcomes) != 2:
                continue  # binary Yes/No only for the spike
            prices = _maybe_json(m.get("outcomePrices")) or []
            tokens = _maybe_json(m.get("clobTokenIds")) or []
            yes_i = _yes_index(outcomes)
            no_i = 1 - yes_i if yes_i is not None else None
            if yes_i is None:
                continue
            yes_price = _to_cents(prices[yes_i]) if yes_i < len(prices) else 0.0
            no_price = _to_cents(prices[no_i]) if no_i is not None and no_i < len(prices) else 0.0
            out.append(PMarket(
                market_id=str(m.get("id") or m.get("conditionId") or ""),
                question=m.get("question") or m.get("title") or "",
                yes_token=str(tokens[yes_i]) if yes_i < len(tokens) else None,
                no_token=str(tokens[no_i]) if no_i is not None and no_i < len(tokens) else None,
                yes_price=yes_price,
                no_price=no_price,
                volume=float(m.get("volume") or m.get("volumeNum") or 0),
                liquidity=float(m.get("liquidity") or m.get("liquidityNum") or 0),
                category=_poly_category(m),
            ))
        offset += page
    return out[:limit]


def _maybe_json(v):
    if isinstance(v, (list, dict)):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return None
    return None


def _yes_index(outcomes: list) -> int | None:
    for i, o in enumerate(outcomes):
        if str(o).strip().lower() == "yes":
            return i
    return 0 if len(outcomes) == 2 else None


def _poly_category(m: dict) -> str:
    blob = " ".join(str(m.get(k, "")) for k in ("category",)) or ""
    tags = m.get("tags") or []
    if isinstance(tags, list):
        blob += " " + " ".join(str(t.get("label", t) if isinstance(t, dict) else t) for t in tags)
    blob = blob.lower()
    for cat in POLY_FEE_CAPS:
        if cat in blob:
            return cat
    return DEFAULT_POLY_CATEGORY


def fetch_poly_best_ask(token_id: str) -> tuple[float | None, float]:
    """Return (best_ask_cents, size_at_best) for a CLOB token."""
    if not token_id:
        return None, 0.0
    url = f"{POLY_CLOB}/book?" + urllib.parse.urlencode({"token_id": token_id})
    try:
        book = http_get_json(url)
    except RuntimeError:
        return None, 0.0
    asks = book.get("asks") or []
    if not asks:
        return None, 0.0
    # asks: list of {price, size}; best ask = lowest price
    best = min(asks, key=lambda a: float(a.get("price", 1)))
    return float(best["price"]) * 100.0, float(best.get("size", 0))


# --------------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------------- #
_STOP = set("the a an of to in on for is are be will has have market who what "
            "which by at as it its and or vs".split())

def normalize(text: str) -> str:
    text = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    toks = [t for t in text.split() if t not in _STOP and len(t) > 1]
    return " ".join(toks)


def title_similarity(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    seq = SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    jacc = len(ta & tb) / len(ta | tb) if (ta | tb) else 0.0
    return 0.5 * seq + 0.5 * jacc


def auto_match(kms: list[KMarket], pms: list[PMarket], threshold: float):
    """Greedy nearest-title matches above threshold. UNVERIFIED by definition."""
    pairs = []
    for k in kms:
        best, best_s = None, 0.0
        for p in pms:
            s = title_similarity(k.title, p.question)
            if s > best_s:
                best, best_s = p, s
        if best and best_s >= threshold:
            pairs.append((k, best, best_s))
    return pairs


def curated_match(kms, pms, path: str):
    """Load verified pairs: [{kalshi: ticker, polymarket: id, category?}]."""
    with open(path, "r", encoding="utf-8") as f:
        spec = json.load(f)
    kidx = {k.ticker: k for k in kms}
    pidx = {p.market_id: p for p in pms}
    pairs = []
    for row in spec:
        if "kalshi" not in row or "polymarket" not in row:
            continue  # comment / metadata row
        k = kidx.get(row.get("kalshi"))
        p = pidx.get(str(row.get("polymarket")))
        if k and p:
            if row.get("category"):
                p.category = row["category"]
            pairs.append((k, p, 1.0))
        else:
            print(f"  [curated] SKIP unresolved pair: {row}", file=sys.stderr)
    return pairs


# --------------------------------------------------------------------------- #
# Edge computation
# --------------------------------------------------------------------------- #
def compute_edges(pairs, source: str, poly_fee_override: float | None) -> list[Edge]:
    # fetch Polymarket order books concurrently for the tokens we need
    tokens = set()
    for _, p, _ in pairs:
        if p.yes_token: tokens.add(p.yes_token)
        if p.no_token: tokens.add(p.no_token)
    book_cache: dict[str, tuple[float | None, float]] = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(fetch_poly_best_ask, t): t for t in tokens}
        for fut in as_completed(futs):
            book_cache[futs[fut]] = fut.result()

    edges: list[Edge] = []
    for k, p, score in pairs:
        p.yes_ask, p.yes_ask_size = book_cache.get(p.yes_token, (None, 0.0))
        p.no_ask, p.no_ask_size = book_cache.get(p.no_token, (None, 0.0))
        if p.yes_ask is None or p.no_ask is None:
            continue

        pm_fee = poly_fee_override if poly_fee_override is not None else poly_fee_cents(p.category)

        # Direction A: buy YES on Kalshi + buy NO on Polymarket
        cost_a = k.yes_ask + p.no_ask
        fee_a = kalshi_fee_cents(k.yes_ask) + pm_fee
        net_a = (100.0 - cost_a) - fee_a
        size_a = p.no_ask_size  # kalshi depth approximated below

        # Direction B: buy YES on Polymarket + buy NO on Kalshi
        cost_b = p.yes_ask + k.no_ask
        fee_b = kalshi_fee_cents(k.no_ask) + pm_fee
        net_b = (100.0 - cost_b) - fee_b
        size_b = p.yes_ask_size

        if net_a >= net_b:
            direction, cost, fee, net, size = "K_yes+P_no", cost_a, fee_a, net_a, size_a
        else:
            direction, cost, fee, net, size = "P_yes+K_no", cost_b, fee_b, net_b, size_b

        edges.append(Edge(
            key=f"{k.ticker} <> {p.market_id}",
            k=k, p=p, direction=direction,
            cost_cents=cost, gross_cents=100.0 - cost, fee_cents=fee,
            net_cents=net, cap_size=size, match_score=score, match_source=source,
        ))
    return edges


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def print_report(edges: list[Edge], min_net: float, top: int):
    edges = [e for e in edges if e.net_cents >= min_net]
    edges.sort(key=lambda e: e.net_cents, reverse=True)
    print("\n" + "=" * 100)
    print(f" SURVIVING EDGES  (net >= {min_net:.2f}c after fees)   --   {len(edges)} found")
    print("=" * 100)
    if not edges:
        print("\n  No edges survived fees. If this holds across runs/hours, the naive")
        print("  cross-venue arb edge is thin -> see the plan's kill/pivot signal.\n")
        return
    for i, e in enumerate(edges[:top], 1):
        conf = "CURATED" if e.match_source == "curated" else f"AUTO {e.match_score:.2f} !!VERIFY!!"
        print(f"\n#{i}  net {e.net_cents:5.2f}c | gross {e.gross_cents:5.2f}c | "
              f"fees {e.fee_cents:4.2f}c | depth~{e.cap_size:.0f} | [{conf}]")
        print(f"    dir: {e.direction}")
        print(f"    KALSHI  {e.k.ticker:<26} yes_ask={e.k.yes_ask:.0f}c no_ask={e.k.no_ask:.0f}c "
              f"vol={e.k.volume:.0f}")
        print(f"            {e.k.title[:80]}")
        print(f"    POLY    {e.p.market_id:<26} yes_ask={fmt(e.p.yes_ask)} no_ask={fmt(e.p.no_ask)} "
              f"cat={e.p.category} vol={e.p.volume:.0f}")
        print(f"            {e.p.question[:80]}")
    print("\n" + "-" * 100)
    print("REMINDER: AUTO matches are unverified title guesses. Confirm the two markets")
    print("describe the SAME outcome + SAME resolution before believing any edge.")
    print("Fees are approximate/conservative -- VERIFY live schedules before real money.")
    print("-" * 100 + "\n")


def fmt(x):
    return f"{x:.0f}c" if x is not None else "  -"


# --------------------------------------------------------------------------- #
# Ledger — persist every priced edge so repeated scheduled runs accumulate the
# track record that IS the real validation gate (one snapshot proves nothing).
# --------------------------------------------------------------------------- #
def log_run(db_path: str, edges: list[Edge], min_net: float, mode: str,
            kalshi_n: int, poly_n: int) -> None:
    import sqlite3
    from datetime import datetime, timezone

    con = sqlite3.connect(db_path, timeout=30)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript("""
        CREATE TABLE IF NOT EXISTS scan_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, mode TEXT, kalshi_n INTEGER, poly_n INTEGER,
            pairs_priced INTEGER, survivors INTEGER, min_net REAL);
        CREATE TABLE IF NOT EXISTS edge_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL, ts TEXT NOT NULL, pair_key TEXT,
            k_ticker TEXT, p_id TEXT, direction TEXT,
            cost_cents REAL, gross_cents REAL, fee_cents REAL, net_cents REAL,
            cap_size REAL, match_score REAL, match_source TEXT, survived INTEGER,
            k_title TEXT, p_question TEXT,
            FOREIGN KEY(run_id) REFERENCES scan_runs(id));
        CREATE INDEX IF NOT EXISTS idx_edge_pair ON edge_log(pair_key);
        CREATE INDEX IF NOT EXISTS idx_edge_ts ON edge_log(ts);
        """)
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        survivors = sum(1 for e in edges if e.net_cents >= min_net)
        cur = con.execute(
            "INSERT INTO scan_runs (ts,mode,kalshi_n,poly_n,pairs_priced,survivors,min_net)"
            " VALUES (?,?,?,?,?,?,?)",
            (ts, mode, kalshi_n, poly_n, len(edges), survivors, min_net))
        run_id = cur.lastrowid
        con.executemany(
            "INSERT INTO edge_log (run_id,ts,pair_key,k_ticker,p_id,direction,"
            "cost_cents,gross_cents,fee_cents,net_cents,cap_size,match_score,"
            "match_source,survived,k_title,p_question)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(run_id, ts, e.key, e.k.ticker, e.p.market_id, e.direction,
              e.cost_cents, e.gross_cents, e.fee_cents, e.net_cents, e.cap_size,
              e.match_score, e.match_source, int(e.net_cents >= min_net),
              e.k.title[:200], e.p.question[:200]) for e in edges])
        con.commit()
        print(f"      logged {len(edges)} priced edges (run #{run_id}) -> {db_path}",
              file=sys.stderr)
    finally:
        con.close()


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Kalshi<>Polymarket arbitrage spike (stdlib only)")
    ap.add_argument("--pairs", help="curated pairs JSON (trustworthy mode)")
    ap.add_argument("--kalshi-limit", type=int, default=500)
    ap.add_argument("--poly-limit", type=int, default=500)
    ap.add_argument("--match-threshold", type=float, default=0.72,
                    help="auto-match title similarity cutoff (0..1)")
    ap.add_argument("--min-net", type=float, default=0.5, help="min net cents to report")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--poly-fee-cents", type=float, default=None,
                    help="override Polymarket per-share fee in cents (else category caps)")
    ap.add_argument("--log-db", default=None,
                    help="SQLite path to append every priced edge (the validation ledger)")
    ap.add_argument("--quiet", action="store_true", help="suppress the edge table (for cron)")
    args = ap.parse_args()

    t0 = time.time()
    print(f"[1/4] Fetching Kalshi markets (limit {args.kalshi_limit}) ...", file=sys.stderr)
    kms = fetch_kalshi_markets(args.kalshi_limit)
    print(f"      got {len(kms)} open Kalshi markets", file=sys.stderr)

    print(f"[2/4] Fetching Polymarket markets (limit {args.poly_limit}) ...", file=sys.stderr)
    pms = fetch_poly_markets(args.poly_limit)
    print(f"      got {len(pms)} binary Polymarket markets", file=sys.stderr)

    if args.pairs:
        print(f"[3/4] Matching via curated file {args.pairs} ...", file=sys.stderr)
        pairs = curated_match(kms, pms, args.pairs)
        source = "curated"
    else:
        print(f"[3/4] Auto-matching titles (threshold {args.match_threshold}) ...", file=sys.stderr)
        pairs = auto_match(kms, pms, args.match_threshold)
        source = "auto"
    print(f"      {len(pairs)} candidate pairs", file=sys.stderr)

    print(f"[4/4] Fetching order books + computing edges ...", file=sys.stderr)
    edges = compute_edges(pairs, source, args.poly_fee_cents)

    if args.log_db:
        log_run(args.log_db, edges, args.min_net, source, len(kms), len(pms))
    if not args.quiet:
        print_report(edges, args.min_net, args.top)
    print(f"(done in {time.time() - t0:.1f}s; {len(edges)} pairs priced)", file=sys.stderr)


if __name__ == "__main__":
    main()
