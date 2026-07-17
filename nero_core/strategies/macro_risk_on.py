"""MACRO_RISK_ON — regime-following strategy driven entirely by two macro legs (dollar
strength and real yields), DAILY timeframe only. Unlike every price-indicator strategy
in this codebase, its entry/exit trigger is a REGIME flag computed upstream by
nero_core.data_sources.macro_data.build_regime_frame from two external series, not a
rolling price statistic — this module only consumes an already-regime-merged candle
frame (see attach_regime), the same separation-of-concerns COINTEGRATION_PAIRS and
LEADLAG_FOLLOW use for their own external inputs.

Regime definition (both legs must independently agree, each evaluated only on data
already published per its own lag rule — see macro_data.py for why the lags differ):
  risk_on = (20-day change in dollar proxy < 0)  AND  (20-day change in DFII10 < 0)
i.e. the dollar is weakening AND real yields are falling — the textbook "risk-on"
macro backdrop for a scarce, non-yielding asset like BTC or GOLD.

ARCHITECTURE NOTE (why this needs its own exit, like DONCHIAN_TREND/SHORT_MOMENTUM):
there is deliberately no fixed target and no max-holding-hours cap — see
MacroRiskOnParameters' docstring. Exit is either the regime turning off, or a 2x-ATR
disaster stop; there is no third exit category.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from nero_core.strategies.mean_reversion import MeanReversionState, apply_slippage, atr, reset_daily_guard_if_needed
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_ID = "MACRO_RISK_ON"
STRATEGY_VERSION = "macro-risk-on-v1.0.0"

STRATEGY_DESCRIPTION = (
    "Long-only, DAILY timeframe only, regime-following strategy: enter BTC or GOLD "
    "whenever risk_on is true (20-day change in a dollar-strength proxy < 0 AND 20-day "
    "change in FRED DFII10 real yield < 0, each leg evaluated only on data already "
    "published per its own lag rule — dollar t+1, DFII10 t+2, see "
    "nero_core.data_sources.macro_data) and no trade is already open. Exit: the regime "
    "turning off (risk_on becomes false), or a 2.0x-ATR(14) disaster stop, whichever "
    "comes first. Deliberately no fixed target and no max-holding-hours cap — a "
    "regime-follower's whole premise is staying in as long as the regime holds; a time "
    "cap or fixed R target would work directly against that. Standard 1% "
    "fixed-fractional sizing on the ATR-stop risk distance."
)


@dataclass(frozen=True)
class MacroRiskOnParameters:
    """No max_holding_hours field and no fixed-target field — a deliberate registry-
    level decision (not an omission), matching DONCHIAN_TREND's precedent: this
    strategy's entire premise is riding a macro regime for as long as it holds, so a
    time cap or price target would cut exactly the trades it exists to catch."""

    atr_period: int = 14
    atr_stop_multiple: float = 2.0
    initial_equity: float = 10000.0
    risk_per_trade: float = 0.01
    daily_loss_guard_r: float = -3.0
    fee_bps: float = 10.0
    slippage_bps: float = 2.0
    max_notional_pct: float = 1.0


DEFAULT_PARAMETERS = MacroRiskOnParameters()

INDICATOR_COLUMNS_TO_CHECK = ["atr", "dollar_change_20d", "dfii10_change_20d"]


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


@dataclass(frozen=True)
class EntryEvaluation:
    passed: bool
    reasons: tuple[str, ...]
    candle_close_time: int
    close: float
    risk_on: bool | None
    atr: float | None


@dataclass(frozen=True)
class ExitEvent:
    exit_reason: str  # "STOP" or "REGIME_OFF" — no third category for this strategy
    exit_price: float
    gross_pnl: float
    fees: float
    net_pnl: float
    r_multiple: float
    holding_hours: float
    equity_after: float
    exit_close_time: int = 0


def add_indicators(candles_with_regime: pd.DataFrame, params: MacroRiskOnParameters = DEFAULT_PARAMETERS) -> pd.DataFrame:
    """Attach ATR(14) to an already regime-merged daily candle frame (see
    nero_core.data_sources.macro_data.build_regime_frame) — this function does not
    fetch or merge macro data itself, only computes the price-based indicator this
    strategy still needs for its stop distance."""
    frame = candles_with_regime.copy().sort_values("close_time").reset_index(drop=True)
    frame["atr"] = atr(frame, params.atr_period)
    return frame


def evaluate_entry(
    candle: pd.Series,
    state: MeanReversionState,
    params: MacroRiskOnParameters = DEFAULT_PARAMETERS,
) -> EntryEvaluation:
    """Evaluate against one closed daily candle already carrying `risk_on` (from
    build_regime_frame) and `atr` (from add_indicators). Every rejection reason is
    reported, not just the first."""
    reasons: list[str] = []
    if state.open_trade is not None:
        reasons.append("OPEN_TRADE_EXISTS")
    if state.daily_r <= params.daily_loss_guard_r:
        reasons.append("DAILY_LOSS_GUARD")

    risk_on = candle.get("risk_on")
    if pd.isna(risk_on) or not bool(risk_on):
        reasons.append("REGIME_NOT_RISK_ON")

    atr_value = candle.get("atr")
    if pd.isna(atr_value):
        reasons.append("ATR_NOT_AVAILABLE")

    return EntryEvaluation(
        passed=not reasons,
        reasons=tuple(reasons),
        candle_close_time=int(candle["close_time"]),
        close=float(candle["close"]),
        risk_on=None if pd.isna(risk_on) else bool(risk_on),
        atr=None if pd.isna(atr_value) else float(atr_value),
    )


def size_entry(
    candle: pd.Series,
    state: MeanReversionState,
    params: MacroRiskOnParameters = DEFAULT_PARAMETERS,
) -> OpenTrade | None:
    """Fixed-fractional sizing against a 2x-ATR stop distance. Returns None if that
    distance isn't positive — callers should only invoke this after `evaluate_entry`
    has passed (a defensive re-check, matching every other strategy's convention)."""
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
    )


