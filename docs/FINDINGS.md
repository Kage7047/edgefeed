# Findings

Live measurements, newest first. Each entry says what was measured, how, and what it changes.
Numbers come from the public APIs and the collector's ledger; nothing here is a recommendation.

## 2026-11-05: the first night, and what it changed

**One real-looking game edge, gone within 15 seconds.** During UCL Lens vs Como, Kalshi YES Como
at 73¢ plus Polymarket NO Como at ~19¢ left 5.9¢ per contract after fees, about $150 at depth
(and a 1.9¢ edge on the draw). The next scan, 15 seconds later, it was gone. Either a fast bot
took it, or one venue's book was stale for a moment. *Change:* games in play are now re-scanned
every 3 seconds, and every new edge is re-fetched at once and paper-traded, so the ledger can say
which it was.

**Lead-lag signals were 90% noise.** 430 fired, hit rate 4.7%. In 385 of the misses the "laggard"
never moved at all: a thin book (often an NCAAB game) with a 10–30¢ spread, whose mid jumped while
the other venue simply did not trade. *Change:* mids only count from books at most 4¢ wide, and the
grade now tells a laggard catching up (hit) from the leader snapping back (revert).

**Carry is small where the money is.** Polymarket pays 4% a year on flagged long-dated markets
(e.g. the 2028 nominations). It only helps when the expensive leg sits on Polymarket: Bernie
Sanders' pair gains 4.0% APR, J.B. Pritzker's 0.1%, because his capital is in a 98¢ Kalshi NO,
and Kalshi's interest on positions is for US users only. Even with both paid, the 2028 pairs
would earn about 4% a year: under the 10% bar.

**Settlement data is available.** Both venues expose final results (Kalshi
`settlement_value_dollars`, Polymarket `outcomePrices` after UMA resolution), checked against
Heat vs Clippers (Nov 4): both report the Heat side paid 1. Paper trades settle from these.

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
