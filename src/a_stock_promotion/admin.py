"""In-memory strategy management for the V1.0 admin module.

PRD §4.2 V1.0 lists 桌面端/管理端 with 策略管理 as a deliverable.  The
admin module exposes a simple, thread-safe CRUD store on top of
:class:`~a_stock_promotion.models.StrategyProfile` so that operators
can:

* List, fetch, create, update and delete custom screening strategies
  alongside the built-in templates.
* Mark which entries are built-in (read-only) to prevent accidental
  destruction of bundled templates.

The store keeps everything in-process so it has no external storage
dependency.  Persistence (PostgreSQL, etc.) is layered on top in
production by replacing :class:`StrategyRegistry` with a thin adapter
that implements the same interface.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .models import StrategyProfile, StrategyRule
from .strategies import list_builtin_strategies

CombineMode = Any  # narrowed via validation below


@dataclass(frozen=True)
class StrategyRecord:
    """Registry record wrapping a strategy with admin metadata."""

    strategy: StrategyProfile
    is_builtin: bool = False

    def as_dict(self) -> dict:
        return {
            "name": self.strategy.name,
            "combine_mode": self.strategy.combine_mode,
            "min_score": self.strategy.min_score,
            "is_builtin": self.is_builtin,
            "rules": [
                {
                    "metric": rule.metric,
                    "operator": rule.operator,
                    "threshold": rule.threshold,
                    "weight": rule.weight,
                    "required": rule.required,
                    "description": rule.description,
                }
                for rule in self.strategy.rules
            ],
        }


class StrategyRegistryError(Exception):
    """Raised for admin-level errors (duplicate name, builtin write …)."""


class StrategyRegistry:
    """Thread-safe in-memory registry of strategy templates."""

    def __init__(
        self,
        builtin_strategies: Iterable[StrategyProfile] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._records: dict[str, StrategyRecord] = {}
        templates = (
            list(builtin_strategies)
            if builtin_strategies is not None
            else list_builtin_strategies()
        )
        for strategy in templates:
            self._records[strategy.name] = StrategyRecord(
                strategy=strategy, is_builtin=True
            )

    # ---- Read --------------------------------------------------------------

    def list(self) -> list[StrategyRecord]:
        with self._lock:
            return list(self._records.values())

    def get(self, name: str) -> StrategyRecord | None:
        with self._lock:
            return self._records.get(name)

    def list_strategies(self) -> list[StrategyProfile]:
        """Return only the :class:`StrategyProfile` instances."""

        with self._lock:
            return [record.strategy for record in self._records.values()]

    # ---- Write -------------------------------------------------------------

    def create(self, payload: Mapping[str, Any]) -> StrategyRecord:
        strategy = _strategy_from_payload(payload)
        with self._lock:
            if strategy.name in self._records:
                raise StrategyRegistryError(f"strategy already exists: {strategy.name}")
            record = StrategyRecord(strategy=strategy, is_builtin=False)
            self._records[strategy.name] = record
            return record

    def update(self, name: str, payload: Mapping[str, Any]) -> StrategyRecord:
        with self._lock:
            existing = self._records.get(name)
            if existing is None:
                raise StrategyRegistryError(f"strategy not found: {name}")
            if existing.is_builtin:
                raise StrategyRegistryError(
                    f"built-in strategy is read-only: {name}"
                )
            merged = dict(payload)
            # Allow renaming, but default to the existing name when not provided.
            merged.setdefault("name", name)
            strategy = _strategy_from_payload(merged)
            if strategy.name != name and strategy.name in self._records:
                raise StrategyRegistryError(
                    f"strategy already exists: {strategy.name}"
                )
            record = StrategyRecord(strategy=strategy, is_builtin=False)
            self._records.pop(name, None)
            self._records[strategy.name] = record
            return record

    def delete(self, name: str) -> None:
        with self._lock:
            existing = self._records.get(name)
            if existing is None:
                raise StrategyRegistryError(f"strategy not found: {name}")
            if existing.is_builtin:
                raise StrategyRegistryError(
                    f"built-in strategy is read-only: {name}"
                )
            self._records.pop(name)


# ---------------------------------------------------------------------------
# Payload validation
# ---------------------------------------------------------------------------
_ALLOWED_OPERATORS = {">", ">=", "<", "<=", "==", "!="}


def _strategy_from_payload(payload: Mapping[str, Any]) -> StrategyProfile:
    """Validate untrusted input and build a :class:`StrategyProfile`.

    Raises :class:`StrategyRegistryError` with a human-readable message
    on any validation failure so the API layer can return a 400.
    """

    if not isinstance(payload, Mapping):
        raise StrategyRegistryError("payload must be an object")
    raw = copy.deepcopy(dict(payload))

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise StrategyRegistryError("name is required")
    name = name.strip()
    if len(name) > 64:
        raise StrategyRegistryError("name must be at most 64 characters")

    combine_mode = raw.get("combine_mode", "and")
    if combine_mode not in {"and", "or"}:
        raise StrategyRegistryError("combine_mode must be 'and' or 'or'")

    min_score = raw.get("min_score", 0.0)
    try:
        min_score = float(min_score)
    except (TypeError, ValueError) as exc:
        raise StrategyRegistryError("min_score must be a number") from exc
    if not 0 <= min_score <= 1:
        raise StrategyRegistryError("min_score must be between 0 and 1")

    rules_payload = raw.get("rules")
    if not isinstance(rules_payload, list) or not rules_payload:
        raise StrategyRegistryError("rules must be a non-empty list")
    if len(rules_payload) > 32:
        raise StrategyRegistryError("rules must contain at most 32 entries")

    rules: list[StrategyRule] = []
    for index, rule_payload in enumerate(rules_payload):
        if not isinstance(rule_payload, Mapping):
            raise StrategyRegistryError(f"rule #{index} must be an object")
        metric = rule_payload.get("metric")
        if not isinstance(metric, str) or not metric.strip():
            raise StrategyRegistryError(f"rule #{index}: metric is required")
        operator_ = rule_payload.get("operator")
        if operator_ not in _ALLOWED_OPERATORS:
            raise StrategyRegistryError(
                f"rule #{index}: operator must be one of {sorted(_ALLOWED_OPERATORS)}"
            )
        threshold = rule_payload.get("threshold")
        try:
            threshold = float(threshold)
        except (TypeError, ValueError) as exc:
            raise StrategyRegistryError(
                f"rule #{index}: threshold must be a number"
            ) from exc
        weight = rule_payload.get("weight", 1.0)
        try:
            weight = float(weight)
        except (TypeError, ValueError) as exc:
            raise StrategyRegistryError(
                f"rule #{index}: weight must be a number"
            ) from exc
        if weight < 0:
            raise StrategyRegistryError(f"rule #{index}: weight must be >= 0")
        required = bool(rule_payload.get("required", False))
        description = str(rule_payload.get("description", ""))
        if len(description) > 200:
            raise StrategyRegistryError(
                f"rule #{index}: description must be at most 200 characters"
            )
        rules.append(
            StrategyRule(
                metric=metric.strip(),
                operator=operator_,
                threshold=threshold,
                weight=weight,
                required=required,
                description=description,
            )
        )

    return StrategyProfile(
        name=name,
        rules=tuple(rules),
        combine_mode=combine_mode,
        min_score=min_score,
    )


__all__ = [
    "StrategyRecord",
    "StrategyRegistry",
    "StrategyRegistryError",
]
