#!/usr/bin/env bash
# Run EdgeFeed 24/7 on a Linux machine as systemd *user* services: no root, no Docker.
#   collector  -> scans every EDGEFEED_INTERVAL seconds, ledger in ~/.local/share/edgefeed
#   dashboard  -> http://127.0.0.1:8090
# Settings: put EDGEFEED_* lines in ~/.config/edgefeed/env (see .env.example).
# Logs: journalctl --user -u edgefeed-collector -f      Stop: systemctl --user disable --now edgefeed-{collector,api}
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
bin="$repo/.venv/bin/edgefeed"
[ -x "$bin" ] || { echo "run 'make install' first"; exit 1; }

data="${XDG_DATA_HOME:-$HOME/.local/share}/edgefeed"
conf="${XDG_CONFIG_HOME:-$HOME/.config}/edgefeed"
units="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$data" "$conf" "$units"
[ -f "$conf/env" ] || printf 'EDGEFEED_DB_URL=sqlite:///%s/edgefeed.sqlite\nEDGEFEED_INTERVAL=15\n' "$data" > "$conf/env"

unit() {  # name, description, args
  cat > "$units/$1.service" <<EOF
[Unit]
Description=$2
After=network-online.target

[Service]
WorkingDirectory=$repo
EnvironmentFile=$conf/env
ExecStart=$bin $3
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF
}
unit edgefeed-collector "EdgeFeed collector" "collect"
unit edgefeed-api "EdgeFeed dashboard and API" "serve --host 127.0.0.1 --port 8090"

systemctl --user daemon-reload
systemctl --user enable --now edgefeed-collector edgefeed-api
echo "running. dashboard: http://127.0.0.1:8090   logs: journalctl --user -u edgefeed-collector -f"
echo "to keep it running after you log out: loginctl enable-linger \"$USER\""
