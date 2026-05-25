"""Tests for the built-in strategy template catalogue."""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from a_stock_promotion import list_builtin_strategies
from a_stock_promotion.strategies import (
    bollinger_breakout_strategy,
    dragon_tiger_strategy,
    growth_stock_strategy,
    industry_etf_rotation_strategy,
    low_volatility_etf_strategy,
    momentum_reversal_strategy,
    northbound_capital_strategy,
    sector_rotation_strategy,
    trend_following_strategy,
    value_blue_chip_strategy,
)


class BuiltinStrategyCatalogTest(unittest.TestCase):
    def test_at_least_ten_builtin_templates(self):
        """PRD §7 acceptance criterion: 至少10个内置策略模板."""

        strategies = list_builtin_strategies()
        self.assertGreaterEqual(len(strategies), 10)

    def test_template_names_are_unique(self):
        names = [strategy.name for strategy in list_builtin_strategies()]
        self.assertEqual(len(set(names)), len(names))

    def test_every_template_has_at_least_one_rule(self):
        for strategy in list_builtin_strategies():
            with self.subTest(strategy=strategy.name):
                self.assertGreater(len(strategy.rules), 0)

    def test_individual_factories_return_expected_names(self):
        # Spot-check several templates so refactors that rename them fail loudly.
        self.assertEqual(trend_following_strategy().name, "技术趋势跟随策略")
        self.assertEqual(momentum_reversal_strategy().name, "超跌反转策略")
        self.assertEqual(bollinger_breakout_strategy().name, "布林带突破策略")
        self.assertEqual(value_blue_chip_strategy().name, "价值蓝筹策略")
        self.assertEqual(growth_stock_strategy().name, "高成长策略")
        self.assertEqual(northbound_capital_strategy().name, "北向资金跟随策略")
        self.assertEqual(dragon_tiger_strategy().name, "龙虎榜强势策略")
        self.assertEqual(sector_rotation_strategy().name, "板块轮动策略")
        self.assertEqual(low_volatility_etf_strategy().name, "ETF低波动稳健策略")
        self.assertEqual(industry_etf_rotation_strategy().name, "行业ETF轮动策略")


if __name__ == "__main__":
    unittest.main()
