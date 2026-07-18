"""v2 A/B trail-exit variant of GOLD-calibrated 1week BREAKOUT_MOMENTUM
(breakout-momentum-v1.2.0-gold-calibrated-1week): IDENTICAL entry conditions, GOLD fee
calibration, and 1.2x ATR disaster stop — see
nero_core.strategies.breakout_momentum_gold_calibrated_1week for those; nothing about
them differs here. ONLY the profit-exit changes, from a fixed 1.25R target + the
(already 1week-corrected) max-holding-hours cap to an ARMED EMA8 trailing stop with NO
max-holding cap at all (let winners run — see nero_core.strategies.ema_trail_exit for
the shared ARMED-TRAIL mechanics both trail variants in this A/B use).

WHY EMA8, NOT EMA21 (the period TREND_PULLBACK-trail uses): this strategy trades
1week candles. EMA21 on weekly candles is a ~5-month lookback — far too slow to
meaningfully trail a position on this timeframe (it would barely move within a typical
multi-week breakout leg). EMA8 (~2 months) is the calibrated equivalent: fast enough to
actually trail weekly price action, while still smoothing out single-candle noise. This
choice is a genuinely new, documented registry parameter
(`BreakoutMomentumGoldCalibratedTrailParameters.trail_ema_period`), not a hidden
constant.

`max_holding_hours` is still present (inherited from the GOLD-calibrated-1week base
parameters) but is genuinely UNUSED by this variant's own `evaluate_exit` — there is no
max-holding check anywhere in this module. This is intentional (v1 keeps its cap; that
difference is exactly what this A/B measures), not an oversight.

Registered as `breakout-momentum-v1.5.0-gold-calibrated-1week-trail` — v1.4.0 is
already taken by the volume-confirmed variant; this is a genuinely new version, never a
mutation of any existing one.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from nero_core.strategies.breakout_momentum import STRATEGY_ID
from nero_core.strategies.breakout_momentum import BreakoutMomentumParameters
from nero_core.strategies.breakout_momentum import add_indicators as base_add_indicators
from nero_core.strategies.breakout_momentum import evaluate_entry
from nero_core.strategies.breakout_momentum_gold_calibrated_1week import GOLD_CALIBRATED_1WEEK_PARAMETERS
from nero_core.strategies.ema_trail_exit import TrailExitEvent, add_ema_column, evaluate_trail_exit
from nero_core.strategies.mean_reversion import MeanReversionState, apply_slippage, reset_daily_guard_if_needed
from nero_core.strategies.regime_risk import regime_scaled_risk_per_trade
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_VERSION = "breakout-momentum-v1.5.0-gold-calibrated-1week-trail"
TRAIL_EMA_COLUMN = "trail_ema"

STRATEGY_DESCRIPTION = (
    "A/B trail-exit variant of BREAKOUT_MOMENTUM breakout-momentum-v1.2.0-gold-"
    "calibrated-1week: IDENTICAL entry conditions, GOLD fee/slippage calibration, and "
    "1.2x ATR disaster stop — ONLY the profit-exit changes, from a fixed 1.25R target "
    "+ the (already timeframe-corrected) max-holding-hours cap to an ARMED EMA8 "
    "trailing stop with NO max-holding cap (let winners run). EMA8, not EMA21 (the "
    "period the sibling TREND_PULLBACK-trail variant uses): EMA21 on 1week candles is "
    "a ~5-month lookback, too slow to meaningfully trail a weekly breakout leg; EMA8 "
    "(~2 months) is the calibrated equivalent for this timeframe. ARMED-TRAIL RULE: "
    "the trail only activates after the FIRST post-entry CLOSE above the EMA8; until "
    "armed, only the disaster stop applies. Evaluated on closed candles only, never "
    "the entry candle itself. See nero_core.strategies.ema_trail_exit for the shared "
    "mechanics."
)


@dataclass(frozen=True)
class BreakoutMomentumGoldCalibratedTrailParameters(BreakoutMomentumParameters):
    # A genuinely new, documented registry parameter — see module docstring for why
    # EMA8 (not EMA21) is the calibrated choice on 1week candles.
    trail_ema_period: int = 8


DEFAULT_PARAMETERS = BreakoutMomentumGoldCalibratedTrailParameters(
    **asdict(GOLD_CALIBRATED_1WEEK_PARAMETERS), trail_ema_period=8
)


@dataclass
class OpenTrade:
    entry_price: float
    stop_loss: float
    quantity: float
    notional: float
    risk_dollars: float
    entry_fee: float
    open_close_time: int
    entry_rsi: float
    entry_ma200: float
    entry_atr: float
    entry_breakout_high: float
    trail_armed: bool = False


def add_indicators(
    candles: pd.DataFrame, params: BreakoutMomentumGoldCalibratedTrailParameters = DEFAULT_PARAMETERS
) -> pd.DataFrame:
    enriched = base_add_indicators(candles, params)
    return add_ema_column(enriched, params.trail_ema_period, TRAIL_EMA_COLUMN)


def size_entry(
    candle: pd.Series, state: MeanReversionState, params: BreakoutMomentumGoldCalibratedTrailParameters = DEFAULT_PARAMETERS
) -> OpenTrade | None:
    """Identical disaster-stop geometry to breakout_momentum.size_entry (1.2x ATR,
    same regime_scaled_risk support for parity with the base module) — no target is
    computed at all; the trail replaces it entirely."""
    raw_entry = float(candle["close"])
    entry_price = apply_slippage(raw_entry, params.slippage_bps, "buy")
    stop_loss = entry_price - params.atr_stop_multiple * float(candle["atr"])
    risk_per_unit = entry_price - stop_loss
    if risk_per_unit <= 0:
        return None

    risk_per_trade = params.risk_per_trade
    if params.regime_scaled_risk:
        current_atr_pct = float(candle["atr"]) / raw_entry if raw_entry != 0 else float("nan")
        risk_per_trade = regime_scaled_risk_per_trade(
            params.risk_per_trade, candle.get("atr_pct_median100"), current_atr_pct
        )
    risk_dollars = state.equity * risk_per_trade
    quantity = risk_dollars / risk_per_unit
    max_notional = state.equity * params.max_notional_pct
    notional = quantity * entry_price
    if notional > max_notional:
        quantity = max_notional / entry_price
        notional = max_notional
        risk_dollars = quantity * risk_per_unit
    fees = notional * params.fee_bps / 10000.0

    breakout_high = candle.get("breakout_high")
    return OpenTrade(
        entry_price=entry_price,
        stop_loss=stop_loss,
        quantity=quantity,
        notional=notional,
        risk_dollars=risk_dollars,
        entry_fee=fees,
        open_close_time=int(candle["close_time"]),
        entry_rsi=float(candle["rsi"]),
        entry_ma200=float(candle["ma200"]),
        entry_atr=float(candle["atr"]),
        entry_breakout_high=float(breakout_high) if not pd.isna(breakout_high) else float("nan"),
    )


def evaluate_exit(
    candle: pd.Series, state: MeanReversionState, params: BreakoutMomentumGoldCalibratedTrailParameters = DEFAULT_PARAMETERS
) -> TrailExitEvent | None:
    return evaluate_trail_exit(candle, state, TRAIL_EMA_COLUMN, params.fee_bps, params.slippage_bps)


def run_backtest(
    evaluable: pd.DataFrame, params: BreakoutMomentumGoldCalibratedTrailParameters = DEFAULT_PARAMETERS
) -> tuple[list[TrailExitEvent], MeanReversionState]:
    state = MeanReversionState(equity=params.initial_equity)
    closed_trades: list[TrailExitEvent] = []
    for i in range(len(evaluable)):
        candle = evaluable.iloc[i]
        reset_daily_guard_if_needed(state, candle["date"])

        exit_event = evaluate_exit(candle, state, params)
        if exit_event is not None:
            closed_trades.append(exit_event)

        evaluation = evaluate_entry(candle, state, params)
        if evaluation.passed:
            trade = size_entry(candle, state, params)
            if trade is not None:
                state.open_trade = trade

    return closed_trades, state


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the trail-exit variant. Raises StrategyAlreadyRegisteredError if called
    twice on the same registry — a new version, never a mutation of any existing one."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
