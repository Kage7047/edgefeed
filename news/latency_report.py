#!/usr/bin/env python3
"""
Summarize the news-latency ledger: signals fired + convergence hit-rate.

Hit-rate is THE calibration bar from the build plan — a latency alert is only
worth selling if the laggard actually converges toward the leader often enough.

Usage:
    python news/latency_report.py --db news/latency.sqlite
"""
from __future__ import annotations

import argparse
import sqlite3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="news/latency.sqlite")
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    total = con.execute("SELECT COUNT(*) n FROM news_signals").fetchone()["n"]
    if not total:
        print("No signals logged yet. Run latency_detector.py first.")
        return

    graded = con.execute("SELECT COUNT(*) n FROM news_signals WHERE outcome IS NOT NULL").fetchone()["n"]
    hits = con.execute("SELECT COUNT(*) n FROM news_signals WHERE outcome='hit'").fetchone()["n"]
    partial = con.execute("SELECT COUNT(*) n FROM news_signals WHERE outcome='partial'").fetchone()["n"]
    miss = con.execute("SELECT COUNT(*) n FROM news_signals WHERE outcome='miss'").fetchone()["n"]
    avg_conv = con.execute("SELECT AVG(convergence_frac) a FROM news_signals WHERE outcome IS NOT NULL").fetchone()["a"]

    print("=" * 80)
    print(" NEWS-LATENCY LEDGER")
    print("=" * 80)
    print(f" signals fired : {total}")
    print(f" graded        : {graded}   (pending {total-graded})")
    if graded:
        print(f" HIT RATE      : {100*hits/graded:.1f}%   (hit {hits} / partial {partial} / miss {miss})")
        print(f" avg convergence: {(avg_conv or 0):.0%} of the gap closed by followup")

    print("\n-- recent signals " + "-" * 60)
    rows = con.execute(
        "SELECT ts,pair_key,leader,laggard,leader_move,gap,outcome,convergence_frac,headline"
        " FROM news_signals ORDER BY id DESC LIMIT ?", (args.top,)).fetchall()
    for r in rows:
        oc = r["outcome"] or "pending"
        conv = f"{r['convergence_frac']:.0%}" if r["convergence_frac"] is not None else "-"
        print(f" {r['ts'][11:19]} {r['pair_key'][:34]:<34} {r['leader'][:4]}->{r['laggard'][:4]} "
              f"mv{r['leader_move']:+.0f} gap{r['gap']:.0f} [{oc} {conv}]")
        if r["headline"]:
            print(f"     news: {r['headline'][:76]}")

    print("\n-- calibration hint " + "-" * 58)
    if graded < 10:
        print(" Not enough graded signals yet. Let it run across real news events.")
    elif hits / graded >= 0.6:
        print(" Hit rate >= 60% -> the latency signal has real predictive power. Build the paid tier.")
    elif hits / graded >= 0.4:
        print(" Hit rate 40-60% -> promising; tune thresholds (move/gap/window) before selling.")
    else:
        print(" Hit rate < 40% -> laggard rarely converges; rethink thresholds or the thesis.")
    print("=" * 80)
    con.close()


if __name__ == "__main__":
    main()
