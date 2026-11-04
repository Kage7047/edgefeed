"""Settings from the environment (``EDGEFEED_*``), with defaults that run out of the box."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal


def _env(name: str, default: str) -> str:
    return os.environ.get(f"EDGEFEED_{name}", default)


@dataclass(frozen=True, slots=True)
class Settings:
    db_url: str = field(default_factory=lambda: _env("DB_URL", "sqlite:///edgefeed.sqlite"))
    pairs_file: str = field(default_factory=lambda: _env("PAIRS", "config/pairs.yaml"))
    interval: float = field(default_factory=lambda: float(_env("INTERVAL", "20")))
    sports: list[str] = field(
        default_factory=lambda: [
            s for s in _env("SPORTS", "nba,nhl,nfl,mlb,ncaab,epl,laliga,seriea,ucl").split(",") if s
        ]
    )
    sports_days_ahead: int = field(default_factory=lambda: int(_env("SPORTS_DAYS_AHEAD", "2")))
    discovery_every: float = field(default_factory=lambda: float(_env("DISCOVERY_EVERY", "900")))
    # an opportunity is recorded once it clears both bars
    min_edge_cents: Decimal = field(default_factory=lambda: Decimal(_env("MIN_EDGE_CENTS", "0.25")))
    min_profit: Decimal = field(default_factory=lambda: Decimal(_env("MIN_PROFIT", "1")))
    # ... and alerted on only when it also beats this annualised return (a T-bill is ~4%)
    alert_min_apr: Decimal = field(default_factory=lambda: Decimal(_env("ALERT_MIN_APR", "0.10")))
    alert_min_profit: Decimal = field(default_factory=lambda: Decimal(_env("ALERT_MIN_PROFIT", "5")))
    max_contracts: Decimal | None = field(
        default_factory=lambda: Decimal(v) if (v := _env("MAX_CONTRACTS", "")) else None
    )
    keep_quotes_days: int = field(default_factory=lambda: int(_env("KEEP_QUOTES_DAYS", "30")))
    telegram_token: str = field(default_factory=lambda: _env("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat: str = field(default_factory=lambda: _env("TELEGRAM_CHAT_ID", ""))
    metrics_port: int = field(default_factory=lambda: int(_env("METRICS_PORT", "9108")))  # 0 = off
    latency_alerts: bool = field(default_factory=lambda: _env("LATENCY_ALERTS", "0") == "1")
