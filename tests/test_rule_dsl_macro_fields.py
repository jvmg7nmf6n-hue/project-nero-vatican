"""CC-1 master directive (2026-08-07), Part B Rung 2: wiring the 4 confirmed-real
Bellwether macro fields (real_yield_10y_chg20, dxy_chg20, vix_chg20,
funding_rate_bps) into the Research Agent's rule DSL. Covers B2b's structural
provenance enforcement and the attach_macro/rule_references_macro_fields
mechanism in nero_core/research_agent/rule_dsl.py.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from nero_core.research_agent.rule_dsl import (
    ALLOWED_FIELDS,
    FIELD_PROVENANCE,
    FIELD_PROVENANCE_DERIVED,
    FIELD_PROVENANCE_REAL,
    FIELD_PROVENANCE_SYNTHETIC,
    FIELD_PROVENANCE_UNAVAILABLE,
    MACRO_CONDITION_FIELDS,
    Condition,
    StructuredRule,
    compute_indicator_frame,
    rule_references_macro_fields,
    validate_field_provenance,
)

HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS


def _daily_candles(n: int = 60) -> pd.DataFrame:
    rows = []
    start = 1_700_000_000_000
    for i in range(n):
        close = 100.0 + (i % 5)
        rows.append({
            "close_time": start + i * DAY_MS, "open": close, "high": close + 1.0,
            "low": close - 1.0, "close": close, "volume": 10.0,
        })
    return pd.DataFrame(rows)


class MacroFieldsAreAllowedTest(unittest.TestCase):
    def test_all_4_macro_fields_are_in_allowed_fields(self) -> None:
        for field in MACRO_CONDITION_FIELDS:
            self.assertIn(field, ALLOWED_FIELDS)

    def test_exactly_4_macro_fields_no_more_no_fewer(self) -> None:
        # Deliberately a snapshot test -- OUT OF SCOPE explicitly forbids
        # wiring any of Bellwether's other 11 agents into this DSL. If this
        # ever needs to grow, that must be a conscious, reviewed change, not
        # something that silently expands.
        self.assertEqual(
            set(MACRO_CONDITION_FIELDS),
            {"real_yield_10y_chg20", "dxy_chg20", "vix_chg20", "funding_rate_bps"},
        )


class ValidateFieldProvenanceTest(unittest.TestCase):
    def test_the_real_allowed_fields_and_provenance_pass_today(self) -> None:
        # Sanity: must not raise against the REAL, current module state.
        validate_field_provenance(ALLOWED_FIELDS, FIELD_PROVENANCE)

    def test_every_macro_field_is_declared_real_not_derived(self) -> None:
        for field in MACRO_CONDITION_FIELDS:
            self.assertEqual(FIELD_PROVENANCE[field], FIELD_PROVENANCE_REAL)

    def test_raises_if_a_field_has_no_provenance_declaration(self) -> None:
        with self.assertRaises(RuntimeError):
            validate_field_provenance(("close", "some_new_field"), {"close": FIELD_PROVENANCE_DERIVED})

    def test_raises_if_a_field_is_declared_synthetic(self) -> None:
        # B2b's exact requirement: a field whose live-mode provenance is
        # synthetic can never be in ALLOWED_FIELDS, even by mistake later.
        with self.assertRaises(RuntimeError):
            validate_field_provenance(
                ("close", "fake_macro_field"),
                {"close": FIELD_PROVENANCE_DERIVED, "fake_macro_field": FIELD_PROVENANCE_SYNTHETIC},
            )

    def test_raises_if_a_field_is_declared_unavailable(self) -> None:
        with self.assertRaises(RuntimeError):
            validate_field_provenance(
                ("close", "fake_macro_field"),
                {"close": FIELD_PROVENANCE_DERIVED, "fake_macro_field": FIELD_PROVENANCE_UNAVAILABLE},
            )

    def test_derived_and_real_fields_together_pass(self) -> None:
        validate_field_provenance(
            ("close", "fake_macro_field"),
            {"close": FIELD_PROVENANCE_DERIVED, "fake_macro_field": FIELD_PROVENANCE_REAL},
        )


class RuleReferencesMacroFieldsTest(unittest.TestCase):
    def test_true_when_a_condition_field_is_macro(self) -> None:
        rule = StructuredRule(conditions=(Condition(field="dxy_chg20", op="lt", value=0.0),))
        self.assertTrue(rule_references_macro_fields(rule))

    def test_true_when_a_compare_to_field_is_macro(self) -> None:
        rule = StructuredRule(conditions=(Condition(field="ma20", op="gt", compare_to_field="vix_chg20"),))
        self.assertTrue(rule_references_macro_fields(rule))

    def test_false_for_a_price_only_rule(self) -> None:
        rule = StructuredRule(conditions=(Condition(field="zscore20", op="lt", value=-2.0),))
        self.assertFalse(rule_references_macro_fields(rule))


class ComputeIndicatorFrameMacroAttachmentTest(unittest.TestCase):
    def test_attach_macro_false_by_default_adds_no_macro_columns(self) -> None:
        frame = compute_indicator_frame(_daily_candles())
        for field in MACRO_CONDITION_FIELDS:
            self.assertNotIn(field, frame.columns)

    def test_attach_macro_false_makes_zero_network_or_cache_calls(self) -> None:
        # The default path used by every non-macro hypothesis (the
        # overwhelming majority) must not even ATTEMPT a macro fetch.
        with patch("nero_core.research_agent.rule_dsl._attach_macro_condition_fields") as mock_attach:
            compute_indicator_frame(_daily_candles(), attach_macro=False)
        mock_attach.assert_not_called()

    def test_attach_macro_true_adds_all_4_columns_when_fetches_succeed(self) -> None:
        candles = _daily_candles(200)
        fake_series = pd.Series(
            [1.0] * 200, index=pd.date_range("2020-01-01", periods=200, freq="D"), name="value",
        )

        def _fake_fetch():
            return fake_series, "FAKE"

        fake_funding = type("R", (), {"settlements": pd.DataFrame({
            "settlement_date": pd.date_range("2020-01-01", periods=200, freq="D", tz="UTC"),
            "funding_rate": [0.0001] * 200,
        })})()

        with patch("nero_core.data_sources.macro_data.fetch_dfii10_daily", side_effect=_fake_fetch), \
             patch("nero_core.data_sources.macro_data.fetch_dxy_daily", side_effect=_fake_fetch), \
             patch("nero_core.data_sources.macro_data.fetch_vix_daily", side_effect=_fake_fetch), \
             patch("nero_core.data_sources.funding_data.load_funding_history", return_value=fake_funding):
            frame = compute_indicator_frame(candles, attach_macro=True)

        for field in MACRO_CONDITION_FIELDS:
            self.assertIn(field, frame.columns)

    def test_one_fields_fetch_failure_leaves_only_that_column_absent(self) -> None:
        # Never guess a substitute -- an independent per-field degrade, not
        # an all-or-nothing failure across the 4 fields.
        from nero_core.data_sources.macro_data import MacroDataUnavailableError

        candles = _daily_candles(200)
        fake_series = pd.Series(
            [1.0] * 200, index=pd.date_range("2020-01-01", periods=200, freq="D"), name="value",
        )

        def _fake_fetch():
            return fake_series, "FAKE"

        def _failing_fetch():
            raise MacroDataUnavailableError("simulated outage")

        fake_funding = type("R", (), {"settlements": pd.DataFrame({
            "settlement_date": pd.date_range("2020-01-01", periods=200, freq="D", tz="UTC"),
            "funding_rate": [0.0001] * 200,
        })})()

        with patch("nero_core.data_sources.macro_data.fetch_dfii10_daily", side_effect=_failing_fetch), \
             patch("nero_core.data_sources.macro_data.fetch_dxy_daily", side_effect=_fake_fetch), \
             patch("nero_core.data_sources.macro_data.fetch_vix_daily", side_effect=_fake_fetch), \
             patch("nero_core.data_sources.funding_data.load_funding_history", return_value=fake_funding):
            frame = compute_indicator_frame(candles, attach_macro=True)

        self.assertNotIn("real_yield_10y_chg20", frame.columns)
        self.assertIn("dxy_chg20", frame.columns)
        self.assertIn("vix_chg20", frame.columns)
        self.assertIn("funding_rate_bps", frame.columns)


if __name__ == "__main__":
    unittest.main()
