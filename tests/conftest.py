from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from edgefeed import fees
from edgefeed.models import Book, Level, Venue
from edgefeed.store import Store

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def lv(*pairs: tuple[str, str | int]) -> list[Level]:
    return [Level(Decimal(p), Decimal(str(s))) for p, s in pairs]


def kbook(yes: list[Level], no: list[Level], *, market: str = "K1", days: float = 1.0, rules: str = "") -> Book:
    return Book(
        Venue.KALSHI,
        market,
        yes,
        no,
        fees.kalshi(1),
        title=market,
        closes_at=NOW + timedelta(days=days),
        rules=rules,
    )


def pbook(
    yes: list[Level],
    no: list[Level],
    *,
    market: str = "P1",
    rate: str = "0.04",
    days: float = 1.0,
    rules: str = "",
    min_size: str = "1",
) -> Book:
    return Book(
        Venue.POLYMARKET,
        market,
        yes,
        no,
        fees.polymarket(rate),
        title=market,
        closes_at=NOW + timedelta(days=days),
        rules=rules,
        min_size=Decimal(min_size),
    )


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(f"sqlite:///{tmp_path / 'ledger.sqlite'}")
