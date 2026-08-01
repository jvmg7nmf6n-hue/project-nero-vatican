from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nero_core.execution import export_quant_metrics as eqm

FIXED_NOW = datetime(2026, 7, 27, 0, 0, 0, tzinfo=timezone.utc)


def _write_candle_file(directory: Path, filename: str, asset: str, timeframe: str, closes: list[float]) -> None:
    payload = {
        "schema_version": 1,
        "asset": asset,
        "timeframe": timeframe,
        "last_updated": "2026-07-01T00:00:00+00:00",
        "candles": [
            {"time": i, "open": c, "high": c, "low": c, "close": c, "volume": 1000.0} for i, c in enumerate(closes)
        ],
    }
    (directory / filename).write_text(json.dumps(payload))


def _good_closes(n: int = 200) -> list[float]:
    return [100.0 + 0.1 * i for i in range(n)]


class ExportQuantMetricsFailIndependentTest(unittest.TestCase):
    def test_one_corrupt_file_does_not_prevent_the_others_from_being_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candles_dir = Path(tmp) / "candles"
            candles_dir.mkdir()
            output_path = Path(tmp) / "quant_metrics.json"

            _write_candle_file(candles_dir, "BTC_24h.json", "BTC", "24h", _good_closes())
            _write_candle_file(candles_dir, "GOLD_1week.json", "GOLD", "1week", _good_closes())
            (candles_dir / "CORRUPT_24h.json").write_text("{not valid json")

            result = eqm.export_quant_metrics(
                candles_dir=candles_dir, output_path=output_path, now=FIXED_NOW, rf_fetch_fn=lambda: (0.04, "fred_dff")
            )

            self.assertEqual(sorted(result.written), ["BTC_24h.json", "GOLD_1week.json"])
            self.assertEqual(len(result.errors), 1)
            self.assertEqual(result.errors[0]["file"], "CORRUPT_24h.json")

            payload = json.loads(output_path.read_text())
            self.assertEqual({m["asset"] for m in payload["metrics"]}, {"BTC", "GOLD"})

    def test_a_file_missing_a_required_key_is_isolated_the_same_way(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candles_dir = Path(tmp) / "candles"
            candles_dir.mkdir()
            output_path = Path(tmp) / "quant_metrics.json"

            _write_candle_file(candles_dir, "BTC_24h.json", "BTC", "24h", _good_closes())
            (candles_dir / "BROKEN_24h.json").write_text(json.dumps({"schema_version": 1, "candles": []}))

            result = eqm.export_quant_metrics(
                candles_dir=candles_dir, output_path=output_path, now=FIXED_NOW, rf_fetch_fn=lambda: (0.04, "fred_dff")
            )
            self.assertEqual(result.written, ["BTC_24h.json"])
            self.assertEqual(len(result.errors), 1)


class ExportQuantMetricsSchemaTest(unittest.TestCase):
    def test_output_matches_the_documented_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candles_dir = Path(tmp) / "candles"
            candles_dir.mkdir()
            output_path = Path(tmp) / "quant_metrics.json"
            _write_candle_file(candles_dir, "GOLD_1week.json", "GOLD", "1week", _good_closes())

            result = eqm.export_quant_metrics(
                candles_dir=candles_dir, output_path=output_path, now=FIXED_NOW, rf_fetch_fn=lambda: (0.0363, "fred_dff")
            )
            self.assertEqual(result.errors, [])

            payload = json.loads(output_path.read_text())
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["last_updated"], FIXED_NOW.isoformat())
            entry = payload["metrics"][0]
            expected_fields = {
                "asset", "timeframe", "periods_per_year", "window_used", "rf_annual", "rf_source",
                "log_return_annualized", "zscore_current", "realized_vol_annualized", "sharpe", "sortino",
                "computed_at",
            }
            self.assertEqual(set(entry.keys()), expected_fields)
            self.assertEqual(entry["asset"], "GOLD")
            self.assertEqual(entry["timeframe"], "1week")
            self.assertEqual(entry["periods_per_year"], 52)
            self.assertEqual(entry["window_used"], 199)  # 200 closes - 1, clamped below the 252 target
            self.assertEqual(entry["rf_source"], "fred_dff")
            self.assertIsNotNone(entry["sharpe"])

    def test_unknown_timeframe_gets_null_annualized_metrics_but_still_reports_a_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candles_dir = Path(tmp) / "candles"
            candles_dir.mkdir()
            output_path = Path(tmp) / "quant_metrics.json"
            _write_candle_file(candles_dir, "ETH_snapshot.json", "ETH", "snapshot", _good_closes())

            eqm.export_quant_metrics(
                candles_dir=candles_dir, output_path=output_path, now=FIXED_NOW, rf_fetch_fn=lambda: (0.04, "fred_dff")
            )
            entry = json.loads(output_path.read_text())["metrics"][0]

            self.assertIsNone(entry["periods_per_year"])
            self.assertIsNone(entry["log_return_annualized"])
            self.assertIsNone(entry["realized_vol_annualized"])
            self.assertIsNone(entry["sharpe"])
            self.assertIsNone(entry["sortino"])
            self.assertEqual(entry["window_used"], 199)  # candle-count based, independent of annualization
            # z-score has no periods_per_year dependency at all -- still real.
            self.assertIsNotNone(entry["zscore_current"])

    def test_thin_history_produces_all_null_metrics_but_no_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candles_dir = Path(tmp) / "candles"
            candles_dir.mkdir()
            output_path = Path(tmp) / "quant_metrics.json"
            _write_candle_file(candles_dir, "THIN_24h.json", "THIN", "24h", _good_closes(10))

            result = eqm.export_quant_metrics(
                candles_dir=candles_dir, output_path=output_path, now=FIXED_NOW, rf_fetch_fn=lambda: (0.04, "fred_dff")
            )
            self.assertEqual(result.errors, [])
            entry = json.loads(output_path.read_text())["metrics"][0]
            self.assertIsNone(entry["log_return_annualized"])
            self.assertIsNone(entry["realized_vol_annualized"])
            self.assertIsNone(entry["sharpe"])
            self.assertIsNone(entry["sortino"])
            self.assertIsNone(entry["zscore_current"])


