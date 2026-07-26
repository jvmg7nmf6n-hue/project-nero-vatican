"""Human-editable "which docs/*.md report backtested this?" lookup for the public
site export (nero_core.execution.export_site_data). Mirrors
nero_core.execution.verification_status's structure and key discipline exactly:
keyed by (strategy_id, strategy_version, asset), never (strategy_id, asset) alone,
since RANGE_MEAN_REVERSION wires two different registered versions against the same
asset (BTC).

A config with no entry here (or one explicitly mapped to None, e.g. NEWS_SENTIMENT
and ORDERFLOW_IMBALANCE, which have no historical backtest at all) renders its
"Backtest evidence" section as "no backtest report available" on the site rather
than a broken or fabricated link.
"""
from __future__ import annotations

from nero_core.strategies.pead import TICKERS as _PEAD_TICKERS

SOURCE_REPORTS: dict[tuple[str, str, str], str] = {
    ("BREAKOUT_MOMENTUM", "breakout-momentum-v1.2.0-gold-calibrated-1week", "GOLD"): "docs/statistical_harness_upgrade.md",
    ("TREND_PULLBACK", "trend-pullback-v1.0.0", "BNB"): "docs/statistical_harness_upgrade.md",
    ("COINTEGRATION_PAIRS", "cointegration-pairs-v1.0.0", "BTC-ETH"): "docs/statistical_harness_upgrade.md",
    # NEWS_SENTIMENT is forward-test-only -- no historical backtest exists to link.
    ("NEWS_SENTIMENT", "news-sentiment-v1.0.0", "GOLD"): None,
    ("NEWS_SENTIMENT", "news-sentiment-v1.0.0", "BTC"): None,
    # Asset Expansion Phase A metals sweep.
    ("BREAKOUT_MOMENTUM", "breakout-momentum-v1.6.0-silver-calibrated-24h", "SILVER"): "docs/metals_phase_a_full_sweep.md",
    ("TREND_PULLBACK", "trend-pullback-v1.5.0-silver-calibrated-24h", "SILVER"): "docs/metals_phase_a_full_sweep.md",
    ("VOLATILITY_SQUEEZE", "volatility-squeeze-v1.1.0-ma200-silver-calibrated-24h", "SILVER"): "docs/metals_phase_a_full_sweep.md",
    ("VOLATILITY_SQUEEZE", "volatility-squeeze-v1.1.0-ma150-silver-calibrated-24h", "SILVER"): "docs/metals_phase_a_full_sweep.md",
    ("VOLATILITY_SQUEEZE", "volatility-squeeze-v1.1.0-ma100-silver-calibrated-24h", "SILVER"): "docs/metals_phase_a_full_sweep.md",
    # ORDERFLOW_IMBALANCE (Task C1) -- snapshot-based, no historical replay exists.
    ("ORDERFLOW_IMBALANCE", "orderflow-imbalance-v1.0.0", "BTC"): None,
    ("ORDERFLOW_IMBALANCE", "orderflow-imbalance-v1.0.0", "ETH"): None,
    # RANGE_MEAN_REVERSION -- v1.0.0 from the original 3-tier sweep, the long-only and
    # confirmation variants from the RMR variant research cycle's Stage 1.
    ("RANGE_MEAN_REVERSION", "range-mean-reversion-v1.0.0", "GOLD"): "docs/range_mean_reversion_task2_sweep.md",
    ("RANGE_MEAN_REVERSION", "range-mean-reversion-v1.0.0", "SILVER"): "docs/range_mean_reversion_task2_sweep.md",
    ("RANGE_MEAN_REVERSION", "range-mean-reversion-v1.1.0-long-only", "BTC"): "docs/rmr_variant_research_stage1.md",
    ("RANGE_MEAN_REVERSION", "range-mean-reversion-v1.3.0-confirmation", "BTC"): "docs/rmr_variant_research_stage1.md",
    # Three New Hypothesis Batch.
    ("GOLD_SILVER_RATIO_MR", "gold-silver-ratio-mr-v1.0.0", "GOLD-SILVER"): "docs/gold_silver_ratio_mr_results.md",
    **{
        ("PEAD", version, ticker): "docs/pead_results.md"
        for version in ("pead-v1.0.0-surprise3pct-hold10", "pead-v1.0.0-surprise8pct-hold10")
        for ticker in _PEAD_TICKERS
    },
    # Donchian Cross-Asset Deep-Dive -- the closing report is the authoritative
    # source for these exact 4 configs' promotion decision (see verification_status.py's
    # own comment on the same rows); the underlying sweep numbers live in
    # docs/donchian_task2_full_sweep.md, which the closing report itself cites.
    ("DONCHIAN_TREND", "donchian-trend-v2.0.0-bracket-gold-n20-1week", "GOLD"): "docs/donchian_deep_dive_closing_report.md",
    ("DONCHIAN_TREND", "donchian-trend-v2.0.0-bracket-eurusd-n20-1week", "EUR/USD"): "docs/donchian_deep_dive_closing_report.md",
    ("DONCHIAN_TREND", "donchian-trend-v2.0.0-bracket-gbpusd-n20-1week", "GBP/USD"): "docs/donchian_deep_dive_closing_report.md",
    ("DONCHIAN_TREND", "donchian-trend-v2.0.0-bracket-usdjpy-n40-1week", "USD/JPY"): "docs/donchian_deep_dive_closing_report.md",
}

DEFAULT_SOURCE_REPORT = None


def source_report_for(strategy_id: str, strategy_version: str, asset: str) -> str | None:
    """Looks up the maintained source-report path for (strategy_id, strategy_version,
    asset). Falls back to DEFAULT_SOURCE_REPORT (None) -- never raises, never guesses
    a doc path for a config nobody has actually annotated here yet."""
    return SOURCE_REPORTS.get((strategy_id, strategy_version, asset), DEFAULT_SOURCE_REPORT)
