# 5. Paper trading and hot scans measure execution, not just existence

**Status:** accepted, 2026-11-05

**Context.** The first night of data had one large game edge (UCL Lens vs Como, 5.9¢ per contract,
~$150 at depth) that lived for a single 15-second scan. A ledger that only records that an edge
was seen cannot say whether anyone could have got it: the books may already have been stale, and
the two venues may settle the game differently. 90% of lead-lag signals were also noise from wide,
thin books.

**Decision.**
- **Hot scans.** Between full scans (every 15s) the collector re-scans, every 3s, the pairs that
  matter now: games from 20 minutes before start to 4 hours after (start time from Polymarket's
  `gameStartTime`) and any pair with an open edge. One hot scan is three batched requests, ~0.4s.
  A scan only closes the edges it looked at.
- **Re-check and paper fill.** When an edge opens, both books are fetched again at once and priced
  at a fixed size (200 contracts). If the edge is still there it becomes an open paper trade at
  those prices, otherwise a "missed" one. The opportunity row records whether it held and how long
  the re-check took. "Actionable" in the report now means "held on re-check".
- **Settlement.** Every 5 minutes open paper trades are checked against both venues' resolved
  results (Kalshi `settlement_value_dollars`, Polymarket `outcomePrices` once UMA resolution is
  final). The payout is booked; legs that do not pay exactly one dollar per contract between them
  raise a `settlement_mismatch` event. That turns the settlement-rule warnings into money.
- **Carry.** Prices carry a per-book yield: Polymarket holding rewards (4%) on flagged markets, and
  Kalshi interest when configured (US-only, so off by default). Alerts and "worth it" use APR
  including carry.
- **Quieter ledger.** Quotes are written when they change, plus a 5-minute heartbeat, so the 3s
  loop does not multiply the quotes table. Columns added since v0.2 are applied by a small
  `Store.migrate()` that only ever adds nullable columns and refuses anything else.

**Consequences.** The go/no-go now rests on fill rate and settled P&L, not on sightings. Paper
trades still assume both legs fill at the re-fetched prices at the same instant; real latency and
partial fills would be worse, so paper P&L is an upper bound. WebSocket feeds are the next step if
the miss rate shows that 3 seconds is too slow.
