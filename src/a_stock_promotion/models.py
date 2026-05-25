"""Domain models for stock and ETF screening."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ComparisonOperator = Literal[">", ">=", "<", "<=", "==", "!="]
CombineMode = Literal["and", "or"]


@dataclass(frozen=True)
class StockMetrics:
    """Normalized metrics for one stock or ETF candidate."""

    symbol: str
    name: str
    metrics: dict[str, float]

    def get(self, metric: str) -> float | None:
        return self.metrics.get(metric)


@dataclass(frozen=True)
class StrategyRule:
    """One rule in a strategy profile."""

    metric: str
    operator: ComparisonOperator
    threshold: float
    weight: float = 1.0
    required: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        if self.weight < 0:
            raise ValueError("rule weight must be non-negative")


@dataclass(frozen=True)
class StrategyProfile:
    """A reusable stock or ETF screening strategy."""

    name: str
    rules: tuple[StrategyRule, ...]
    combine_mode: CombineMode = "and"
    min_score: float = 0.0

    def __post_init__(self) -> None:
        if self.combine_mode not in {"and", "or"}:
            raise ValueError("combine_mode must be 'and' or 'or'")
        if not 0 <= self.min_score <= 1:
            raise ValueError("min_score must be between 0 and 1")


@dataclass(frozen=True)
class SelectionResult:
    """Explainable result for one candidate."""

    candidate: StockMetrics
    score: float
    selected: bool
    matched_rules: tuple[str, ...] = field(default_factory=tuple)
    missed_rules: tuple[str, ...] = field(default_factory=tuple)
