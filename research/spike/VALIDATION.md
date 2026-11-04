# Running the validation (the real go/no-go gate)

A single scan proves nothing — edges open and close in 15–60s. The gate is whether
edges survive fees **repeatably** over time. This is also the seed of the product's
track-record ledger.

## 1. Build a curated pairs file
Copy `curated_pairs.example.json` and fill 20–30 hand-verified overlaps. For each pair:
- `kalshi`: market ticker (from `/events?with_nested_markets=true`).
- `polymarket`: Gamma market id (numeric).
- `category`: sets the Polymarket fee cap (geopolitics/world = 0¢ → best arb candidates).
- Verify **both markets resolve on the same event, same date, same source** before adding.

Bias the list toward **high-liquidity** markets and **fee-free Polymarket categories**.

## 2. Schedule it (every ~10 min for a week), $0

**Oracle Cloud Always Free VM (Linux, cron):**
```bash
chmod +x spike/run_validation.sh
crontab -e
# */10 * * * * /path/to/edgefeed/spike/run_validation.sh >> /path/to/edgefeed/spike/cron.log 2>&1
```

**Windows Task Scheduler:** see the header of `spike/run_validation.ps1` for the
`Register-ScheduledTask` snippet.

Override defaults via env vars: `PAIRS`, `DB`, `PYTHON`.

## 3. Read the signal
```bash
python spike/report_ledger.py --db spike/ledger.sqlite --min-net 0.5
```
The report prints survivor rate, per-pair stats, and a verdict hint:
- **0 survivors ever** → arb kill-signal; pivot the paid tier to news-latency (plan v2 §4 Phase 3).
- **<5% of scans** → arb is real but fleeting; use it as a free hook, prioritize speed.
- **regular survivors** → harden the arb path (realtime, more pairs, more venues).

## 4. In parallel — the non-technical half of the gate
The build plan's validation gate also needs: organic free-channel subscribers, a handful
of paid/waitlist signups, and interviews confirming actionability. The ledger only
settles the "is the edge real" question; it does not settle "will people pay."
