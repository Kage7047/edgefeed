# 2. Games are matched deterministically, never by fuzzy title

**Status:** accepted, 2026-11-04

**Context.** A wrong match is worse than no match: it shows a large "edge" that is really two
different bets. The spike's fuzzy title matching was both sparse and unsafe. Games are the only
liquid, near-term overlap between the venues, and both venues encode them in structured
identifiers.

**Decision.** Match games by league, date and team codes: Kalshi `KX{LEAGUE}GAME-{YYMMMDD}{A}{B}`
with one market per team, Polymarket slug `{league}-{a}-{b}-{yyyy-mm-dd}`. Map codes through a
small alias table where the venues differ (Kalshi `JAC`, Polymarket `jax`). Drop any mapping
where the two prices disagree by more than 25¢, which signals a flipped outcome. Attach the known
settlement differences to every game pair.

**Consequences.** Coverage is limited to what both venues list and the alias table knows; the
matcher reports coverage per league so gaps are visible. New leagues are one line each.
