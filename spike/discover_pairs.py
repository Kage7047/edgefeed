#!/usr/bin/env python3
"""
Discovery helper: surface high-liquidity Kalshi<>Polymarket candidate pairs for
HUMAN review, so a trustworthy curated_pairs.json can be hand-built.

It does NOT decide matches. It ranks likely overlaps by title similarity and prints
both sides (title, id, price, volume) so a person can verify same-outcome + same-
resolution before curating.

    python spike/discover_pairs.py --poly-top 300 --kalshi-limit 2500 --min-score 0.35 \
        --out spike/candidates.json
"""
from __future__ import annotations

import argparse
import json
import sys

import arb_spike as A


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--poly-top", type=int, default=300)
    ap.add_argument("--kalshi-limit", type=int, default=2500)
    ap.add_argument("--min-score", type=float, default=0.35)
    ap.add_argument("--per-poly", type=int, default=2, help="top-K Kalshi candidates per PM market")
    ap.add_argument("--out", default="spike/candidates.json")
    args = ap.parse_args()

    print(f"Fetching Polymarket top {args.poly_top} by volume ...", file=sys.stderr)
    pms = A.fetch_poly_markets(args.poly_top, max_pages=20)
    print(f"Fetching Kalshi up to {args.kalshi_limit} liquid markets ...", file=sys.stderr)
    kms = A.fetch_kalshi_markets(args.kalshi_limit, max_pages=20)
    print(f"  PM={len(pms)}  Kalshi={len(kms)}", file=sys.stderr)

    # index Kalshi normalized titles once
    k_norm = [(k, A.normalize(k.title)) for k in kms]

    cands = []
    for p in pms:
        pn = A.normalize(p.question)
        if not pn:
            continue
        scored = []
        for k, kn in k_norm:
            if not kn:
                continue
            s = A.title_similarity(p.question, k.title)
            if s >= args.min_score:
                scored.append((s, k))
        scored.sort(key=lambda x: x[0], reverse=True)
        for s, k in scored[:args.per_poly]:
            cands.append({
                "score": round(s, 3),
                "polymarket": p.market_id,
                "pm_question": p.question,
                "pm_vol": round(p.volume),
                "pm_cat": p.category,
                "kalshi": k.ticker,
                "k_title": k.title,
                "k_vol": round(k.volume),
                "k_yes_ask": round(k.yes_ask, 1),
            })

    cands.sort(key=lambda c: c["score"], reverse=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(cands, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 100)
    print(f" {len(cands)} candidate pairs (score >= {args.min_score}) -> {args.out}")
    print("=" * 100)
    for c in cands[:60]:
        print(f"\n[{c['score']:.2f}] pmVol={c['pm_vol']:>9}  kVol={c['k_vol']:>7}  cat={c['pm_cat']}")
        print(f"   PM  {c['polymarket']:<12} {c['pm_question'][:82]}")
        print(f"   K   {c['kalshi'][:30]:<30} {c['k_title'][:82]}")


if __name__ == "__main__":
    main()
