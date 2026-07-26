"""REPAIR_BREAKOUT_QUALITY, v1.0.0 — 4H long-only breakout-and-retest momentum.

ORIGIN: user-supplied external spec (display name FIX_BREAKOUT_QUALITY), already
forward-tested outside Vatican on a small (N=12) sample. Per this project's rule that
no strategy's reported "edge" is trusted until it clears Vatican's own verification
harness (70/30 split, bootstrap CI, random-entry baseline, grid-shift — see
tools/backtest_repair_breakout_quality.py), the external 12-trade stats are NEVER
reused anywhere in this codebase; this module exists to let Vatican run its own,
independent measurement of the mechanism.

MECHANISM (long-only): candle N is a BREAKOUT candle when close > the prior
30-candle high (shift(1) before the rolling max — a candle can't break its own
threshold), close > MA200, MA20 > MA200, and ATR(14)/close <= atr_pct_max (4%
default). A breakout candle ARMS a pending setup at that breakout level, which
expires after `retest_window` (10) candles if never confirmed. A SUBSEQUENT closed
candle whose LOW touches (<=) the armed level and whose CLOSE is back above it is the
CONFIRMATION candle. Entry happens on the candle AFTER confirmation (never on the
confirmation candle itself) — see "NO SAME-CANDLE ENTRY" below — and re-checks every
regime filter (MA200, MA20>MA200, ATR cap) at that later entry candle too, not just at
the original breakout, since price/indicators can move during the up-to-10-candle gap
between breakout and confirmation.

NO SAME-CANDLE ENTRY (retest rule, external-testing finding #1): every other breakout
strategy in this codebase (breakout_momentum.py, donchian_breakout_bracket.py) fills
its entry on the SAME candle whose close triggered the signal. That convention is
provably safe there because the signal (breakout) and the fill (that same candle's own
close) are both fully known the instant the candle closes. It is NOT safe for a retest
rule: "candle M's low touched the level and closed back above it" is only knowable once
candle M closes, so filling on candle M itself would be indistinguishable from
peeking at a candle's own outcome before using it as the trigger. Entry is therefore
deliberately deferred to candle M+1's close (one full bar later than every other
breakout family here) — slower, but not lookahead.

STOP-LOSS, NO GAP TOLERANCE (external-testing finding #2): every existing ATR-stop
strategy in this codebase (mean_reversion.py, donchian_breakout_bracket.py) fills a
stop-loss hit at the EXACT stop price whenever a candle's low touches it, even if the
candle's own close finished far below that price — a fine approximation for a shallow
wick, but a fiction when the whole candle broke cleanly through and kept going (there
was no real fill available at the stop price; the market gapped past it). This modules
distinguishes the two: if a candle's low touches the stop but its CLOSE recovers back
above the stop, that's a same-bar wick — filled at the stop price, as usual. If the
candle's close ALSO finishes at/below the stop (the whole bar broke through), no
same-bar fill is assumed; the trade is marked `gap_pending` and the exit is realized on
the NEXT candle's OPEN — genuinely worse than -1R when the market actually gapped,
reported honestly, never clipped back to -1.0R. (external testing observed exactly
this failure mode: stops realizing -1.29R to -1.81R instead of a clean -1.0R.) Target
fills are NOT given the same treatment — filling at the fixed target price when a
candle's high merely touches it is, if anything, conservative (it can only understate a
real gap-up win, never overstate it), so there is no honesty problem to fix there.

RULE 6 ("planned reward >= 1.35R") IS STRUCTURALLY A NO-OP, DISCLOSED, NOT HIDDEN: the
external spec calls for a minimum planned reward of 1.35R alongside a FIXED 1.5R
target. Since the target is fixed at 1.5R by construction of the exit rule (stop = 1.0x
ATR = 1R, target = 1.5R, always), every candidate that reaches this check already has a
"planned reward" of exactly 1.5R > 1.35R — the condition can never reject a trade. It
is kept as an explicit, always-true check (see `PLANNED_REWARD_MIN_R` /
`_planned_reward_r`) rather than silently dropped, so this fact is visible in the code
and in every EntryEvaluation, not swept under the rug.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from nero_core.strategies.mean_reversion import apply_slippage, atr
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_ID = "REPAIR_BREAKOUT_QUALITY"
STRATEGY_VERSION = "repair-breakout-quality-v1.0.0"

STRATEGY_DESCRIPTION = (
    "4H long-only breakout-and-retest momentum (external spec, display name "
    "FIX_BREAKOUT_QUALITY): breakout above the prior 30-candle high with MA200/"
    "MA20>MA200 trend support and ATR/close <= 4%, ARMS a pending setup; a later "
    "closed candle (within 10 candles) whose low retests the breakout level and "
    "closes back above it CONFIRMS it; entry fills on the candle AFTER confirmation "
    "(never the confirmation candle itself, to avoid using a candle's own close as "
    "both trigger and fill). Stop = entry - 1.0x ATR with no gap tolerance (a candle "
    "that closes through the stop defers the exit, honestly, to the next candle's "
    "open); target = fixed 1.5R. 1% fixed-fractional risk per trade."
)

DEFAULT_ATR_PCT_MAX = 0.04
PLANNED_REWARD_MIN_R = 1.35  # see module docstring: always satisfied given target_r_multiple=1.5


@dataclass(frozen=True)
class RepairBreakoutParameters:
    breakout_lookback: int = 30
    ma20_period: int = 20
    ma200_period: int = 200
    atr_period: int = 14
    atr_stop_multiple: float = 1.0
    target_r_multiple: float = 1.5
    atr_pct_max: float = DEFAULT_ATR_PCT_MAX
    retest_window: int = 10  # candles a pending breakout stays armed before expiring unconfirmed
    max_holding_hours: int = 240  # 10 days at 4H bars -- a backstop, not the primary exit; see docstring below
    initial_equity: float = 10000.0
    risk_per_trade: float = 0.01
    daily_loss_guard_r: float = -3.0
    fee_bps: float = 10.0
    slippage_bps: float = 2.0
    max_notional_pct: float = 1.0


# HOLDING CAP DISCLOSURE: the external spec defines only a stop/target bracket, no
# holding-period rule. max_holding_hours=240 (10 days) is this implementation's own
# addition — a backstop against a trade sitting open indefinitely without ever
# resolving, not something the user specified. Flagged here, not smuggled in.
DEFAULT_PARAMETERS = RepairBreakoutParameters()


@dataclass
class PendingBreakout:
    breakout_level: float
    candles_remaining: int
    confirmed: bool = False


@dataclass
class OpenTrade:
    entry_price: float
    stop_loss: float
    target: float
    quantity: float
    notional: float
    risk_dollars: float
    entry_fee: float
    open_close_time: int
    entry_atr: float
    entry_breakout_level: float
    gap_pending: bool = False


@dataclass
class RepairBreakoutState:
    equity: float
    daily_r: float = 0.0
    daily_guard_day: str | None = None
    open_trade: OpenTrade | None = None
    pending: PendingBreakout | None = None


@dataclass(frozen=True)
class EntryEvaluation:
    passed: bool
    reasons: tuple[str, ...]
    candle_close_time: int
    close: float
    action: str  # "NONE" | "ARMED" | "CONFIRMED" | "ENTER"
    breakout_level: float | None


@dataclass(frozen=True)
class ExitEvent:
    exit_reason: str  # "SL", "SL_GAP", "TARGET", or "TIME"
    exit_price: float
    gross_pnl: float
    fees: float
    net_pnl: float
    r_multiple: float
    holding_hours: float
    equity_after: float
    exit_close_time: int = 0


INDICATOR_COLUMNS_TO_CHECK = ["breakout_high", "ma20", "ma200", "atr", "atr_pct"]


def add_indicators(candles: pd.DataFrame, params: RepairBreakoutParameters = DEFAULT_PARAMETERS) -> pd.DataFrame:
    """Attach breakout_high (shift(1) before the rolling max -- no lookahead, a candle
    never counts toward its own breakout threshold), MA20, MA200, ATR(14), and
    atr_pct (ATR / close) to closed candles."""
    frame = candles.copy().sort_values("close_time").reset_index(drop=True)
    close = frame["close"].astype(float)
    frame["breakout_high"] = frame["high"].shift(1).rolling(params.breakout_lookback).max()
    frame["ma20"] = close.rolling(params.ma20_period).mean()
    frame["ma200"] = close.rolling(params.ma200_period).mean()
    frame["atr"] = atr(frame, params.atr_period)
    frame["atr_pct"] = frame["atr"] / close
    return frame


def _regime_ok(candle: pd.Series, params: RepairBreakoutParameters) -> tuple[bool, list[str]]:
    """MA200/MA20>MA200/ATR-cap filter, shared by both the breakout-arming check and
    the later entry-candle re-check (external testing's own conservatism: re-verify
    the regime hasn't flipped during the up-to-10-candle gap to confirmation)."""
    reasons: list[str] = []
    close = float(candle["close"])
    ma200 = float(candle["ma200"])
    ma20 = float(candle["ma20"])
    atr_pct = float(candle["atr_pct"])
    if close <= ma200:
        reasons.append("CLOSE_NOT_ABOVE_MA200")
    if ma20 <= ma200:
        reasons.append("MA20_NOT_ABOVE_MA200")
    if atr_pct > params.atr_pct_max:
        reasons.append("ATR_PCT_TOO_HIGH")
    return not reasons, reasons


def _planned_reward_r(params: RepairBreakoutParameters) -> float:
    """Always equal to target_r_multiple -- see module docstring's Rule 6 disclosure."""
    return params.target_r_multiple


def evaluate_entry(
    candle: pd.Series,
    state: RepairBreakoutState,
    params: RepairBreakoutParameters = DEFAULT_PARAMETERS,
) -> EntryEvaluation:
    """Advances the pending-breakout state machine by exactly one candle and reports
    what happened. Mutates `state.pending` (arm / confirm / expire) but never
    `state.open_trade` — the caller is responsible for calling `size_entry` only when
    `passed` is True (action == "ENTER"), matching every other strategy's own
    evaluate_entry/size_entry split in this codebase."""
    reasons: list[str] = []
    close_time = int(candle["close_time"])
    close = float(candle["close"])

    if state.open_trade is not None:
        reasons.append("OPEN_TRADE_EXISTS")
    if state.daily_r <= params.daily_loss_guard_r:
        reasons.append("DAILY_LOSS_GUARD")
    if reasons:
        return EntryEvaluation(False, tuple(reasons), close_time, close, "NONE", None)

    if any(pd.isna(candle.get(c)) for c in INDICATOR_COLUMNS_TO_CHECK):
        return EntryEvaluation(False, ("INDICATORS_NOT_AVAILABLE",), close_time, close, "NONE", None)

    pending = state.pending

    # 1) A pending setup confirmed on the PREVIOUS candle -- this is "the candle after
    # confirmation": re-check the regime (external testing's conservative re-verify)
    # and enter now if it still holds; the pending setup is consumed either way.
    if pending is not None and pending.confirmed:
        state.pending = None
        regime_ok, regime_reasons = _regime_ok(candle, params)
        if not regime_ok:
            return EntryEvaluation(False, tuple(["REGIME_FLIPPED_SINCE_CONFIRMATION", *regime_reasons]), close_time, close, "NONE", None)
        return EntryEvaluation(True, (), close_time, close, "ENTER", pending.breakout_level)

    # 2) A pending setup is still awaiting retest confirmation.
    if pending is not None:
        low = float(candle["low"])
        if low <= pending.breakout_level and close > pending.breakout_level:
            pending.confirmed = True
            return EntryEvaluation(False, ("RETEST_CONFIRMED_ENTER_NEXT_CANDLE",), close_time, close, "CONFIRMED", pending.breakout_level)
        pending.candles_remaining -= 1
        if pending.candles_remaining <= 0:
            state.pending = None
            return EntryEvaluation(False, ("PENDING_BREAKOUT_EXPIRED",), close_time, close, "NONE", None)
        return EntryEvaluation(False, ("AWAITING_RETEST",), close_time, close, "NONE", pending.breakout_level)

    # 3) No pending setup -- check for a brand-new breakout.
    breakout_high = float(candle["breakout_high"])
    if close <= breakout_high:
        return EntryEvaluation(False, ("NO_BREAKOUT",), close_time, close, "NONE", None)
    regime_ok, regime_reasons = _regime_ok(candle, params)
    if not regime_ok:
        return EntryEvaluation(False, tuple(regime_reasons), close_time, close, "NONE", None)

    state.pending = PendingBreakout(breakout_level=breakout_high, candles_remaining=params.retest_window)
    return EntryEvaluation(False, ("BREAKOUT_ARMED_AWAITING_RETEST",), close_time, close, "ARMED", breakout_high)


def size_entry(
    candle: pd.Series,
    state: RepairBreakoutState,
    params: RepairBreakoutParameters = DEFAULT_PARAMETERS,
    breakout_level: float = 0.0,
) -> OpenTrade | None:
    """Fixed-fractional sizing against a 1.0x-ATR stop distance; target = fixed 1.5R
    (target_r_multiple x that distance). Only call after `evaluate_entry` has returned
    action == "ENTER"."""
    raw_entry = float(candle["close"])
    entry_price = apply_slippage(raw_entry, params.slippage_bps, "buy")
    atr_value = float(candle["atr"])
    stop_loss = entry_price - params.atr_stop_multiple * atr_value
    risk_per_unit = entry_price - stop_loss
    if risk_per_unit <= 0:
        return None

    target = entry_price + _planned_reward_r(params) * risk_per_unit

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
        entry_price=entry_price, stop_loss=stop_loss, target=target, quantity=quantity,
        notional=notional, risk_dollars=risk_dollars, entry_fee=fees,
        open_close_time=int(candle["close_time"]), entry_atr=atr_value, entry_breakout_level=breakout_level,
    )


