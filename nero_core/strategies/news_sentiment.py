"""NEWS_SENTIMENT — forward-test-only news sentiment signal (see
nero_core.execution.live_scheduler).

Not a paper-trading strategy in the sense every other module in this package is: no
entry/exit, no OpenTrade, nothing backtested against history. See
docs/research_phase_closure.md — no historical dataset with a trustworthy backdated
publication timestamp exists, so this is scoped to live/forward use only, never
retroactively fabricated. It is still registered in the strategy registry (per project
convention: any live signal source must be versionable), so a future prompt/threshold/
model change is a new version, never a silent parameter mutation of this one.

LOOKAHEAD GUARD: a headline only counts toward the sentiment signal if its own PUBLISHED
timestamp (not the time we happened to fetch it) is at least `min_publication_age_hours`
old relative to the moment of evaluation — modeling real-world propagation lag between a
story publishing and a trader being able to react to it. Enforced in
`select_eligible_headlines`, independent of whatever ranking/fallback logic
`NewsFeedClient` itself does. Signals act on news >= 2h old to avoid lookahead bias.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

from nero_core.data_sources.news_feed import NewsItem
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_ID = "NEWS_SENTIMENT"
STRATEGY_VERSION = "news-sentiment-v1.0.0"

STRATEGY_DESCRIPTION = (
    "Forward-test-only news sentiment signal for GOLD and BTC. Fetches RSS headlines "
    "(nero_core.data_sources.news_feed, ported unchanged from the original NERO "
    "news_feed.py), keeps only headlines whose PUBLISHED timestamp is at least "
    "min_publication_age_hours old as of evaluation time (default 2h — the lookahead "
    "buffer), then scores sentiment via Gemini (GEMINI_API_KEY) with a local "
    "keyword-count fallback — same dual-path pattern as the original NERO "
    "ai_sentiment.py. No historical backtest exists for this signal (see "
    "docs/research_phase_closure.md); it is logged live, forward-only, never "
    "retroactively fabricated."
)

POSITIVE_WORDS = {"surge", "jump", "rise", "gain", "record high", "breakout", "rally", "strong", "bullish", "improves"}
NEGATIVE_WORDS = {"selloff", "crash", "drop", "collapse", "weak", "bearish", "falls", "risk", "caution", "slumps"}


@dataclass(frozen=True)
class NewsSentimentParameters:
    min_publication_age_hours: float = 2.0
    daily_run_hour_utc: int = 19
    headline_limit: int = 12
    bullish_score_threshold: int = 3   # score >= this -> BUY_BIAS
    bearish_score_threshold: int = -3  # score <= this -> SELL_BIAS
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout_seconds: int = 20


DEFAULT_PARAMETERS = NewsSentimentParameters()


@dataclass(frozen=True)
class SentimentResult:
    signal_type: str  # "BUY_BIAS" | "SELL_BIAS" | "NEUTRAL"
    sentiment_score: int
    confidence: float
    summary: str
    source: str  # "Gemini" | "local" | "local fallback after Gemini error" | "no eligible headlines"


def parse_published(published: str) -> datetime | None:
    """Parse an RSS pubDate (RFC822) into a UTC-aware datetime. Returns None — never a
    guessed/assumed timestamp — if the string can't be parsed, so a malformed feed can
    only make this signal MORE conservative (the headline gets excluded), never less
    lookahead-safe."""
    if not published:
        return None
    try:
        parsed = parsedate_to_datetime(published)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def select_eligible_headlines(
    headlines: list[NewsItem],
    now: datetime,
    min_publication_age_hours: float = DEFAULT_PARAMETERS.min_publication_age_hours,
) -> list[NewsItem]:
    """Keep only headlines published at least `min_publication_age_hours` before `now`.
    A headline with an unparseable/missing published timestamp is excluded, not assumed
    eligible — see `parse_published`."""
    if now.tzinfo is None:
        raise ValueError("`now` must be timezone-aware (UTC)")
    cutoff = now.astimezone(timezone.utc) - timedelta(hours=min_publication_age_hours)
    eligible = []
    for item in headlines:
        published_at = parse_published(item.published)
        if published_at is not None and published_at <= cutoff:
            eligible.append(item)
    return eligible


def analyze_sentiment(
    headlines: list[NewsItem],
    asset: str,
    now: datetime,
    gemini_api_key: str = "",
    params: NewsSentimentParameters = DEFAULT_PARAMETERS,
) -> SentimentResult:
    eligible = select_eligible_headlines(headlines, now, params.min_publication_age_hours)
    if not eligible:
        return SentimentResult(
            "NEUTRAL", 0, 0.0,
            f"No headlines published >= {params.min_publication_age_hours}h ago as of evaluation time "
            "(lookahead buffer not satisfied) — no signal generated.",
            "no eligible headlines",
        )

    if gemini_api_key.strip():
        try:
            return _analyze_with_gemini(eligible, asset, gemini_api_key.strip(), params)
        except (requests.RequestException, KeyError, ValueError, json.JSONDecodeError):
            return _local_sentiment(eligible, asset, params, source="local fallback after Gemini error")
    return _local_sentiment(eligible, asset, params, source="local")


def _signal_from_score(score: int, params: NewsSentimentParameters) -> str:
    if score >= params.bullish_score_threshold:
        return "BUY_BIAS"
    if score <= params.bearish_score_threshold:
        return "SELL_BIAS"
    return "NEUTRAL"


def _confidence_from_score(score: int) -> float:
    """A simple, honestly-heuristic mapping — |score| (0-10 scale) to a 0-1 confidence.
    Not a calibrated probability; documented as a heuristic in nero_core/execution/DESIGN.md."""
    return max(0.0, min(1.0, abs(score) / 10.0))


def _analyze_with_gemini(
    headlines: list[NewsItem], asset: str, api_key: str, params: NewsSentimentParameters
) -> SentimentResult:
    news_text = "\n".join(
        f"[{item.source}] [Tags: {', '.join(item.tags) or 'None'}] {item.title}\nLink: {item.link}"
        for item in headlines[: params.headline_limit]
    )
    prompt = f"""
