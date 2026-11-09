"""Collector timers: the first run of each periodic job must not wait a full period after boot."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from edgefeed import collector as collector_mod
from edgefeed.config import Settings


@pytest.fixture
def just_booted(monkeypatch: pytest.MonkeyPatch) -> None:
    # time.monotonic() counts from boot (and stops during suspend): a few seconds after a reboot
    monkeypatch.setattr(collector_mod.time, "monotonic", lambda: 5.0)


def make(tmp_path: Path) -> collector_mod.Collector:
    return collector_mod.Collector(Settings(db_url=f"sqlite:///{tmp_path / 'c.sqlite'}", metrics_port=0))


async def test_first_sports_discovery_runs_right_after_boot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, just_booted: None
) -> None:
    calls: list[Any] = []

    async def discover(*args: Any, **kwargs: Any) -> tuple[list[Any], list[Any]]:
        calls.append(args)
        return [], []

    monkeypatch.setattr(collector_mod.sports, "discover", discover)
    c = make(tmp_path)
    await c.refresh_sports()
    await c.refresh_sports()  # second call inside the period is skipped
    assert len(calls) == 1


async def test_first_paper_settle_runs_right_after_boot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, just_booted: None
) -> None:
    calls: list[int] = []
    c = make(tmp_path)

    async def settle() -> list[Any]:
        calls.append(1)
        return []

    monkeypatch.setattr(c.paper, "settle", settle)
    await c.settle()
    await c.settle()
    assert calls == [1]