def evaluate_exit(
    candle: pd.Series,
    state: RepairBreakoutState,
    params: RepairBreakoutParameters = DEFAULT_PARAMETERS,
) -> ExitEvent | None:
    """Bracket exit with the no-gap-tolerance stop rule (see module docstring, external
    finding #2). Stop takes priority over target if both are touched in the same
    candle (this codebase's standard conservative tie-break, e.g.
    donchian_breakout_bracket.evaluate_exit)."""
    trade = state.open_trade
    if trade is None:
        return None

    candle_time = int(candle["close_time"])
    hours_held = (candle_time - trade.open_close_time) / 3600000.0
    open_ = float(candle["open"])
    low = float(candle["low"])
    high = float(candle["high"])
    close = float(candle["close"])

    if trade.gap_pending:
        # Previous candle already closed through the stop with no clean same-bar fill
        # available -- realize the exit now, honestly, at the first tradeable price
        # (this candle's open), whatever it turns out to be.
        exit_reason, raw_exit = "SL_GAP", open_
    elif low <= trade.stop_loss:
        if close <= trade.stop_loss:
            # The whole candle broke through and stayed through -- a genuine gap-style
            # break, not a same-bar wick reclaim. A fill at stop_loss here would be
            # fictional (no guarantee of an actual fill at that exact price during a
            # break this size) -- defer the honest fill to the next candle's open.
            trade.gap_pending = True
            return None
        exit_reason, raw_exit = "SL", trade.stop_loss
    elif high >= trade.target:
        exit_reason, raw_exit = "TARGET", trade.target
    elif hours_held >= params.max_holding_hours:
        exit_reason, raw_exit = "TIME", close
    else:
        return None

    exit_price = apply_slippage(raw_exit, params.slippage_bps, "sell")
    gross_pnl = (exit_price - trade.entry_price) * trade.quantity
    exit_fee = exit_price * trade.quantity * params.fee_bps / 10000.0
    total_fees = trade.entry_fee + exit_fee
    net_pnl = gross_pnl - total_fees
    risk_dollars = max(trade.risk_dollars, 1e-9)
    r_multiple = net_pnl / risk_dollars
    equity_after = state.equity + net_pnl

    state.equity = equity_after
    state.daily_r += r_multiple
    state.open_trade = None

    return ExitEvent(
        exit_reason=exit_reason, exit_price=exit_price, gross_pnl=gross_pnl, fees=total_fees,
        net_pnl=net_pnl, r_multiple=r_multiple, holding_hours=hours_held, equity_after=equity_after,
        exit_close_time=candle_time,
    )


