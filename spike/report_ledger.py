#!/usr/bin/env python3
"""
Summarize the validation ledger produced by `arb_spike.py --log-db`.

This turns accumulated scheduled scans into the go/no-go signal:
  * how often does ANY edge survive fees?
  * which pairs produce edges, how big, how persistent?
  * is the arb thesis alive, or should the paid tier pivot to news-latency?

Usage:
    python spike/report_ledger.py --db ledger.sqlite
    python spike/report_ledger.py --db ledger.sqlite --min-net 1.0 --top 15
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="ledger.sqlite")
    ap.add_argument("--min-net", type=float, default=0.5,
                    help="net cents threshold that counts as a 'real' edge")
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row

    runs = con.execute("SELECT COUNT(*) n, MIN(ts) a, MAX(ts) b FROM scan_runs").fetchone()
    if not runs["n"]:
        print("No scans logged yet. Run arb_spike.py --log-db first.")
        return

    total_priced = con.execute("SELECT COUNT(*) n FROM edge_log").fetchone()["n"]
    survivors = con.execute("SELECT COUNT(*) n FROM edge_log WHERE net_cents >= ?",
                            (args.min_net,)).fetchone()["n"]
    runs_with_edge = con.execute(
        "SELECT COUNT(DISTINCT run_id) n FROM edge_log WHERE net_cents >= ?",
        (args.min_net,)).fetchone()["n"]

    print("=" * 84)
    print(" VALIDATION LEDGER SUMMARY")
    print("=" * 84)
    print(f" scans:            {runs['n']}")
    print(f" window:           {runs['a']}  ->  {runs['b']}")
    print(f" priced edges:     {total_priced}")
    print(f" survivors(>={args.min_net:.1f}c): {survivors}  "
          f"({100*survivors/max(1,total_priced):.1f}% of priced)")
    print(f" scans w/ >=1 edge:{runs_with_edge}  "
          f"({100*runs_with_edge/max(1,runs['n']):.1f}% of scans)")

    print("\n-- Per-pair stats (by best net ever) " + "-" * 46)
    rows = con.execute("""
        SELECT pair_key, k_ticker, p_id,
               COUNT(*) seen,
               SUM(CASE WHEN net_cents >= ? THEN 1 ELSE 0 END) hits,
               MAX(net_cents) best, AVG(net_cents) avg, MAX(cap_size) depth,
               MAX(match_source) src
        FROM edge_log GROUP BY pair_key
        ORDER BY best DESC LIMIT ?
    """, (args.min_net, args.top)).fetchall()
    print(f" {'best':>6} {'avg':>6} {'hits/seen':>10} {'depth':>8}  pair")
    for r in rows:
        print(f" {r['best']:6.2f} {r['avg']:6.2f} {r['hits']:>4}/{r['seen']:<4}  "
              f"{r['depth']:8.0f}  [{r['src']}] {r['pair_key'][:46]}")

    print("\n-- Verdict hint " + "-" * 66)
    if survivors == 0:
        print(" No edge has EVER survived fees across all logged scans.")
        print(" -> Arb kill-signal territory. Pivot the paid tier to news-latency (plan v2 Phase 3).")
    elif runs_with_edge / max(1, runs["n"]) < 0.05:
        print(" Edges survive in <5% of scans -> arb is real but rare/fleeting.")
        print(" -> Arb works as a free hook, not a standalone paid product. Prioritize speed + news.")
    else:
        print(" Edges survive regularly -> the arb path is worth hardening (realtime, more pairs).")
    print("=" * 84)
    con.close()


if __name__ == "__main__":
    main()
