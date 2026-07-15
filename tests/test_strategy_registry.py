from __future__ import annotations

import unittest

from nero_core.strategies.registry import (
    StrategyAlreadyRegisteredError,
    StrategyNotFoundError,
    StrategyRegistry,
    StrategyVersionNotFoundError,
)


class StrategyRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = StrategyRegistry()

    def test_register_new_variant_succeeds(self) -> None:
        variant = self.registry.register(
            "MEAN_REVERSION", "v1", {"rsi_entry_below": 35.0}, description="first cut"
        )

        self.assertEqual(variant.strategy_id, "MEAN_REVERSION")
        self.assertEqual(variant.version, "v1")
        self.assertEqual(variant.parameters["rsi_entry_below"], 35.0)

    def test_changing_parameters_on_existing_version_is_rejected(self) -> None:
        self.registry.register("MEAN_REVERSION", "v1", {"rsi_entry_below": 35.0})

        with self.assertRaises(StrategyAlreadyRegisteredError):
            self.registry.register("MEAN_REVERSION", "v1", {"rsi_entry_below": 30.0})

        # the original parameters must be untouched by the rejected attempt
        stored = self.registry.get("MEAN_REVERSION", "v1")
        self.assertEqual(stored.parameters["rsi_entry_below"], 35.0)

    def test_re_registering_identical_parameters_on_existing_version_is_also_rejected(self) -> None:
        params = {"rsi_entry_below": 35.0}
        self.registry.register("MEAN_REVERSION", "v1", params)

        with self.assertRaises(StrategyAlreadyRegisteredError):
            self.registry.register("MEAN_REVERSION", "v1", dict(params))

    def test_parameter_change_must_go_through_a_new_version(self) -> None:
        self.registry.register("MEAN_REVERSION", "v1", {"rsi_entry_below": 35.0})

        variant_v2 = self.registry.register("MEAN_REVERSION", "v2", {"rsi_entry_below": 30.0})

        self.assertEqual(variant_v2.version, "v2")
        self.assertEqual(variant_v2.parameters["rsi_entry_below"], 30.0)
        # v1 remains available and unchanged
        self.assertEqual(self.registry.get("MEAN_REVERSION", "v1").parameters["rsi_entry_below"], 35.0)

    def test_registered_parameters_are_immutable_from_outside_mutation(self) -> None:
        source = {"rsi_entry_below": 35.0}
        variant = self.registry.register("MEAN_REVERSION", "v1", source)

        source["rsi_entry_below"] = 999.0  # mutating the caller's dict after registration
        with self.assertRaises(TypeError):
            variant.parameters["rsi_entry_below"] = 1.0  # returned mapping itself is read-only

        self.assertEqual(self.registry.get("MEAN_REVERSION", "v1").parameters["rsi_entry_below"], 35.0)

    def test_get_raises_for_unknown_version(self) -> None:
        self.registry.register("MEAN_REVERSION", "v1", {})

        with self.assertRaises(StrategyVersionNotFoundError):
            self.registry.get("MEAN_REVERSION", "v2")

    def test_list_versions_raises_for_unknown_strategy(self) -> None:
        with self.assertRaises(StrategyNotFoundError):
            self.registry.list_versions("UNKNOWN_STRATEGY")

    def test_latest_returns_most_recently_registered_version(self) -> None:
        self.registry.register("MEAN_REVERSION", "v1", {})
        self.registry.register("MEAN_REVERSION", "v2", {})

        self.assertEqual(self.registry.latest("MEAN_REVERSION").version, "v2")

    def test_strategy_ids_and_all_variants_reflect_registrations(self) -> None:
        self.registry.register("MEAN_REVERSION", "v1", {})
        self.registry.register("BREAKOUT_MOMENTUM", "v1", {})

        self.assertEqual(self.registry.strategy_ids(), ["BREAKOUT_MOMENTUM", "MEAN_REVERSION"])
        self.assertEqual(len(self.registry.all_variants()), 2)


if __name__ == "__main__":
    unittest.main()
