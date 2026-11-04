# research/

The September 2026 validation spike, kept for the record. It is superseded by the `edgefeed`
package in `src/`, which fixed what the spike got wrong once it was measured:

| Spike | Package |
|---|---|
| Kalshi fee rounded up **per contract** (overcounts ~14% at 100 lots) | rounded up per fill, the venue's rule, times the series `fee_multiplier` |
| Polymarket fee = flat category cap per share | `C x rate x p(1-p)` from each market's own `feeSchedule` |
| Polymarket depth only; Kalshi depth "approximated" | both ladders walked together to the size that maximises total profit |
| No notion of capital lock-up | APR on capital locked until the later resolution date |
| Yes/No markets only | named outcomes (moneylines), so games can be matched |
| Fuzzy title matching | deterministic game matching by league, date and team codes |
| One request per market | batched: ~6 requests price 150 pairs |
| Latency detector as a separate poller | runs inside the collector on every scan, graded in the ledger |

Scripts here are stdlib-only and run from this folder, e.g. `python spike/arb_spike.py --pairs spike/curated_pairs.json`.
