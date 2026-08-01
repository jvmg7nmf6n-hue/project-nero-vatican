"""Repair Lab v1, Task 2: the diagnosis step and the hard modification-scope
boundary enforcement. Uses the REAL docs/site_data/repair_candidates.json
file (not mocked) for the asset/timeframe-change tests, per the task's own
explicit "must check against this file, not free-reason a new target"."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import requests as requests_module

from nero_core.research_agent.repair_lab import (
    DEFAULT_REPAIR_CANDIDATES_PATH,
    MODIFICATION_ASSET_TIMEFRAME_CHANGE,
    MODIFICATION_DIRECTION_ADD_MIRROR,
    MODIFICATION_ENTRY_THRESHOLD,
    MODIFICATION_EXIT_STRUCTURE,
    allowed_modification_types,
    is_sample_thin,
    load_repair_candidates,
    propose_modification,
    validate_modification,
)

ADEQUATE_SAMPLE_RESULT = {
    "verdict": "DIED", "reason": "train: N=176 ExpR=-0.330; test: N=53 ExpR=-0.057 -> DIED",
    "train": {"trades": 176, "expectancy_r": -0.330, "bootstrap_ci": {"lower_2_5": -0.5, "upper_97_5": -0.1, "crosses_zero": False}},
    "test": {"trades": 53, "expectancy_r": -0.057, "bootstrap_ci": {"lower_2_5": -0.3, "upper_97_5": 0.2, "crosses_zero": True}},
}

THIN_SAMPLE_RESULT = {
    # Modeled on the real graveyard's own RANGE_MEAN_REVERSION BTC/1d diagnosis
    # (docs/site_data/repair_candidates.json's own RMR_CONFIRMATION_METALS_WEEKLY
    # entry: "tested it only on ... the thinnest config ... 7-19 trades per half").
    "verdict": "DIED", "reason": "train: N=12 ExpR=0.120; test: N=8 ExpR=-0.340 -> DIED",
    "train": {"trades": 12, "expectancy_r": 0.120, "bootstrap_ci": {"lower_2_5": -0.4, "upper_97_5": 0.6, "crosses_zero": True}},
    "test": {"trades": 8, "expectancy_r": -0.340, "bootstrap_ci": None},
}

ORIGINAL_HYPOTHESIS = {
    "hypothesis_name": "EXT_WISE_MAN_HOLD_V5_ETH_4H", "asset": "ETH", "timeframe": "4h",
    "structured_entry_rule": {
        "conditions": [
            {"field": "close", "op": "lt", "compare_to_field": "bb_lower"},
            {"field": "adx14", "op": "lt", "value": 25.0},
        ],
    },
    "structured_exit_plan": {
        "stop_pct_of_entry": 0.015, "target_pct_of_entry": 0.03,
        "regime_break_condition": {"field": "adx14", "op": "gte", "value": 28.0},
        "regime_break_consecutive_bars": 2,
    },
}


class SampleThinnessGateTest(unittest.TestCase):
    def test_adequate_sample_is_not_thin(self) -> None:
        self.assertFalse(is_sample_thin(ADEQUATE_SAMPLE_RESULT))

    def test_thin_sample_is_thin(self) -> None:
        self.assertTrue(is_sample_thin(THIN_SAMPLE_RESULT))

    def test_asset_timeframe_change_excluded_when_sample_adequate(self) -> None:
        allowed = allowed_modification_types(ADEQUATE_SAMPLE_RESULT)
        self.assertNotIn(MODIFICATION_ASSET_TIMEFRAME_CHANGE, allowed)
        self.assertIn(MODIFICATION_ENTRY_THRESHOLD, allowed)
        self.assertIn(MODIFICATION_EXIT_STRUCTURE, allowed)
        self.assertIn(MODIFICATION_DIRECTION_ADD_MIRROR, allowed)

    def test_asset_timeframe_change_offered_when_sample_thin(self) -> None:
        allowed = allowed_modification_types(THIN_SAMPLE_RESULT)
        self.assertIn(MODIFICATION_ASSET_TIMEFRAME_CHANGE, allowed)


class RepairCandidatesFileTest(unittest.TestCase):
    def test_the_real_repair_candidates_file_loads_and_contains_the_known_precedent(self) -> None:
        self.assertTrue(DEFAULT_REPAIR_CANDIDATES_PATH.exists())
        candidates = load_repair_candidates()
        names = [c["hypothesis_name"] for c in candidates]
        self.assertIn("RMR_CONFIRMATION_METALS_WEEKLY", names)


class DirectionAddMirrorValidationTest(unittest.TestCase):
    def test_a_correct_mirror_is_approved(self) -> None:
        # Matches this project's own REAL precedent exactly (EXT_ADX_RANGE_V3/
        # V4_BTC_1D, tools/external_candidates_formal_test.py): the shared ADX
        # regime condition is left COMPLETELY UNCHANGED, and the directional
        # condition mirrors "close < bb_lower" to "close > bb_upper" -- same
        # field (close), op flipped (lt->gt), compare_to_field swapped to its
        # natural opposite-side companion. This is NOT the literal output of
        # calling rule_dsl.mirror_condition() on every condition (that would
        # keep compare_to_field as bb_lower) -- see _is_legitimate_direction_
        # mirror's own docstring for why that stricter check would incorrectly
        # reject this project's own already-accepted real hypothesis shape.
        proposal = {
            "modification_type": MODIFICATION_DIRECTION_ADD_MIRROR,
            "structured_entry_rule": ORIGINAL_HYPOTHESIS["structured_entry_rule"],
            "structured_entry_rule_short": {
                "conditions": [
                    {"field": "close", "op": "gt", "compare_to_field": "bb_upper"},
                    {"field": "adx14", "op": "lt", "value": 25.0},
                ],
            },
            "structured_exit_plan": ORIGINAL_HYPOTHESIS["structured_exit_plan"],
            "asset": "ETH", "timeframe": "4h",
        }
        result = validate_modification(ORIGINAL_HYPOTHESIS, proposal, [])
        self.assertTrue(result.approved, result.reason)

    def test_missing_short_rule_is_rejected(self) -> None:
        proposal = {
            "modification_type": MODIFICATION_DIRECTION_ADD_MIRROR,
            "structured_entry_rule": ORIGINAL_HYPOTHESIS["structured_entry_rule"],
            "structured_entry_rule_short": None,
            "structured_exit_plan": ORIGINAL_HYPOTHESIS["structured_exit_plan"],
            "asset": "ETH", "timeframe": "4h",
        }
        result = validate_modification(ORIGINAL_HYPOTHESIS, proposal, [])
        self.assertFalse(result.approved)
        self.assertIn("nothing was added", result.reason)

    def test_a_short_rule_that_is_not_the_exact_mirror_is_rejected(self) -> None:
        proposal = {
            "modification_type": MODIFICATION_DIRECTION_ADD_MIRROR,
            "structured_entry_rule": ORIGINAL_HYPOTHESIS["structured_entry_rule"],
            # wrong: adx14 threshold changed to 30 instead of staying 25 (not the exact mirror)
            "structured_entry_rule_short": {
                "conditions": [
                    {"field": "close", "op": "gt", "compare_to_field": "bb_upper"},
                    {"field": "adx14", "op": "lt", "value": 30.0},
                ],
            },
            "structured_exit_plan": ORIGINAL_HYPOTHESIS["structured_exit_plan"],
            "asset": "ETH", "timeframe": "4h",
        }
        result = validate_modification(ORIGINAL_HYPOTHESIS, proposal, [])
        self.assertFalse(result.approved)
        self.assertIn("not a legitimate mirror", result.reason)

    def test_a_short_rule_that_swaps_the_tested_field_entirely_is_rejected(self) -> None:
        proposal = {
            "modification_type": MODIFICATION_DIRECTION_ADD_MIRROR,
            "structured_entry_rule": ORIGINAL_HYPOTHESIS["structured_entry_rule"],
            # field swapped from "close" to "rsi14" -- not a mirror of the same mechanism at all
            "structured_entry_rule_short": {
                "conditions": [
                    {"field": "rsi14", "op": "gt", "value": 70.0},
                    {"field": "adx14", "op": "lt", "value": 25.0},
                ],
            },
            "structured_exit_plan": ORIGINAL_HYPOTHESIS["structured_exit_plan"],
            "asset": "ETH", "timeframe": "4h",
        }
        result = validate_modification(ORIGINAL_HYPOTHESIS, proposal, [])
        self.assertFalse(result.approved)
        self.assertIn("not a legitimate mirror", result.reason)

    def test_direction_add_mirror_that_also_changes_the_long_rule_is_rejected(self) -> None:
        mutated_long = {
            "conditions": [
                {"field": "close", "op": "lt", "compare_to_field": "bb_lower"},
                {"field": "adx14", "op": "lt", "value": 20.0},  # changed from 25 to 20
            ],
        }
        proposal = {
            "modification_type": MODIFICATION_DIRECTION_ADD_MIRROR,
            "structured_entry_rule": mutated_long,
            "structured_entry_rule_short": {
                "conditions": [
                    {"field": "close", "op": "gt", "compare_to_field": "bb_upper"},
                    {"field": "adx14", "op": "lt", "value": 20.0},
                ],
            },
            "structured_exit_plan": ORIGINAL_HYPOTHESIS["structured_exit_plan"],
            "asset": "ETH", "timeframe": "4h",
        }
        result = validate_modification(ORIGINAL_HYPOTHESIS, proposal, [])
        self.assertFalse(result.approved)
        self.assertIn("byte-identical", result.reason)


class AssetTimeframeChangeValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repair_candidates = load_repair_candidates()
        self.rmr_original = {
            "hypothesis_name": "RMR_CONFIRMATION_BTC_1D", "asset": "BTC", "timeframe": "1d",
            "structured_entry_rule": {"conditions": [{"field": "adx14", "op": "lt", "value": 25.0}]},
            "structured_exit_plan": {"stop_atr_multiple": 2.0, "target_r_multiple": 2.0, "max_holding_hours": 480.0},
        }

    def test_target_supported_by_the_real_repair_candidates_file_is_approved(self) -> None:
        proposal = {
            "modification_type": MODIFICATION_ASSET_TIMEFRAME_CHANGE,
            "structured_entry_rule": self.rmr_original["structured_entry_rule"],
            "structured_entry_rule_short": None,
            "structured_exit_plan": self.rmr_original["structured_exit_plan"],
            "asset": "GOLD", "timeframe": "1week",
            "failure_attribution": "sample_thinness",
        }
        result = validate_modification(self.rmr_original, proposal, self.repair_candidates)
        self.assertTrue(result.approved, result.reason)
        self.assertIn("RMR_CONFIRMATION_METALS_WEEKLY", result.reason)

    def test_target_with_no_support_in_repair_candidates_json_is_rejected(self) -> None:
        proposal = {
            "modification_type": MODIFICATION_ASSET_TIMEFRAME_CHANGE,
            "structured_entry_rule": self.rmr_original["structured_entry_rule"],
            "structured_entry_rule_short": None,
            "structured_exit_plan": self.rmr_original["structured_exit_plan"],
            "asset": "USD/CAD", "timeframe": "1h",  # not named anywhere in repair_candidates.json
            "failure_attribution": "sample_thinness",
        }
        result = validate_modification(self.rmr_original, proposal, self.repair_candidates)
        self.assertFalse(result.approved)
        self.assertIn("no supporting evidence", result.reason)

    def test_mechanism_attribution_instead_of_sample_thinness_is_rejected_even_with_a_supported_target(self) -> None:
        proposal = {
            "modification_type": MODIFICATION_ASSET_TIMEFRAME_CHANGE,
            "structured_entry_rule": self.rmr_original["structured_entry_rule"],
            "structured_entry_rule_short": None,
            "structured_exit_plan": self.rmr_original["structured_exit_plan"],
            "asset": "GOLD", "timeframe": "1week",
            "failure_attribution": "mechanism",
        }
        result = validate_modification(self.rmr_original, proposal, self.repair_candidates)
        self.assertFalse(result.approved)
        self.assertIn("sample thinness", result.reason)

    def test_changing_the_mechanism_alongside_the_asset_is_rejected(self) -> None:
        mutated_exit = {"stop_atr_multiple": 3.0, "target_r_multiple": 2.0, "max_holding_hours": 480.0}
        proposal = {
            "modification_type": MODIFICATION_ASSET_TIMEFRAME_CHANGE,
            "structured_entry_rule": self.rmr_original["structured_entry_rule"],
            "structured_entry_rule_short": None,
            "structured_exit_plan": mutated_exit,
            "asset": "GOLD", "timeframe": "1week",
            "failure_attribution": "sample_thinness",
        }
        result = validate_modification(self.rmr_original, proposal, self.repair_candidates)
        self.assertFalse(result.approved)
        self.assertIn("byte-identical", result.reason)

    def test_unchanged_asset_timeframe_with_this_type_is_rejected(self) -> None:
        proposal = {
            "modification_type": MODIFICATION_ASSET_TIMEFRAME_CHANGE,
            "structured_entry_rule": self.rmr_original["structured_entry_rule"],
            "structured_entry_rule_short": None,
            "structured_exit_plan": self.rmr_original["structured_exit_plan"],
            "asset": "BTC", "timeframe": "1d",
            "failure_attribution": "sample_thinness",
        }
        result = validate_modification(self.rmr_original, proposal, self.repair_candidates)
        self.assertFalse(result.approved)
        self.assertIn("nothing was actually changed", result.reason)


class EntryThresholdAndExitStructureValidationTest(unittest.TestCase):
    def test_a_pure_threshold_retune_is_approved(self) -> None:
        proposal = {
            "modification_type": MODIFICATION_ENTRY_THRESHOLD,
            "structured_entry_rule": {
                "conditions": [
                    {"field": "close", "op": "lt", "compare_to_field": "bb_lower"},
                    {"field": "adx14", "op": "lt", "value": 20.0},  # retuned from 25.0
                ],
            },
            "structured_entry_rule_short": None,
            "structured_exit_plan": ORIGINAL_HYPOTHESIS["structured_exit_plan"],
            "asset": "ETH", "timeframe": "4h",
        }
        result = validate_modification(ORIGINAL_HYPOTHESIS, proposal, [])
        self.assertTrue(result.approved, result.reason)

    def test_a_structural_entry_change_disguised_as_a_threshold_is_rejected(self) -> None:
        proposal = {
            "modification_type": MODIFICATION_ENTRY_THRESHOLD,
            "structured_entry_rule": {
                # extra condition added -- this is a structural change, not a threshold retune
                "conditions": [
                    {"field": "close", "op": "lt", "compare_to_field": "bb_lower"},
                    {"field": "adx14", "op": "lt", "value": 25.0},
                    {"field": "rsi14", "op": "lt", "value": 30.0},
                ],
            },
            "structured_entry_rule_short": None,
            "structured_exit_plan": ORIGINAL_HYPOTHESIS["structured_exit_plan"],
            "asset": "ETH", "timeframe": "4h",
        }
        result = validate_modification(ORIGINAL_HYPOTHESIS, proposal, [])
        self.assertFalse(result.approved)
        self.assertIn("structure, not just a threshold", result.reason)

    def test_exit_structure_change_with_unchanged_entry_is_approved(self) -> None:
        proposal = {
            "modification_type": MODIFICATION_EXIT_STRUCTURE,
            "structured_entry_rule": ORIGINAL_HYPOTHESIS["structured_entry_rule"],
            "structured_entry_rule_short": None,
            "structured_exit_plan": {
                "stop_pct_of_entry": 0.015,
                "dynamic_target_condition": {"field": "close", "op": "gte", "compare_to_field": "ma20"},
                "regime_break_condition": {"field": "adx14", "op": "gte", "value": 28.0},
                "regime_break_consecutive_bars": 2,
            },
            "asset": "ETH", "timeframe": "4h",
        }
        result = validate_modification(ORIGINAL_HYPOTHESIS, proposal, [])
        self.assertTrue(result.approved, result.reason)

    def test_exit_structure_that_also_changes_the_entry_rule_is_rejected(self) -> None:
        proposal = {
            "modification_type": MODIFICATION_EXIT_STRUCTURE,
            "structured_entry_rule": {"conditions": [{"field": "adx14", "op": "lt", "value": 25.0}]},
            "structured_entry_rule_short": None,
            "structured_exit_plan": {"stop_pct_of_entry": 0.01, "target_pct_of_entry": 0.02},
            "asset": "ETH", "timeframe": "4h",
        }
        result = validate_modification(ORIGINAL_HYPOTHESIS, proposal, [])
        self.assertFalse(result.approved)
        self.assertIn("byte-identical", result.reason)

    def test_out_of_boundary_modification_type_is_rejected(self) -> None:
        proposal = {
            "modification_type": "invent_a_completely_new_strategy",
            "structured_entry_rule": ORIGINAL_HYPOTHESIS["structured_entry_rule"],
            "structured_entry_rule_short": None,
            "structured_exit_plan": ORIGINAL_HYPOTHESIS["structured_exit_plan"],
            "asset": "ETH", "timeframe": "4h",
        }
        result = validate_modification(ORIGINAL_HYPOTHESIS, proposal, [])
        self.assertFalse(result.approved)
        self.assertIn("not one of the approved repair-scope types", result.reason)

    def test_asset_change_smuggled_into_entry_threshold_type_is_rejected(self) -> None:
        proposal = {
            "modification_type": MODIFICATION_ENTRY_THRESHOLD,
            "structured_entry_rule": ORIGINAL_HYPOTHESIS["structured_entry_rule"],
            "structured_entry_rule_short": None,
            "structured_exit_plan": ORIGINAL_HYPOTHESIS["structured_exit_plan"],
            "asset": "BTC", "timeframe": "4h",  # sneaking in an asset change under the wrong type
        }
        result = validate_modification(ORIGINAL_HYPOTHESIS, proposal, [])
        self.assertFalse(result.approved)
        self.assertIn("must keep asset/timeframe unchanged", result.reason)


class _FakeResponse:
    def __init__(self, payload: dict, status_ok: bool = True, status_code: int = 200) -> None:
        self._payload = payload
        self._status_ok = status_ok
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if not self._status_ok:
            raise requests_module.HTTPError("bad status")

    def json(self) -> dict:
        return self._payload


class ProposeModificationLlmCallTest(unittest.TestCase):
    def test_no_api_key_makes_no_call(self) -> None:
        with patch("nero_core.research_agent.repair_lab.requests.post") as mock_post:
            result = propose_modification(ORIGINAL_HYPOTHESIS, ADEQUATE_SAMPLE_RESULT, [], "")
        mock_post.assert_not_called()
        self.assertIsNone(result.proposal)
        self.assertIn("no Claude API key", result.error)

    def test_successful_call_parses_the_proposal_and_reports_real_cost(self) -> None:
        # propose_modification's own preflight (validate_api_key, imported
        # from hypothesis_gen.py rather than re-inlined) makes its requests.post
        # call from INSIDE hypothesis_gen's own module namespace -- a patch on
        # repair_lab.requests.post alone would leave that call hitting the real
        # network, so both call sites are mocked here.
        proposal_json = {
            "modification_type": "entry_threshold", "modification_summary": "x", "diagnosis_basis": "y",
            "failure_attribution": "mechanism",
            "structured_entry_rule": ORIGINAL_HYPOTHESIS["structured_entry_rule"],
            "structured_entry_rule_short": None,
            "structured_exit_plan": ORIGINAL_HYPOTHESIS["structured_exit_plan"],
            "asset": "ETH", "timeframe": "4h",
        }
        payload = {
            "content": [{"type": "text", "text": json.dumps(proposal_json)}],
            "usage": {"input_tokens": 1000, "output_tokens": 200},
        }
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse({})), \
             patch("nero_core.research_agent.repair_lab.requests.post", return_value=_FakeResponse(payload)):
            result = propose_modification(ORIGINAL_HYPOTHESIS, ADEQUATE_SAMPLE_RESULT, [], "fake-key")
        self.assertIsNone(result.error)
        self.assertEqual(result.proposal["modification_type"], "entry_threshold")
        self.assertGreater(result.cost_usd, 0.0)

    def test_401_raises_api_key_rejected(self) -> None:
        from nero_core.research_agent.repair_lab import ApiKeyRejectedError

        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse({}, status_code=401)):
            with self.assertRaises(ApiKeyRejectedError):
                propose_modification(ORIGINAL_HYPOTHESIS, ADEQUATE_SAMPLE_RESULT, [], "fake-key")

    def test_unparseable_response_is_reported_as_billed_error_not_raised(self) -> None:
        payload = {"content": [{"type": "text", "text": "not json"}], "usage": {"input_tokens": 500, "output_tokens": 50}}
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse({})), \
             patch("nero_core.research_agent.repair_lab.requests.post", return_value=_FakeResponse(payload)):
            result = propose_modification(ORIGINAL_HYPOTHESIS, ADEQUATE_SAMPLE_RESULT, [], "fake-key")
        self.assertIsNone(result.proposal)
        self.assertIn("call WAS billed", result.error)
        self.assertGreater(result.cost_usd, 0.0)


if __name__ == "__main__":
    unittest.main()
