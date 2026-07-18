"""FUNDING_EXTREME — contrarian, long-only, funding-rate regime strategy.

Thesis: deeply negative perpetual funding means shorts are paying longs to stay short —
a crowded-short signal. This strategy goes long when funding is both negative AND at or
below its own trailing 90-day 10th percentile (an extreme, not just "slightly
negative"), and holds until funding normalizes back above its trailing median, with an
ATR disaster stop as the only other exit. This is a REGIME strategy, not a swing-trade
one: there is deliberately no fixed profit target and no max-holding-hours cap (see
FundingExtremeParameters — those fields don't exist on this dataclass at all, not
"set to a large number"). Its exit/state mechanics are consequently NOT compatible with
nero_core.strategies.mean_reversion.evaluate_exit (which assumes a target price and a
max-holding cap always exist) — this module defines its own evaluate_exit, while still
reusing MeanReversionState/reset_daily_guard_if_needed/apply_slippage from that module
for the parts that ARE identical (equity/daily-guard bookkeeping, slippage math).

LOOKAHEAD-SAFETY RULES (see nero_core.data_sources.funding_data for the settlement data
itself):
1. Only SETTLED funding values are ever used (funding_data.py only fetches Binance's
   already-settled funding-rate history; nothing "predicted/pending" is ever touched).
2. On 8h candles (grid-aligned to 00/08/16 UTC — see tools/backtest_funding_extreme_
   sweep.py's fetch_8h_candles, which resamples native 1h via resample_hourly_to_grid),
   each candle's OWN close corresponds to exactly one settlement (matched within a
   small tolerance — see _attach_funding_to_candles for why an exact-equality join
   doesn't work), so it is attached that settlement's value.
3. On 24h candles, a trading day has three settlements; this strategy uses ONLY the
   day's LAST one (16:00 UTC) as "that day's" funding value.
4. The trailing 90-CALENDAR-day percentile/median is computed with a time-based rolling
   window (`closed="left"`), which excludes the CURRENT settlement from its own trailing
   distribution — a settlement is never compared against a distribution that includes
   itself.
5. Signals act on the NEXT candle (t+1): every value described above is additionally
   shifted forward by one row (`entry_funding_rate` / `entry_funding_p10` /
   `entry_funding_median`) before `evaluate_entry`/`evaluate_exit` ever read it — the
   funding info "known" at candle i's close is only acted on starting at candle i+1.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from nero_core.strategies.mean_reversion import (
    MeanReversionState,
    apply_slippage,
    atr,
    reset_daily_guard_if_needed,
)
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_ID = "FUNDING_EXTREME"
STRATEGY_VERSION = "funding-extreme-v1.0.0"

SUPPORTED_TIMEFRAMES = ("8h", "24h")
DAILY_SETTLEMENT_HOUR_UTC = 16  # "that day's" funding value on 24h candles

STRATEGY_DESCRIPTION = (
    "Contrarian, long-only funding-rate regime strategy. Entry LONG when the "
    "just-settled funding rate is negative AND at or below the trailing 90-day 10th "
    "percentile of its own funding distribution (crowded shorts). Exit when funding "
    "rises back above the trailing 90-day median, OR a 2.0x ATR(14) disaster stop is "
    "hit — whichever comes first. Deliberately no fixed profit target and no "
    "max-holding-hours cap (a regime strategy, not a swing trade): the trade is held "
    "for as long as the funding regime that justified entering it persists. Standard "
    "1% risk-per-trade sizing and 10bps/2bps fee/slippage, matching every other "
    "strategy in this codebase."
)


@dataclass(frozen=True)
class FundingExtremeParameters:
    trailing_window_days: int = 90
    entry_percentile: float = 0.10
    atr_period: int = 14
    atr_stop_multiple: float = 2.0
    initial_equity: float = 10000.0
    risk_per_trade: float = 0.01
    daily_loss_guard_r: float = -3.0
    fee_bps: float = 10.0
    slippage_bps: float = 2.0
    max_notional_pct: float = 1.0
    # No `target`/`reward_multiple` field and no `max_holding_hours` field — both are
    # absent BY DESIGN (see module docstring), not omitted defaults standing in for
    # "unlimited." Every exit this strategy can ever take is enumerated in evaluate_exit.


DEFAULT_PARAMETERS = FundingExtremeParameters()


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
    entry_funding_rate: float


@dataclass(frozen=True)
class EntryEvaluation:
    passed: bool
    reasons: tuple[str, ...]
    candle_close_time: int
    close: float
    funding_rate: float | None
    funding_p10: float | None


@dataclass(frozen=True)
class ExitEvent:
    exit_reason: str  # "SL" or "FUNDING_NORMALIZED"
    exit_price: float
    gross_pnl: float
    fees: float
    net_pnl: float
    r_multiple: float
    holding_hours: float
    equity_after: float
    exit_close_time: int


def _funding_frame_for_timeframe(settlements: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """The funding settlements at the cadence this strategy's timeframe needs: every
    settlement for 8h, or only the day's LAST (16:00 UTC) settlement for 24h. Keeps
    `settlement_time` (epoch ms) alongside `settlement_date` — the exact-timestamp join
    key `_attach_funding_to_candles` needs for 8h, carried through explicitly rather
    than reconstructed from the datetime column later."""
    frame = settlements.sort_values("settlement_time").reset_index(drop=True)
    if timeframe == "24h":
        frame = frame[frame["settlement_date"].dt.hour == DAILY_SETTLEMENT_HOUR_UTC].reset_index(drop=True)
    return frame[["settlement_time", "settlement_date", "funding_rate"]]


def _trailing_percentile_and_median(frame: pd.DataFrame, window_days: int, percentile: float) -> pd.DataFrame:
    """Trailing `window_days`-CALENDAR-day percentile/median, `closed="left"` so the
    window never includes the row's own settlement — a genuine no-self-inclusion
    trailing window, robust to any gap in the settlement series (a fixed observation
    count would silently misrepresent the window's real calendar span across a gap).
    Returns `frame` with `funding_p10`/`funding_median` columns appended."""
    indexed = frame.set_index("settlement_date")["funding_rate"]
    rolling = indexed.rolling(f"{window_days}D", closed="left")
    result = frame.copy()
    result["funding_p10"] = rolling.quantile(percentile).to_numpy()
    result["funding_median"] = rolling.median().to_numpy()
    return result


FUNDING_JOIN_TOLERANCE_MS = 60_000  # 1 minute — far smaller than the 8h gap between settlements


def _attach_funding_to_candles(candles: pd.DataFrame, stats: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Join each candle to its OWN funding settlement: nearest-match (within
    FUNDING_JOIN_TOLERANCE_MS) close_time match on 8h, calendar-date match on 24h (the
    daily candle's close falls on the same UTC date as that day's 16:00 UTC settlement,
    not at the same timestamp).

    8h is NOT an exact-equality join: verified empirically that Binance kline
    `close_time` is `period_end - 1ms` (not the period boundary itself), while funding
    `fundingTime` carries its own few-millisecond exchange jitter — an exact-integer
    join between the two matches ZERO rows. The tolerance is far smaller than the 8h
    gap between settlements, so there is no risk of a candle matching the wrong
    period's settlement."""
    frame = candles.copy().sort_values("close_time").reset_index(drop=True)

    if timeframe == "8h":
        merged = pd.merge_asof(
            frame,
            stats.drop(columns=["settlement_date"]).sort_values("settlement_time"),
            left_on="close_time",
            right_on="settlement_time",
            direction="nearest",
            tolerance=FUNDING_JOIN_TOLERANCE_MS,
        )
        return merged.drop(columns=["settlement_time"])

    if timeframe == "24h":
        frame["_date_only"] = pd.to_datetime(frame["close_time"], unit="ms", utc=True).dt.date
        stats_by_date = stats.copy()
        stats_by_date["_date_only"] = stats_by_date["settlement_date"].dt.date
        merged = frame.merge(stats_by_date.drop(columns=["settlement_date", "settlement_time"]), on="_date_only", how="left")
        return merged.drop(columns=["_date_only"])

    raise ValueError(f"FUNDING_EXTREME only supports timeframes {SUPPORTED_TIMEFRAMES}, got {timeframe!r}")


def add_indicators(
    candles: pd.DataFrame,
    funding_settlements: pd.DataFrame,
    timeframe: str,
    params: FundingExtremeParameters = DEFAULT_PARAMETERS,
) -> pd.DataFrame:
    """Attach ATR and the (t+1-lagged) funding signal columns to closed candles.
    `entry_funding_rate` / `entry_funding_p10` / `entry_funding_median` are what
    evaluate_entry/evaluate_exit actually read — each is the PRIOR candle's own
    (already trailing-window-excluding-self) funding stats, implementing the "signals
    act on the next candle" rule."""
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"FUNDING_EXTREME only supports timeframes {SUPPORTED_TIMEFRAMES}, got {timeframe!r}")

    frame = candles.copy().sort_values("close_time").reset_index(drop=True)
    frame["atr"] = atr(frame, params.atr_period)

    funding_frame = _funding_frame_for_timeframe(funding_settlements, timeframe)
    stats = _trailing_percentile_and_median(funding_frame, params.trailing_window_days, params.entry_percentile)
    frame = _attach_funding_to_candles(frame, stats, timeframe)

    frame["entry_funding_rate"] = frame["funding_rate"].shift(1)
    frame["entry_funding_p10"] = frame["funding_p10"].shift(1)
    frame["entry_funding_median"] = frame["funding_median"].shift(1)
    return frame


