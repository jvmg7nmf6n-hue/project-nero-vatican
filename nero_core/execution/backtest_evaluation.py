"""Human-editable structured backtest-evaluation lookup for the public site
export (nero_core.execution.export_site_data). Mirrors
nero_core.execution.verification_status's structure and key discipline
exactly: keyed by (strategy_id, strategy_version, asset), never
(strategy_id, asset) alone.

WHY THIS EXISTS (added after a real gap was found -- see
docs/investigations/live_strategy_backtest_and_universe_expansion_report.md):
verification_status.py's free-text status strings already SAY things like
"LOW SAMPLE, CI crosses zero" in prose, but the site never showed the
underlying structured numbers (verdict_is, verdict_oos, trade counts,
when it was evaluated, what data it ran against) -- a strategy could look
identically "watchlist" on the card whether it had never been tested or
had DIED in-sample on a real multi-year backtest. This is the same failure
class as the 401 dashboard gap fixed earlier this session: a display that
asserts (by omission) something more favorable than the truth.

A config with no entry here renders DEFAULT_BACKTEST_EVALUATION on the
site -- an honest "not yet evaluated with this structured format" rather
than either a blank card (silently implies nothing is known) or a
fabricated verdict inferred from the free-text verification_status string
(which was never computed with a consistent, comparable methodology across
every strategy, and inferring structured numbers from prose would just be
a different-shaped version of the same dishonesty this module exists to
fix). Only add a real entry here once an actual backtest was run and its
numbers are known -- never guess.

UNTESTABLE IS NOT THE SAME CLAIM AS "NO EVIDENCE EXISTS" -- see
COINTEGRATION_PAIRS below: it cannot run through the single-asset
rule_dsl/auto_tester harness (confirmed structurally, not just historically
true), but it DOES have real, dedicated backtest evidence from its own
`run_pairs_backtest` engine. `untestable_reason` is populated ONLY to
explain the harness incompatibility -- verdict_is/verdict_oos being None
for that entry reflects that classify_verdict's own SURVIVED/DIED/
PROMISING-WATCHLIST vocabulary was never applied (no bootstrap CI was
computed with this module), NOT that no evaluation happened at all; read
`is_trades`/`oos_trades`/`is_expectancy_r`/`oos_expectancy_r` together with
`method` for what was actually measured.
"""
from __future__ import annotations

BACKTEST_EVALUATIONS: dict[tuple[str, str, str], dict[str, object]] = {
    # BTC/24h evaluation-universe backtest (this session) -- see
    # docs/investigations/live_strategy_backtest_and_universe_expansion_report.md
    # and tests/test_btc_24h_evaluation_backtest.py for the reproducible,
    # deterministic numbers below. verdict_is/verdict_oos mirror
    # nero_core.eve.scoring._map_half_verdict's own self-compared-half
    # derivation, applied for methodological consistency with the rest of
    # this project's own convention.
    ("RANGE_MEAN_REVERSION", "range-mean-reversion-v1.1.0-long-only", "BTC"): {
        "verdict_is": "DIED",
        "verdict_oos": "INSUFFICIENT_SAMPLE",
        "is_trades": 10,
        "oos_trades": 5,
        "is_expectancy_r": -0.280,
        "oos_expectancy_r": 0.744,
        "evaluated_at": "2026-08-02",
        "data_source": "docs/research_data/evaluation_candles/BTC_24h.json — 1800 daily candles, 2021-08-29 to 2026-08-02, Binance",
        "method": (
            "split_chronological + bootstrap_mean_r_ci + classify_verdict (the same statistical "
            "harness Adam/Eve hypotheses use), applied to this strategy's own real entry/exit/sizing "
            "logic via tools.backtest_compare.run_backtest"
        ),
        "untestable_reason": None,
        "note": None,
    },
    ("RANGE_MEAN_REVERSION", "range-mean-reversion-v1.3.0-confirmation", "BTC"): {
        "verdict_is": "DIED",
        "verdict_oos": "INSUFFICIENT_SAMPLE",
        "is_trades": 9,
        "oos_trades": 7,
        "is_expectancy_r": -0.101,
        "oos_expectancy_r": 0.433,
        "evaluated_at": "2026-08-02",
        "data_source": "docs/research_data/evaluation_candles/BTC_24h.json — 1800 daily candles, 2021-08-29 to 2026-08-02, Binance",
        "method": (
            "split_chronological + bootstrap_mean_r_ci + classify_verdict (the same statistical "
            "harness Adam/Eve hypotheses use), applied to this strategy's own real entry/exit/sizing "
            "logic via tools.backtest_compare.run_backtest"
        ),
        "untestable_reason": None,
        "note": None,
    },
    # COINTEGRATION_PAIRS -- see this module's own docstring on why
    # "untestable" here means "not compatible with the single-asset
    # rule_dsl/auto_tester harness," not "never backtested." Real evidence
    # from its own dedicated engine, both halves positive and PASS across
    # all 4 grid-shift offsets (docs/grid_shift_robustness_followup.md).
    ("COINTEGRATION_PAIRS", "cointegration-pairs-v1.0.0", "BTC-ETH"): {
        "verdict_is": None,
        "verdict_oos": None,
        "is_trades": 61,
        "oos_trades": 22,
        "is_expectancy_r": 0.047,
        "oos_expectancy_r": 0.003,
        "evaluated_at": "2026-07-17",
        "data_source": "Binance 12h BTC+ETH, native grid, 6509 aligned candles",
        "method": "run_pairs_backtest (this strategy's own dedicated two-asset engine) + grid-shift robustness audit across 4 offsets, all PASS",
        "untestable_reason": (
            "Not compatible with the single-asset rule_dsl/auto_tester harness Adam/Eve hypotheses "
            "use -- confirmed structurally this session: auto_tester.test_hypothesis takes exactly "
            "one candles DataFrame, and rule_dsl has no two-asset field concept at all. This does NOT "
            "mean no evidence exists -- see is_trades/oos_trades/is_expectancy_r/oos_expectancy_r "
            "above, measured via this strategy's own separate, real backtest engine instead."
        ),
        "note": None,
    },
}

DEFAULT_BACKTEST_EVALUATION: dict[str, object] = {
    "verdict_is": None,
    "verdict_oos": None,
    "is_trades": None,
    "oos_trades": None,
    "is_expectancy_r": None,
    "oos_expectancy_r": None,
    "evaluated_at": None,
    "data_source": None,
    "method": None,
    "untestable_reason": None,
    "note": "Not yet evaluated with this structured format — see the research status and linked source report above for the original backtest description.",
}


def backtest_evaluation_for(strategy_id: str, strategy_version: str, asset: str) -> dict[str, object]:
    """Looks up the maintained structured evaluation for (strategy_id,
    strategy_version, asset). Falls back to DEFAULT_BACKTEST_EVALUATION --
    never raises, never fabricates a specific-sounding verdict for a
    config nobody has actually run through a real backtest here yet."""
    return BACKTEST_EVALUATIONS.get((strategy_id, strategy_version, asset), DEFAULT_BACKTEST_EVALUATION)
