"""GOLD_SILVER_RATIO_MR v1.0.0 — Three New Hypothesis Batch, Hypothesis 1 (Metals).

MECHANISM: the GOLD/SILVER price ratio oscillates in a historical band; extremes
mean-revert. A genuine two-leg pairs trade (unlike COINTEGRATION_PAIRS' own
long-leg-only simplification — this project's SHORT accounting is already well
established, see short_momentum.py/range_mean_reversion.py, so both legs are
modeled here): ratio HIGH -> LONG SILVER + SHORT GOLD (silver looks cheap
relative to gold); ratio LOW -> LONG GOLD + SHORT SILVER.

DATA AUDIT (tools/gold_silver_ratio_data_audit.py, docs/gold_silver_ratio_data_audit.md):
GOLD (Twelve Data XAU/USD) and SILVER (yfinance SI=F futures) daily closes are
stamped at DIFFERENT times of day (00:00 UTC vs 04:00 UTC) — an exact close_time
join produces ZERO matches; alignment must be by CALENDAR DATE (see
align_gold_silver_candles). 18.7 years of aligned daily history, 25.9 years
weekly — both comfortably clear the 5-year adequacy bar. The 2020-03 COVID spike
(ratio to ~125-131, exactly the ">120" the task called out) badly distorts any
FIXed full-history percentile band (full-history 90th pct: 88.0 daily / 86.6
weekly) — this is precisely why entries use a ROLLING 252-session percentile,
which stays locally adaptive (most recent rolling 90th pct: 87.7 daily / 91.2
weekly) rather than permanently skewed by one historical event.

ENTRY (rolling window EXCLUDES the current candle throughout — shift(1) before
every rolling stat): ratio > trailing 252-session 90th percentile -> LONG_SILVER_
SHORT_GOLD. ratio < trailing 10th percentile -> LONG_GOLD_SHORT_SILVER. Both legs
open simultaneously.

SIZING: each leg targets `risk_per_leg` (0.5%) of equity, with each leg's OWN
price-stop-distance derived from the ratio's own ATR-analog stop distance
(`ratio_atr`, 20-session mean absolute ratio change — the ratio has no natural
high/low of its own, so this is a documented proxy for a true-range ATR),
converted to that leg's own price terms via the SAME percentage move
(`ratio_stop_pct = ratio_stop_distance / entry_ratio`, applied to each leg's own
entry price). This ties position sizing to the SAME divergence measure the pairs-
aware stop uses, without introducing a second, independent per-leg stop trigger.

EXIT priority (checked every closed candle, both legs together — NEVER
independently, since leg noise must not trigger an exit the pair itself hasn't
earned): 1. PAIRS-AWARE STOP — the ratio itself has moved a further
2.0x-ratio_atr (at entry) beyond the entry ratio, in the ADVERSE direction (the
divergence widened, not narrowed). 2. REVERSION — ratio has reverted to (or past)
the trailing 252-session median. No fixed holding cap — reversion is slow by
construction (a 252-session percentile is not something that resolves in days).

SHORT ACCOUNTING reuses the standard convention (apply_slippage direction,
inverted gross_pnl) already established by short_momentum.py/
range_mean_reversion.py — not re-derived here.

Like COINTEGRATION_PAIRS, this needs two aligned price series and does not fit
the single-asset add_indicators/evaluate_entry/size_entry/VariantSpec shape — its
own self-contained state machine and backtest loop, reusing only apply_slippage
from mean_reversion.py.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace

import pandas as pd

from nero_core.strategies.mean_reversion import apply_slippage
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_ID = "GOLD_SILVER_RATIO_MR"
STRATEGY_VERSION = "gold-silver-ratio-mr-v1.0.0"

STRATEGY_DESCRIPTION = (
    "GOLD/SILVER ratio pairs mean-reversion, both directions: LONG_SILVER_SHORT_"
    "GOLD when ratio > trailing 252-session 90th percentile (excl. current "
    "candle); LONG_GOLD_SHORT_SILVER when ratio < trailing 10th percentile. Exit: "
    "pairs-aware stop (ratio diverges a further 2x its own 20-session ATR-analog "
    "beyond the entry ratio) checked first, then reversion to the trailing "
    "252-session median. No fixed holding cap. Each leg sized to 0.5% risk (1% "
    "pair total), stop distance derived from the ratio's own divergence measure. "
    "Both legs genuinely modeled (LONG and SHORT), unlike COINTEGRATION_PAIRS' "
    "long-leg-only simplification."
)


@dataclass(frozen=True)
class GoldSilverRatioParameters:
    rolling_window: int = 252  # sessions, always shift(1)'d -- excludes the current candle
    ratio_atr_period: int = 20
    stop_atr_multiple: float = 2.0
    risk_per_leg: float = 0.005
    initial_equity: float = 10000.0
    fee_bps: float = 10.0  # 0.1% per side per leg
    slippage_bps: float = 2.0
    max_notional_pct: float = 1.0  # per leg


DEFAULT_PARAMETERS = GoldSilverRatioParameters()

INDICATOR_COLUMNS_TO_CHECK = ["ratio", "rolling_p10", "rolling_p90", "rolling_median", "ratio_atr"]


@dataclass
class PairLeg:
    asset: str  # "GOLD" or "SILVER"
    direction: str  # "LONG" or "SHORT"
    entry_price: float
    quantity: float
    notional: float
    entry_fee: float


@dataclass
class OpenPairTrade:
    direction: str  # "LONG_SILVER_SHORT_GOLD" or "LONG_GOLD_SHORT_SILVER"
    gold_leg: PairLeg
    silver_leg: PairLeg
    entry_ratio: float
    entry_ratio_atr: float
    open_close_time: int


@dataclass
class GoldSilverRatioState:
    equity: float
    open_trade: OpenPairTrade | None = None


@dataclass(frozen=True)
class EntryEvaluation:
    passed: bool
    direction: str | None
    reasons: tuple[str, ...]
    ratio: float | None


@dataclass(frozen=True)
class ExitEvent:
    exit_reason: str  # "RATIO_STOP" | "REVERSION"
    exit_ratio: float
    gold_exit_price: float
    silver_exit_price: float
    gross_pnl: float
    fees: float
    net_pnl: float
    r_multiple: float
    equity_after: float
    holding_sessions: int
    exit_close_time: int = 0


def align_gold_silver_candles(gold: pd.DataFrame, silver: pd.DataFrame) -> pd.DataFrame:
    """Inner-join GOLD/SILVER on CALENDAR DATE, not exact close_time — confirmed
    directly (docs/gold_silver_ratio_data_audit.md) that GOLD (Twelve Data
    XAU/USD) stamps its daily/weekly close at 00:00 UTC while SILVER (yfinance
    SI=F futures) stamps at 04:00 UTC, a fixed 4-hour offset from a different
    data source's own convention — an exact close_time join produces ZERO
    matches. Both inputs are already-closed candles; joining on the normalized
    date is the correct alignment for "the same trading day" across sources."""
    g = gold[["close_time", "date", "close"]].rename(columns={"close": "gold_close"}).copy()
    s = silver[["date", "close"]].rename(columns={"close": "silver_close"}).copy()
    g["_date_only"] = pd.to_datetime(g["date"]).dt.tz_localize(None).dt.normalize()
    s["_date_only"] = pd.to_datetime(s["date"]).dt.tz_localize(None).dt.normalize()
    merged = g.merge(s[["_date_only", "silver_close"]], on="_date_only", how="inner")
    return merged.sort_values("close_time").drop(columns=["_date_only"]).reset_index(drop=True)


def add_indicators(aligned: pd.DataFrame, params: GoldSilverRatioParameters = DEFAULT_PARAMETERS) -> pd.DataFrame:
    """No lookahead: every rolling stat is shift(1)'d before the rolling window,
    so row i's threshold/target values only ever reflect candles strictly BEFORE
    i — row i's own ratio never influences its own entry/exit thresholds."""
    frame = aligned.copy().sort_values("close_time").reset_index(drop=True)
    frame["ratio"] = frame["gold_close"] / frame["silver_close"]
    prior_ratio = frame["ratio"].shift(1)
    frame["rolling_p10"] = prior_ratio.rolling(params.rolling_window).quantile(0.10)
    frame["rolling_p90"] = prior_ratio.rolling(params.rolling_window).quantile(0.90)
    frame["rolling_median"] = prior_ratio.rolling(params.rolling_window).median()
    # "Ratio ATR" -- a documented true-range analog for a synthetic ratio series
    # with no natural high/low of its own: mean absolute session-over-session
    # ratio change over the trailing window.
    frame["ratio_atr"] = frame["ratio"].diff().abs().rolling(params.ratio_atr_period).mean()
    return frame