def evaluate_entry(
    candle: pd.Series,
    state: MeanReversionState,
    params: FundingExtremeParameters = DEFAULT_PARAMETERS,
) -> EntryEvaluation:
    reasons: list[str] = []
    if state.open_trade is not None:
        reasons.append("OPEN_TRADE_EXISTS")
    if state.daily_r <= params.daily_loss_guard_r:
        reasons.append("DAILY_LOSS_GUARD")

    funding_rate = candle.get("entry_funding_rate")
    funding_p10 = candle.get("entry_funding_p10")
    funding_missing = funding_rate is None or funding_p10 is None or pd.isna(funding_rate) or pd.isna(funding_p10)
    if funding_missing:
        reasons.append("FUNDING_DATA_NOT_YET_AVAILABLE")
    else:
        if not (float(funding_rate) < 0.0):
            reasons.append("FUNDING_NOT_NEGATIVE")
        if not (float(funding_rate) <= float(funding_p10)):
            reasons.append("FUNDING_NOT_AT_OR_BELOW_TRAILING_P10")

    return EntryEvaluation(
        passed=not reasons,
        reasons=tuple(reasons),
        candle_close_time=int(candle["close_time"]),
        close=float(candle["close"]),
        funding_rate=None if funding_missing else float(funding_rate),
        funding_p10=None if funding_missing else float(funding_p10),
    )


