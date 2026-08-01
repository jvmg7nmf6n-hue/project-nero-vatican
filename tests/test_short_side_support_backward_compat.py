"""feature/short-side-support Task 3 -- the hard merge-gate proof that every
existing long-only hypothesis result is EXACTLY reproducible after the
bidirectional changes to auto_tester.py, rule_dsl.py, and mean_reversion.py.

METHODOLOGY: frozen-candle snapshots (tests/fixtures/frozen_candles/*.json)
were captured ONCE, before any Task 2 code changes, from live BTC/ETH/EURUSD
4h data. tests/fixtures/frozen_candles/backward_compat_baseline_before.json
is the recorded output of running these 5 spot-check hypotheses (2 from the
native WISE_MAN_HOLD_V1/ADX_RANGE_V4 graveyard, 3 from the EXT_WISE_MAN_HOLD
external-candidates set) through the OLD (pre-Task-2) code against those same
frozen candles -- computed from a detached git worktree checked out at this
branch's pre-Task-2 commit, so it is genuinely the old code, not a relabeled
re-run of the new code. This test re-runs the SAME hypotheses against the
SAME frozen candles through the CURRENT (post-Task-2) code and asserts exact
equality against those recorded values -- not a re-run-and-eyeball comparison.

SCOPE NOTE -- grid_shift is deliberately excluded from this proof:
run_hypothesis_live's grid-shift re-run (build_4h_grids -> fetch_hourly_for_
grid -> client.load_intraday) performs its OWN independent, live, unfrozen
network fetch every time it runs, completely bypassing the frozen `candles`
argument -- this is a pre-existing property of tools/philosophy_hypotheses_
live_test.py (unmodified by this branch, confirmed by `git diff` against
this branch's merge-base with main having zero output for that file) and not
something a frozen-candle fixture can control. A live diff-before-after run
during this branch's own development surfaced exactly this: the top-level
`result` field (which is 100% driven by the frozen candles and IS what this
test proves) was byte-identical across all 5 cases, while ONE grid-shift
offset for ONE case showed tiny drift confined to random-baseline/frequency
numbers that trace directly to hourly candles accruing between the two live
fetches -- verdict/frequency_classification/review_status/reason and the
underlying train/test trade lists were unaffected even there. This test
therefore calls run_hypothesis_live with run_grid_shift=False: it proves the
part of the pipeline this branch actually changed (frequency measurement,
entry sizing, exit evaluation, random-entry baseline) reproduces byte-for-
byte, and does not attempt to falsely claim byte-equality over a sub-step
that was never frozen to begin with."""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nero_core.strategies.mean_reversion import MeanReversionParameters
from tools.philosophy_hypotheses_live_test import _to_jsonable, run_hypothesis_live

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "frozen_candles"
RECORDED_BASELINE_PATH = FIXTURES_DIR / "backward_compat_baseline_before.json"

FIXED_NOW = datetime(2026, 8, 1, 16, 0, 0, tzinfo=timezone.utc)

WISE_MAN_ENTRY_RULE = {
    "conditions": [
        {"field": "close", "op": "lt", "compare_to_field": "bb_lower"},
        {"field": "adx14", "op": "lt", "value": 25.0},
    ],
}
WISE_MAN_EXT_ENTRY_RULE = {
    "conditions": [
        {"field": "close", "op": "lt", "compare_to_field": "bb_lower"},
        {"field": "adx14", "op": "lt", "value": 25.0},
        {"field": "atr14", "op": "gt", "value": 0.0},
    ],
}

CRYPTO_PARAMS = MeanReversionParameters(initial_equity=10_000.0, risk_per_trade=0.01, fee_bps=10.0, slippage_bps=2.0)
FOREX_PARAMS = MeanReversionParameters(initial_equity=10_000.0, risk_per_trade=0.01, fee_bps=2.0, slippage_bps=2.0)

