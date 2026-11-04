from datetime import date

from edgefeed.discovery import sports as S


def kev(ticker, markets, title="Atlanta vs Washington"):
    return {"event_ticker": ticker, "title": title, "markets": markets}


def km(ticker, ask, sub):
    return {"ticker": ticker, "yes_ask_dollars": ask, "yes_sub_title": sub}


def test_parse_event_and_codes():
    assert S.parse_event("KXNBAGAME-26NOV04ATLWAS") == (date(2026, 11, 4), "ATLWAS")
    assert S.parse_event("garbage") is None
    ms = [
        km("KXNBAGAME-26NOV04ATLWAS-WAS", "0.45", "Washington"),
        km("KXNBAGAME-26NOV04ATLWAS-ATL", "0.56", "Atlanta"),
    ]
    assert S.team_codes("KXNBAGAME-26NOV04ATLWAS", ms) == ["ATL", "WAS"]


def test_slugs_use_aliases_and_both_orders():
    lg = S.LEAGUES["nfl"]
    assert S.slug_candidates(lg, ["JAC", "BAL"], date(2026, 11, 5)) == [
        "nfl-jax-bal-2026-11-05",
        "nfl-bal-jax-2026-11-05",
    ]


def two_way_pev(prices='["0.555", "0.445"]'):
    return {
        "markets": [
            {"id": 1, "sportsMarketType": "totals", "outcomes": '["Over", "Under"]'},
            {
                "id": 6374092,
                "sportsMarketType": "moneyline",
                "outcomes": '["Hawks", "Wizards"]',
                "outcomePrices": prices,
            },
        ]
    }


def test_two_way_maps_each_kalshi_team_to_its_outcome():
    ms = [
        km("KXNBAGAME-26NOV04ATLWAS-ATL", "0.56", "Atlanta"),
        km("KXNBAGAME-26NOV04ATLWAS-WAS", "0.45", "Washington"),
    ]
    pairs = S.match_two_way(
        S.LEAGUES["nba"], kev("KXNBAGAME-26NOV04ATLWAS", ms), two_way_pev(), "nba-atl-was-2026-11-04"
    )
    assert {(p.kalshi[-3:], p.outcome) for p in pairs} == {("ATL", "Hawks"), ("WAS", "Wizards")}
    assert all(p.source == "sports" and p.rule_risk for p in pairs)


def test_two_way_drops_a_suspect_mapping():
    ms = [km("KXNBAGAME-26NOV04ATLWAS-ATL", "0.90", "Atlanta")]
    ms.append(km("KXNBAGAME-26NOV04ATLWAS-WAS", "0.12", "Washington"))
    pev = two_way_pev('["0.10", "0.90"]')  # prices say the outcomes are the other way round
    assert S.match_two_way(S.LEAGUES["nba"], kev("KXNBAGAME-26NOV04ATLWAS", ms), pev, "nba-atl-was-2026-11-04") == []


def test_three_way_soccer_matches_team_and_draw_markets():
    ms = [
        km("KXEPLGAME-26NOV06EVECOV-EVE", "0.57", "Everton"),
        km("KXEPLGAME-26NOV06EVECOV-COV", "0.20", "Coventry"),
        km("KXEPLGAME-26NOV06EVECOV-TIE", "0.25", "Tie"),
    ]
    pev = {
        "markets": [
            {
                "id": 1,
                "sportsMarketType": "moneyline",
                "question": "Will Everton FC win on 2026-11-06?",
                "outcomePrices": '["0.565","0.435"]',
            },
            {
                "id": 2,
                "sportsMarketType": "moneyline",
                "question": "Will Everton FC vs. Coventry City FC end in a draw?",
                "outcomePrices": '["0.24","0.76"]',
            },
            {
                "id": 3,
                "sportsMarketType": "moneyline",
                "question": "Will Coventry City FC win on 2026-11-06?",
                "outcomePrices": '["0.195","0.805"]',
            },
        ]
    }
    pairs = S.match_three_way(S.LEAGUES["epl"], kev("KXEPLGAME-26NOV06EVECOV", ms, "Everton vs Coventry"), pev)
    assert {(p.kalshi[-3:], p.polymarket) for p in pairs} == {("EVE", "1"), ("COV", "3"), ("TIE", "2")}
    assert all("draw" in p.rule_risk for p in pairs)