def evaluate_exit(
    candle: pd.Series,
    state: MeanReversionState,
    params: MacroRiskOnParameters = DEFAULT_PARAMETERS,
) -> ExitEvent | None:
    """Exactly two exit conditions, checked in this priority order: the 2x-ATR disaster
    stop (an intrabar price touch, using the candle's low), then the regime turning off
    (a signal-based exit at the candle's own close). No target, no time cap."""
    trade = state.open_trade
    if trade is None:
        return None

    candle_time = int(candle["close_time"])
    hours_held = (candle_time - trade.open_close_time) / 3600000.0
    low = float(candle["low"])
    close = float(candle["close"])
    risk_on = candle.get("risk_on")

    if low <= trade.stop_loss:
        exit_reason, raw_exit = "STOP", trade.stop_loss
    elif pd.isna(risk_on) or not bool(risk_on):
        exit_reason, raw_exit = "REGIME_OFF", close
    else:
        return None

    exit_price = apply_slippage(raw_exit, params.slippage_bps, "sell")
    quantity = trade.quantity
    gross_pnl = (exit_price - trade.entry_price) * quantity
    exit_fee = exit_price * quantity * params.fee_bps / 10000.0
    total_fees = trade.entry_fee + exit_fee
    net_pnl = gross_pnl - total_fees
    risk_dollars = max(trade.risk_dollars, 1e-9)
    r_multiple = net_pnl / risk_dollars
    equity_after = state.equity + net_pnl

    state.equity = equity_after
    state.daily_r = state.daily_r + r_multiple
    state.open_trade = None

    return ExitEvent(
        exit_reason=exit_reason,
        exit_price=exit_price,
        gross_pnl=gross_pnl,
        fees=total_fees,
        net_pnl=net_pnl,
        r_multiple=r_multiple,
        holding_hours=hours_held,
        equity_after=equity_after,
        exit_close_time=candle_time,
    )


def run_macro_risk_on_backtest(
    candles_with_regime: pd.DataFrame,
    params: MacroRiskOnParameters = DEFAULT_PARAMETERS,
) -> tuple[list[ExitEvent], MeanReversionState]:
    """Candle-by-candle simulation — same shape/contract as
    tools.backtest_compare.run_backtest, but wired to this module's own regime/ATR-stop
    exit instead of the shared fixed-price long-only one. `candles_with_regime` must
    already carry `risk_on` (and the two change columns used for warmup dropna) from
    nero_core.data_sources.macro_data.build_regime_frame."""
    state = MeanReversionState(equity=params.initial_equity)
    enriched = add_indicators(candles_with_regime, params)
    dropna_columns = [c for c in INDICATOR_COLUMNS_TO_CHECK if c in enriched.columns]
    evaluable = enriched.dropna(subset=dropna_columns).reset_index(drop=True)
    closed_trades: list[ExitEvent] = []

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
    """Register the Macro Risk-On strategy's first version. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
