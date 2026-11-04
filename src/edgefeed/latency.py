"""Lead-lag detection: one venue reprices, the other has not caught up yet.

For every pair we keep a rolling window of both venues' YES mids. A signal fires when one venue
moved at least ``move`` cents over the window while the other moved at most ``lag`` cents and
they now disagree by at least ``gap`` cents. After ``followup`` seconds the signal is graded: did
the laggard close at least ``hit_frac`` of the gap? The hit rate is the calibration bar for the
whole idea; until it is measured, signals are research output, not advice.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class LatencyConfig:
    window: float = 240.0  # seconds
    move: float = 2.0  # cents the leader must move
    lag: float = 1.0  # cents the laggard may have moved at most
    gap: float = 2.0  # cents of disagreement required
    cooldown: float = 180.0
    followup: float = 600.0
    hit_frac: float = 0.4


@dataclass(slots=True)
class Track:
    hist: deque[tuple[float, float]] = field(default_factory=deque)

    def push(self, ts: float, mid: float | None, window: float) -> None:
        if mid is not None:
            self.hist.append((ts, mid))
        while self.hist and ts - self.hist[0][0] > window:
            self.hist.popleft()

    def latest(self) -> float | None:
        return self.hist[-1][1] if self.hist else None

    def move(self) -> float:
        return self.hist[-1][1] - self.hist[0][1] if len(self.hist) >= 2 else 0.0


@dataclass(frozen=True, slots=True)
class Signal:
    pair_key: str
    leader: str
    laggard: str
    leader_move: float
    laggard_move: float
    gap: float
    leader_mid: float
    laggard_mid: float


@dataclass(slots=True)
class PairTracks:
    kalshi: Track = field(default_factory=Track)
    poly: Track = field(default_factory=Track)
    last_fired: float = -1e18


def detect(key: str, t: PairTracks, cfg: LatencyConfig) -> Signal | None:
    k, p = t.kalshi.latest(), t.poly.latest()
    if k is None or p is None or abs(k - p) < cfg.gap:
        return None
    km, pm = t.kalshi.move(), t.poly.move()
    if abs(km) >= cfg.move and abs(pm) <= cfg.lag:
        return Signal(key, "kalshi", "polymarket", round(km, 2), round(pm, 2), round(abs(k - p), 2), k, p)
    if abs(pm) >= cfg.move and abs(km) <= cfg.lag:
        return Signal(key, "polymarket", "kalshi", round(pm, 2), round(km, 2), round(abs(k - p), 2), p, k)
    return None


def grade(leader_mid: float, laggard_mid0: float, laggard_now: float, hit_frac: float) -> tuple[float, str]:
    """Fraction of the original gap the laggard closed, and hit / partial / miss."""
    gap0 = abs(laggard_mid0 - leader_mid)
    frac = (gap0 - abs(laggard_now - leader_mid)) / gap0 if gap0 > 0 else 0.0
    return round(frac, 3), ("hit" if frac >= hit_frac else "partial" if frac > 0 else "miss")


class Detector:
    def __init__(self, cfg: LatencyConfig | None = None) -> None:
        self.cfg = cfg or LatencyConfig()
        self.tracks: dict[str, PairTracks] = {}

    def observe(self, key: str, ts: float, k_mid: float | None, p_mid: float | None) -> Signal | None:
        t = self.tracks.setdefault(key, PairTracks())
        t.kalshi.push(ts, k_mid, self.cfg.window)
        t.poly.push(ts, p_mid, self.cfg.window)
        sig = detect(key, t, self.cfg)
        if sig is None or ts - t.last_fired < self.cfg.cooldown:
            return None
        t.last_fired = ts
        return sig

    def latest(self, key: str, venue: str) -> float | None:
        t = self.tracks.get(key)
        if not t:
            return None
        return (t.kalshi if venue == "kalshi" else t.poly).latest()
