"""Ported from the original NERO nero_app/core/white_house_impact.py — the
Jaccard-similarity keyword classifier and event-memory scoring logic are unchanged.
Import path and default data path are adapted to this repo's layout only.

AUDIT NOTE (see docs/white_house_audit.md): this module's classification and scoring
logic is pure keyword-matching + Jaccard similarity over historical event tags — no LLM,
no Gemini or other API key is used anywhere in this file. `load_white_house_events`
reads a local CSV; nothing here makes a network call.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

DEFAULT_WHITE_HOUSE_MEMORY_PATH = Path("data/white_house_market_events.csv")

TAG_KEYWORDS = {
    "crypto_regulation": ["crypto", "digital asset", "bitcoin", "stablecoin", "cbdc", "token"],
    "crypto_friendly_policy": ["crypto capital", "digital financial technology", "strategic bitcoin reserve", "digital asset stockpile"],
    "policy_hostile": ["veto", "crackdown", "enforcement", "ban", "restriction"],
    "policy_clarity": ["framework", "clarity", "legislation", "rules", "responsible development"],
    "strategic_bitcoin_reserve": ["bitcoin reserve", "strategic reserve"],
    "stablecoin_legislation": ["stablecoin", "genius act"],
    "sanctions": ["sanction", "sanctions"],
    "war": ["war", "attack", "invasion", "military"],
    "geopolitical_risk": ["ukraine", "russia", "iran", "israel", "middle east", "nato", "conflict"],
    "risk_off": ["risk-off", "uncertainty", "crisis", "emergency"],
    "safe_haven": ["safe haven", "safe-haven"],
    "oil_supply_risk": ["oil", "energy", "opec", "supply"],
    "tariff": ["tariff", "trade war"],
    "inflation_risk": ["inflation", "prices", "cost of living"],
    "institutional_legitimacy": ["reserve", "stockpile", "institutional", "treasury"],
    "structural_adoption": ["adoption", "stockpile", "reserve", "framework", "stablecoin"],
}


@dataclass(frozen=True)
class WhiteHouseImpactResult:
    query_tags: set[str]
    matched_events: int
    btc_average_impact: float
    gold_average_impact: float
    btc_direction: str
    gold_direction: str
    confidence: float
    top_events: list[str]
    notes: list[str]


def load_white_house_events(path: Path = DEFAULT_WHITE_HOUSE_MEMORY_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        frame = pd.read_csv(path)
    except (OSError, UnicodeDecodeError, pd.errors.EmptyDataError):
        return pd.DataFrame()
    return frame.fillna("")


def classify_white_house_text(text: str) -> set[str]:
    lowered = text.lower()
    tags = {tag for tag, keywords in TAG_KEYWORDS.items() if any(keyword in lowered for keyword in keywords)}
    if "sanctions" in tags or "war" in tags or "geopolitical_risk" in tags:
        tags.add("risk_off")
        tags.add("safe_haven")
    if "strategic_bitcoin_reserve" in tags:
        tags.add("crypto_friendly_policy")
        tags.add("institutional_legitimacy")
        tags.add("structural_adoption")
    if "stablecoin_legislation" in tags:
        tags.add("policy_clarity")
        tags.add("structural_adoption")
    return tags


def score_white_house_impact(text: str, events: pd.DataFrame | None = None, top_n: int = 3) -> WhiteHouseImpactResult:
    memory = load_white_house_events() if events is None else events.fillna("")
    query_tags = classify_white_house_text(text)
    if memory.empty or not query_tags:
        return WhiteHouseImpactResult(
            query_tags=query_tags,
            matched_events=0,
            btc_average_impact=0.0,
            gold_average_impact=0.0,
            btc_direction="neutral",
            gold_direction="neutral",
            confidence=0.0,
            top_events=[],
            notes=["No matching tags or memory events available."],
        )

    scored = memory.copy()
    scored["tag_set"] = scored["tags"].astype(str).apply(_split_tags)
    scored["similarity"] = scored["tag_set"].apply(lambda tags: _jaccard(query_tags, tags))
    scored = scored[scored["similarity"] > 0].sort_values(["similarity", "confidence"], ascending=False)
    if scored.empty:
        return WhiteHouseImpactResult(
            query_tags=query_tags,
            matched_events=0,
            btc_average_impact=0.0,
            gold_average_impact=0.0,
            btc_direction="neutral",
            gold_direction="neutral",
            confidence=0.0,
            top_events=[],
            notes=["No similar White House memory event found."],
        )

    top = scored.head(max(1, top_n)).copy()
    weights = pd.to_numeric(top["similarity"], errors="coerce").fillna(0.0)
    btc_impacts = pd.to_numeric(top.get("btc_impact_score", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    gold_impacts = pd.to_numeric(top.get("gold_impact_score", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    confidences = pd.to_numeric(top.get("confidence", pd.Series(dtype=float)), errors="coerce").fillna(0.0)

    btc_average = _weighted_average(btc_impacts, weights)
    gold_average = _weighted_average(gold_impacts, weights)
    confidence = min(1.0, float(confidences.mean()) * min(1.0, len(top) / 3) * (0.7 + float(weights.mean()) * 0.3))

    top_events = [
        f"{row.get('date', '')} | {row.get('headline', '')} | similarity={row.get('similarity', 0):.2f}"
        for _, row in top.iterrows()
    ]
    notes = _notes(query_tags, btc_average, gold_average)
    return WhiteHouseImpactResult(
        query_tags=query_tags,
        matched_events=int(len(scored)),
        btc_average_impact=btc_average,
        gold_average_impact=gold_average,
        btc_direction=_direction(btc_average),
        gold_direction=_direction(gold_average),
        confidence=confidence,
        top_events=top_events,
        notes=notes,
    )


def format_white_house_impact_report(result: WhiteHouseImpactResult) -> str:
    return "\n".join(
        [
            "NERO White House Market Impact",
            f"Detected tags: {', '.join(sorted(result.query_tags)) if result.query_tags else 'none'}",
            f"Matched events: {result.matched_events}",
            f"BTC impact: {result.btc_direction} ({result.btc_average_impact:.0f}/100)",
            f"Gold impact: {result.gold_direction} ({result.gold_average_impact:.0f}/100)",
            f"Confidence: {result.confidence:.0%}",
            "Top historical matches:",
            *(f"- {event}" for event in result.top_events[:3]),
            "Notes:",
            *(f"- {note}" for note in result.notes),
        ]
    )


def _split_tags(value: str) -> set[str]:
    return {item.strip() for item in str(value).split("|") if item.strip()}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _weighted_average(values: pd.Series, weights: pd.Series) -> float:
    total_weight = float(weights.sum())
    if total_weight <= 0:
        return 0.0
    return float((values * weights).sum() / total_weight)


def _direction(score: float) -> str:
    if score >= 65:
        return "bullish/high positive impact"
    if score >= 35:
        return "mixed/moderate impact"
    if score > 0:
        return "low impact"
    if score <= -35:
        return "bearish/high negative impact"
    return "neutral"


def _notes(tags: set[str], btc_average: float, gold_average: float) -> list[str]:
    notes: list[str] = []
    if "crypto_friendly_policy" in tags or "strategic_bitcoin_reserve" in tags:
        notes.append("Crypto-friendly White House policy historically supports BTC mainly through legitimacy and institutional adoption narratives.")
    if "policy_hostile" in tags:
        notes.append("Hostile crypto policy can pressure BTC by increasing custody/regulatory friction.")
    if "sanctions" in tags or "geopolitical_risk" in tags:
        notes.append("Sanctions/geopolitical shocks can support Gold as safe haven but BTC impact can be mixed because BTC also behaves like a risk asset.")
    if btc_average >= 65 and gold_average < 35:
        notes.append("This setup is more BTC-specific than Gold-specific.")
    if gold_average >= 65 and btc_average < 45:
        notes.append("This setup is more Gold/safe-haven specific than BTC-specific.")
    return notes or ["Impact is likely mixed; confirm with DXY, yields, Nasdaq, ETF flows and BTC/Gold technical structure."]