def evaluate_entry(row: pd.Series, state: GoldSilverRatioState, params: GoldSilverRatioParameters = DEFAULT_PARAMETERS) -> EntryEvaluation:
    """Every rejection reason is reported, not just the first."""
    reasons: list[str] = []
    if state.open_trade is not None:
        reasons.append("OPEN_TRADE_EXISTS")

    ratio = row.get("ratio")
    p10 = row.get("rolling_p10")
    p90 = row.get("rolling_p90")
    if ratio is None or p10 is None or p90 is None or pd.isna(ratio) or pd.isna(p10) or pd.isna(p90):
        reasons.append("INDICATORS_NOT_AVAILABLE")
        return EntryEvaluation(passed=False, direction=None, reasons=tuple(reasons), ratio=None if ratio is None or pd.isna(ratio) else float(ratio))

    ratio = float(ratio)
    direction: str | None = None
    if ratio > float(p90):
        direction = "LONG_SILVER_SHORT_GOLD"
    elif ratio < float(p10):
        direction = "LONG_GOLD_SHORT_SILVER"
    else:
        reasons.append("RATIO_WITHIN_BAND")

    passed = direction is not None and not reasons
    return EntryEvaluation(passed=passed, direction=direction if passed else None, reasons=tuple(reasons), ratio=ratio)


