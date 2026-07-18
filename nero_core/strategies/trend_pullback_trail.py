"""v2 A/B trail-exit variant of TREND_PULLBACK (trend-pullback-v1.0.0): IDENTICAL entry
conditions and 1.5x ATR disaster stop — see nero_core.strategies.trend_pullback for
those; nothing about them differs here. ONLY the profit-exit changes, from a fixed
2.0x ATR target + max-holding-hours cap to an ARMED EMA21 trailing stop with NO
max-holding cap at all (let winners run — see nero_core.strategies.ema_trail_exit for
the shared ARMED-TRAIL mechanics both trail variants in this A/B use).

`max_holding_hours` is still present on `TrendPullbackTrailParameters` (inherited from
`TrendPullbackParameters`) but is genuinely UNUSED by this variant's own `evaluate_exit`
— there is no max-holding check anywhere in this module. This is intentional (v1 keeps
its cap; that difference is exactly what this A/B measures), not an oversight; the
field is inert dead data on this variant, not a de-facto "unlimited" setting.

Registered as `trend-pullback-v1.2.0-trail` — a genuinely new version, never a mutation
of v1.0.0 or the v1.1.0 regime-scaled-risk variant.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from nero_core.strategies.ema_trail_exit import TrailExitEvent, add_ema_column, evaluate_trail_exit
from nero_core.strategies.mean_reversion import MeanReversionState, apply_slippage, reset_daily_guard_if_needed
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry
from nero_core.strategies.trend_pullback import STRATEGY_ID
from nero_core.strategies.trend_pullback import TrendPullbackParameters
from nero_core.strategies.trend_pullback import add_indicators as base_add_indicators
from nero_core.strategies.trend_pullback import evaluate_entry

STRATEGY_VERSION = "trend-pullback-v1.2.0-trail"
TRAIL_EMA_COLUMN = "trail_ema"

STRATEGY_DESCRIPTION = (
    "A/B trail-exit variant of TREND_PULLBACK trend-pullback-v1.0.0: IDENTICAL entry "
    "conditions and 1.5x ATR disaster stop — ONLY the profit-exit changes, from a "
    "fixed 2.0x ATR target + max-holding-hours cap to an ARMED EMA21 trailing stop "
    "with NO max-holding cap (let winners run). ARMED-TRAIL RULE: the trail only "
    "activates after the FIRST post-entry CLOSE above the EMA21 (pullback entries "
    "start below/near it — without arming, the trail would exit almost instantly on "
    "entry); until armed, only the disaster stop applies. The trail is evaluated on "
    "closed candles only, never the entry candle itself. See "
    "nero_core.strategies.ema_trail_exit for the shared mechanics."
)


@dataclass(frozen=True)
class TrendPullbackTrailParameters(TrendPullbackParameters):
    # A genuinely new, documented registry parameter (not a hidden module constant) —
    # 21-period EMA on 12h candles is the same trailing-MA lookback TREND_PULLBACK's
    # own entry logic already anchors to (ma50/ma200), just fast enough to actually
    # trail a live trade rather than describe the broader trend.
    trail_ema_period: int = 21


DEFAULT_PARAMETERS = TrendPullbackTrailParameters()


@dataclass
class OpenTrade:
    entry_price: float
    stop_loss: float
    quantity: float
    notional: float
    risk_dollars: float
    entry_fee: float
    open_close_time: int
    entry_atr: float
    entry_rsi: float
    entry_ma50: float
    entry_ma200: float
    trail_armed: bool = False


def add_indicators(candles: pd.DataFrame, params: TrendPullbackTrailParameters = DEFAULT_PARAMETERS) -> pd.DataFrame:
    enriched = base_add_indicators(candles, params)
    return add_ema_column(enriched, params.trail_ema_period, TRAIL_EMA_COLUMN)


def size_entry(
    candle: pd.Series, state: MeanReversionState, params: TrendPullbackTrailParameters = DEFAULT_PARAMETERS
) -> OpenTrade | None:
    """Identical disaster-stop geometry to trend_pullback.size_entry (1.5x ATR) — no
    target is computed at all; the trail replaces it entirely."""
    raw_entry = float(candle["close"])
    entry_price = apply_slippage(raw_entry, params.slippage_bps, "buy")
    entry_atr = float(candle["atr"])
    stop_loss = entry_price - params.atr_stop_multiple * entry_atr
    risk_per_unit = entry_price - stop_loss
    if risk_per_unit <= 0:
        return None

    risk_dollars = state.equity * params.risk_per_trade
    quantity = risk_dollars / risk_per_unit
    max_notional = state.equity * params.max_notional_pct
    notional = quantity * entry_price
    if notional > max_notional:
        quantity = max_notional / entry_price
        notional = max_notional
        risk_dollars = quantity * risk_per_unit
    fees = notional * params.fee_bps / 10000.0

    return OpenTrade(
        entry_price=entry_price,
        stop_loss=stop_loss,
        quantity=quantity,
        notional=notional,
        risk_dollars=risk_dollars,
        entry_fee=fees,
        open_close_time=int(candle["close_time"]),
        entry_atr=entry_atr,
        entry_rsi=float(candle["rsi"]),
        entry_ma50=float(candle["ma50"]),
        entry_ma200=float(candle["ma200"]),
    )


def evaluate_exit(
    candle: pd.Series, state: MeanReversionState, params: TrendPullbackTrailParameters = DEFAULT_PARAMETERS
) -> TrailExitEvent | None:
    return evaluate_trail_exit(candle, state, TRAIL_EMA_COLUMN, params.fee_bps, params.slippage_bps)


def run_backtest(
    evaluable: pd.DataFrame, params: TrendPullbackTrailParameters = DEFAULT_PARAMETERS
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
    twice on the same registry — a new version, never a mutation of an existing one."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