class ClassifyAssetClassTest(unittest.TestCase):
    """feature/timeframe-periods-asset-aware: classify_asset_class reuses
    export_candle_data.IN_SCOPE_PAIRS's own fetch_family exactly (not a second
    classification scheme), with an explicit GOLD/SILVER override on top since
    fetch_family alone conflates two different trading calendars."""

    def test_crypto_assets_on_the_live_roster(self) -> None:
        self.assertEqual(eqm.classify_asset_class("BTC"), "crypto")
        self.assertEqual(eqm.classify_asset_class("BNB"), "crypto")

    def test_forex_assets_on_the_live_roster(self) -> None:
        self.assertEqual(eqm.classify_asset_class("EUR/USD"), "forex")
        self.assertEqual(eqm.classify_asset_class("GBP/USD"), "forex")
        self.assertEqual(eqm.classify_asset_class("USD/JPY"), "forex")

    def test_stock_assets_on_the_live_roster(self) -> None:
        self.assertEqual(eqm.classify_asset_class("AAPL"), "stock")
        self.assertEqual(eqm.classify_asset_class("TSLA"), "stock")

    def test_gold_and_silver_split_despite_sharing_fetch_family(self) -> None:
        # Both are "crypto_metals" in export_candle_data.CandlePair.fetch_family
        # (a fetch-ROUTING label) but must NOT collapse into one asset class --
        # see quant_panel.py's own TIMEFRAME_PERIODS_PER_YEAR docstring for why.
        self.assertEqual(eqm.classify_asset_class("GOLD"), "commodity_spot")
        self.assertEqual(eqm.classify_asset_class("SILVER"), "commodity_futures")
        self.assertNotEqual(eqm.classify_asset_class("GOLD"), eqm.classify_asset_class("SILVER"))

    def test_asset_not_on_the_live_roster_returns_none(self) -> None:
        # ETH is deliberately excluded from IN_SCOPE_PAIRS (see that module's
        # own docstring) -- classify_asset_class must not guess.
        self.assertIsNone(eqm.classify_asset_class("ETH"))
        self.assertIsNone(eqm.classify_asset_class("NOT_A_REAL_ASSET"))


