"""Deterministic game matching: league + date + team codes, no fuzzy titles.

Kalshi lists a game as ``KXNBAGAME-26NOV04ATLWAS`` with one market per team (``...-ATL``) and,
for soccer, ``...-TIE``. Polymarket lists the same game under the slug
``nba-atl-was-2026-11-04``: a single moneyline market whose two outcomes are the team names
(US leagues), or one Yes/No market per team plus a draw market (soccer).

Every match is sanity-checked on price: if the two venues disagree by more than
``MAX_PRICE_GAP`` the mapping is probably flipped and the pair is dropped, not traded on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from edgefeed.arb import Relation
from edgefeed.pairs import Pair
from edgefeed.venues.kalshi import KalshiClient, parse_time
from edgefeed.venues.polymarket import PolymarketClient, _json_list

MAX_PRICE_GAP = Decimal("0.25")

TWO_WAY_RISK = (
    "postponed or cancelled games settle differently "
    "(Kalshi: fair price if not started within 48h; Polymarket: stays open, or 50-50 if cancelled)"
)
SOCCER_RISK = "cancelled match settles differently (Polymarket's draw market resolves Yes; Kalshi pays a fair price)"


@dataclass(frozen=True, slots=True)
class League:
    name: str
    kalshi_series: str
    poly_prefix: str
    three_way: bool = False


LEAGUES: dict[str, League] = {
    lg.name: lg
    for lg in (
        League("nba", "KXNBAGAME", "nba"),
        League("nhl", "KXNHLGAME", "nhl"),
        League("nfl", "KXNFLGAME", "nfl"),
        League("mlb", "KXMLBGAME", "mlb"),
        League("wnba", "KXWNBAGAME", "wnba"),
        League("ncaab", "KXNCAAMBGAME", "cbb"),
        League("epl", "KXEPLGAME", "epl", three_way=True),
        League("laliga", "KXLALIGAGAME", "lal", three_way=True),
        League("seriea", "KXSERIEAGAME", "sea", three_way=True),
        League("bundesliga", "KXBUNDESLIGAGAME", "bun", three_way=True),
        League("ligue1", "KXLIGUE1GAME", "fl1", three_way=True),
        League("ucl", "KXUCLGAME", "ucl", three_way=True),
    )
}

# Kalshi code -> Polymarket slug code, where they differ.
ALIASES: dict[str, dict[str, str]] = {
    "nfl": {"JAC": "jax", "LA": "lar"},
    "nba": {"GS": "gsw", "NO": "nop", "NY": "nyk", "SA": "sas"},
    "nhl": {"LA": "lak", "NJ": "njd", "SJ": "sjs", "TB": "tbl"},
}

_MONTHS = {
    m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)
}
_EVENT = re.compile(r"^[A-Z0-9]+-(\d{2})([A-Z]{3})(\d{2})([A-Z]+)$")


def parse_event(event_ticker: str) -> tuple[date, str] | None:
    """``KXNBAGAME-26NOV04ATLWAS`` -> (2026-11-04, 'ATLWAS')."""
    m = _EVENT.match(event_ticker)
    if not m or m.group(2) not in _MONTHS:
        return None
    yy, mon, dd, teams = m.groups()
    try:
        return date(2000 + int(yy), _MONTHS[mon], int(dd)), teams
    except ValueError:
        return None


def team_codes(event_ticker: str, markets: list[dict[str, Any]]) -> list[str]:
    """Team codes in event order (away, home), from the market ticker suffixes."""
    parsed = parse_event(event_ticker)
    codes = [m["ticker"].rsplit("-", 1)[-1] for m in markets]
    codes = [c for c in codes if c != "TIE"]
    if not parsed or len(codes) != 2:
        return []
    teams = parsed[1]
    a = next((c for c in codes if teams.startswith(c) and teams[len(c) :] in codes), None)
    if a is None:
        return []
    return [a, teams[len(a) :]]


def slug_candidates(league: League, codes: list[str], day: date) -> list[str]:
    al = ALIASES.get(league.name, {})
    a, b = (al.get(c, c.lower()) for c in codes)
    d = day.isoformat()
    return [f"{league.poly_prefix}-{a}-{b}-{d}", f"{league.poly_prefix}-{b}-{a}-{d}"]


def _price(v: Any) -> Decimal | None:
    try:
        d = Decimal(str(v))
    except (ArithmeticError, ValueError):
        return None
    return d if 0 < d < 1 else None


def _close(a: Decimal | None, b: Decimal | None) -> bool:
    return a is None or b is None or abs(a - b) <= MAX_PRICE_GAP


def match_two_way(league: League, kev: dict[str, Any], pev: dict[str, Any], slug: str) -> list[Pair]:
    ml = next((m for m in pev.get("markets") or [] if m.get("sportsMarketType") == "moneyline"), None)
    if not ml:
        return []
    outcomes = [str(o) for o in _json_list(ml.get("outcomes"))]
    prices = [_price(p) for p in _json_list(ml.get("outcomePrices"))]
    codes = team_codes(kev["event_ticker"], kev["markets"])
    if len(outcomes) != 2 or len(codes) != 2:
        return []
    al = ALIASES.get(league.name, {})
    slug_order = slug.split("-")[1:3]
    out: list[Pair] = []
    for km in kev["markets"]:
        code = km["ticker"].rsplit("-", 1)[-1]
        poly_code = al.get(code, code.lower())
        if poly_code not in slug_order:
            continue
        idx = slug_order.index(poly_code)
        if not _close(_price(km.get("yes_ask_dollars")), prices[idx] if idx < len(prices) else None):
            continue  # venues disagree too much: mapping is suspect, skip it
        out.append(
            Pair(
                kalshi=km["ticker"],
                polymarket=str(ml["id"]),
                relation=Relation.SAME,
                outcome=outcomes[idx],
                label=f"{league.name.upper()} {kev.get('title', '')}: {km.get('yes_sub_title') or code}",
                source="sports",
                rule_risk=TWO_WAY_RISK,
                starts_at=game_start(ml, pev),
            )
        )
    return out


def game_start(market: dict[str, Any], event: dict[str, Any]) -> datetime | None:
    """Kick-off / tip-off time. Polymarket has it per market; Kalshi only has an expected end."""
    return parse_time(market.get("gameStartTime")) or parse_time(event.get("startTime"))


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower())


def match_three_way(league: League, kev: dict[str, Any], pev: dict[str, Any]) -> list[Pair]:
    pms = [m for m in pev.get("markets") or [] if m.get("sportsMarketType") == "moneyline"]
    out: list[Pair] = []
    for km in kev["markets"]:
        code = km["ticker"].rsplit("-", 1)[-1]
        name = _norm(str(km.get("yes_sub_title") or ""))
        if code == "TIE":
            pm = next((m for m in pms if "draw" in _norm(str(m.get("question")))), None)
        else:
            pm = next(
                (m for m in pms if name and f"will {name}" in _norm(str(m.get("question")))),
                None,
            )
        if not pm:
            continue
        yes = _price((_json_list(pm.get("outcomePrices")) or [None])[0])
        if not _close(_price(km.get("yes_ask_dollars")), yes):
            continue
        out.append(
            Pair(
                kalshi=km["ticker"],
                polymarket=str(pm["id"]),
                relation=Relation.SAME,
                label=f"{league.name.upper()} {kev.get('title', '')}: {km.get('yes_sub_title') or code}",
                source="sports",
                rule_risk=SOCCER_RISK,
                starts_at=game_start(pm, pev),
            )
        )
    return out


@dataclass(slots=True)
class Coverage:
    league: str
    kalshi_games: int = 0
    matched_games: int = 0
    pairs: int = 0


async def discover(
    kalshi: KalshiClient,
    poly: PolymarketClient,
    leagues: list[str] | None = None,
    *,
    days_ahead: int = 3,
    today: date | None = None,
) -> tuple[list[Pair], list[Coverage]]:
    today = today or datetime.now().date()
    pairs: list[Pair] = []
    coverage: list[Coverage] = []
    for name in leagues or list(LEAGUES):
        lg = LEAGUES[name]
        cov = Coverage(lg.name)
        data = await kalshi.http.get(
            "/events", series_ticker=lg.kalshi_series, status="open", with_nested_markets="true", limit=200
        )
        for kev in data.get("events", []):
            parsed = parse_event(kev.get("event_ticker", ""))
            if not parsed or not (0 <= (parsed[0] - today).days <= days_ahead):
                continue
            cov.kalshi_games += 1
            codes = team_codes(kev["event_ticker"], kev.get("markets") or [])
            if not codes:
                continue
            for slug in slug_candidates(lg, codes, parsed[0]):
                pev = await poly.event_by_slug(slug)
                if not pev:
                    continue
                found = match_three_way(lg, kev, pev) if lg.three_way else match_two_way(lg, kev, pev, slug)
                if found:
                    cov.matched_games += 1
                    cov.pairs += len(found)
                    pairs.extend(found)
                break
        coverage.append(cov)
    return pairs, coverage
