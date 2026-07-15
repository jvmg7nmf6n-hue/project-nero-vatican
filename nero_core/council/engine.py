from __future__ import annotations

from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from nero_core.quant.quant_intelligence import (
    QuantConsensusReport,
    build_garch_volatility_report,
    build_quant_consensus_report,
    build_quant_snapshot,
)
from nero_core.strategies.mean_reversion import (
    DEFAULT_PARAMETERS as MEAN_REVERSION_DEFAULT_PARAMETERS,
    STRATEGY_ID as MEAN_REVERSION_STRATEGY_ID,
    STRATEGY_VERSION as MEAN_REVERSION_STRATEGY_VERSION,
    EntryEvaluation,
    MeanReversionParameters,
    MeanReversionState,
    add_indicators,
    evaluate_entry,
)

Stance = Literal["NO_TRADE", "WATCH", "PAPER_TEST_READY", "HIGH_QUALITY_SETUP"]
DirectionalBias = Literal["LONG", "SHORT", "NEUTRAL"]

# Council inputs the full spec calls for that are NOT wired up in Phase 0/1. Every verdict
# discloses these explicitly rather than silently omitting them or defaulting them to a
# plausible-looking neutral value.
UNPORTED_INPUTS: tuple[str, ...] = (
    "news sentiment",
    "ETF flow intelligence",
    "gold real-yield macro pressure",
    "BTC structural (halving / miner-cost) context",
    "White House / policy event impact",
    "historical market memory (macro regime matching)",
    "social intelligence",
    "cross-asset quant drivers (correlation / beta / cointegration / Granger / Kalman beta)",
    "strategy-lab variants beyond Mean Reversion",
)

# Of the Council's ~11 planned inputs, only these 2 exist this phase. Confidence is scaled
# against this total so it stays structurally honest even when both available inputs agree.
TOTAL_PLANNED_INPUTS = 2 + len(UNPORTED_INPUTS)

MIN_QUANT_OBSERVATIONS = 30  # below this, rolling quant stats are too thin to trust at all


class CouncilVerdict(BaseModel):
    """Council Engine output. `global_score` and `confidence`/`risk` intentionally use
    different scales: global_score (0-100) mirrors the quant consensus score it is built
    from, while confidence/risk (0-1) mirror schema.VerdictOutput's convention elsewhere
    in the codebase."""

    asset: str
    global_score: float = Field(ge=0, le=100)
    stance: Stance
    directional_bias: DirectionalBias
    confidence: float = Field(ge=0, le=1)
    risk: float = Field(ge=0, le=1)
    top_supportive_factors: list[str] = Field(default_factory=list)
    top_blockers: list[str] = Field(default_factory=list)
    recommended_strategy: str = ""
    summary: str = ""


def _quant_component(asset: str, price_history: pd.DataFrame) -> tuple[QuantConsensusReport | None, list[str]]:
    if price_history is None or price_history.empty or "close" not in price_history.columns:
        return None, ["Quant consensus: insufficient data (no price history supplied)."]
    if len(price_history) < MIN_QUANT_OBSERVATIONS:
        return None, [f"Quant consensus: insufficient data (fewer than {MIN_QUANT_OBSERVATIONS} price observations)."]

    snapshot = build_quant_snapshot(price_history, asset=asset, source="council-engine")
    if snapshot.regime == "NO_DATA":
        return None, ["Quant consensus: insufficient data (snapshot could not be built from supplied price history)."]

    garch_report = build_garch_volatility_report(price_history, asset)
    consensus = build_quant_consensus_report(snapshot, garch_report=garch_report)
    return consensus, []


def _mean_reversion_component(
    price_history: pd.DataFrame,
    state: MeanReversionState,
    params: MeanReversionParameters = MEAN_REVERSION_DEFAULT_PARAMETERS,
) -> tuple[EntryEvaluation | None, list[str]]:
    if price_history is None or price_history.empty:
        return None, ["Mean Reversion signal: insufficient data (no price history supplied)."]
    required_columns = {"close_time", "open", "high", "low", "close"}
    if not required_columns.issubset(price_history.columns):
        missing = sorted(required_columns - set(price_history.columns))
        return None, [f"Mean Reversion signal: insufficient data (price history missing columns {missing})."]

    enriched = add_indicators(price_history, params)
    evaluable = enriched.dropna(subset=["rsi", "bb_lower", "ma20", "ma200", "atr"])
    if evaluable.empty:
        return None, [
            f"Mean Reversion signal: insufficient data (fewer than {params.ma200_period} closed "
            "candles needed for RSI/Bollinger/MA200/ATR)."
        ]

    latest_candle = evaluable.iloc[-1]
    return evaluate_entry(latest_candle, state, params), []


def _resolve_stance(
    quant_report: QuantConsensusReport | None,
    mean_reversion_signal: bool,
) -> Stance:
    """HIGH_QUALITY_SETUP is structurally unreachable in this skeleton: it should require
    corroboration from multiple independent Council inputs, and only 2 of ~11 are wired
    up yet. Reaching it honestly has to wait for later phases."""
    if quant_report is None and not mean_reversion_signal:
        return "NO_TRADE"
    if quant_report is not None and quant_report.label == "QUANT_HOSTILE" and not mean_reversion_signal:
        return "NO_TRADE"
    if mean_reversion_signal:
        return "PAPER_TEST_READY" if (quant_report is None or quant_report.score >= 45) else "WATCH"
    return "WATCH"


