# News-Latency Detector (MVP)

The paid-tier differentiator. Detects when one venue reprices on news before the
other, and grades whether the laggard actually catches up.

**Why it can work at $0:** research shows Polymarket can lag Kalshi by **1–30+ minutes**
after news (on-chain settlement latency; markets initially move only ~64% of the way).
That window is *minutes*, so a cheap ~15s poller catches it — no realtime infra, no LLM,
no paid news feed. The sharp price move *is* the news signal.

## Files
- `latency_detector.py` — polls both venues' mids for curated pairs, detects
  cross-venue lead-lag divergence, logs signals, grades convergence follow-ups.
- `latency_report.py` — signals fired + **convergence hit-rate** (the calibration bar).
- `news_context.py` — optional free Google News RSS headline attached to each signal.

## Run
```bash
python news/latency_detector.py --self-test        # prove the logic (no network)
python news/latency_detector.py --duration 70 --poll 20 --no-news   # plumbing check
python news/latency_detector.py                     # run forever (Ctrl-C)
python news/latency_report.py --db news/latency.sqlite
```

## How detection works
For each pair, keep a rolling `--window` (default 180s) of both venues' mid prices.
Fire when one venue moved `>= --move-threshold` (3¢) while the other moved
`<= --lag-max` (1.5¢) **and** they now disagree by `>= --gap-min` (3¢). Predicted
direction: laggard converges toward leader. After `--followup` (600s) grade the
convergence fraction; `>= --hit-frac` (0.5) counts as a hit.

## Tunables (cents / seconds)
`--window --move-threshold --lag-max --gap-min --cooldown --followup --hit-frac`

## Status & honest limitations
- Detection logic is unit-proven (`--self-test`); live polling/mid-fetch verified.
- **Not yet validated on real news** — needs to run across actual news events to
  produce a hit-rate. That's the next step: run it continuously for a stretch that
  spans real market-moving news, then read `latency_report.py`.
- Mid = CLOB best-bid/ask midpoint (Polymarket) and yes bid/ask midpoint (Kalshi).
- Next candidates if signal is weak: faster poll on a small hot set; use last-trade
  vs mid; add volume/velocity confirmation; widen curated pairs to volatile categories.
