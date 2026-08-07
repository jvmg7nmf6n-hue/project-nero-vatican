"""CC-1 master directive (2026-08-07), Part B Rung 1: `agreement` must no
longer treat two agents driven by correlated real macro fields as
independent confirmations. See bellwether/agents/_synthesis.py's own
_REAL_FIELD_CORRELATION/_AGENT_REAL_FIELDS/_discounted_agreement_numerator
for the mechanism, and docs/bellwether_stage2_report.md's Rung 1 section for
the real correlation matrix (n=1229 real overlapping days) this is built
from.
"""
from __future__ import annotations

from bellwether.agents._synthesis import _agent_pair_correlation, aggregate
from bellwether.schemas import Asset, Bias, Signal


def test_perfectly_correlated_agreeing_signals_do_not_match_independent_ones():
    """B1e: the exact required regression. Two signals of identical
    individual strength/bias from DIFFERENT real-field-driven agents whose
    underlying fields are IDENTICAL (correlation 1.0 by construction, via
    _agent_pair_correlation's same-field branch) must produce LOWER
    agreement than two signals of the same strength/bias from agents with
    NO measured correlation (0.0)."""
    correlated_signals = [
        Signal(asset=Asset.GOLD, bias=Bias.BULLISH, strength=0.8, source_agent="liquidity"),
        Signal(asset=Asset.GOLD, bias=Bias.BULLISH, strength=0.8, source_agent="liquidity_twin"),
    ]
    # liquidity_twin isn't a real agent name -- monkeypatch-free: reuse the
    # same field set as "liquidity" itself so _agent_pair_correlation's
    # same-field branch (rho=1.0) fires deterministically without touching
    # the module's real _AGENT_REAL_FIELDS table.
    import bellwether.agents._synthesis as synthesis_mod
    original_map = dict(synthesis_mod._AGENT_REAL_FIELDS)
    synthesis_mod._AGENT_REAL_FIELDS["liquidity_twin"] = ("vix",)
    try:
        correlated_read = aggregate(Asset.GOLD, correlated_signals)
    finally:
        synthesis_mod._AGENT_REAL_FIELDS.clear()
        synthesis_mod._AGENT_REAL_FIELDS.update(original_map)

    independent_signals = [
        Signal(asset=Asset.GOLD, bias=Bias.BULLISH, strength=0.8, source_agent="unrelated_a"),
        Signal(asset=Asset.GOLD, bias=Bias.BULLISH, strength=0.8, source_agent="unrelated_b"),
    ]
    independent_read = aggregate(Asset.GOLD, independent_signals)

    assert correlated_read.agreement < independent_read.agreement
    # Coverage must be UNTOUCHED by the discount -- both cases have the
    # identical raw total strength (0.8 + 0.8), so coverage must match
    # exactly regardless of correlation.
    assert correlated_read.coverage == independent_read.coverage
    # net_score/bias must also be UNTOUCHED (this directive's scope is
    # `agreement` only) -- both cases are 2 identical-strength BULLISH
    # signals, so the undiscounted net/bias must be identical too.
    assert correlated_read.net_score == independent_read.net_score
    assert correlated_read.bias == independent_read.bias


def test_a_lone_signal_is_never_discounted():
    """No prior signal exists to be correlated against -- agreement must
    equal the original undiscounted formula exactly for a single signal,
    regardless of which agent it's from."""
    signals = [Signal(asset=Asset.GOLD, bias=Bias.STRONG_BULLISH, strength=1.0, source_agent="monetary_policy")]
    read = aggregate(Asset.GOLD, signals)
    assert read.agreement == round(abs(read.net_score) / 2.0, 3)


def test_real_agent_pair_with_measured_correlation_is_discounted():
    """monetary_policy (real_yield_10y, dxy) and liquidity (vix) are REAL
    agent names with a real measured correlation
    (max(|corr(real_yield,vix)|, |corr(dxy,vix)|) = 0.3444, per
    docs/bellwether_stage2_report.md's Rung 1 matrix) -- not the synthetic
    same-field case above. Confirms the discount fires for the actual
    production agent names this directive's own table covers."""
    assert _agent_pair_correlation("monetary_policy", "liquidity") > 0.0

    correlated_signals = [
        Signal(asset=Asset.GOLD, bias=Bias.BULLISH, strength=0.8, source_agent="monetary_policy"),
        Signal(asset=Asset.GOLD, bias=Bias.BULLISH, strength=0.8, source_agent="liquidity"),
    ]
    correlated_read = aggregate(Asset.GOLD, correlated_signals)

    independent_signals = [
        Signal(asset=Asset.GOLD, bias=Bias.BULLISH, strength=0.8, source_agent="monetary_policy"),
        Signal(asset=Asset.GOLD, bias=Bias.BULLISH, strength=0.8, source_agent="derivatives_etf"),
    ]
    # monetary_policy vs derivatives_etf: max(|corr(real_yield,funding)|,
    # |corr(dxy,funding)|) = max(0.1551, 0.0883) = 0.1551 -- real, but
    # smaller than monetary_policy/liquidity's 0.3444, so this is a WEAKER
    # discount, not a zero one; still expected to show less discount than
    # the liquidity pairing above.
    weaker_pair_read = aggregate(Asset.GOLD, independent_signals)

    assert correlated_read.agreement < weaker_pair_read.agreement


def test_disagreement_between_correlated_agents_is_not_discounted():
    """A signal that DISAGREES with a correlated peer is genuinely more
    informative (the usual relationship broke down this cycle), not
    redundant -- must be counted at full weight, same as if the two agents
    were completely independent."""
    disagreeing_signals = [
        Signal(asset=Asset.GOLD, bias=Bias.BULLISH, strength=0.8, source_agent="monetary_policy"),
        Signal(asset=Asset.GOLD, bias=Bias.BEARISH, strength=0.8, source_agent="liquidity"),
    ]
    read = aggregate(Asset.GOLD, disagreeing_signals)
    # With no discount applied to either signal, this must match the
    # ORIGINAL (pre-directive) formula exactly: agreement = |net_score|/2.
    assert read.agreement == round(abs(read.net_score) / 2.0, 3)


def test_agents_outside_the_real_field_map_are_never_discounted_against_each_other():
    """Two signals from agents with no entry in _AGENT_REAL_FIELDS (e.g.
    mock-only or not-yet-wired agents) have no measured correlation to
    discount by -- must behave exactly like the pre-directive formula,
    matching the existing test_vatican_aggregation.py assertions this
    directive must not break."""
    signals = [
        Signal(asset=Asset.GOLD, bias=Bias.BULLISH, strength=1.0, source_agent="a"),
        Signal(asset=Asset.GOLD, bias=Bias.BULLISH, strength=1.0, source_agent="b"),
    ]
    read = aggregate(Asset.GOLD, signals)
    assert read.agreement == round(abs(read.net_score) / 2.0, 3)


def test_agent_pair_correlation_is_symmetric_and_bounded():
    for agent_a, agent_b in [("monetary_policy", "liquidity"), ("monetary_policy", "derivatives_etf"), ("liquidity", "derivatives_etf")]:
        rho_ab = _agent_pair_correlation(agent_a, agent_b)
        rho_ba = _agent_pair_correlation(agent_b, agent_a)
        assert rho_ab == rho_ba
        assert 0.0 <= rho_ab <= 1.0


def test_unknown_agent_has_zero_correlation_with_anything():
    assert _agent_pair_correlation("monetary_policy", "some_future_agent") == 0.0
    assert _agent_pair_correlation("some_future_agent", "another_future_agent") == 0.0