# Mirrors the CASES list used to produce backward_compat_baseline_before.json
# exactly -- same names, same candles files, same rules/exit-plans/params.
# Changing any of these values would invalidate the recorded comparison.
CASES = [
    {
        "name": "WISE_MAN_HOLD_V1", "candles_file": "BTC_4h.json", "asset": "BTC", "timeframe": "4h",
        "structured_entry_rule": WISE_MAN_ENTRY_RULE,
        "structured_exit_plan": {"stop_pct_of_entry": 0.040, "target_pct_of_entry": 0.008},
        "backtest_params": None,
    },
    {
        "name": "ADX_RANGE_V4", "candles_file": "BTC_4h.json", "asset": "BTC", "timeframe": "4h",
        "structured_entry_rule": {"conditions": [{"field": "adx14", "op": "lt", "value": 30.0}]},
        "structured_exit_plan": {
            "stop_atr_multiple": 2.0, "target_r_multiple": 50.0,
            "regime_break_condition": {"field": "adx14", "op": "gte", "value": 25.0},
            "regime_break_consecutive_bars": 1, "max_holding_hours": 480.0,
        },
        "backtest_params": None,
    },
    {
        "name": "EXT_WISE_MAN_HOLD_V5_ETH_4H", "candles_file": "ETH_4h.json", "asset": "ETH", "timeframe": "4h",
        "structured_entry_rule": WISE_MAN_EXT_ENTRY_RULE,
        "structured_exit_plan": {
            "stop_pct_of_entry": 0.015, "target_pct_of_entry": 0.03,
            "regime_break_condition": {"field": "adx14", "op": "gte", "value": 28.0},
            "regime_break_consecutive_bars": 2,
        },
        "backtest_params": CRYPTO_PARAMS,
    },
    {
        "name": "EXT_WISE_MAN_HOLD_V6_EURUSD_4H", "candles_file": "EURUSD_4h.json", "asset": "EUR/USD", "timeframe": "4h",
        "structured_entry_rule": WISE_MAN_EXT_ENTRY_RULE,
        "structured_exit_plan": {
            "stop_pct_of_entry": 0.01, "target_pct_of_entry": 0.01,
            "regime_break_condition": {"field": "adx14", "op": "gte", "value": 28.0},
            "regime_break_consecutive_bars": 2,
        },
        "backtest_params": FOREX_PARAMS,
    },
    {
        "name": "EXT_WISE_MAN_HOLD_V5_EURUSD_4H", "candles_file": "EURUSD_4h.json", "asset": "EUR/USD", "timeframe": "4h",
        "structured_entry_rule": WISE_MAN_EXT_ENTRY_RULE,
        "structured_exit_plan": {
            "stop_pct_of_entry": 0.015, "target_pct_of_entry": 0.03,
            "regime_break_condition": {"field": "adx14", "op": "gte", "value": 28.0},
            "regime_break_consecutive_bars": 2,
        },
        "backtest_params": FOREX_PARAMS,
    },
]


def _load_frozen_candles(filename: str):
    import pandas as pd

    data = json.loads((FIXTURES_DIR / filename).read_text())
    return pd.DataFrame(data["candles"])


