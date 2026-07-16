"""Shared timeframe/instrument calibration helpers, reused across strategy families so
each new strategy doesn't re-derive its own copy.

Two independent corrections, established while fixing MEAN_REVERSION/BREAKOUT_MOMENTUM's
GOLD 1week bug and then reused as-designed (not retrofitted) in VOLATILITY_SQUEEZE:

1. max_holding_hours is a candle-COUNT cap (originally "hold up to 24 candles" under the
   source NERO agent's interval="1h" assumption), not an instrument-independent wall-clock
   cap — see nero_core.strategies.mean_reversion_gold_calibrated_1week for the full
   derivation and the bug it fixes.
2. fee_bps/slippage_bps were calibrated for crypto exchange fee structures and need
   rescaling for GOLD's much lower relative volatility — see
   nero_core.strategies.mean_reversion_gold_calibrated for the measured scale factor.

Callers building per-(asset, timeframe) run parameters should use
`build_calibrated_params` rather than reading a registered variant's raw defaults
directly, exactly as VOLATILITY_SQUEEZE's build_params_for_run already does.
"""
from __future__ import annotations

from dataclasses import replace
from typing import TypeVar

from nero_core.strategies.mean_reversion_gold_calibrated import GOLD_FEE_SCALE_FACTOR

HOURS_PER_TIMEFRAME = {"2h": 2, "4h": 4, "12h": 12, "24h": 24, "1week": 168}
ORIGINAL_MAX_HOLDING_CANDLES = 24  # preserve "hold up to 24 candles" regardless of timeframe

ParamsT = TypeVar("ParamsT")


def max_holding_hours_for_timeframe(timeframe: str, candles: int = ORIGINAL_MAX_HOLDING_CANDLES) -> int:
    """Convert a candle-count holding cap into hours for `timeframe`. Raises KeyError for
    an unrecognized timeframe rather than silently defaulting."""
    return candles * HOURS_PER_TIMEFRAME[timeframe]


def gold_calibrated_fees(params: ParamsT) -> ParamsT:
    """Return `params` with fee_bps/slippage_bps scaled by the measured BTC/GOLD
    price-to-ATR ratio. Works on any frozen dataclass exposing fee_bps/slippage_bps
    fields (MeanReversionParameters, BreakoutMomentumParameters, VolatilitySqueezeParameters,
    TrendPullbackParameters, ...) via dataclasses.replace."""
    return replace(
        params,
        fee_bps=params.fee_bps * GOLD_FEE_SCALE_FACTOR,
        slippage_bps=params.slippage_bps * GOLD_FEE_SCALE_FACTOR,
    )


def build_calibrated_params(base_params: ParamsT, timeframe: str, asset: str) -> ParamsT:
    """Build the correctly-calibrated, correctly-timeframed parameter set for one
    asset/timeframe backtest run, without mutating or re-registering `base_params` — the
    registered strategy variant's canonical parameters never change; this only produces an
    ephemeral, honestly-derived clone for the run at hand."""
    params = replace(base_params, max_holding_hours=max_holding_hours_for_timeframe(timeframe))
    if asset == "GOLD":
        params = gold_calibrated_fees(params)
    return params
