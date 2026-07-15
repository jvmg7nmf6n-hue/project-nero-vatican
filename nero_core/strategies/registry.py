from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping


class StrategyAlreadyRegisteredError(Exception):
    """Raised when (strategy_id, version) is already registered.

    A registered variant is immutable for life — even re-registering it with the exact
    same parameters is rejected. To change parameters, register a new version string
    instead; never mutate an existing one in place.
    """


class StrategyVersionNotFoundError(Exception):
    """Raised when (strategy_id, version) has not been registered."""


class StrategyNotFoundError(Exception):
    """Raised when strategy_id has no registered versions at all."""


@dataclass(frozen=True)
class StrategyVariant:
    strategy_id: str
    version: str
    parameters: Mapping[str, Any]
    description: str
    registered_at: datetime


class StrategyRegistry:
    """Append-only registry mapping (strategy_id, version) -> immutable parameter set.

    Enforces the project rule that no strategy may silently self-modify its parameters:
    a parameter change must always be registered under a new, explicit version string.
    """

    def __init__(self) -> None:
        self._variants: dict[tuple[str, str], StrategyVariant] = {}

    def register(
        self,
        strategy_id: str,
        version: str,
        parameters: dict[str, Any],
        description: str = "",
    ) -> StrategyVariant:
        key = (strategy_id, version)
        if key in self._variants:
            raise StrategyAlreadyRegisteredError(
                f"{strategy_id!r} version {version!r} is already registered. "
                "Parameters are immutable once registered — register a new version instead "
                "of changing this one."
            )
        variant = StrategyVariant(
            strategy_id=strategy_id,
            version=version,
            parameters=MappingProxyType(dict(parameters)),
            description=description,
            registered_at=datetime.now(timezone.utc),
        )
        self._variants[key] = variant
        return variant

    def get(self, strategy_id: str, version: str) -> StrategyVariant:
        try:
            return self._variants[(strategy_id, version)]
        except KeyError as exc:
            raise StrategyVersionNotFoundError(
                f"No registered variant for strategy_id={strategy_id!r}, version={version!r}."
            ) from exc

    def list_versions(self, strategy_id: str) -> list[StrategyVariant]:
        variants = [v for (sid, _), v in self._variants.items() if sid == strategy_id]
        if not variants:
            raise StrategyNotFoundError(f"No versions registered for strategy_id={strategy_id!r}.")
        return sorted(variants, key=lambda v: v.registered_at)

    def latest(self, strategy_id: str) -> StrategyVariant:
        return self.list_versions(strategy_id)[-1]

    def strategy_ids(self) -> list[str]:
        return sorted({sid for sid, _ in self._variants.keys()})

    def all_variants(self) -> list[StrategyVariant]:
        return sorted(self._variants.values(), key=lambda v: (v.strategy_id, v.registered_at))


default_registry = StrategyRegistry()
