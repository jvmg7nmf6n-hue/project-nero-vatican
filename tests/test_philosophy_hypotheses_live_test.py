"""feature/philosophy-hypotheses-live-test: the reusable manual-submission
mechanism itself (tools.philosophy_hypotheses_live_test) -- proves it wires
frequency_gate.measure_entry_frequency + auto_tester.test_hypothesis/
run_grid_shift_check correctly, WITHOUT hitting the network (every fetch
function is mocked, matching tests/test_rmr_variant_research_stage1.py's own
convention for this project's other "fetch real data, backtest, report" CLI
tools)."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.forex_data import ForexDataResult
from nero_core.research_agent import auto_tester, frequency_gate
from tools.philosophy_hypotheses_live_test import (
    GRID_OFFSETS_4H,
    build_4h_grids,
    fetch_full_history,
    run_hypothesis_live,
)

HOUR_MS = 3_600_000
START_MS = 1_700_000_000_000

RANGE_ENTRY_RULE = {
    "conditions": [
        {"field": "close", "op": "lt", "compare_to_field": "bb_lower"},
        {"field": "adx14", "op": "lt", "value": 25.0},
    ],
}
FIXED_EXIT_PLAN = {"stop_pct_of_entry": 0.03, "target_pct_of_entry": 0.01}


def _flat_history(n: int, hours_per_candle: int = 4) -> pd.DataFrame:
    """Never triggers RANGE_ENTRY_RULE (a flat, low-volatility series never
    closes below its own bollinger lower band) -- used to force TOO_SLOW/
    UNMEASURABLE without needing a real dip."""
    rows = []
    close_time = START_MS
    price = 100.0
    for i in range(n):
        price += 0.01 * ((i % 2) - 0.5)
        rows.append({"close_time": close_time, "close": price, "high": price + 0.05, "low": price - 0.05, "volume": 1.0})
        close_time += hours_per_candle * HOUR_MS
    return pd.DataFrame(rows)


def _dip_history(n: int, hours_per_candle: int = 4) -> pd.DataFrame:
    """Regular dips well below a trailing mean/band so RANGE_ENTRY_RULE fires
    often enough to clear FAST/VIABLE within a short synthetic span."""
    rows = []
    close_time = START_MS
    for i in range(n):
        price = 100.0 - (6.0 if i % 5 == 0 else 0.0) + 0.2 * (i % 3)
        rows.append({"close_time": close_time, "close": price, "high": price + 0.3, "low": price - 0.3, "volume": 1.0})
        close_time += hours_per_candle * HOUR_MS
    return pd.DataFrame(rows)


class FetchFullHistoryDispatchTest(unittest.TestCase):
    def test_forex_pair_routes_through_fetch_forex_ohlcv(self) -> None:
        history = _flat_history(100)
        with patch("tools.philosophy_hypotheses_live_test.fetch_forex_ohlcv") as mock_forex:
            mock_forex.return_value = ForexDataResult(prices=history, source="test-fixture", pair="EUR/USD", timeframe="4h")
            result = fetch_full_history("EUR/USD", "4h", client=None)
        mock_forex.assert_called_once_with("EUR/USD", "4h")
        self.assertIs(result, history)

    def test_crypto_asset_routes_through_fetch_timeframe_candles(self) -> None:
        history = _flat_history(100)
        with patch("tools.philosophy_hypotheses_live_test.fetch_timeframe_candles") as mock_tf:
            mock_tf.return_value = (history, "test-fixture")
            result = fetch_full_history("BTC", "4h", client="fake-client")
        mock_tf.assert_called_once_with("fake-client", "BTC", "4h")
        self.assertIs(result, history)


class Build4hGridsTest(unittest.TestCase):
    def test_builds_exactly_the_four_possible_alignments(self) -> None:
        # 300 hourly candles is plenty for every offset to produce >= 1 complete 4h bin.
        hourly_rows = []
        t = START_MS
        for i in range(300):
            hourly_rows.append({"close_time": t, "open_time": t - HOUR_MS, "date": t, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1.0})
            t += HOUR_MS
        hourly = pd.DataFrame(hourly_rows)

        with patch("tools.philosophy_hypotheses_live_test.fetch_forex_ohlcv") as mock_forex:
            mock_forex.return_value = ForexDataResult(prices=hourly, source="test-fixture", pair="EUR/USD", timeframe="1h")
            grids = build_4h_grids("EUR/USD", client=None)

        self.assertEqual(len(grids), len(GRID_OFFSETS_4H))
        self.assertIn("native (offset+0h)", grids)
        for offset in GRID_OFFSETS_4H[1:]:
            self.assertIn(f"offset+{offset}h", grids)
        for label, grid in grids.items():
            self.assertFalse(grid.empty, f"grid {label} produced no complete bins")


class RunHypothesisLiveTest(unittest.TestCase):
    NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)

    def _hypothesis(self, name: str) -> dict:
        return {
            "hypothesis_name": name,
            "asset": "BTC",
            "timeframe": "4h",
            "generated_at": self.NOW.isoformat(),
            "structured_entry_rule": RANGE_ENTRY_RULE,
            "structured_exit_plan": FIXED_EXIT_PLAN,
        }

    def test_too_slow_hypothesis_never_triggers_a_grid_shift_fetch(self) -> None:
        candles = _flat_history(200)  # RANGE_ENTRY_RULE never fires -> TOO_SLOW (0 triggers)
        hypothesis = self._hypothesis("NEVER_FIRES")

        with patch("tools.philosophy_hypotheses_live_test.build_4h_grids") as mock_build_grids:
            run = run_hypothesis_live(hypothesis, candles, self.NOW)

        mock_build_grids.assert_not_called()
        self.assertEqual(run["result"].frequency_classification, frequency_gate.TOO_SLOW)
        self.assertIsNone(run["grid_shift"])

    def test_fast_or_viable_hypothesis_runs_grid_shift_across_all_four_offsets(self) -> None:
        candles = _dip_history(400)
        hypothesis = self._hypothesis("FIRES_OFTEN")

        base_result = auto_tester.test_hypothesis(hypothesis, candles, self.NOW)
        self.assertIn(base_result.frequency_classification, (frequency_gate.FAST, frequency_gate.VIABLE))

        fake_grids = {"native (offset+0h)": candles, "offset+1h": candles, "offset+2h": candles, "offset+3h": candles}
        with patch("tools.philosophy_hypotheses_live_test.build_4h_grids", return_value=fake_grids) as mock_build_grids:
            run = run_hypothesis_live(hypothesis, candles, self.NOW, client="fake-client")

        mock_build_grids.assert_called_once_with("BTC", "fake-client")
        self.assertIsNotNone(run["grid_shift"])
        self.assertEqual(set(run["grid_shift"].keys()), set(fake_grids.keys()))
        for label, grid_result in run["grid_shift"].items():
            self.assertEqual(grid_result.hypothesis_name, "FIRES_OFTEN")

    def test_run_grid_shift_false_skips_the_grid_entirely_even_when_fast(self) -> None:
        candles = _dip_history(400)
        hypothesis = self._hypothesis("FIRES_OFTEN")
        with patch("tools.philosophy_hypotheses_live_test.build_4h_grids") as mock_build_grids:
            run = run_hypothesis_live(hypothesis, candles, self.NOW, run_grid_shift=False)
        mock_build_grids.assert_not_called()
        self.assertIsNone(run["grid_shift"])

    def test_backtest_params_forwarded_unchanged_to_both_the_main_run_and_every_grid_shift_call(self) -> None:
        # feature/external-candidates-formal-test: a hypothesis's cost
        # assumptions (e.g. a forex-specific fee_bps) must stay identical
        # across its main run and its grid-shift verification -- proven by
        # mocking both auto_tester entry points directly, not inferred from
        # a P&L difference.
        from nero_core.strategies.mean_reversion import MeanReversionParameters

        custom_params = MeanReversionParameters(fee_bps=2.0, slippage_bps=2.0)
        candles = _dip_history(400)
        hypothesis = self._hypothesis("FIRES_OFTEN")
        fake_grids = {"native (offset+0h)": candles}
        # Computed BEFORE the patch context -- the real function, not the mock.
        base_result = auto_tester.test_hypothesis(hypothesis, candles, self.NOW)
        self.assertIn(base_result.frequency_classification, (frequency_gate.FAST, frequency_gate.VIABLE))

        with patch("tools.philosophy_hypotheses_live_test.auto_tester.test_hypothesis") as mock_test_hypothesis, \
             patch("tools.philosophy_hypotheses_live_test.auto_tester.run_grid_shift_check") as mock_grid_check, \
             patch("tools.philosophy_hypotheses_live_test.build_4h_grids", return_value=fake_grids):
            mock_test_hypothesis.return_value = base_result
            run_hypothesis_live(hypothesis, candles, self.NOW, backtest_params=custom_params)

        self.assertIs(mock_test_hypothesis.call_args.kwargs["backtest_params"], custom_params)
        self.assertIs(mock_grid_check.call_args.kwargs["backtest_params"], custom_params)


class NoAutoWireTest(unittest.TestCase):
    """Same static AST check as tests/test_research_agent_no_auto_wire.py,
    applied to this new tool -- it must never import live_scheduler or
    reference default_registry either."""

    def test_source_file_references_neither_live_scheduler_nor_the_registry(self) -> None:
        import ast
        from pathlib import Path

        path = Path(__file__).resolve().parents[1] / "tools" / "philosophy_hypotheses_live_test.py"
        tree = ast.parse(path.read_text(), filename=str(path))
        hits = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if "live_scheduler" in alias.name:
                        hits.append(f"import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if "live_scheduler" in module:
                    hits.append(f"from {module} import ...")
                if module.endswith("strategies.registry"):
                    hits.append(f"from {module} import ...")
            elif isinstance(node, ast.Name) and node.id == "default_registry":
                hits.append("reference to name 'default_registry'")
        self.assertEqual(hits, [])

    def test_persist_report_never_writes_the_shared_agent_test_results_ledger(self) -> None:
        from tools.philosophy_hypotheses_live_test import DEFAULT_REPORT_PATH

        self.assertNotEqual(DEFAULT_REPORT_PATH.name, "agent_test_results.json")
        self.assertNotIn("site_data", DEFAULT_REPORT_PATH.parts)


if __name__ == "__main__":
    unittest.main()
