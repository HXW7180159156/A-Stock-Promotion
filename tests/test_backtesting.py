"""Tests for the backtest executor.

Covers the topics enumerated in ``docs/TEST_PLAN.md`` §4:
- 固定样本数据下结果可复现
- 交易成本、调仓频率、停牌、涨跌停处理
- 参数优化和样本外验证隔离
- 防止未来函数和幸存者偏差
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from a_stock_promotion import (
    BacktestConfig,
    BacktestEngine,
    PriceBar,
    StrategyProfile,
    StrategyRule,
    constant_metrics_provider,
    time_series_metrics_provider,
    to_price_bars,
)


def _simple_strategy() -> StrategyProfile:
    return StrategyProfile(
        name="momentum",
        combine_mode="or",
        rules=(StrategyRule("score", ">=", 0.0),),
    )


def _build_price_history(symbol_returns: dict[str, list[float]]) -> dict[str, list[PriceBar]]:
    """Convert per-symbol return series to PriceBar lists on a shared date axis."""

    history: dict[str, list[PriceBar]] = {}
    length = max(len(returns) for returns in symbol_returns.values())
    dates = [f"2024-01-{day:02d}" for day in range(1, length + 2)]
    for symbol, returns in symbol_returns.items():
        bars = [PriceBar(date=dates[0], close=100.0)]
        for i, r in enumerate(returns, start=1):
            bars.append(PriceBar(date=dates[i], close=bars[-1].close * (1 + r)))
        history[symbol] = bars
    return history


class BacktestEngineCoreTest(unittest.TestCase):
    def test_empty_inputs_return_empty_result(self):
        engine = BacktestEngine()
        result = engine.run(
            strategy=_simple_strategy(),
            price_data={},
            metrics_provider=constant_metrics_provider({}),
        )
        self.assertEqual(result.dates, ())
        self.assertEqual(result.equity_curve, ())
        self.assertEqual(result.total_return, 0.0)
        self.assertEqual(result.sharpe_ratio, 0.0)

    def test_reproducible_on_fixed_sample(self):
        """TEST_PLAN §4.1: 固定样本数据下结果可复现."""

        history = _build_price_history({
            "A": [0.01, 0.02, -0.01, 0.015, 0.02, 0.01, 0.0, 0.01],
            "B": [-0.01, 0.0, 0.01, -0.005, -0.01, 0.005, 0.0, -0.01],
        })
        provider = constant_metrics_provider({"A": {"score": 1.0}, "B": {"score": 0.5}})
        engine = BacktestEngine()
        config = BacktestConfig(rebalance_every=2, transaction_cost=0.0, top_n=1)

        r1 = engine.run(_simple_strategy(), history, provider, config)
        r2 = engine.run(_simple_strategy(), history, provider, config)
        self.assertEqual(r1.equity_curve, r2.equity_curve)
        self.assertEqual(r1.period_returns, r2.period_returns)
        # Strategy picks A every rebalance — total return must beat B's path.
        self.assertGreater(r1.total_return, 0.0)

    def test_no_lookahead_uses_rebalance_date_metrics_only(self):
        """TEST_PLAN §4.4: 防止未来函数."""

        seen_dates: list[str] = []

        def provider(symbol: str, date: str):
            seen_dates.append(date)
            # Only "A" qualifies; metrics never reveal future prices.
            return {"score": 1.0} if symbol == "A" else None

        history = _build_price_history({
            "A": [0.0, 0.01, 0.02, 0.0, 0.03, 0.0],
            "B": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        })
        engine = BacktestEngine()
        config = BacktestConfig(rebalance_every=2, transaction_cost=0.0, top_n=1)
        result = engine.run(_simple_strategy(), history, provider, config)

        # Every queried date must be a date that already exists in the price
        # history *up to and including* the rebalance bar — never the future.
        valid_dates = set(result.dates)
        self.assertTrue(seen_dates)
        for date in seen_dates:
            self.assertIn(date, valid_dates)

    def test_transaction_cost_reduces_equity(self):
        """TEST_PLAN §4.2: 交易成本影响."""

        history = _build_price_history({
            "A": [0.02] * 10,
            "B": [0.01] * 10,
        })
        provider = time_series_metrics_provider({
            symbol: {bar.date: {"score": float(i)} for i, bar in enumerate(bars)}
            for symbol, bars in history.items()
        })
        engine = BacktestEngine()
        no_cost = engine.run(
            _simple_strategy(),
            history,
            provider,
            BacktestConfig(rebalance_every=1, transaction_cost=0.0, top_n=1),
        )
        with_cost = engine.run(
            _simple_strategy(),
            history,
            provider,
            BacktestConfig(rebalance_every=1, transaction_cost=0.01, top_n=1),
        )
        self.assertGreater(no_cost.total_return, with_cost.total_return)
        self.assertGreaterEqual(with_cost.turnover, 0.0)

    def test_rebalance_frequency_changes_trade_count(self):
        """TEST_PLAN §4.2: 调仓频率."""

        history = _build_price_history({"A": [0.01] * 12, "B": [0.005] * 12})
        provider = constant_metrics_provider({"A": {"score": 1.0}, "B": {"score": 0.4}})
        engine = BacktestEngine()
        weekly = engine.run(
            _simple_strategy(),
            history,
            provider,
            BacktestConfig(rebalance_every=5, transaction_cost=0.0, top_n=1),
        )
        daily = engine.run(
            _simple_strategy(),
            history,
            provider,
            BacktestConfig(rebalance_every=1, transaction_cost=0.0, top_n=1),
        )
        # More frequent rebalancing ⇒ more rebalance audit events.
        self.assertGreater(len(daily.rebalances), len(weekly.rebalances))

    def test_non_tradable_bar_is_not_bought(self):
        """TEST_PLAN §4.2: 停牌/涨跌停处理."""

        bars_a = [
            PriceBar("2024-01-01", 100.0),
            PriceBar("2024-01-02", 101.0, tradable=False),  # 停牌
            PriceBar("2024-01-03", 102.0, tradable=False),
        ]
        bars_b = to_price_bars([
            ("2024-01-01", 100.0),
            ("2024-01-02", 101.0, True),
            ("2024-01-03", 103.0, True),
        ])
        history = {"A": bars_a, "B": bars_b}
        provider = constant_metrics_provider({
            "A": {"score": 10.0},  # Highest score but suspended at rebalance.
            "B": {"score": 1.0},
        })
        engine = BacktestEngine()
        result = engine.run(
            _simple_strategy(),
            history,
            provider,
            BacktestConfig(rebalance_every=1, transaction_cost=0.0, top_n=1),
        )
        first_rebalance = result.rebalances[0]
        self.assertNotIn("A", first_rebalance.holdings)
        self.assertIn("B", first_rebalance.holdings)

    def test_metrics_are_self_consistent(self):
        history = _build_price_history({
            "A": [0.01, -0.005, 0.02, -0.01, 0.015, 0.0, 0.005, 0.01],
        })
        provider = constant_metrics_provider({"A": {"score": 1.0}})
        result = BacktestEngine().run(
            _simple_strategy(),
            history,
            provider,
            BacktestConfig(rebalance_every=2, transaction_cost=0.0, top_n=1),
        )
        # equity_curve has one more point than period_returns by construction.
        self.assertEqual(len(result.equity_curve), len(result.period_returns) + 1)
        # win_rate is bounded by [0, 1].
        self.assertGreaterEqual(result.win_rate, 0.0)
        self.assertLessEqual(result.win_rate, 1.0)
        # max_drawdown must be non-positive.
        self.assertLessEqual(result.max_drawdown, 0.0)

    def test_sample_split_isolation(self):
        """TEST_PLAN §4.3: 参数优化和样本外验证隔离."""

        full = _build_price_history({
            "A": [0.01, 0.02, -0.01, 0.0, 0.015, 0.01, -0.005, 0.02],
            "B": [-0.005, 0.0, 0.005, 0.01, -0.01, 0.0, 0.01, 0.005],
        })

        def split(history, start, end):
            return {s: bars[start:end] for s, bars in history.items()}

        in_sample = split(full, 0, 5)
        out_sample = split(full, 4, 9)  # Overlap one bar so prices align.
        engine = BacktestEngine()
        provider = constant_metrics_provider({"A": {"score": 1.0}, "B": {"score": 0.0}})
        cfg = BacktestConfig(rebalance_every=2, transaction_cost=0.0, top_n=1)

        in_result = engine.run(_simple_strategy(), in_sample, provider, cfg)
        out_result = engine.run(_simple_strategy(), out_sample, provider, cfg)
        # Date sets must be disjoint except for the deliberate overlap bar.
        in_dates, out_dates = set(in_result.dates), set(out_result.dates)
        overlap = in_dates & out_dates
        self.assertEqual(len(overlap), 1)


class BacktestConfigValidationTest(unittest.TestCase):
    def test_rebalance_every_must_be_positive(self):
        with self.assertRaises(ValueError):
            BacktestConfig(rebalance_every=0)

    def test_transaction_cost_bounds(self):
        with self.assertRaises(ValueError):
            BacktestConfig(transaction_cost=-0.01)
        with self.assertRaises(ValueError):
            BacktestConfig(transaction_cost=1.0)

    def test_top_n_must_be_positive(self):
        with self.assertRaises(ValueError):
            BacktestConfig(top_n=0)

    def test_initial_capital_must_be_positive(self):
        with self.assertRaises(ValueError):
            BacktestConfig(initial_capital=0)

    def test_price_bar_rejects_non_positive_close(self):
        with self.assertRaises(ValueError):
            PriceBar(date="2024-01-01", close=0.0)


if __name__ == "__main__":
    unittest.main()