def size_entry(
    row: pd.Series, state: GoldSilverRatioState, params: GoldSilverRatioParameters = DEFAULT_PARAMETERS, direction: str = "LONG_SILVER_SHORT_GOLD",
) -> OpenPairTrade | None:
    """Each leg's stop distance is derived from the ratio's own stop distance
    (stop_atr_multiple * ratio_atr), converted to that leg's own price terms via
    the ratio-stop-as-a-percentage-of-the-entry-ratio. Returns None if the
    resulting stop distance isn't positive on either leg."""
    ratio = float(row["ratio"])
    ratio_atr = row.get("ratio_atr")
    if ratio_atr is None or pd.isna(ratio_atr) or float(ratio_atr) <= 0:
        return None
    ratio_atr = float(ratio_atr)

    ratio_stop_distance = params.stop_atr_multiple * ratio_atr
    ratio_stop_pct = ratio_stop_distance / ratio
    if ratio_stop_pct <= 0:
        return None

    gold_raw = float(row["gold_close"])
    silver_raw = float(row["silver_close"])
    gold_stop_distance = gold_raw * ratio_stop_pct
    silver_stop_distance = silver_raw * ratio_stop_pct
    if gold_stop_distance <= 0 or silver_stop_distance <= 0:
        return None

    if direction == "LONG_SILVER_SHORT_GOLD":
        gold_direction, silver_direction = "SHORT", "LONG"
    else:
        gold_direction, silver_direction = "LONG", "SHORT"

    def _build_leg(asset: str, raw_price: float, leg_direction: str, stop_distance: float) -> PairLeg:
        side = "buy" if leg_direction == "LONG" else "sell"
        entry_price = apply_slippage(raw_price, params.slippage_bps, side)
        risk_dollars = state.equity * params.risk_per_leg
        quantity = risk_dollars / stop_distance
        max_notional = state.equity * params.max_notional_pct
        notional = quantity * entry_price
        if notional > max_notional:
            quantity = max_notional / entry_price
            notional = max_notional
        entry_fee = notional * params.fee_bps / 10000.0
        return PairLeg(asset=asset, direction=leg_direction, entry_price=entry_price, quantity=quantity, notional=notional, entry_fee=entry_fee)

    gold_leg = _build_leg("GOLD", gold_raw, gold_direction, gold_stop_distance)
    silver_leg = _build_leg("SILVER", silver_raw, silver_direction, silver_stop_distance)

    return OpenPairTrade(
        direction=direction, gold_leg=gold_leg, silver_leg=silver_leg,
        entry_ratio=ratio, entry_ratio_atr=ratio_atr, open_close_time=int(row["close_time"]),
    )


def _close_leg(leg: PairLeg, exit_price: float, params: GoldSilverRatioParameters) -> tuple[float, float]:
    """Returns (gross_pnl, exit_fee) for closing one leg. SHORT accounting reuses
    the standard convention (inverted gross_pnl vs LONG)."""
    if leg.direction == "LONG":
        gross_pnl = (exit_price - leg.entry_price) * leg.quantity
    else:  # SHORT
        gross_pnl = (leg.entry_price - exit_price) * leg.quantity
    exit_fee = exit_price * leg.quantity * params.fee_bps / 10000.0
    return gross_pnl, exit_fee