class FourHourTransitionTest(unittest.TestCase):
    """Task 3 migration safety: confirms the full export_quant_metrics pipeline
    (not just the lookup function in isolation) now produces REAL annualized
    numbers for "4h" where it previously produced null, for asset classes
    where a value is now defined -- and confirms this doesn't silently break
    anything that only ever expected null for "4h" before."""

    def test_btc_4h_transitions_from_null_to_a_real_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candles_dir = Path(tmp) / "candles"
            candles_dir.mkdir()
            output_path = Path(tmp) / "quant_metrics.json"
            _write_candle_file(candles_dir, "BTC_4h.json", "BTC", "4h", _good_closes())

            eqm.export_quant_metrics(
                candles_dir=candles_dir, output_path=output_path, now=FIXED_NOW, rf_fetch_fn=lambda: (0.04, "fred_dff")
            )
            entry = json.loads(output_path.read_text())["metrics"][0]

            # NOTE: sortino is legitimately None here even with a real periods_per_year --
            # _good_closes() is a perfectly monotonic uptrend with zero downside relative
            # to the (small, positive) default MAR, and sortino_ratio correctly returns
            # None for zero downside deviation (see quant_panel.sortino_ratio's own
            # docstring) -- a property of this fixture, not of the periods_per_year wiring.
            self.assertEqual(entry["periods_per_year"], 2190)
            self.assertIsNotNone(entry["sharpe"])
            self.assertIsNotNone(entry["realized_vol_annualized"])
            self.assertIsNotNone(entry["log_return_annualized"])

    def test_eurusd_4h_transitions_from_null_to_a_real_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candles_dir = Path(tmp) / "candles"
            candles_dir.mkdir()
            output_path = Path(tmp) / "quant_metrics.json"
            _write_candle_file(candles_dir, "EURUSD_4h.json", "EUR/USD", "4h", _good_closes())

            eqm.export_quant_metrics(
                candles_dir=candles_dir, output_path=output_path, now=FIXED_NOW, rf_fetch_fn=lambda: (0.04, "fred_dff")
            )
            entry = json.loads(output_path.read_text())["metrics"][0]

            self.assertEqual(entry["periods_per_year"], 2190)
            self.assertIsNotNone(entry["sharpe"])

    def test_aapl_4h_transitions_from_null_to_a_real_number_and_differs_from_crypto(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candles_dir = Path(tmp) / "candles"
            candles_dir.mkdir()
            output_path = Path(tmp) / "quant_metrics.json"
            _write_candle_file(candles_dir, "AAPL_4h.json", "AAPL", "4h", _good_closes())

            eqm.export_quant_metrics(
                candles_dir=candles_dir, output_path=output_path, now=FIXED_NOW, rf_fetch_fn=lambda: (0.04, "fred_dff")
            )
            entry = json.loads(output_path.read_text())["metrics"][0]

            self.assertEqual(entry["periods_per_year"], 252)  # NOT 2190 -- a genuinely different cadence
            self.assertIsNotNone(entry["sharpe"])

    def test_silver_4h_stays_null_never_borrows_golds_or_anything_elses_constant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candles_dir = Path(tmp) / "candles"
            candles_dir.mkdir()
            output_path = Path(tmp) / "quant_metrics.json"
            _write_candle_file(candles_dir, "SILVER_4h.json", "SILVER", "4h", _good_closes())

            eqm.export_quant_metrics(
                candles_dir=candles_dir, output_path=output_path, now=FIXED_NOW, rf_fetch_fn=lambda: (0.04, "fred_dff")
            )
            entry = json.loads(output_path.read_text())["metrics"][0]

            self.assertIsNone(entry["periods_per_year"])
            self.assertIsNone(entry["sharpe"])
            self.assertIsNone(entry["sortino"])
            self.assertIsNone(entry["realized_vol_annualized"])
            self.assertIsNone(entry["log_return_annualized"])
            # z-score has no periods_per_year dependency -- still real, proving
            # the null is specifically about annualization, not a broken file.
            self.assertIsNotNone(entry["zscore_current"])

    def test_averted_bug_regression_btc_4h_never_gets_forexs_old_1560_constant(self) -> None:
        """Direct reconstruction of the averted-bug scenario: a non-forex asset
        requesting "4h" annualization must resolve to ITS OWN asset-specific
        constant, never silently inherit forex's (old or new)."""
        with tempfile.TemporaryDirectory() as tmp:
            candles_dir = Path(tmp) / "candles"
            candles_dir.mkdir()
            output_path = Path(tmp) / "quant_metrics.json"
            _write_candle_file(candles_dir, "BTC_4h.json", "BTC", "4h", _good_closes())
            _write_candle_file(candles_dir, "EURUSD_4h.json", "EUR/USD", "4h", _good_closes())
            _write_candle_file(candles_dir, "AAPL_4h.json", "AAPL", "4h", _good_closes())

            eqm.export_quant_metrics(
                candles_dir=candles_dir, output_path=output_path, now=FIXED_NOW, rf_fetch_fn=lambda: (0.04, "fred_dff")
            )
            by_asset = {m["asset"]: m for m in json.loads(output_path.read_text())["metrics"]}

            self.assertNotEqual(by_asset["BTC"]["periods_per_year"], 1560)  # the old forex-only constant
            self.assertNotEqual(by_asset["AAPL"]["periods_per_year"], 1560)
            self.assertEqual(by_asset["BTC"]["periods_per_year"], 2190)
            self.assertEqual(by_asset["EUR/USD"]["periods_per_year"], 2190)
            self.assertEqual(by_asset["AAPL"]["periods_per_year"], 252)


class NonFourHourRegressionTest(unittest.TestCase):
    """Task 3 migration safety: reconstructs the manual before/after diff run
    directly against docs/site_data/candles/ (every existing non-4h asset/
    timeframe combination byte-identical, only SILVER's 1week/24h changed --
    an explicitly-approved consequence of the commodity_futures=None decision,
    not a regression) as a permanent, CI-repeatable test using synthetic
    fixtures, so this doesn't rely on a one-off manual run against live data
    that can change over time."""

    # (asset, timeframe, expected periods_per_year) for every currently-live
    # non-4h combination in docs/site_data/candles/ as of this branch, EXCLUDING
    # SILVER (see the dedicated test below for why its OLD value must NOT
    # survive) and EXCLUDING EUR/USD-USD/JPY "1day" (Phase 1 Fix B,
    # docs/investigations/phase_b_forex_annualization.md -- see
    # test_eurusd_and_usdjpy_1day_deliberately_change_from_252_to_365 below;
    # these two are deliberately NOT byte-identical to the pre-fix value).
    EXISTING_NON_4H_COMBOS = [
        ("BTC", "12h", 730), ("BNB", "12h", 730),
        ("BTC", "24h", 365), ("BNB", "24h", 365), ("GOLD", "24h", 365),
        ("AAPL", "1day", 252), ("MSFT", "1day", 252), ("GOOGL", "1day", 252),
        ("TSLA", "1day", 252), ("AMZN", "1day", 252), ("NVDA", "1day", 252), ("META", "1day", 252),
        ("EUR/USD", "1week", 52), ("GBP/USD", "1week", 52), ("USD/JPY", "1week", 52), ("GOLD", "1week", 52),
    ]

    def test_every_existing_non_4h_combo_keeps_its_old_periods_per_year(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candles_dir = Path(tmp) / "candles"
            candles_dir.mkdir()
            output_path = Path(tmp) / "quant_metrics.json"
            for asset, timeframe, _expected in self.EXISTING_NON_4H_COMBOS:
                filename = f"{asset.replace('/', '')}_{timeframe}.json"
                _write_candle_file(candles_dir, filename, asset, timeframe, _good_closes())

            eqm.export_quant_metrics(
                candles_dir=candles_dir, output_path=output_path, now=FIXED_NOW, rf_fetch_fn=lambda: (0.04, "fred_dff")
            )
            by_key = {(m["asset"], m["timeframe"]): m for m in json.loads(output_path.read_text())["metrics"]}

            for asset, timeframe, expected in self.EXISTING_NON_4H_COMBOS:
                with self.subTest(asset=asset, timeframe=timeframe):
                    self.assertEqual(by_key[(asset, timeframe)]["periods_per_year"], expected)

    def test_silver_1week_and_24h_deliberately_change_from_a_real_number_to_null(self) -> None:
        # NOT a byte-identical case, DELIBERATELY: before this branch, the old
        # flat table applied "1week": 52 / "24h": 365 to SILVER too (no asset-
        # class awareness to stop it), producing a real (but per this branch's
        # own investigation, unverified and likely wrong -- SILVER is a COMEX
        # futures contract on a different calendar than GOLD) Sharpe/vol. The
        # explicit decision (2026-08-01 review) was commodity_futures returns
        # None for ALL timeframes, not just "4h" -- so this specific change,
        # unlike every other non-4h combo, is an intended, approved output
        # change, not a regression. Documented here so it's never mistaken for
        # one later.
        with tempfile.TemporaryDirectory() as tmp:
            candles_dir = Path(tmp) / "candles"
            candles_dir.mkdir()
            output_path = Path(tmp) / "quant_metrics.json"
            _write_candle_file(candles_dir, "SILVER_1week.json", "SILVER", "1week", _good_closes())
            _write_candle_file(candles_dir, "SILVER_24h.json", "SILVER", "24h", _good_closes())

            eqm.export_quant_metrics(
                candles_dir=candles_dir, output_path=output_path, now=FIXED_NOW, rf_fetch_fn=lambda: (0.04, "fred_dff")
            )
            by_key = {(m["asset"], m["timeframe"]): m for m in json.loads(output_path.read_text())["metrics"]}

            self.assertIsNone(by_key[("SILVER", "1week")]["periods_per_year"])
            self.assertIsNone(by_key[("SILVER", "1week")]["sharpe"])
            self.assertIsNone(by_key[("SILVER", "24h")]["periods_per_year"])
            self.assertIsNone(by_key[("SILVER", "24h")]["sharpe"])

    def test_eurusd_and_usdjpy_1day_deliberately_change_from_252_to_365(self) -> None:
        # NOT a byte-identical case, DELIBERATELY (Phase 1 Fix B,
        # docs/investigations/phase_b_forex_annualization.md): 252 (trading-
        # days-only) was flagged as likely wrong by the timeframe-periods-
        # asset-aware branch's own backlog and confirmed empirically by a
        # dedicated follow-up investigation -- EURUSD_1day.json/
        # USDJPY_1day.json measure ~366.8 implied candles/year, weekday
        # distribution statistically uniform including Saturday/Sunday, zero
        # flat-OHLC candles. 365 (matching the CRYPTO/COMMODITY_SPOT 24h
        # convention) replaces 252 for FOREX/"1day" specifically -- STOCK's
        # own "1day" (a genuinely trading-days-only feed) is unaffected, see
        # EXISTING_NON_4H_COMBOS above.
        with tempfile.TemporaryDirectory() as tmp:
            candles_dir = Path(tmp) / "candles"
            candles_dir.mkdir()
            output_path = Path(tmp) / "quant_metrics.json"
            _write_candle_file(candles_dir, "EURUSD_1day.json", "EUR/USD", "1day", _good_closes())
            _write_candle_file(candles_dir, "USDJPY_1day.json", "USD/JPY", "1day", _good_closes())

            eqm.export_quant_metrics(
                candles_dir=candles_dir, output_path=output_path, now=FIXED_NOW, rf_fetch_fn=lambda: (0.04, "fred_dff")
            )
            by_key = {(m["asset"], m["timeframe"]): m for m in json.loads(output_path.read_text())["metrics"]}

            self.assertEqual(by_key[("EUR/USD", "1day")]["periods_per_year"], 365)
            self.assertEqual(by_key[("USD/JPY", "1day")]["periods_per_year"], 365)
            self.assertNotEqual(by_key[("EUR/USD", "1day")]["periods_per_year"], 252)
            self.assertNotEqual(by_key[("USD/JPY", "1day")]["periods_per_year"], 252)


class FetchRiskFreeRateFallbackTest(unittest.TestCase):
    def test_falls_back_to_the_documented_constant_when_fred_raises(self) -> None:
        def _raising_fetch_policy_rate(*_args, **_kwargs):
            raise RuntimeError("network down")

        original = eqm.fetch_policy_rate
        eqm.fetch_policy_rate = _raising_fetch_policy_rate  # type: ignore[assignment]
        try:
            rf_annual, rf_source = eqm.fetch_risk_free_rate()
        finally:
            eqm.fetch_policy_rate = original  # type: ignore[assignment]

        self.assertEqual(rf_annual, eqm.FALLBACK_RF_ANNUAL)
        self.assertEqual(rf_source, "fallback_constant")

    def test_falls_back_when_the_lag_shifted_series_has_no_usable_observation(self) -> None:
        import pandas as pd

        def _empty_series_fetch(*_args, **_kwargs):
            return pd.Series(dtype=float), "NATIVE: FRED DFF", "D"

        original = eqm.fetch_policy_rate
        eqm.fetch_policy_rate = _empty_series_fetch  # type: ignore[assignment]
        try:
            rf_annual, rf_source = eqm.fetch_risk_free_rate()
        finally:
            eqm.fetch_policy_rate = original  # type: ignore[assignment]

        self.assertEqual(rf_annual, eqm.FALLBACK_RF_ANNUAL)
        self.assertEqual(rf_source, "fallback_constant")

    def test_a_real_series_produces_the_live_source_label(self) -> None:
        import pandas as pd

        def _real_series_fetch(*_args, **_kwargs):
            dates = pd.date_range("2026-01-01", periods=10, freq="D")
            return pd.Series([5.33] * 10, index=dates), "NATIVE: FRED DFF", "D"

        original = eqm.fetch_policy_rate
        eqm.fetch_policy_rate = _real_series_fetch  # type: ignore[assignment]
        try:
            rf_annual, rf_source = eqm.fetch_risk_free_rate()
        finally:
            eqm.fetch_policy_rate = original  # type: ignore[assignment]

        self.assertEqual(rf_source, "fred_dff")
        self.assertAlmostEqual(rf_annual, 0.0533, places=6)


if __name__ == "__main__":
    unittest.main()
