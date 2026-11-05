"""Lead-lag detection: one venue reprices, the other has not caught up yet.

For every pair we keep a rolling window of both venues' YES mids. A signal fires when one venue
moved at least ``move`` cents over the window while the other moved at most ``lag`` cents and
they now disagree by at least ``gap`` cents. After ``followup`` seconds the signal is graded:

- hit: the laggard moved at least ``hit_frac`` of the gap toward where the leader was;
- revert: the leader came back instead (it was noise, not news);
- partial / miss: some or no convergence by the laggard.

A mid is only trusted when that book is tight (YES ask + NO ask - 1 <= ``max_width`` cents). The
first night of data showed why: 90% of signals were a wide, thin book whose mid jumped while the
other venue simply never traded. The hit rate is the calibration bar for the whole idea; until it
is measured, signals are research output, not advice.
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
    max_width: float = 4.0  # cents; wider books are ignored (their mid is noise)


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


def grade(
    leader_mid0: float, laggard_mid0: float, leader_now: float | None, laggard_now: float, hit_frac: float
) -> tuple[float, str]:
    """Share of the original gap the laggard closed toward the leader, and the outcome."""
    gap0 = leader_mid0 - laggard_mid0
    if gap0 == 0:
        return 0.0, "miss"
    frac = (laggard_now - laggard_mid0) / gap0
    if frac >= hit_frac:
        return round(frac, 3), "hit"
    if leader_now is not None and (leader_mid0 - leader_now) / gap0 >= hit_frac:
        return round(frac, 3), "revert"
    return round(frac, 3), ("partial" if frac > 0 else "miss")


class Detector:
    def __init__(self, cfg: LatencyConfig | None = None) -> None:
        self.cfg = cfg or LatencyConfig()
        self.tracks: dict[str, PairTracks] = {}

    def observe(
        self,
        key: str,
        ts: float,
        k_mid: float | None,
        p_mid: float | None,
        k_width: float | None = None,
        p_width: float | None = None,
    ) -> Signal | None:
        t = self.tracks.setdefault(key, PairTracks())
        # a wide book has no trustworthy mid: forget its history rather than compare against it
        if k_width is not None and k_width > self.cfg.max_width:
            t.kalshi.hist.clear()
            k_mid = None
        if p_width is not None and p_width > self.cfg.max_width:
            t.poly.hist.clear()
            p_mid = None
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
