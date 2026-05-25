"""Core rule engine for explainable stock and ETF screening."""

from __future__ import annotations

import operator
from collections.abc import Iterable

from .models import SelectionResult, StockMetrics, StrategyProfile, StrategyRule

_OPERATORS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}


class SelectionEngine:
    """Evaluate candidates against a strategy profile."""

    def rank(
        self,
        candidates: Iterable[StockMetrics],
        strategy: StrategyProfile,
    ) -> list[SelectionResult]:
        results = [self.evaluate(candidate, strategy) for candidate in candidates]
        return sorted(results, key=lambda item: (-item.score, item.candidate.symbol))

    def evaluate(self, candidate: StockMetrics, strategy: StrategyProfile) -> SelectionResult:
        matched: list[str] = []
        missed: list[str] = []
        matched_weight = 0.0
        total_weight = sum(rule.weight for rule in strategy.rules)
        required_missed = False

        for rule in strategy.rules:
            if self._matches(candidate, rule):
                matched.append(self._describe(rule))
                matched_weight += rule.weight
            else:
                missed.append(self._describe(rule))
                required_missed = required_missed or rule.required

        score = matched_weight / total_weight if total_weight else 0.0
        selected = self._is_selected(strategy, score, matched, required_missed)
        return SelectionResult(
            candidate=candidate,
            score=round(score, 4),
            selected=selected,
            matched_rules=tuple(matched),
            missed_rules=tuple(missed),
        )

    def _matches(self, candidate: StockMetrics, rule: StrategyRule) -> bool:
        value = candidate.get(rule.metric)
        if value is None:
            return False
        comparator = _OPERATORS.get(rule.operator)
        if comparator is None:
            raise ValueError(f"unsupported operator: {rule.operator}")
        return bool(comparator(value, rule.threshold))

    def _is_selected(
        self,
        strategy: StrategyProfile,
        score: float,
        matched: list[str],
        required_missed: bool,
    ) -> bool:
        if required_missed or score < strategy.min_score:
            return False
        if strategy.combine_mode == "and":
            return len(matched) == len(strategy.rules)
        return bool(matched)

    def _describe(self, rule: StrategyRule) -> str:
        if rule.description:
            return rule.description
        return f"{rule.metric} {rule.operator} {rule.threshold}"
