"""Tests covering TEST_PLAN.md §2 gaps for the selection engine."""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from a_stock_promotion import (
    SelectionEngine,
    StockMetrics,
    StrategyProfile,
    StrategyRule,
)


class ComparisonOperatorTest(unittest.TestCase):
    """All six comparison operators must be supported (TEST_PLAN §2)."""

    def setUp(self):
        self.engine = SelectionEngine()
        self.candidate = StockMetrics("000001", "示例", {"roe": 10.0})

    def _evaluate(self, operator: str, threshold: float) -> bool:
        strategy = StrategyProfile(
            name="op-test",
            combine_mode="and",
            rules=(StrategyRule("roe", operator, threshold),),  # type: ignore[arg-type]
        )
        return self.engine.evaluate(self.candidate, strategy).selected

    def test_greater_than(self):
        self.assertTrue(self._evaluate(">", 9))
        self.assertFalse(self._evaluate(">", 10))

    def test_greater_or_equal(self):
        self.assertTrue(self._evaluate(">=", 10))
        self.assertFalse(self._evaluate(">=", 11))

    def test_less_than(self):
        self.assertTrue(self._evaluate("<", 11))
        self.assertFalse(self._evaluate("<", 10))

    def test_less_or_equal(self):
        self.assertTrue(self._evaluate("<=", 10))
        self.assertFalse(self._evaluate("<=", 9))

    def test_equality(self):
        self.assertTrue(self._evaluate("==", 10))
        self.assertFalse(self._evaluate("==", 9))

    def test_inequality(self):
        self.assertTrue(self._evaluate("!=", 9))
        self.assertFalse(self._evaluate("!=", 10))


class EdgeCaseTest(unittest.TestCase):
    def setUp(self):
        self.engine = SelectionEngine()

    def test_empty_candidate_iterable_returns_empty_results(self):
        strategy = StrategyProfile(
            name="empty",
            rules=(StrategyRule("roe", ">=", 10),),
        )
        self.assertEqual(self.engine.rank([], strategy), [])

    def test_missing_metric_is_treated_as_miss(self):
        strategy = StrategyProfile(
            name="missing",
            combine_mode="and",
            rules=(
                StrategyRule("roe", ">=", 10, description="ROE门槛"),
                StrategyRule("pe", "<=", 20, description="PE门槛"),
            ),
        )
        candidate = StockMetrics("000002", "缺PE", {"roe": 12})

        result = self.engine.evaluate(candidate, strategy)

        self.assertFalse(result.selected)
        self.assertIn("ROE门槛", result.matched_rules)
        self.assertIn("PE门槛", result.missed_rules)
        # weight-normalised score: 1 of 2 equal-weight rules matched.
        self.assertEqual(result.score, 0.5)

    def test_negative_weight_rejected_at_construction(self):
        with self.assertRaises(ValueError):
            StrategyRule("roe", ">=", 10, weight=-0.1)

    def test_invalid_combine_mode_rejected(self):
        with self.assertRaises(ValueError):
            StrategyProfile(
                name="bad",
                combine_mode="xor",  # type: ignore[arg-type]
                rules=(StrategyRule("roe", ">=", 10),),
            )

    def test_min_score_out_of_range_rejected(self):
        with self.assertRaises(ValueError):
            StrategyProfile(
                name="bad-score",
                min_score=1.5,
                rules=(StrategyRule("roe", ">=", 10),),
            )

    def test_or_strategy_requires_at_least_one_match(self):
        strategy = StrategyProfile(
            name="or-strategy",
            combine_mode="or",
            rules=(
                StrategyRule("roe", ">=", 10),
                StrategyRule("rsi", ">=", 60),
            ),
        )
        no_match = StockMetrics("000003", "无命中", {"roe": 1, "rsi": 10})

        result = self.engine.evaluate(no_match, strategy)

        self.assertFalse(result.selected)
        self.assertEqual(result.matched_rules, ())

    def test_zero_total_weight_does_not_divide_by_zero(self):
        strategy = StrategyProfile(
            name="zero-weight",
            combine_mode="or",
            rules=(StrategyRule("roe", ">=", 10, weight=0),),
        )
        candidate = StockMetrics("000004", "零权重", {"roe": 12})

        result = self.engine.evaluate(candidate, strategy)

        # No total weight ⇒ score is 0 but matched rules still reported.
        self.assertEqual(result.score, 0.0)
        self.assertEqual(len(result.matched_rules), 1)


if __name__ == "__main__":
    unittest.main()
