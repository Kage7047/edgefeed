#!/usr/bin/env bash
# Validation runner for cron (e.g. Oracle Cloud Always Free VM).
# Appends one scan of the curated pairs to the ledger. $0 cost.
#
# Install (every 10 min):
#   crontab -e
#   */10 * * * * /path/to/edgefeed/spike/run_validation.sh >> /path/to/edgefeed/spike/cron.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root
PYTHON="${PYTHON:-python3}"
PAIRS="${PAIRS:-spike/curated_pairs.example.json}"
DB="${DB:-spike/ledger.sqlite}"

"$PYTHON" spike/arb_spike.py \
  --pairs "$PAIRS" \
  --log-db "$DB" \
  --min-net 0.5 \
  --quiet \
  --kalshi-limit 1500 --poly-limit 800
