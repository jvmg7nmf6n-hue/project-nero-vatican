"""NEWS_SENTIMENT (LLM variant) — Claude-powered replacement for the keyword-matching
signal in nero_core.strategies.news_sentiment.

WHY THIS EXISTS: the original module's local fallback (and its only path when no
GEMINI_API_KEY is set) is naive substring keyword matching — `POSITIVE_WORDS` /
`NEGATIVE_WORDS` counted against the raw headline text. That misfires on negation and
reversal: "Fed unexpectedly RAISES rates" contains no negative keyword and would not be
caught, while a headline like "gold falls despite strong demand" mixes a NEGATIVE_WORDS
hit ("falls") with a POSITIVE_WORDS hit ("strong") into an uninterpretable wash. This
module replaces the *analysis* step with a real per-headline read from Claude, structured
as strict JSON, gated by explicit honesty rules before any bias is allowed to publish.

Still forward-test-only — same status as nero_core.strategies.news_sentiment (see
docs/research_phase_closure.md): no historical dataset with a trustworthy backdated
publication timestamp exists, so this is never backtested against fabricated history,
only ever evaluated live/forward. Registered in the strategy registry as a NEW version
of NEWS_SENTIMENT (never a mutation of news-sentiment-v1.0.0's parameters) per project
convention: an analysis-engine change (keyword -> LLM, Gemini -> Claude) is exactly the
kind of change that must be a new version string.

HONESTY GATES (see analyze_headline) — all mandatory, none configurable away silently:
  (a) confidence < params.confidence_gate         -> signal_type forced NO_SIGNAL,
      both impact fields forced NEUTRAL. A coin-flip-confidence read must never publish
      a directional bias.
  (b) surprise_score < params.surprise_gate       -> both impact fields forced NEUTRAL.
      Fully-expected news is already priced in; only genuine surprises should move a
      bias. (Confidence can still be high for expected news, so this is independent of
      gate (a), not a duplicate of it.)
  (c) calibration_status is ALWAYS "uncalibrated" in this build. No resolution/Brier-
      score pipeline exists yet (that requires the Truth Ledger's truth_label workflow
      to close the loop on 50+ resolved predictions) — every row honestly says so rather
      than implying a probability that hasn't been validated. `confidence` and
      `surprise_score` are still logged on every row specifically so a Brier score CAN be
      computed once that pipeline exists.
  (d) LOOKAHEAD GUARD: only headlines already >= params.min_publication_age_hours old
      (reusing nero_core.strategies.news_sentiment.select_eligible_headlines /
      parse_published — not reimplemented here) are ever analyzed. `publication_age_hours`
      is logged on every row, not just enforced silently.
  (e) No `historical_matches` field exists anywhere in this module. Comparing a live
      headline to "similar past events" would require fabricating a historical event
      dataset this project has explicitly decided does not exist trustworthily (see
      docs/research_phase_closure.md) — so the field is omitted entirely, never
      populated with an empty/placeholder value.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import requests

from nero_core.data_sources.news_feed import NewsItem
from nero_core.strategies.news_sentiment import parse_published, select_eligible_headlines
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_ID = "NEWS_SENTIMENT"
STRATEGY_VERSION = "news-sentiment-v2.0.0-llm-claude"

STRATEGY_DESCRIPTION = (
    "Forward-test-only news sentiment signal for GOLD and BTC (v2: LLM-powered). Reuses "
    "the existing RSS feed (nero_core.data_sources.news_feed) and lookahead buffer "
    "(nero_core.strategies.news_sentiment.select_eligible_headlines, >= "
    "min_publication_age_hours old) unchanged. Replaces v1's Gemini/keyword analysis "
    "with a per-headline Claude Messages API call producing structured "
    "impact/confidence/surprise JSON, gated by explicit honesty rules: low confidence -> "
    "NO_SIGNAL, low surprise -> forced NEUTRAL, calibration_status always 'uncalibrated' "
    "(no Brier-score pipeline exists yet), no historical_matches field ever. No "
    "historical backtest exists for this signal (see docs/research_phase_closure.md); "
    "logged live, forward-only, never retroactively fabricated."
)

Bias = str  # "BULLISH" | "BEARISH" | "NEUTRAL"
_VALID_BIASES = {"BULLISH", "BEARISH", "NEUTRAL"}


@dataclass(frozen=True)
class LLMNewsParameters:
    min_publication_age_hours: float = 2.0
    confidence_gate: float = 0.6
    surprise_gate: float = 0.1
    calibration_threshold: int = 50
    headline_limit: int = 12
    claude_model: str = "claude-sonnet-5"
    claude_api_url: str = "https://api.anthropic.com/v1/messages"
    claude_api_version: str = "2023-06-01"
    claude_max_tokens: int = 400
    claude_timeout_seconds: int = 20


DEFAULT_PARAMETERS = LLMNewsParameters()


@dataclass(frozen=True)
class HeadlineAnalysis:
    headline: str
    timestamp: str  # ISO8601 — the headline's own published time, never a guess
    publication_age_hours: float  # lookahead buffer, logged explicitly per row (gate d)
    impact_on_gold: Bias
    impact_on_btc: Bias
    confidence: float
    surprise_score: float
    reasoning: str
    signal_type: str  # "SIGNAL" | "NO_SIGNAL" — post-gate, never the raw model output
    calibration_status: str  # always "uncalibrated" until calibration_threshold resolved predictions exist
    source: str  # "claude" | "error: <ExceptionClassName>"


@dataclass(frozen=True)
class LLMSentimentResult:
    signal_type: str  # "BUY_BIAS" | "SELL_BIAS" | "NEUTRAL" — matches v1's vocabulary for eventual DB/live_scheduler compatibility
    confidence: float
    summary: str
    source: str
    calibration_status: str
    headline_analyses: tuple[HeadlineAnalysis, ...] = field(default_factory=tuple)


def calibration_status_for(resolved_predictions_count: int, threshold: int = DEFAULT_PARAMETERS.calibration_threshold) -> str:
    """Honest calibration label. No resolution-counting pipeline is wired into this
    module yet (that lives in the Truth Ledger's truth_label workflow) — callers without
    a real count MUST pass 0, never a guess, so this defaults to 'uncalibrated'."""
    return "calibrated" if resolved_predictions_count >= threshold else "uncalibrated"


def _clamp01(value: object) -> float:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if parsed != parsed:  # NaN
        return 0.0
    return max(0.0, min(1.0, parsed))


def _sanitize_bias(value: object) -> Bias:
    upper = str(value).strip().upper() if value is not None else ""
    return upper if upper in _VALID_BIASES else "NEUTRAL"


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


def _apply_honesty_gates(
    raw_impact_on_gold: Bias,
    raw_impact_on_btc: Bias,
    confidence: float,
    surprise_score: float,
    params: LLMNewsParameters,
) -> tuple[Bias, Bias, str]:
    """Returns (gated_impact_on_gold, gated_impact_on_btc, signal_type). Never mutates
    the raw model output in place — callers that want the raw read still have it in the
    Claude response; this is the one place all three honesty gates are enforced."""
    if confidence < params.confidence_gate:
        return "NEUTRAL", "NEUTRAL", "NO_SIGNAL"  # gate (a)

    gold = raw_impact_on_gold
    btc = raw_impact_on_btc
    if surprise_score < params.surprise_gate:
        gold, btc = "NEUTRAL", "NEUTRAL"  # gate (b)

    signal_type = "NO_SIGNAL" if gold == "NEUTRAL" and btc == "NEUTRAL" else "SIGNAL"
    return gold, btc, signal_type


def _call_claude(headline: str, api_key: str, params: LLMNewsParameters) -> dict:
    prompt = f"""You are an expert quantitative financial analyst. Analyze this single news headline
for its likely market impact on GOLD and BTC (Bitcoin).

Headline: {headline}

Return STRICT JSON only, with exactly these keys and no others:
- impact_on_gold: one of "BULLISH", "BEARISH", "NEUTRAL"
- impact_on_btc: one of "BULLISH", "BEARISH", "NEUTRAL"
- confidence: float from 0.0 to 1.0 (your genuine confidence in this read — do not
  default to a high number; a routine or ambiguous headline should score low)
- surprise_score: float from 0.0 to 1.0 (0 = fully expected/already priced in, 1 = a
  genuine surprise versus prior market expectations)
- reasoning: a 2-3 sentence explanation

Do not include any field other than these five. Do not include historical event
comparisons."""

    response = requests.post(
        params.claude_api_url,
        headers={
            "x-api-key": api_key,
            "anthropic-version": params.claude_api_version,
            "content-type": "application/json",
        },
        json={
            "model": params.claude_model,
            "max_tokens": params.claude_max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=params.claude_timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    text = payload["content"][0]["text"].strip()
    return json.loads(_strip_markdown_json(text))


def analyze_headline(
    item: NewsItem,
    now: datetime,
    api_key: str,
    params: LLMNewsParameters = DEFAULT_PARAMETERS,
) -> HeadlineAnalysis:
    """Analyze exactly one headline through Claude and apply all honesty gates.

    Assumes `item` has already cleared the lookahead eligibility check (see
    select_eligible_headlines) — this function still computes and logs
    `publication_age_hours` independently so the buffer is auditable per row, not just
    trusted from the caller."""
    published_at = parse_published(item.published)
    publication_age_hours = (
        (now.astimezone(timezone.utc) - published_at).total_seconds() / 3600.0
        if published_at is not None
        else 0.0
    )
    timestamp = published_at.isoformat() if published_at is not None else ""
    calibration_status = calibration_status_for(0, params.calibration_threshold)

    try:
        data = _call_claude(item.title, api_key, params)
    except (requests.RequestException, KeyError, ValueError, json.JSONDecodeError) as exc:
        return HeadlineAnalysis(
            headline=item.title,
            timestamp=timestamp,
            publication_age_hours=publication_age_hours,
            impact_on_gold="NEUTRAL",
            impact_on_btc="NEUTRAL",
            confidence=0.0,
            surprise_score=0.0,
            reasoning=f"Claude API call failed: {exc.__class__.__name__}: {exc}",
            signal_type="NO_SIGNAL",
            calibration_status=calibration_status,
            source=f"error: {exc.__class__.__name__}",
        )

    confidence = _clamp01(data.get("confidence"))
    surprise_score = _clamp01(data.get("surprise_score"))
    raw_gold = _sanitize_bias(data.get("impact_on_gold"))
    raw_btc = _sanitize_bias(data.get("impact_on_btc"))
    gated_gold, gated_btc, signal_type = _apply_honesty_gates(raw_gold, raw_btc, confidence, surprise_score, params)

    return HeadlineAnalysis(
        headline=item.title,
        timestamp=timestamp,
        publication_age_hours=publication_age_hours,
        impact_on_gold=gated_gold,
        impact_on_btc=gated_btc,
        confidence=confidence,
        surprise_score=surprise_score,
        reasoning=str(data.get("reasoning", "")),
        signal_type=signal_type,
        calibration_status=calibration_status,
        source="claude",
    )


def analyze_sentiment_llm(
    headlines: list[NewsItem],
    asset: str,
    now: datetime,
    api_key: str = "",
    params: LLMNewsParameters = DEFAULT_PARAMETERS,
) -> LLMSentimentResult:
    """Aggregate per-headline Claude analyses into one asset-level signal.

    `asset` must be "GOLD" or "BTC" — selects which per-headline impact field
    (impact_on_gold / impact_on_btc) counts toward the aggregate. Only headlines whose
    gated signal_type is "SIGNAL" (i.e. cleared both honesty gates) ever contribute a
    direction; NO_SIGNAL headlines are still returned in `headline_analyses` for full
    audit but never move the aggregate."""
    calibration_status = calibration_status_for(0, params.calibration_threshold)
    eligible = select_eligible_headlines(headlines, now, params.min_publication_age_hours)
    if not eligible:
        return LLMSentimentResult(
            "NEUTRAL", 0.0,
            f"No headlines published >= {params.min_publication_age_hours}h ago as of evaluation time "
            "(lookahead buffer not satisfied) — no signal generated.",
            "no eligible headlines",
            calibration_status,
            (),
        )

    if not api_key.strip():
        return LLMSentimentResult(
            "NEUTRAL", 0.0,
            "No Claude API key configured — no signal generated (no keyword fallback in the LLM variant, "
            "by design: silently reverting to keyword matching would defeat the point of this upgrade).",
            "no api key",
            calibration_status,
            (),
        )

    analyses = tuple(analyze_headline(item, now, api_key, params) for item in eligible[: params.headline_limit])

    field_name = "impact_on_gold" if asset.upper() == "GOLD" else "impact_on_btc"
    signaling = [a for a in analyses if a.signal_type == "SIGNAL"]
    bullish = [a for a in signaling if getattr(a, field_name) == "BULLISH"]
    bearish = [a for a in signaling if getattr(a, field_name) == "BEARISH"]

    if not signaling or len(bullish) == len(bearish):
        signal_type, contributing = "NEUTRAL", []
    elif len(bullish) > len(bearish):
        signal_type, contributing = "BUY_BIAS", bullish
    else:
        signal_type, contributing = "SELL_BIAS", bearish

    confidence = sum(a.confidence for a in contributing) / len(contributing) if contributing else 0.0
    summary = (
        f"LLM sentiment for {asset}: {len(contributing)}/{len(analyses)} eligible headline(s) "
        f"cleared both honesty gates in the {signal_type} direction."
        if analyses
        else "No headlines available to analyze."
    )
    return LLMSentimentResult(signal_type, confidence, summary, "claude", calibration_status, analyses)


def register_llm_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the LLM-powered NEWS_SENTIMENT as a NEW version (never a mutation of
    news-sentiment-v1.0.0's parameters). Raises StrategyAlreadyRegisteredError if called
    twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
