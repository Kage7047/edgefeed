# Arb Spike — validation probe

Zero-dependency (Python 3.12 stdlib only) probe that answers the go/no-go question
**before** building the full app:

> Do capturable Kalshi↔Polymarket arbitrage edges exist right now, after real fees
> and with real order-book depth?

## Run it

```bash
# auto-match discovery (noisy, slow ~80s; O(N^2) title matching)
python spike/arb_spike.py --min-net 0.5 --top 20

# trustworthy: verified curated pairs only (fast ~6s)
python spike/arb_spike.py --pairs spike/curated_pairs.example.json --min-net -30
```

No account, no API key, no money. Hits only PUBLIC market-data endpoints.

## Key flags
- `--pairs FILE` curated pairs (see `curated_pairs.example.json`) — the trustworthy path.
- `--min-net C` minimum net cents after fees to report (use negative to see near-misses).
- `--match-threshold 0..1` fuzzy title cutoff for auto mode.
- `--poly-fee-cents C` override Polymarket per-share fee (else category caps).
- `--log-db PATH` append every priced edge to a SQLite validation ledger.
- `--quiet` suppress the table (for scheduled/cron runs).

## Week-long validation
A single run is not the gate. To actually decide go/no-go, schedule repeated logged
scans and summarize them — see **[VALIDATION.md](VALIDATION.md)**. Tools:
- `run_validation.sh` / `run_validation.ps1` — cron / Task Scheduler wrappers.
- `report_ledger.py --db ledger.sqlite` — survivor rate, per-pair stats, verdict hint.

## What the spike PROVED (2026-09-13, live data)

1. **Both venues expose free, public, no-auth market data.** Confirmed working:
   - Kalshi: `GET /trade-api/v2/events?status=open&with_nested_markets=true`
   - Polymarket: Gamma `GET /markets` + CLOB `GET /book?token_id=...`

2. **Kalshi's flat `/markets` firehose is unusable for discovery.** Of 15,000 open
   markets scanned, **14,996 were auto-generated parlay combos** (`MVE`/
   `CROSSCATEGORY`) with no live prices. Only the `/events?with_nested_markets=true`
   path surfaces genuine liquid markets. **Auto-discovery via the firehose is dead.**

3. **Kalshi renamed its fields** since the plan was written: prices are now
   `yes_ask_dollars` / `no_ask_dollars` (in **dollars**), sizes are `_fp` fixed-point.
   Old cents-named fields are gone.

4. **Auto-matching is very low-yield.** ~1,000,000 title comparisons produced only
   4 candidate pairs. It *did* find semantically correct pairs (same PM candidate on
   both venues), but sparsely — confirming the plan's thesis that **curated matching
   is mandatory for a trustworthy MVP**, and that Phase-2 auto-matching is harder
   than assumed (embeddings, not fuzzy strings, and combos must be filtered).

5. **No arb survived fees in the sampled pairs.** Every matched edge was net-negative
   after conservative fees. Small sample + a snapshot, not a verdict — but it lines up
   with the competitive finding that pure retail arb is thin and crowded.

## Caveats
- Fee math is APPROXIMATE and intentionally conservative (over-counts). VERIFY live
  fee schedules before trusting a number for real trading.
- A single snapshot is not the validation gate. To actually decide, run this on a cron
  every few minutes for a week against 20–30 curated high-liquidity pairs and log
  results (that logging is the MVP's track-record ledger).
- Depth shown is best-level only; real capturable size needs walking the book.