def build_council_verdict(
    asset: str,
    price_history: pd.DataFrame,
    mean_reversion_state: MeanReversionState | None = None,
) -> CouncilVerdict:
    """Council Engine skeleton (Phase 0/1).

    Composes a verdict from ONLY the two Council inputs ported so far: quant consensus
    (nero_core.quant) and the Mean Reversion strategy (nero_core.strategies.mean_reversion).
    Every other planned Council input is explicitly listed in `top_blockers` as insufficient
    data rather than being silently dropped or defaulted to a plausible-looking value —
    see UNPORTED_INPUTS. Nothing here fabricates an edge that hasn't been earned.
    """
    state = mean_reversion_state or MeanReversionState(equity=MEAN_REVERSION_DEFAULT_PARAMETERS.initial_equity)

    quant_report, quant_notes = _quant_component(asset, price_history)
    entry_evaluation, mr_notes = _mean_reversion_component(price_history, state)

    supportive: list[str] = []
    blockers: list[str] = list(quant_notes) + list(mr_notes)

    if quant_report is not None:
        supportive.append(
            f"Quant consensus: {quant_report.label} ({quant_report.score:.0f}/100), bias {quant_report.bias}."
        )
        if quant_report.score < 45:
            blockers.append(f"Quant environment is weak/hostile ({quant_report.label}).")

    mean_reversion_signal = False
    if entry_evaluation is not None:
        if state.open_trade is not None:
            supportive.append("Mean Reversion: a paper trade is currently open.")
        elif entry_evaluation.passed:
            mean_reversion_signal = True
            supportive.append(
                "Mean Reversion: entry conditions confirmed (RSI oversold, close below lower "
                "Bollinger Band, close above MA200 uptrend filter, MA20 target above entry)."
            )
        else:
            blockers.append(f"Mean Reversion: entry rejected ({', '.join(entry_evaluation.reasons)}).")

    for missing in UNPORTED_INPUTS:
        blockers.append(f"{missing}: insufficient data (not yet ported into Vatican).")

    # -- scoring --------------------------------------------------------------------
    # Deliberately simple and fully transparent for this skeleton. global_score tracks the
    # quant environment score (0-100), with a flat bonus only for a REAL, confirmed Mean
    # Reversion entry — no other factor may move this score until it is actually ported.
    quant_score = quant_report.score if quant_report is not None else 0.0
    global_score = round(min(100.0, quant_score + (15.0 if mean_reversion_signal else 0.0)), 1)

    directional_bias: DirectionalBias = (
        "LONG" if mean_reversion_signal and (quant_report is None or quant_report.bias != "SHORT_RISK_OR_AVOID_LONGS") else "NEUTRAL"
    )

    # Confidence is the fraction of ALL planned Council inputs (11) that are both wired up
    # and actively supportive right now — never just the 2 that exist in this phase, so the
    # number stays honest about how much of the full Council this skeleton represents.
    supportive_input_count = sum(
        [
            quant_report is not None and quant_report.score >= 55,
            mean_reversion_signal,
        ]
    )
    confidence = round(supportive_input_count / TOTAL_PLANNED_INPUTS, 2)

    # Risk uses the one real volatility signal available (GARCH/EWMA regime via the quant
    # component) when present; otherwise it stays at the conservative "unknown" midpoint,
    # since most risk-relevant inputs (macro, policy, liquidity) are not ported yet.
    risk = 0.5
    if quant_report is not None:
        risk = {
            "QUANT_HOSTILE": 0.8,
            "QUANT_WEAK": 0.65,
            "QUANT_NEUTRAL": 0.5,
            "QUANT_MILD_SUPPORT": 0.4,
            "QUANT_SUPPORTIVE": 0.3,
        }.get(quant_report.label, 0.5)

    stance = _resolve_stance(quant_report, mean_reversion_signal)

    recommended_strategy = (
        f"{MEAN_REVERSION_STRATEGY_ID}@{MEAN_REVERSION_STRATEGY_VERSION}" if mean_reversion_signal else ""
    )

    summary = _build_summary(asset, stance, directional_bias, quant_report, mean_reversion_signal)

    return CouncilVerdict(
        asset=asset,
        global_score=global_score,
        stance=stance,
        directional_bias=directional_bias,
        confidence=confidence,
        risk=risk,
        top_supportive_factors=supportive[:5],
        top_blockers=blockers[:5],
        recommended_strategy=recommended_strategy,
        summary=summary,
    )


def _build_summary(
    asset: str,
    stance: Stance,
    directional_bias: DirectionalBias,
    quant_report: QuantConsensusReport | None,
    mean_reversion_signal: bool,
) -> str:
    quant_phrase = f"quant is {quant_report.label.replace('_', ' ').lower()}" if quant_report else "quant consensus is unavailable"
    strategy_phrase = (
        "Mean Reversion has a confirmed entry signal" if mean_reversion_signal else "Mean Reversion has no confirmed entry signal"
    )
    return (
        f"{asset}: {stance} ({directional_bias} bias). {quant_phrase.capitalize()}; {strategy_phrase}. "
        f"This is a Phase 0/1 skeleton verdict built from only 2 of {TOTAL_PLANNED_INPUTS} planned "
        "Council inputs — treat it as a partial, not a final, read."
    )
