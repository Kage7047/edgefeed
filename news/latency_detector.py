#!/usr/bin/env python3
"""
News-Latency Detector (smallest viable MVP)
===========================================

Thesis (research-backed): after real news, one venue reprices faster than the other.
Polymarket can lag Kalshi by 1-30+ minutes (on-chain settlement latency); markets
initially move only ~64% of the way to the corrected price. That lag is the edge —
and because it's MINUTES, a cheap ~15s poller catches it (no realtime infra, no LLM,
no paid news feed).

Mechanism: for each curated pair, poll both venues' MID prices, keep a short rolling
history. When one venue moves >= MOVE_THRESHOLD over WINDOW while the other stays flat
(<= LAG_MAX) AND they now disagree by >= GAP_MIN, fire a latency signal:
    "LEADER moved X.Xc; LAGGARD hasn't repriced -> expected to converge toward LEADER."
Then follow up after FOLLOWUP_SECONDS: did the laggard actually converge? -> hit-rate.

The move IS the news signal. Optionally attach a free news headline (news_context.py).

Zero dependencies (stdlib only). Reuses spike/arb_spike.py ingestion.

Usage:
    python news/latency_detector.py --self-test          # prove the logic fires (no network)
    python news/latency_detector.py --duration 120        # run 2 min against live venues
    python news/latency_detector.py                       # run forever (Ctrl-C to stop)
    python news/latency_detector.py --pairs spike/curated_pairs.json --poll 15 --db news/latency.sqlite
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

# import the spike's verified ingestion
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "spike"))
import arb_spike as A  # noqa: E402

# --------------------------------------------------------------------------- #
# Tunables (cents; seconds). Defaults are deliberately conservative.
# --------------------------------------------------------------------------- #
DEFAULTS = dict(
    poll=15,               # seconds between polls
    window=180,            # rolling lookback for "a move"
    move_threshold=3.0,    # leader must move at least this many cents over the window
    lag_max=1.5,           # laggard must have moved LESS than this (still stale)
    gap_min=3.0,           # current mid disagreement required to fire
    cooldown=300,          # per-pair seconds before re-firing
    followup=600,          # seconds after firing to grade convergence
    hit_frac=0.5,          # laggard must close >= this fraction of the gap to count as a hit
)


@dataclass
class Leg:
    venue: str
    ident: str             # kalshi ticker OR polymarket yes-token
    hist: deque = field(default_factory=lambda: deque())  # (ts, mid_cents)

    def push(self, ts: float, mid: float | None):
        if mid is None:
            return
        self.hist.append((ts, mid))

    def prune(self, now: float, window: float):
        while self.hist and now - self.hist[0][0] > window:
            self.hist.popleft()

    def latest(self) -> float | None:
        return self.hist[-1][1] if self.hist else None

    def move(self, window: float) -> float:
        """Signed move over the window: latest - oldest-in-window."""
        if len(self.hist) < 2:
            return 0.0
        return self.hist[-1][1] - self.hist[0][1]


@dataclass
class Pair:
    key: str
    k_ticker: str
    p_id: str
    p_yes_token: str
    category: str
    kalshi: Leg
    poly: Leg
    last_fired: float = 0.0


# --------------------------------------------------------------------------- #
# Price sourcing (mids)
# --------------------------------------------------------------------------- #
def kalshi_mid() :  # placeholder to keep symmetry; real fetch below
    ...


def fetch_kalshi_mid(ticker: str) -> float | None:
    m = A.fetch_kalshi_market(ticker)
    if not m:
        return None
    if m.yes_bid and m.yes_ask and 0 < m.yes_ask < 100:
        return (m.yes_bid + m.yes_ask) / 2.0
    return m.yes_ask or None


def fetch_poly_mid(token: str) -> float | None:
    """Mid of the YES token from the CLOB book = (best_bid + best_ask)/2, in cents."""
    if not token:
        return None
    url = f"{A.POLY_CLOB}/book?" + A.urllib.parse.urlencode({"token_id": token})
    try:
        book = A.http_get_json(url)
    except RuntimeError:
        return None
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    if not bids or not asks:
        return None
    best_bid = max(float(b["price"]) for b in bids)
    best_ask = min(float(a["price"]) for a in asks)
    return (best_bid + best_ask) / 2.0 * 100.0


# --------------------------------------------------------------------------- #
# Detection core (pure function — unit-testable, used by --self-test)
# --------------------------------------------------------------------------- #
@dataclass
class Signal:
    pair_key: str
    k_ticker: str
    p_id: str
    leader: str            # "kalshi" | "polymarket"
    laggard: str
    leader_move: float
    laggard_move: float
    gap: float
    leader_mid: float
    laggard_mid: float


def detect(pair: Pair, cfg: dict) -> Signal | None:
    k_mid, p_mid = pair.kalshi.latest(), pair.poly.latest()
    if k_mid is None or p_mid is None:
        return None
    k_move, p_move = pair.kalshi.move(cfg["window"]), pair.poly.move(cfg["window"])
    gap = abs(k_mid - p_mid)
    if gap < cfg["gap_min"]:
        return None

    # who moved (leader) vs who's stale (laggard)?
    if abs(k_move) >= cfg["move_threshold"] and abs(p_move) <= cfg["lag_max"]:
        leader, laggard = "kalshi", "polymarket"
        lead_move, lag_move, lead_mid, lag_mid = k_move, p_move, k_mid, p_mid
    elif abs(p_move) >= cfg["move_threshold"] and abs(k_move) <= cfg["lag_max"]:
        leader, laggard = "polymarket", "kalshi"
        lead_move, lag_move, lead_mid, lag_mid = p_move, k_move, p_mid, k_mid
    else:
        return None

    return Signal(pair.key, pair.k_ticker, pair.p_id, leader, laggard,
                  round(lead_move, 2), round(lag_move, 2), round(gap, 2),
                  round(lead_mid, 2), round(lag_mid, 2))


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
def open_db(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
    CREATE TABLE IF NOT EXISTS news_signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT, pair_key TEXT, k_ticker TEXT, p_id TEXT,
        leader TEXT, laggard TEXT, leader_move REAL, laggard_move REAL,
        gap REAL, leader_mid REAL, laggard_mid REAL, headline TEXT,
        followup_ts TEXT, laggard_mid_after REAL, convergence_frac REAL, outcome TEXT);
    CREATE INDEX IF NOT EXISTS idx_sig_pair ON news_signals(pair_key);
    """)
    return con


