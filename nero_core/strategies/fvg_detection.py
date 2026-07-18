"""Fair Value Gap (FVG) detection and lifecycle tracking — a shared, stateful,
sequential pass over closed candles, used by both FVG_REVERSION
(nero_core.strategies.fvg_reversion) and the FVG-filtered TREND_PULLBACK variant
(nero_core.strategies.trend_pullback_fvg_filtered).

GAP DEFINITION:
- Bullish FVG forms AT candle i when low[i] > high[i-2]. Zone = [high[i-2], low[i]]
  (zone_bottom = high[i-2], zone_top = low[i]).
- Bearish FVG forms AT candle i when high[i] < low[i-2]. Zone = [high[i], low[i-2]]
  (zone_bottom = high[i], zone_top = low[i-2]).
A gap formed at candle i is only appended to the open-gaps list AFTER that candle's
touch-check has already run (see the loop below) — so the earliest any candle can be
touched by a gap is the candle AFTER it formed. This is "tradeable only after candle i
CLOSES": no candle can ever react to a gap that (from its own perspective) hasn't
finished forming yet.

GAP LIFECYCLE:
1. OPEN until fully filled: a bullish gap dies the first candle whose LOW <= zone_bottom
   (price has retraced all the way through it); a bearish gap dies the first candle
   whose HIGH >= zone_top.
2. Partial fills shrink the untested zone: for a bullish gap, `remaining_top` starts at
   zone_top and ratchets DOWN to track the lowest low seen (while still > zone_bottom)
   among candles that dipped into it without fully filling it — the untested region is
   always [zone_bottom, remaining_top]. Mirrored for bearish (`remaining_bottom`
   ratchets UP toward zone_top, untested region [remaining_bottom, zone_top]).
3. EXPIRY: a gap still open FVG_EXPIRY_CANDLES (100) candles after its OWN formation
   index is retired — it produces no further signals and is dropped from tracking.
4. At most FVG_MAX_OPEN_PER_DIRECTION (5) open gaps are tracked per direction; when a
   new gap forms and the cap is already reached, the OLDEST tracked gap (by formation
   index) is evicted first.

TOUCH / SIGNAL: on each candle, an open gap's zone is checked for a "touch" using the
zone as it stood BEFORE this candle's own update, so a candle's own contribution to
filling the zone can't retroactively exempt it from having triggered a signal. A
bullish gap is touched when this candle's LOW falls in (zone_bottom, remaining_top]; a
bearish gap is touched when this candle's HIGH falls in [remaining_bottom, zone_top).

ONE SIGNAL PER GAP, EVER: the first candle that touches a gap consumes its one shot —
`signal_used` is set on that candle regardless of whether some OTHER filter (e.g. a
trend filter applied by the caller) turns it into an actual entry. A later re-touch of
the same (now smaller) zone can never fire another signal for that gap. This is this
module's specific reading of "first touch only" — the touch OPPORTUNITY is what's
spent, not "the first touch that also happens to pass some other filter" — deliberately
conservative, and documented here since the spec doesn't pin down what happens when a
first touch fails a caller-side filter.

If a candle could touch more than one still-open, not-yet-signaled gap of the same
direction at once (rare — requires overlapping remaining zones from different
formations), the OLDEST (earliest-formed) gap wins the touch and consumes its signal;
later-formed overlapping gaps are left untouched for that candle.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

FVG_EXPIRY_CANDLES = 100
FVG_MAX_OPEN_PER_DIRECTION = 5


@dataclass
class _Gap:
    direction: str  # "bullish" | "bearish"
    formed_at_index: int
    zone_bottom: float
    zone_top: float
    remaining_bottom: float
    remaining_top: float
    signal_used: bool = False
    dead: bool = False


@dataclass(frozen=True)
class FvgTouchSignal:
    direction: str
    zone_bottom: float
    zone_top: float
    remaining_bottom: float
    remaining_top: float
    formed_at_index: int


@dataclass(frozen=True)
class FvgCandleState:
    bullish_signal: FvgTouchSignal | None
    bearish_signal: FvgTouchSignal | None
    # (zone_bottom, remaining_top) per open bullish gap, (remaining_bottom, zone_top)
    # per open bearish gap, both AS OF AFTER this candle's own updates.
    open_bullish_gaps: tuple[tuple[float, float], ...]
    open_bearish_gaps: tuple[tuple[float, float], ...]


def _new_gap(direction: str, index: int, zone_bottom: float, zone_top: float) -> _Gap:
    return _Gap(
        direction=direction,
        formed_at_index=index,
        zone_bottom=zone_bottom,
        zone_top=zone_top,
        remaining_bottom=zone_bottom,
        remaining_top=zone_top,
    )


def compute_fvg_states(candles: pd.DataFrame) -> list[FvgCandleState]:
    """Sequential pass over closed candles (must already be sorted ascending by
    close_time). Returns one FvgCandleState per candle, in the same order."""
    frame = candles.reset_index(drop=True)
    highs = frame["high"].astype(float).to_numpy()
    lows = frame["low"].astype(float).to_numpy()
    n = len(frame)

    open_bullish: list[_Gap] = []
    open_bearish: list[_Gap] = []
    results: list[FvgCandleState] = []

    for i in range(n):
        low_i = lows[i]
        high_i = highs[i]

        bullish_signal: FvgTouchSignal | None = None
        for gap in open_bullish:
            if gap.dead or gap.signal_used:
                continue
            if gap.zone_bottom < low_i <= gap.remaining_top:
                bullish_signal = FvgTouchSignal(
                    "bullish", gap.zone_bottom, gap.zone_top, gap.remaining_bottom, gap.remaining_top, gap.formed_at_index
                )
                gap.signal_used = True
                break

        bearish_signal: FvgTouchSignal | None = None
        for gap in open_bearish:
            if gap.dead or gap.signal_used:
                continue
            if gap.remaining_bottom <= high_i < gap.zone_top:
                bearish_signal = FvgTouchSignal(
                    "bearish", gap.zone_bottom, gap.zone_top, gap.remaining_bottom, gap.remaining_top, gap.formed_at_index
                )
                gap.signal_used = True
                break

        for gap in open_bullish:
            if gap.dead:
                continue
            if low_i <= gap.zone_bottom:
                gap.dead = True
                continue
            if low_i < gap.remaining_top:
                gap.remaining_top = low_i
            if i - gap.formed_at_index >= FVG_EXPIRY_CANDLES:
                gap.dead = True

        for gap in open_bearish:
            if gap.dead:
                continue
            if high_i >= gap.zone_top:
                gap.dead = True
                continue
            if high_i > gap.remaining_bottom:
                gap.remaining_bottom = high_i
            if i - gap.formed_at_index >= FVG_EXPIRY_CANDLES:
                gap.dead = True

        open_bullish = [g for g in open_bullish if not g.dead]
        open_bearish = [g for g in open_bearish if not g.dead]

        if i >= 2:
            if low_i > highs[i - 2]:
                open_bullish.append(_new_gap("bullish", i, zone_bottom=highs[i - 2], zone_top=low_i))
                if len(open_bullish) > FVG_MAX_OPEN_PER_DIRECTION:
                    open_bullish.sort(key=lambda g: g.formed_at_index)
                    open_bullish.pop(0)
            if high_i < lows[i - 2]:
                open_bearish.append(_new_gap("bearish", i, zone_bottom=high_i, zone_top=lows[i - 2]))
                if len(open_bearish) > FVG_MAX_OPEN_PER_DIRECTION:
                    open_bearish.sort(key=lambda g: g.formed_at_index)
                    open_bearish.pop(0)

        results.append(
            FvgCandleState(
                bullish_signal=bullish_signal,
                bearish_signal=bearish_signal,
                open_bullish_gaps=tuple((g.zone_bottom, g.remaining_top) for g in open_bullish),
                open_bearish_gaps=tuple((g.remaining_bottom, g.zone_top) for g in open_bearish),
            )
        )

    return results


def attach_fvg_columns(candles: pd.DataFrame) -> pd.DataFrame:
    """Attaches, per candle: fvg_bullish_signal_zone_bottom / _remaining_top (NaN if no
    bullish touch signal this candle), fvg_bearish_signal_zone_top / _remaining_bottom
    (NaN if no bearish touch signal this candle), and fvg_open_bullish_gaps /
    fvg_open_bearish_gaps — object columns holding a tuple of (bottom, top) pairs for
    every gap open AFTER this candle, for callers that need to check zone overlap
    (e.g. the FVG-filtered TREND_PULLBACK variant) rather than react to a fresh touch."""
    frame = candles.copy().sort_values("close_time").reset_index(drop=True)
    states = compute_fvg_states(frame)

    frame["fvg_bullish_signal_zone_bottom"] = [s.bullish_signal.zone_bottom if s.bullish_signal else float("nan") for s in states]
    frame["fvg_bullish_signal_remaining_top"] = [s.bullish_signal.remaining_top if s.bullish_signal else float("nan") for s in states]
    frame["fvg_bearish_signal_zone_top"] = [s.bearish_signal.zone_top if s.bearish_signal else float("nan") for s in states]
    frame["fvg_bearish_signal_remaining_bottom"] = [
        s.bearish_signal.remaining_bottom if s.bearish_signal else float("nan") for s in states
    ]
    frame["fvg_open_bullish_gaps"] = [s.open_bullish_gaps for s in states]
    frame["fvg_open_bearish_gaps"] = [s.open_bearish_gaps for s in states]
    return frame


def any_bullish_gap_overlaps_range(open_bullish_gaps: tuple[tuple[float, float], ...], range_low: float, range_high: float) -> bool:
    """True if any (zone_bottom, remaining_top) pair overlaps [range_low, range_high] —
    standard interval overlap: gap_bottom <= range_high AND gap_top >= range_low."""
    return any(bottom <= range_high and top >= range_low for bottom, top in open_bullish_gaps)
