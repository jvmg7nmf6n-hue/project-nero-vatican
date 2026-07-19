"""Volatility-clustering position-sizing hypothesis (H2) — a distinct, OPPOSITE-direction
counterpart to nero_core.strategies.regime_risk's H3 hypothesis. H3 shrinks risk when
current ATR% is above its trailing median (defensive: less size in choppier regimes).
H2 instead tests whether a recent SPIKE in realized volatility relative to its own
older reference window ("clustering" — vol begets vol, a well-documented empirical
regularity) should INCREASE position size, on the thesis that clustered volatility
often precedes a real directional move worth sizing up into. Neither is assumed
correct — both are testable, self-labeled hypotheses; see tools/vol_clustering_harness.py
for the backtest integration and docs/vol_clustering_*.md for empirical results.
"""
from __future__ import annotations

import pandas as pd

# The fixed "recent" window this module compares against its own older reference.
RECENT_WINDOW = 20

# ratio <= 1.0 (recent realized vol at or below the older reference average) -> score 0.0
# ("calm/normal" floor). ratio >= 2.0 (recent vol at or above double the older reference
# average) -> score 1.0 ("strongly clustered" ceiling). Linear in between. 2.0x is an
# explicit, documented choice for "what counts as maximal clustering" — not derived from
# data, but bounded and monotonic so it never produces a nonsensical score.
CLUSTER_RATIO_FLOOR = 1.0
CLUSTER_RATIO_CEILING = 2.0

# position_multiplier's own linear mapping: score 0.0 -> 1.0x (baseline, unchanged
# sizing), score 1.0 -> 2.0x (double risk in a strongly clustered regime). The same unit
# slope (1.0 multiplier-unit per 1.0 score-unit) is honored below 0.0 too, down to a
# 0.5x floor at score -0.5 — volatility_cluster_score itself never produces a value below
# 0.0 (it floors there by design), but position_multiplier is written as a general
# monotonic mapping, not hardcoded to [0,1] input, so a caller with a genuinely
# below-baseline-volatility score (a different score definition) still gets a sensibly
# reduced multiplier instead of an out-of-domain value.
MULTIPLIER_AT_SCORE_ZERO = 1.0
MULTIPLIER_AT_SCORE_ONE = 2.0
MULTIPLIER_FLOOR = 0.5
MULTIPLIER_CEILING = 2.0


def volatility_cluster_score(closes: pd.Series, lookback: int = 100) -> float:
    """Ratio of recent (last RECENT_WINDOW=20 bars) mean absolute bar-to-bar % return to
    the OLDER portion of the trailing `lookback` window's own mean absolute % return
    (bars [-lookback : -RECENT_WINDOW], i.e. excluding the recent window itself so the
    two halves are independent), mapped through a bounded linear scale into [0.0, 1.0].

    0.0 = recent realized volatility at or below the older reference average
    (calm/normal — no clustering detected).
    1.0 = recent realized volatility at or above double the older reference average
    (strongly clustered/elevated).

    Deterministic and lookahead-free: callers must pass only closes already known as of
    the decision candle (see tools/vol_clustering_harness.py for the as-of slicing used
    in a real backtest loop). Returns 0.0 (never fabricates a signal) if fewer than
    `lookback` closes are available, or if the older window's reference volatility is
    zero/unusable.
    """
    if lookback <= RECENT_WINDOW:
        raise ValueError(f"lookback ({lookback}) must exceed RECENT_WINDOW ({RECENT_WINDOW})")
    if len(closes) < lookback:
        return 0.0

    window = closes.iloc[-lookback:].reset_index(drop=True)
    pct_changes = window.pct_change().abs()

    older = pct_changes.iloc[: lookback - RECENT_WINDOW].dropna()
    recent = pct_changes.iloc[lookback - RECENT_WINDOW :].dropna()
    if older.empty or recent.empty:
        return 0.0

    older_vol = older.mean()
    recent_vol = recent.mean()
    if pd.isna(older_vol) or pd.isna(recent_vol) or older_vol <= 0:
        return 0.0

    ratio = recent_vol / older_vol
    score = (ratio - CLUSTER_RATIO_FLOOR) / (CLUSTER_RATIO_CEILING - CLUSTER_RATIO_FLOOR)
    return float(min(max(score, 0.0), 1.0))


def position_multiplier(cluster_score: float) -> float:
    """Monotonic linear mapping from a volatility_cluster_score-shaped input to a
    position-sizing multiplier — see the module-level constants above for the exact
    anchor points and floor/ceiling. Always returns a value in [MULTIPLIER_FLOOR,
    MULTIPLIER_CEILING] regardless of input, by clamping."""
    slope = MULTIPLIER_AT_SCORE_ONE - MULTIPLIER_AT_SCORE_ZERO
    raw = MULTIPLIER_AT_SCORE_ZERO + slope * cluster_score
    return float(min(max(raw, MULTIPLIER_FLOOR), MULTIPLIER_CEILING))
