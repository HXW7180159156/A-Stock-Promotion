import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from a_stock_promotion import SelectionEngine, StockMetrics, StrategyProfile, StrategyRule
from a_stock_promotion.strategies import default_etf_strategy, default_stock_strategy


class SelectionEngineTest(unittest.TestCase):
    def setUp(self):
        self.engine = SelectionEngine()

    def test_default_stock_strategy_selects_explainable_candidate(self):
        candidate = StockMetrics(
            symbol="600000",
            name="示例银行",
            metrics={
                "ma_trend": 1,
                "rsi": 58,
                "roe": 12,
                "revenue_growth": 9,
                "debt_ratio": 55,
                "northbound_inflow": 1000,
            },
        )

        result = self.engine.evaluate(candidate, default_stock_strategy())

        self.assertTrue(result.selected)
        self.assertEqual(result.score, 1.0)
        self.assertIn("均线趋势向上", result.matched_rules)
        self.assertEqual(result.missed_rules, ())

    def test_required_rule_miss_rejects_candidate(self):
        candidate = StockMetrics(
            symbol="000001",
            name="示例科技",
            metrics={"ma_trend": 1, "roe": 5, "rsi": 70, "revenue_growth": 20},
        )

        result = self.engine.evaluate(candidate, default_stock_strategy())

        self.assertFalse(result.selected)
        self.assertIn("ROE不低于10%", result.missed_rules)

    def test_and_strategy_requires_all_rules(self):
        candidate = StockMetrics(
            symbol="510300",
            name="沪深300ETF",
            metrics={
                "tracking_error": 0.01,
                "daily_turnover": 80_000_000,
                "fund_size": 1_000_000_000,
                "expense_ratio": 0.005,
                "premium_discount": 0.02,
            },
        )

        result = self.engine.evaluate(candidate, default_etf_strategy())

        self.assertFalse(result.selected)
        self.assertIn("折溢价率不高于1%", result.missed_rules)

    def test_rank_sorts_by_score_then_symbol(self):
        strategy = StrategyProfile(
            name="排序策略",
            combine_mode="or",
            rules=(StrategyRule("roe", ">=", 10), StrategyRule("rsi", ">=", 50)),
        )
        candidates = [
            StockMetrics("000002", "B", {"roe": 8, "rsi": 60}),
            StockMetrics("000001", "A", {"roe": 12, "rsi": 60}),
            StockMetrics("000003", "C", {"roe": 3, "rsi": 20}),
        ]

        results = self.engine.rank(candidates, strategy)

        self.assertEqual([item.candidate.symbol for item in results], ["000001", "000002", "000003"])
        self.assertEqual([item.score for item in results], [1.0, 0.5, 0.0])

    def test_invalid_operator_raises_error(self):
        strategy = StrategyProfile(
            name="非法策略",
            rules=(StrategyRule("roe", "contains", 10),),  # type: ignore[arg-type]
        )
        candidate = StockMetrics("000001", "A", {"roe": 12})

        with self.assertRaises(ValueError):
            self.engine.evaluate(candidate, strategy)


if __name__ == "__main__":
    unittest.main()
