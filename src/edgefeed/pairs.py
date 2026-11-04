"""The curated pair list (config/pairs.yaml) and rule fingerprints."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from edgefeed.arb import Relation


@dataclass(frozen=True, slots=True)
class Pair:
    kalshi: str
    polymarket: str
    relation: Relation = Relation.SAME
    label: str = ""
    verified: date | None = None
    outcome: str = "Yes"  # the Polymarket outcome that plays YES (a team name on moneylines)
    source: str = "curated"  # curated | sports
    rule_risk: str = ""  # known settlement differences between the two rule texts

    @property
    def key(self) -> str:
        suffix = "" if self.outcome.lower() == "yes" else f":{self.outcome}"
        return f"{self.kalshi}<>{self.polymarket}{suffix}"


def load(path: str | Path) -> list[Pair]:
    data: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    out: list[Pair] = []
    seen: set[str] = set()
    for i, row in enumerate(data.get("pairs") or []):
        if not row.get("kalshi") or not row.get("polymarket"):
            raise ValueError(f"{path}: pair #{i + 1} needs both 'kalshi' and 'polymarket'")
        p = Pair(
            kalshi=str(row["kalshi"]),
            polymarket=str(row["polymarket"]),
            relation=Relation(row.get("relation", "same")),
            label=str(row.get("label", "")),
            verified=row.get("verified"),
            outcome=str(row.get("outcome", "Yes")),
            rule_risk=str(row.get("rule_risk", "")),
        )
        if p.key in seen:
            raise ValueError(f"{path}: duplicate pair {p.key}")
        seen.add(p.key)
        out.append(p)
    return out


_WS = re.compile(r"\s+")


def fingerprint(rules: str) -> str:
    """Stable hash of a rules text: whitespace and case changes don't count as a rule change."""
    norm = _WS.sub(" ", rules).strip().lower()
    return hashlib.sha256(norm.encode()).hexdigest()[:16]