def evaluate_exit(row: pd.Series, state: GoldSilverRatioState, params: GoldSilverRatioParameters = DEFAULT_PARAMETERS) -> ExitEvent | None:
    """Priority: RATIO_STOP (safety) before REVERSION (target) — matching every
    other strategy's convention. Both legs close together, always."""
    trade = state.open_trade
    if trade is None:
        return None

    ratio = row.get("ratio")
    if ratio is None or pd.isna(ratio):
        return None
    ratio = float(ratio)

    median = row.get("rolling_median")
    close_time = int(row["close_time"])

    exit_reason: str | None = None
    stop_distance = params.stop_atr_multiple * trade.entry_ratio_atr

    if trade.direction == "LONG_SILVER_SHORT_GOLD":
        # Opened because ratio was HIGH; adverse divergence = ratio going even HIGHER.
        if ratio >= trade.entry_ratio + stop_distance:
            exit_reason = "RATIO_STOP"
        elif median is not None and not pd.isna(median) and ratio <= float(median):
            exit_reason = "REVERSION"
    else:  # LONG_GOLD_SHORT_SILVER, opened because ratio was LOW
        if ratio <= trade.entry_ratio - stop_distance:
            exit_reason = "RATIO_STOP"
        elif median is not None and not pd.isna(median) and ratio >= float(median):
            exit_reason = "REVERSION"

    if exit_reason is None:
        return None

    gold_raw = float(row["gold_close"])
    silver_raw = float(row["silver_close"])
    gold_exit_price = apply_slippage(gold_raw, params.slippage_bps, "sell" if trade.gold_leg.direction == "LONG" else "buy")
    silver_exit_price = apply_slippage(silver_raw, params.slippage_bps, "sell" if trade.silver_leg.direction == "LONG" else "buy")

    gold_gross, gold_exit_fee = _close_leg(trade.gold_leg, gold_exit_price, params)
    silver_gross, silver_exit_fee = _close_leg(trade.silver_leg, silver_exit_price, params)

    gross_pnl = gold_gross + silver_gross
    fees = trade.gold_leg.entry_fee + trade.silver_leg.entry_fee + gold_exit_fee + silver_exit_fee
    net_pnl = gross_pnl - fees
    risk_dollars = max(state.equity * params.risk_per_leg * 2, 1e-9)  # both legs' combined risk allocation
    r_multiple = net_pnl / risk_dollars
    equity_after = state.equity + net_pnl

    state.equity = equity_after
    state.open_trade = None

    return ExitEvent(
        exit_reason=exit_reason, exit_ratio=ratio, gold_exit_price=gold_exit_price, silver_exit_price=silver_exit_price,
        gross_pnl=gross_pnl, fees=fees, net_pnl=net_pnl, r_multiple=r_multiple, equity_after=equity_after,
        holding_sessions=0, exit_close_time=close_time,
    )


def run_backtest(evaluable: pd.DataFrame, params: GoldSilverRatioParameters = DEFAULT_PARAMETERS) -> tuple[list[ExitEvent], GoldSilverRatioState]:
    state = GoldSilverRatioState(equity=params.initial_equity)
    closed_trades: list[ExitEvent] = []
    open_index: int | None = None

    for i in range(len(evaluable)):
        row = evaluable.iloc[i]

        exit_event = evaluate_exit(row, state, params)
        if exit_event is not None:
            holding_sessions = (i - open_index) if open_index is not None else 0
            exit_event = replace(exit_event, holding_sessions=holding_sessions)
            closed_trades.append(exit_event)
            open_index = None

        evaluation = evaluate_entry(row, state, params)
        if evaluation.passed:
            trade = size_entry(row, state, params, evaluation.direction)
            if trade is not None:
                state.open_trade = trade
                open_index = i

    return closed_trades, state


def ratio_eligible_mask(evaluable: pd.DataFrame) -> pd.Series:
    """The eligible pool for a random-entry baseline: candles where the ratio is
    OUTSIDE the trailing band (>90th or <10th percentile) -- same pool the real
    strategy draws its entries from, isolating whether picking the EXTREME side
    correctly (not just trading anywhere outside the band) adds value."""
    return (evaluable["ratio"] > evaluable["rolling_p90"]) | (evaluable["ratio"] < evaluable["rolling_p10"])


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register GOLD_SILVER_RATIO_MR's first version. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID, version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_PARAMETERS), description=STRATEGY_DESCRIPTION,
    )