You are an expert quantitative financial analyst. Analyze these recent market news headlines for {asset}.
Return strict JSON only with keys:
- overall_sentiment: one of Bullish, Bearish, Neutral
- sentiment_score: integer from -10 to 10
- summary: brief 2-3 sentence explanation

News:
{news_text}
"""
    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{params.gemini_model}:generateContent",
        params={"key": api_key},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=params.gemini_timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    text = payload["candidates"][0]["content"]["parts"][0]["text"].strip()
    data = json.loads(_strip_markdown_json(text))
    score = max(-10, min(10, int(data.get("sentiment_score", 0))))
    signal_type = _signal_from_score(score, params)
    return SentimentResult(signal_type, score, _confidence_from_score(score), str(data.get("summary", "")), "Gemini")


def _local_sentiment(
    headlines: list[NewsItem], asset: str, params: NewsSentimentParameters, source: str
) -> SentimentResult:
    joined = " ".join(item.title.lower() for item in headlines)
    positive = sum(1 for word in POSITIVE_WORDS if word in joined)
    negative = sum(1 for word in NEGATIVE_WORDS if word in joined)
    score = max(-10, min(10, (positive - negative) * 2))
    signal_type = _signal_from_score(score, params)
    summary = f"Local keyword sentiment for {asset}: score {score} from {len(headlines)} eligible headline(s)."
    return SentimentResult(signal_type, score, _confidence_from_score(score), summary, source)


def _strip_markdown_json(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```json"):
        stripped = stripped[7:]
    if stripped.startswith("```"):
        stripped = stripped[3:]
    if stripped.endswith("```"):
        stripped = stripped[:-3]
    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    return match.group(0) if match else stripped.strip()


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register NEWS_SENTIMENT as a versionable live signal source (not a backtested
    strategy — see module docstring). Raises StrategyAlreadyRegisteredError if called
    twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
