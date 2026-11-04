"""Alert delivery. Telegram when configured; otherwise alerts only go to the log."""

from __future__ import annotations

import logging
from typing import Any, Protocol

import httpx

from edgefeed import metrics

log = logging.getLogger("edgefeed.alerts")

DISCLAIMER = "Analytics only, not financial advice."


class Notifier(Protocol):
    async def send(self, text: str) -> None: ...


class LogNotifier:
    async def send(self, text: str) -> None:
        log.info("alert: %s", text.replace("\n", " | "))
        metrics.alerts_sent.labels("log", "ok").inc()


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, client: httpx.AsyncClient | None = None) -> None:
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id
        self.client = client or httpx.AsyncClient(timeout=10)

    async def send(self, text: str) -> None:
        try:
            r = await self.client.post(
                self.url, json={"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True}
            )
            r.raise_for_status()
            metrics.alerts_sent.labels("telegram", "ok").inc()
        except httpx.HTTPError as e:  # an alert must never take the collector down
            metrics.alerts_sent.labels("telegram", "error").inc()
            log.warning("telegram send failed: %s", type(e).__name__)


def notifier(token: str, chat_id: str) -> Notifier:
    return TelegramNotifier(token, chat_id) if token and chat_id else LogNotifier()


def format_opportunity(o: dict[str, Any], label: str) -> str:
    legs = "\n".join(
        f"  buy {leg['side'].upper()} on {leg['venue']} x{leg['contracts']:.0f} "
        f"(avg {leg['avg_price'] * 100:.1f}c, worst {leg['worst_price'] * 100:.1f}c)"
        for leg in o["legs"]
    )
    warn = "".join(f"\n  ! {w}" for w in o.get("warnings") or [])
    return (
        f"EDGE {o['per_contract_cents']:.2f}c/contract, ${o['profit']:.2f} on ${o['cost'] + o['fees']:.0f}"
        f" ({o['apr'] * 100:.0f}% APR, {o['lock_days']:.1f}d lock)\n{label}\n{legs}{warn}\n{DISCLAIMER}"
    )