def size_entry(
    candle: pd.Series,
    state: MeanReversionState,
    params: FundingExtremeParameters = DEFAULT_PARAMETERS,
) -> OpenTrade | None:
    """Fixed-fractional sizing, 2.0x ATR disaster stop, no target. Returns None if the
    stop geometry is invalid (non-positive risk per unit) — callers should only invoke
    this after `evaluate_entry` has passed."""
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
        entry_funding_rate=float(candle["entry_funding_rate"]),
    )


def evaluate_exit(
    candle: pd.Series,
    state: MeanReversionState,
    params: FundingExtremeParameters = DEFAULT_PARAMETERS,
) -> ExitEvent | None:
    """Only two possible exits, checked in this priority order: the ATR disaster stop
    (SL), then funding normalization (FUNDING_NORMALIZED — the same t+1-lagged
    entry_funding_rate/entry_funding_median columns evaluate_entry uses). There is no
    target and no max-holding-hours check — neither concept exists for this strategy
    (see module docstring)."""
    trade = state.open_trade
    if trade is None:
        return None

    candle_time = int(candle["close_time"])
    low = float(candle["low"])
    close = float(candle["close"])

    funding_rate = candle.get("entry_funding_rate")
    funding_median = candle.get("entry_funding_median")
    funding_normalized = (
        funding_rate is not None
        and funding_median is not None
        and not pd.isna(funding_rate)
        and not pd.isna(funding_median)
        and float(funding_rate) > float(funding_median)
    )

    if low <= trade.stop_loss:
        exit_reason, raw_exit = "SL", trade.stop_loss
    elif funding_normalized:
        exit_reason, raw_exit = "FUNDING_NORMALIZED", close
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
    hours_held = (candle_time - trade.open_close_time) / 3600000.0
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


def funding_data_available_mask(evaluable: pd.DataFrame) -> pd.Series:
    """The regime PRECONDITION for this strategy's random-entry baseline (see
    tools.backtest_statistics): "funding data is known and usable" (both the t+1-lagged
    rate and its trailing p10 are non-NaN) — deliberately excludes the specific
    "negative AND at-or-below p10" TRIGGER, which is exactly what random-entry timing
    within this same eligible pool is meant to test against."""
    return evaluable["entry_funding_rate"].notna() & evaluable["entry_funding_p10"].notna()


def run_backtest(
    evaluable: pd.DataFrame, params: FundingExtremeParameters = DEFAULT_PARAMETERS
) -> tuple[list[ExitEvent], MeanReversionState]:
    """Runs FUNDING_EXTREME candle-by-candle over an already-indicator-enriched,
    already-warmup-dropna'd frame (see add_indicators) — the same shape convention as
    tools.backtest_compare.run_backtest and cointegration_pairs.run_pairs_backtest,
    just using this module's own evaluate_entry/evaluate_exit/size_entry rather than the
    shared ones (see module docstring for why they can't be shared)."""
    state = MeanReversionState(equity=params.initial_equity)
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
    """Register the Funding Extreme strategy's first version. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
