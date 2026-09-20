# EdgeFeed

Detection & alerts for prediction markets — cross-venue **arbitrage** and (later)
**news-latency** signals across Kalshi and Polymarket.

> **Analytics & information only. Not financial advice.** EdgeFeed displays public
> market data. It takes no custody of funds and executes no trades. Prediction markets
> carry risk and may be restricted in your jurisdiction.

## Status: validation

This repo is at the pre-MVP validation stage. Before building the full app, we run a
zero-cost spike to answer one question: **do capturable cross-venue edges actually
exist after real fees and depth?**

- [`BUILD-PLAN-v2.md`](BUILD-PLAN-v2.md) — the current, research-backed build plan.
- [`spike/`](spike/) — a zero-dependency probe + the validation ledger tooling.
- [`spike/VALIDATION.md`](spike/VALIDATION.md) — how to run the week-long validation.

## Quick start

```bash
# one-off scan of curated pairs, human-readable
python spike/arb_spike.py --pairs spike/curated_pairs.example.json

# logged scan (append to the validation ledger)
python spike/arb_spike.py --pairs spike/curated_pairs.example.json --log-db spike/ledger.sqlite --quiet

# summarize accumulated scans into a go/no-go signal
python spike/report_ledger.py --db spike/ledger.sqlite
```

Requires only Python 3.12+ (standard library — no `pip install`).

## Findings so far (2026-09)

- Both venues expose free, public, no-auth market data.
- Kalshi's flat `/markets` feed is ~99.97% auto-generated parlay combos; discovery must
  use `/events?with_nested_markets=true`.
- Polymarket now charges taker fees (V2, Mar 2026) — the arb math is tighter than legacy
  assumptions; fee-free categories (geopolitics/world) are the best arb candidates.
- Cross-venue arb scanning is already commoditized by several paid/free competitors, so
  the strategy treats arb as a free hook and positions news-latency as the paid moat.

See `BUILD-PLAN-v2.md` for the full analysis.