class SpotCheckExactReproductionTest(unittest.TestCase):
    """Re-runs each of the 5 spot-check hypotheses through the CURRENT
    (post-Task-2) code against the frozen candles and asserts the `result`
    field is byte-for-byte identical to the value recorded from the OLD
    (pre-Task-2) code -- the hard backward-compatibility gate itself."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.recorded = json.loads(RECORDED_BASELINE_PATH.read_text())

    def test_every_spot_check_hypothesis_result_is_byte_identical_to_the_recorded_pre_change_baseline(self) -> None:
        for case in CASES:
            with self.subTest(name=case["name"]):
                candles = _load_frozen_candles(case["candles_file"])
                hypothesis = {
                    "hypothesis_name": case["name"], "asset": case["asset"], "timeframe": case["timeframe"],
                    "generated_at": FIXED_NOW.isoformat(),
                    "structured_entry_rule": case["structured_entry_rule"],
                    "structured_exit_plan": case["structured_exit_plan"],
                }
                run = run_hypothesis_live(
                    hypothesis, candles, FIXED_NOW, client=None, run_grid_shift=False,
                    backtest_params=case["backtest_params"],
                )
                fresh_result = _to_jsonable(run)["result"]
                recorded_result = self.recorded[case["name"]]["result"]
                self.assertEqual(
                    json.dumps(fresh_result, sort_keys=True, default=str),
                    json.dumps(recorded_result, sort_keys=True, default=str),
                    f"{case['name']}: current code's result diverges from the recorded pre-Task-2 baseline",
                )

    def test_recorded_baseline_verdicts_match_the_historical_record(self) -> None:
        # Sanity-check on the fixture itself, not the code under test: proves
        # the recorded "before" values are what this branch's own report
        # (and, for the 2 native-graveyard entries, the original pre-existing
        # graveyard record) says they should be -- so a corrupted or
        # accidentally-regenerated-with-new-code fixture can't silently
        # rubber-stamp this test.
        expected = {
            "WISE_MAN_HOLD_V1": ("DIED", "VIABLE"),
            "ADX_RANGE_V4": ("DIED", "FAST"),
            "EXT_WISE_MAN_HOLD_V5_ETH_4H": ("DIED", "VIABLE"),
            "EXT_WISE_MAN_HOLD_V6_EURUSD_4H": ("SKIPPED", "TOO_SLOW"),
            "EXT_WISE_MAN_HOLD_V5_EURUSD_4H": ("SKIPPED", "TOO_SLOW"),
        }
        for name, (verdict, freq) in expected.items():
            with self.subTest(name=name):
                result = self.recorded[name]["result"]
                self.assertEqual(result["verdict"], verdict)
                self.assertEqual(result["frequency_classification"], freq)


class UntouchedProductionStrategiesTest(unittest.TestCase):
    """range_mean_reversion.py and short_momentum.py are the two existing
    production bidirectional strategies this branch's design was modeled on
    -- they must be provably untouched, not merely "probably fine"."""

    def test_range_mean_reversion_and_short_momentum_have_zero_diff_since_branch_divergence(self) -> None:
        import subprocess

        merge_base = subprocess.run(
            ["git", "merge-base", "main", "HEAD"], cwd=Path(__file__).parent.parent,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        for relpath in ("nero_core/strategies/range_mean_reversion.py", "nero_core/strategies/short_momentum.py"):
            with self.subTest(relpath=relpath):
                diff = subprocess.run(
                    ["git", "diff", merge_base, "--", relpath], cwd=Path(__file__).parent.parent,
                    capture_output=True, text=True, check=True,
                ).stdout
                self.assertEqual(diff, "", f"{relpath} has diverged from main since this branch started -- not untouched")

    def test_no_new_code_imports_mutable_state_or_logic_from_the_two_reference_strategies(self) -> None:
        # rule_dsl.py's PRE-EXISTING (unrelated to this branch) import of
        # range_mean_reversion.adx is a pure indicator function, not shared
        # mutable state or entry/exit logic -- this test proves this branch's
        # own new code doesn't additionally import evaluate_exit/size_entry/
        # RangeMeanReversionState/OpenTrade from either reference module,
        # which would create an actual shared code path (there isn't one --
        # every strategy in this codebase, including these two, evaluates its
        # own trades independently; this branch's design REUSES THE PATTERN,
        # not the code). Checks actual `import`/`from ... import ...`
        # statements via ast, not raw source text -- these 3 modules'
        # docstrings legitimately MENTION range_mean_reversion.evaluate_exit
        # in prose (explaining the mirrored convention), which a plain
        # substring search would misfire on.
        import ast
        import inspect

        from nero_core.research_agent import auto_tester, rule_dsl
        from nero_core.strategies import mean_reversion

        allowed_names_from_range_mean_reversion = {"adx"}
        forbidden_modules = {"nero_core.strategies.range_mean_reversion", "nero_core.strategies.short_momentum"}

        for module in (auto_tester, rule_dsl, mean_reversion):
            tree = ast.parse(inspect.getsource(module))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module in forbidden_modules:
                    imported = {alias.name for alias in node.names}
                    if node.module == "nero_core.strategies.range_mean_reversion":
                        imported -= allowed_names_from_range_mean_reversion
                    with self.subTest(module=module.__name__, source_module=node.module):
                        self.assertEqual(
                            imported, set(),
                            f"{module.__name__} imports {imported} from {node.module} -- "
                            f"an actual shared code path beyond the known pure adx() reuse",
                        )


if __name__ == "__main__":
    unittest.main()
