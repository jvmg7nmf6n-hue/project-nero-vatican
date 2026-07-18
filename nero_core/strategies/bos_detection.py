"""Break of Structure (BOS) pivot detection and one-shot break tracking — a shared,
stateful, sequential pass over closed candles, used by both BOS_CONTINUATION
(nero_core.strategies.bos_continuation) and the BOS-filtered TREND_PULLBACK variant
(nero_core.strategies.trend_pullback_bos_filtered).

PIVOT DEFINITION: candle j is a confirmed swing HIGH if high[j] is strictly greater
than every one of the PIVOT_LOOKAROUND (5) candles immediately before it AND every one
of the 5 candles immediately after it. Mirrored for swing LOWS (low[j] strictly less
than all 10 surrounding candles). A pivot at j is only CONFIRMED once candle j+5 has
been reached — the 5-candles-after half of the window isn't knowable any earlier — so
this module only ever treats a pivot as existing starting the candle at index j+5,
never before. No lookahead: the value itself (high[j]/low[j]) has been visible since
candle j, but the CLASSIFICATION ("this was a swing point") only becomes usable at
j+5.

ACTIVE PIVOT / ONE-SHOT BREAK RULE: only the SINGLE most-recently-confirmed swing high
is ever "active" for BOS-up purposes at any given moment — when a newer swing high
confirms, it immediately supersedes whatever was active before, whether or not the
older one had already broken. A BOS-up fires the first time a candle's CLOSE exceeds
the currently-active, not-yet-broken swing high; that pivot is then marked broken and
can never fire again (one-shot — the spec's own words: "mark it broken after the first
break, no re-firing"). Mirrored independently for swing lows / BOS-down. Pivot
confirmation for candle i (at j = i - 5) is processed BEFORE that same candle's BOS
trigger check, so a pivot confirmed exactly on candle i is already eligible to be
broken by that same candle's own close — the confirmation and any break it enables are
both first legitimately knowable at candle i, so this is not lookahead either way.

STOP CONTEXT: BOS_CONTINUATION's stop needs "the swing low preceding the broken high"
(and mirrored for BOS-down) — this module tracks every confirmed swing high/low (not
just the currently-active one) so that query can be answered: the most recently
CONFIRMED opposite-type pivot whose formation index precedes the broken pivot's own
formation index. None if no such pivot has been confirmed yet (e.g. very early in
history) — callers must treat that as "no valid structural stop," never guess one.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

PIVOT_LOOKAROUND = 5


@dataclass
class _Pivot:
    value: float
    formed_at_index: int
    broken: bool = False


@dataclass(frozen=True)
class BosSignal:
    direction: str  # "up" | "down"
    broken_pivot_value: float
    broken_pivot_formed_index: int
    preceding_extreme_value: float | None
    preceding_extreme_formed_index: int | None


@dataclass(frozen=True)
class BosCandleState:
    bos_up_signal: BosSignal | None
    bos_down_signal: BosSignal | None


def _find_preceding(pivots: list[_Pivot], before_index: int) -> _Pivot | None:
    for pivot in reversed(pivots):
        if pivot.formed_at_index < before_index:
            return pivot
    return None


def compute_bos_states(candles: pd.DataFrame, lookaround: int = PIVOT_LOOKAROUND) -> list[BosCandleState]:
    """Sequential pass over closed candles (must already be sorted ascending by
    close_time). Returns one BosCandleState per candle, in the same order."""
    frame = candles.reset_index(drop=True)
    highs = frame["high"].astype(float).to_numpy()
    lows = frame["low"].astype(float).to_numpy()
    closes = frame["close"].astype(float).to_numpy()
    n = len(frame)

    confirmed_highs: list[_Pivot] = []
    confirmed_lows: list[_Pivot] = []
    active_high: _Pivot | None = None
    active_low: _Pivot | None = None

    results: list[BosCandleState] = []

    for i in range(n):
        j = i - lookaround
        if i >= 2 * lookaround:
            surrounding_high = list(highs[j - lookaround : j]) + list(highs[j + 1 : j + lookaround + 1])
            if highs[j] > max(surrounding_high):
                new_high = _Pivot(value=float(highs[j]), formed_at_index=j)
                confirmed_highs.append(new_high)
                active_high = new_high

            surrounding_low = list(lows[j - lookaround : j]) + list(lows[j + 1 : j + lookaround + 1])
            if lows[j] < min(surrounding_low):
                new_low = _Pivot(value=float(lows[j]), formed_at_index=j)
                confirmed_lows.append(new_low)
                active_low = new_low

        bos_up_signal: BosSignal | None = None
        if active_high is not None and not active_high.broken and closes[i] > active_high.value:
            preceding_low = _find_preceding(confirmed_lows, active_high.formed_at_index)
            bos_up_signal = BosSignal(
                direction="up",
                broken_pivot_value=active_high.value,
                broken_pivot_formed_index=active_high.formed_at_index,
                preceding_extreme_value=preceding_low.value if preceding_low else None,
                preceding_extreme_formed_index=preceding_low.formed_at_index if preceding_low else None,
            )
            active_high.broken = True

        bos_down_signal: BosSignal | None = None
        if active_low is not None and not active_low.broken and closes[i] < active_low.value:
            preceding_high = _find_preceding(confirmed_highs, active_low.formed_at_index)
            bos_down_signal = BosSignal(
                direction="down",
                broken_pivot_value=active_low.value,
                broken_pivot_formed_index=active_low.formed_at_index,
                preceding_extreme_value=preceding_high.value if preceding_high else None,
                preceding_extreme_formed_index=preceding_high.formed_at_index if preceding_high else None,
            )
            active_low.broken = True

        results.append(BosCandleState(bos_up_signal=bos_up_signal, bos_down_signal=bos_down_signal))

    return results


def attach_bos_columns(candles: pd.DataFrame) -> pd.DataFrame:
    """Attaches, per candle: bos_up_signal_pivot_value / _pivot_index /
    _preceding_low_value (NaN if no BOS-up this candle), the bearish mirror
    (bos_down_signal_pivot_value / _pivot_index / _preceding_high_value), and
    bos_up_recent_index / bos_down_recent_index — the candle INDEX of the most recent
    BOS-up/BOS-down signal seen so far (NaN if none yet), for callers (e.g. the
    BOS-filtered TREND_PULLBACK variant) that need "did a BOS happen within the last N
    candles" rather than react to a fresh one."""
    frame = candles.copy().sort_values("close_time").reset_index(drop=True)
    states = compute_bos_states(frame)

    frame["bos_up_signal_pivot_value"] = [s.bos_up_signal.broken_pivot_value if s.bos_up_signal else float("nan") for s in states]
    frame["bos_up_signal_pivot_index"] = [s.bos_up_signal.broken_pivot_formed_index if s.bos_up_signal else float("nan") for s in states]
    frame["bos_up_signal_preceding_low"] = [
        s.bos_up_signal.preceding_extreme_value if s.bos_up_signal and s.bos_up_signal.preceding_extreme_value is not None else float("nan")
        for s in states
    ]
    frame["bos_down_signal_pivot_value"] = [s.bos_down_signal.broken_pivot_value if s.bos_down_signal else float("nan") for s in states]
    frame["bos_down_signal_pivot_index"] = [s.bos_down_signal.broken_pivot_formed_index if s.bos_down_signal else float("nan") for s in states]
    frame["bos_down_signal_preceding_high"] = [
        s.bos_down_signal.preceding_extreme_value if s.bos_down_signal and s.bos_down_signal.preceding_extreme_value is not None else float("nan")
        for s in states
    ]

    last_bos_up_index: float = float("nan")
    last_bos_down_index: float = float("nan")
    bos_up_recent: list[float] = []
    bos_down_recent: list[float] = []
    for i, s in enumerate(states):
        if s.bos_up_signal is not None:
            last_bos_up_index = i
        if s.bos_down_signal is not None:
            last_bos_down_index = i
        bos_up_recent.append(last_bos_up_index)
        bos_down_recent.append(last_bos_down_index)
    frame["bos_up_recent_index"] = bos_up_recent
    frame["bos_down_recent_index"] = bos_down_recent
    return frame
