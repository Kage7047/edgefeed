# 1. Fees come from the venues' own rules and fields

**Status:** accepted, 2026-11-04

**Context.** The whole question is whether an edge survives fees, and the spike's fee model was
wrong in both directions: Kalshi rounded per contract (overcounting), Polymarket used the 50¢
peak as a flat fee (overcounting away from 50¢). Fee schedules also change: Polymarket added
taker fees in March 2026.

**Decision.** Implement each venue's published formula exactly, with Decimal arithmetic and the
venue's rounding, and read parameters from the API where the venue exposes them: Kalshi's series
`fee_multiplier`, Polymarket's per-market `feeSchedule` and `feesEnabled`. Fall back to the
published category rate only when a field is missing, and to the most expensive rate when the
category is unknown. Kalshi is rounded per fill, which is the conservative reading.

**Consequences.** Tests pin the venues' own worked examples. A fee change on one market is picked
up on the next metadata refresh with no code change. The daily contract test fails if the fee
fields disappear.
