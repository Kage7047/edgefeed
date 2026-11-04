# Findings

Live measurements, newest first. Each entry says what was measured, how, and what it changes.
Numbers come from the public APIs and the collector's ledger; nothing here is a recommendation.

## 2026-11-04: first day of the rebuilt engine

**Curated political pairs (21, all 2028 or later).** 19 priced, 9 with a locked edge at full
depth, best: AOC 2028 nomination, buy Kalshi YES at 14¢ + Polymarket NO at ~84¢, 22,200
contracts, ~$120 profit. Every one resolves in November 2028 or later, so the APR on locked
capital is 0.0–0.3%. *Change:* lock-up is now part of every price; alerts need ≥10% APR. These
pairs stay in the file as a long-run calibration set, not as opportunities.

**Fees.** Checked against the venues' docs and API fields:
- Kalshi `round_up(0.07 × C × P × (1−P))` per trade, series `fee_multiplier` (1 on elections).
  The spike rounded per contract: at 100 contracts and 50¢ it charged $2.00 instead of $1.75.
- Polymarket `C × feeRate × p × (1−p)`, per-market `feeSchedule` (`rate` 0.04 politics, 0.05
  sports, 0 geopolitics), rounded to 5 dp, taker only. The spike used the 50¢ peak as a flat fee
  at every price: at 14¢ it charged 1¢ instead of 0.48¢.

**Intra-venue baskets.** Buying NO on every outcome of a mutually exclusive event pays at least
N−1 whatever happens, so `sum(NO asks) + fees < N−1` would be riskless.
- Kalshi: 0 edges across 4,773 mutually exclusive events.
- Polymarket: 0 edges across 942 neg-risk events.
- The YES-basket version (`sum(YES asks) < 1`) showed 20 "edges" of 20–89¢ on Polymarket. They
  are not real: those events do not list every outcome (a later candidate can win), and some had
  already passed. *Change:* no YES baskets; NO baskets are not worth a collector loop.

**Games.** Matched by league, date and team codes, no fuzzy titles:
`KXNBAGAME-26NOV04ATLWAS` ↔ `nba-atl-was-2026-11-04`. Coverage for the next two days:
NBA 32/32 games, NHL 17/30, NCAAB 12/160 (Polymarket lists few college games), EPL 4/5,
Serie A 4/5, La Liga 2/5, UCL 2/9. A price check drops any mapping where the venues disagree by
more than 25¢, which would mean a flipped outcome.
- Pre-game, across 5,600 quotes: mean distance to an edge −4.1¢, best −0.12¢, 3.8% within 1¢.
  At even odds the two fees alone are ~3¢ (Kalshi 1.75¢ + Polymarket 1.25¢).
- Rule texts agree on normal results and differ on edge cases (postponement past 48 hours,
  cancellation, a cancelled soccer match's draw market). Each game pair carries that warning.

**Open question for the next week:** do in-game swings open edges above 3¢, and for how many
scans? The collector logs every one with its duration; `edgefeed report` gives the verdict once
3+ days are observed.
