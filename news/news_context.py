#!/usr/bin/env python3
"""
Free news context (optional, best-effort, $0).

When a latency signal fires, attach a plausible recent headline so the alert is
human-meaningful. Uses Google News RSS (free, unlimited, no key). GDELT is an
alternative for structured event data (free, 15-min cadence) but RSS is enough
to surface a headline. All failures are swallowed — this is a nicety, not core.

Keyword source: the pair key is "<kalshi_ticker><><poly_id>"; we derive rough
keywords from the Kalshi ticker. For real use, pass better keywords from the
curated pair's notes.
"""
from __future__ import annotations

import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

_UA = {"User-Agent": "edgefeed-news/0.1", "Accept": "application/rss+xml"}

# very small ticker->keyword hints; extend as needed
_HINTS = {
    "KXPRESNOMD": "2028 Democratic presidential nomination",
    "KXPRESNOMR": "2028 Republican presidential nomination",
    "KXPRESPERSON": "2028 US presidential election",
    "KXNEXTISRAELPM": "Israel prime minister",
    "KXNEXTROMANIAPM": "Romania prime minister",
}


def _keywords_from_key(pair_key: str) -> str:
    ticker = pair_key.split("<>")[0]
    for prefix, kw in _HINTS.items():
        if ticker.startswith(prefix):
            # append the candidate suffix (e.g. -BS, -TCAR) as a loose hint
            return kw
    # fallback: strip non-alpha from the ticker
    return re.sub(r"[^A-Za-z ]", " ", ticker)


def headline_for(pair_key: str, when_hours: int = 12) -> str | None:
    """Return the most recent Google News headline for the pair's topic, or None."""
    kw = _keywords_from_key(pair_key)
    if not kw.strip():
        return None
    q = urllib.parse.quote(f"{kw} when:{when_hours}h")
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=8) as resp:
            root = ET.fromstring(resp.read())
    except Exception:
        return None
    item = root.find(".//item")
    if item is None:
        return None
    title = item.findtext("title")
    return title.strip() if title else None


if __name__ == "__main__":
    import sys
    key = sys.argv[1] if len(sys.argv) > 1 else "KXPRESNOMD-28-BS<>559679"
    print(f"keywords: {_keywords_from_key(key)}")
    print(f"headline: {headline_for(key)}")