def run_repair_breakout_backtest(
    candles: pd.DataFrame,
    params: RepairBreakoutParameters = DEFAULT_PARAMETERS,
) -> tuple[list[ExitEvent], RepairBreakoutState]:
    """Candle-by-candle simulation, same shape/contract as every other strategy's own
    run_*_backtest in this codebase (e.g. donchian_breakout_bracket.
    run_donchian_bracket_backtest)."""
    state = RepairBreakoutState(equity=params.initial_equity)
    enriched = add_indicators(candles, params)
    evaluable = enriched.dropna(subset=INDICATOR_COLUMNS_TO_CHECK).reset_index(drop=True)
    closed_trades: list[ExitEvent] = []

    for i in range(len(evaluable)):
        candle = evaluable.iloc[i]
        day = pd.Timestamp(candle["date"]).date().isoformat()
        if state.daily_guard_day != day:
            state.daily_guard_day = day
            state.daily_r = 0.0

        exit_event = evaluate_exit(candle, state, params)
        if exit_event is not None:
            closed_trades.append(exit_event)

        evaluation = evaluate_entry(candle, state, params)
        if evaluation.passed:
            trade = size_entry(candle, state, params, breakout_level=evaluation.breakout_level or 0.0)
            if trade is not None:
                state.open_trade = trade

    return closed_trades, state


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register REPAIR_BREAKOUT_QUALITY's first version. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry — parameters
    are immutable once registered; a change requires a new version string."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