def record_signal(con, sig: Signal, headline: str | None) -> int:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cur = con.execute(
        "INSERT INTO news_signals (ts,pair_key,k_ticker,p_id,leader,laggard,"
        "leader_move,laggard_move,gap,leader_mid,laggard_mid,headline)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (ts, sig.pair_key, sig.k_ticker, sig.p_id, sig.leader, sig.laggard,
         sig.leader_move, sig.laggard_move, sig.gap, sig.leader_mid, sig.laggard_mid,
         headline))
    con.commit()
    return cur.lastrowid


def grade_followups(con, pairs: dict[str, Pair], cfg: dict):
    """Grade signals whose follow-up window elapsed: did the laggard converge?"""
    now = datetime.now(timezone.utc)
    rows = con.execute(
        "SELECT id,ts,pair_key,leader,laggard,leader_mid,laggard_mid FROM news_signals"
        " WHERE outcome IS NULL").fetchall()
    for sid, ts, pk, leader, laggard, leader_mid, lag_mid0 in rows:
        age = (now - datetime.fromisoformat(ts)).total_seconds()
        if age < cfg["followup"]:
            continue
        pair = pairs.get(pk)
        if not pair:
            continue
        lag_leg = pair.poly if laggard == "polymarket" else pair.kalshi
        lag_now = lag_leg.latest()
        if lag_now is None:
            continue
        init_gap = abs(lag_mid0 - leader_mid)
        new_gap = abs(lag_now - leader_mid)
        frac = (init_gap - new_gap) / init_gap if init_gap > 0 else 0.0
        outcome = "hit" if frac >= cfg["hit_frac"] else ("partial" if frac > 0 else "miss")
        con.execute(
            "UPDATE news_signals SET followup_ts=?, laggard_mid_after=?, convergence_frac=?,"
            " outcome=? WHERE id=?",
            (now.isoformat(timespec="seconds"), round(lag_now, 2), round(frac, 3), outcome, sid))
        con.commit()
        print(f"  [followup] sig#{sid} {pk}: laggard {lag_mid0:.1f}->{lag_now:.1f} "
              f"(target {leader_mid:.1f}) conv={frac:.0%} -> {outcome}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# Setup + live loop
# --------------------------------------------------------------------------- #
def build_pairs(path: str) -> dict[str, Pair]:
    with open(path, encoding="utf-8") as f:
        spec = [r for r in json.load(f) if "kalshi" in r and "polymarket" in r]
    pairs: dict[str, Pair] = {}
    print(f"Resolving {len(spec)} curated pairs (tokens/tickers) ...", file=sys.stderr)

    def resolve(r):
        pm = A.fetch_poly_market(str(r["polymarket"]))
        return r, pm

    with ThreadPoolExecutor(max_workers=10) as ex:
        for r, pm in ex.map(resolve, spec):
            if not pm or not pm.yes_token:
                print(f"  skip {r['kalshi']} (no PM token)", file=sys.stderr)
                continue
            key = f"{r['kalshi']}<>{r['polymarket']}"
            pairs[key] = Pair(
                key=key, k_ticker=r["kalshi"], p_id=str(r["polymarket"]),
                p_yes_token=pm.yes_token, category=r.get("category", "politics"),
                kalshi=Leg("kalshi", r["kalshi"]), poly=Leg("polymarket", pm.yes_token))
    print(f"  ready: {len(pairs)} pairs", file=sys.stderr)
    return pairs


def poll_once(pairs: dict[str, Pair]):
    now = time.time()
    tasks = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {}
        for p in pairs.values():
            futs[ex.submit(fetch_kalshi_mid, p.k_ticker)] = (p, "k")
            futs[ex.submit(fetch_poly_mid, p.p_yes_token)] = (p, "p")
        for fut in futs:
            pass
        for fut, (p, which) in futs.items():
            try:
                mid = fut.result()
            except Exception:
                mid = None
            (p.kalshi if which == "k" else p.poly).push(now, mid)
    for p in pairs.values():
        p.kalshi.prune(now, DEFAULTS["window"])
        p.poly.prune(now, DEFAULTS["window"])


def run_live(args, cfg):
    pairs = build_pairs(args.pairs)
    if not pairs:
        print("No pairs resolved; aborting.", file=sys.stderr)
        return
    con = open_db(args.db)
    news_fn = None
    if not args.no_news:
        try:
            sys.path.insert(0, os.path.dirname(__file__))
            import news_context
            news_fn = news_context.headline_for
        except Exception as e:
            print(f"  (news context disabled: {e})", file=sys.stderr)

    print(f"Polling every {args.poll}s. Ctrl-C to stop. DB={args.db}", file=sys.stderr)
    t_end = time.time() + args.duration if args.duration else None
    try:
        while True:
            t0 = time.time()
            poll_once(pairs)
            fired = 0
            for p in pairs.values():
                sig = detect(p, cfg)
                if sig and (t0 - p.last_fired) >= cfg["cooldown"]:
                    p.last_fired = t0
                    headline = None
                    if news_fn:
                        try:
                            headline = news_fn(p.key)
                        except Exception:
                            headline = None
                    sid = record_signal(con, sig, headline)
                    fired += 1
                    print(f"\n*** LATENCY SIGNAL #{sid}  {sig.pair_key}", file=sys.stderr)
                    print(f"    {sig.leader.upper()} moved {sig.leader_move:+.1f}c to "
                          f"{sig.leader_mid:.1f}c; {sig.laggard.upper()} stale at "
                          f"{sig.laggard_mid:.1f}c (gap {sig.gap:.1f}c)", file=sys.stderr)
                    print(f"    -> expect {sig.laggard.upper()} to move toward "
                          f"{sig.leader_mid:.1f}c" + (f" | {headline}" if headline else ""),
                          file=sys.stderr)
            grade_followups(con, pairs, cfg)
            n_samples = sum(len(p.kalshi.hist) for p in pairs.values())
            print(f"  tick {datetime.now().strftime('%H:%M:%S')}  "
                  f"pairs={len(pairs)} fired={fired} buf={n_samples} "
                  f"({time.time()-t0:.1f}s)", file=sys.stderr)
            if t_end and time.time() >= t_end:
                print("Duration elapsed; stopping.", file=sys.stderr)
                break
            time.sleep(max(0, args.poll - (time.time() - t0)))
    except KeyboardInterrupt:
        print("\nStopped by user.", file=sys.stderr)
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# Self-test: prove detect() fires on a synthetic repricing, without network.
# --------------------------------------------------------------------------- #
def self_test(cfg):
    print("SELF-TEST: synthetic Kalshi jump +8c over window, Polymarket flat ...")
    now = time.time()
    p = Pair(key="TEST", k_ticker="K", p_id="P", p_yes_token="tok", category="politics",
             kalshi=Leg("kalshi", "K"), poly=Leg("polymarket", "tok"))
    # Kalshi rises 40 -> 48 over the window; Polymarket flat at 40.
    for i, t in enumerate(range(0, int(cfg["window"]) + 1, 30)):
        p.kalshi.push(now - cfg["window"] + t, 40.0 + 8.0 * (i / max(1, (cfg["window"] // 30))))
        p.poly.push(now - cfg["window"] + t, 40.2)
    p.kalshi.prune(now, cfg["window"]); p.poly.prune(now, cfg["window"])
    sig = detect(p, cfg)
    assert sig is not None, "FAIL: detector did not fire on a clear repricing"
    assert sig.leader == "kalshi" and sig.laggard == "polymarket", f"FAIL: wrong roles {sig}"
    print(f"  PASS: fired -> leader={sig.leader} move={sig.leader_move:+.1f}c "
          f"gap={sig.gap:.1f}c, expect polymarket -> {sig.leader_mid:.1f}c")

    print("SELF-TEST: both venues move together (real move, not latency) -> no fire ...")
    p2 = Pair(key="T2", k_ticker="K", p_id="P", p_yes_token="tok", category="politics",
              kalshi=Leg("kalshi", "K"), poly=Leg("polymarket", "tok"))
    for t in range(0, int(cfg["window"]) + 1, 30):
        frac = t / cfg["window"]
        p2.kalshi.push(now - cfg["window"] + t, 40.0 + 8.0 * frac)
        p2.poly.push(now - cfg["window"] + t, 40.0 + 8.0 * frac)
    p2.kalshi.prune(now, cfg["window"]); p2.poly.prune(now, cfg["window"])
    assert detect(p2, cfg) is None, "FAIL: fired when both venues moved together"
    print("  PASS: no false signal when both venues reprice together.")
    print("\nSELF-TEST OK.")


def main():
    ap = argparse.ArgumentParser(description="News-latency (cross-venue lead-lag) detector")
    ap.add_argument("--pairs", default="spike/curated_pairs.json")
    ap.add_argument("--db", default="news/latency.sqlite")
    ap.add_argument("--poll", type=int, default=DEFAULTS["poll"])
    ap.add_argument("--duration", type=int, default=0, help="seconds to run (0 = forever)")
    ap.add_argument("--no-news", action="store_true", help="skip free news-headline lookup")
    ap.add_argument("--self-test", action="store_true")
    # threshold overrides
    for k in ("window", "move_threshold", "lag_max", "gap_min", "cooldown", "followup", "hit_frac"):
        ap.add_argument(f"--{k.replace('_','-')}", type=float, default=DEFAULTS[k])
    args = ap.parse_args()

    cfg = {k: getattr(args, k) for k in
           ("window", "move_threshold", "lag_max", "gap_min", "cooldown", "followup", "hit_frac")}
    cfg["window"] = float(cfg["window"])

    if args.self_test:
        self_test(cfg)
        return
    run_live(args, cfg)


if __name__ == "__main__":
    main()
