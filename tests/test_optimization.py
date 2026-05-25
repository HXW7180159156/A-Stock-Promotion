"""Tests for the parameter-grid optimisation module.

Covers ``docs/TEST_PLAN.md`` §4.3: 参数优化和样本外验证隔离, and the
follow-up feature called out in ``docs/IMPLEMENTATION_PLAN.md`` §3.3.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from a_stock_promotion import (
    BacktestConfig,
    BacktestResult,
    GridSearchOptimizer,
    OptimizationReport,
    OptimizationTrial,
    PriceBar,
    StrategyProfile,
    StrategyRule,
    WalkForwardReport,
    constant_metrics_provider,
    expand_grid,
    score_calmar,
    score_sharpe,
    score_total_return,
)


def _make_strategy(params):
    """Factory: build a strategy whose 'score' threshold is a tunable parameter."""

    threshold = params.get("threshold", 0.0)
    return StrategyProfile(
        name=f"thr-{threshold}",
        combine_mode="or",
        rules=(StrategyRule("score", ">=", threshold),),
    )


def _build_price_history(symbol_returns):
    history = {}
    length = max(len(returns) for returns in symbol_returns.values())
    dates = [f"2024-01-{day:02d}" for day in range(1, length + 2)]
    for symbol, returns in symbol_returns.items():
        bars = [PriceBar(date=dates[0], close=100.0)]
        for i, r in enumerate(returns, start=1):
            bars.append(PriceBar(date=dates[i], close=bars[-1].close * (1 + r)))
        history[symbol] = bars
    return history


class ExpandGridTest(unittest.TestCase):
    def test_empty_grid_yields_single_empty_assignment(self):
        self.assertEqual(expand_grid({}), [{}])

    def test_single_axis_expansion(self):
        self.assertEqual(
            expand_grid({"x": [1, 2, 3]}),
            [{"x": 1}, {"x": 2}, {"x": 3}],
        )

    def test_cartesian_product_of_multiple_axes(self):
        result = expand_grid({"a": [1, 2], "b": ["x", "y"]})
        self.assertEqual(len(result), 4)
        self.assertIn({"a": 1, "b": "x"}, result)
        self.assertIn({"a": 2, "b": "y"}, result)

    def test_empty_axis_rejected(self):
        with self.assertRaises(ValueError):
            expand_grid({"a": [1], "b": []})


class ScoreFunctionTest(unittest.TestCase):
    def _make_result(
        self,
        equity_curve=(100.0, 110.0, 121.0),
        period_returns=(0.1, 0.1),
    ):
        return BacktestResult(
            dates=tuple(f"2024-01-{i:02d}" for i in range(1, len(equity_curve) + 1)),
            equity_curve=equity_curve,
            period_returns=period_returns,
        )

    def test_score_total_return_matches_property(self):
        result = self._make_result()
        self.assertAlmostEqual(score_total_return(result), result.total_return)

    def test_score_sharpe_matches_property(self):
        result = self._make_result(
            equity_curve=(100.0, 101.0, 102.5, 101.8, 103.0),
            period_returns=(0.01, 0.0148, -0.0068, 0.0118),
        )
        self.assertAlmostEqual(score_sharpe(result), result.sharpe_ratio)

    def test_score_calmar_returns_neg_inf_when_no_drawdown(self):
        result = self._make_result()  # monotonically increasing → no drawdown
        self.assertEqual(score_calmar(result), float("-inf"))

    def test_score_calmar_uses_annualized_over_abs_drawdown(self):
        result = self._make_result(
            equity_curve=(100.0, 90.0, 95.0),
            period_returns=(-0.1, 0.0556),
        )
        expected = result.annualized_return / abs(result.max_drawdown)
        self.assertAlmostEqual(score_calmar(result), expected)


class GridSearchOptimizerTest(unittest.TestCase):
    def setUp(self):
        self.history = _build_price_history({
            "A": [0.02, 0.015, -0.01, 0.02, 0.01, 0.02, 0.0, 0.015],
            "B": [-0.005, 0.0, 0.005, -0.01, 0.0, -0.005, 0.0, -0.005],
        })
        # Score = factor; A is the high-quality signal, B is noise.
        self.provider = constant_metrics_provider({
            "A": {"score": 1.0},
            "B": {"score": 0.2},
        })
        self.config = BacktestConfig(rebalance_every=2, transaction_cost=0.0, top_n=1)
        self.optimizer = GridSearchOptimizer()

    def test_run_produces_one_trial_per_grid_point(self):
        report = self.optimizer.run(
            strategy_factory=_make_strategy,
            parameter_grid={"threshold": [0.0, 0.5, 0.9]},
            price_data=self.history,
            metrics_provider=self.provider,
            config=self.config,
            score_fn=score_total_return,
        )
        self.assertIsInstance(report, OptimizationReport)
        self.assertEqual(len(report.trials), 3)
        thresholds = sorted(t.parameters["threshold"] for t in report.trials)
        self.assertEqual(thresholds, [0.0, 0.5, 0.9])

    def test_run_with_empty_grid_runs_baseline_trial(self):
        report = self.optimizer.run(
            strategy_factory=_make_strategy,
            parameter_grid={},
            price_data=self.history,
            metrics_provider=self.provider,
            config=self.config,
            score_fn=score_total_return,
        )
        self.assertEqual(len(report.trials), 1)
        self.assertEqual(report.trials[0].parameters, {})

    def test_best_trial_maximises_score(self):
        # With threshold 0.0 and 0.5 both A and B qualify (top_n=1 keeps A);
        # threshold 1.5 rejects both, producing a 0% return curve. Therefore
        # the best trial must NOT be the threshold-1.5 one.
        report = self.optimizer.run(
            strategy_factory=_make_strategy,
            parameter_grid={"threshold": [0.0, 0.5, 1.5]},
            price_data=self.history,
            metrics_provider=self.provider,
            config=self.config,
            score_fn=score_total_return,
        )
        self.assertNotEqual(report.best.parameters["threshold"], 1.5)
        self.assertGreater(report.best.score, 0.0)

    def test_ranked_orders_trials_high_to_low(self):
        report = self.optimizer.run(
            strategy_factory=_make_strategy,
            parameter_grid={"threshold": [0.0, 0.5, 1.5]},
            price_data=self.history,
            metrics_provider=self.provider,
            config=self.config,
            score_fn=score_total_return,
        )
        ranked = report.ranked
        scores = [t.score for t in ranked]
        # Finite scores come first and are non-increasing.
        finite_scores = [s for s in scores if s != float("-inf")]
        self.assertEqual(finite_scores, sorted(finite_scores, reverse=True))

    def test_best_raises_on_empty_report(self):
        with self.assertRaises(ValueError):
            OptimizationReport().best

    def test_trial_returns_full_backtest_result(self):
        report = self.optimizer.run(
            strategy_factory=_make_strategy,
            parameter_grid={"threshold": [0.0]},
            price_data=self.history,
            metrics_provider=self.provider,
            config=self.config,
        )
        trial = report.trials[0]
        self.assertIsInstance(trial, OptimizationTrial)
        self.assertIsInstance(trial.result, BacktestResult)
        self.assertGreater(len(trial.result.equity_curve), 0)


class WalkForwardTest(unittest.TestCase):
    def setUp(self):
        # Build two disjoint date windows.
        in_history = {
            "A": [
                PriceBar("2024-01-01", 100.0),
                PriceBar("2024-01-02", 101.0),
                PriceBar("2024-01-03", 102.0),
                PriceBar("2024-01-04", 103.0),
                PriceBar("2024-01-05", 104.0),
            ],
            "B": [
                PriceBar("2024-01-01", 100.0),
                PriceBar("2024-01-02", 99.0),
                PriceBar("2024-01-03", 98.5),
                PriceBar("2024-01-04", 98.0),
                PriceBar("2024-01-05", 97.0),
            ],
        }
        out_history = {
            "A": [
                PriceBar("2024-02-01", 110.0),
                PriceBar("2024-02-02", 111.0),
                PriceBar("2024-02-03", 112.5),
                PriceBar("2024-02-04", 113.0),
                PriceBar("2024-02-05", 114.0),
            ],
            "B": [
                PriceBar("2024-02-01", 95.0),
                PriceBar("2024-02-02", 94.0),
                PriceBar("2024-02-03", 93.5),
                PriceBar("2024-02-04", 93.0),
                PriceBar("2024-02-05", 92.0),
            ],
        }
        self.in_history = in_history
        self.out_history = out_history
        self.provider = constant_metrics_provider({
            "A": {"score": 1.0},
            "B": {"score": 0.2},
        })
        self.config = BacktestConfig(rebalance_every=1, transaction_cost=0.0, top_n=1)

    def test_walk_forward_reports_in_and_out_of_sample(self):
        optimizer = GridSearchOptimizer()
        report = optimizer.walk_forward(
            strategy_factory=_make_strategy,
            parameter_grid={"threshold": [0.0, 0.5]},
            in_sample_price_data=self.in_history,
            out_of_sample_price_data=self.out_history,
            metrics_provider=self.provider,
            config=self.config,
            score_fn=score_total_return,
        )
        self.assertIsInstance(report, WalkForwardReport)
        # Best params from in-sample carry into the out-of-sample trial.
        self.assertEqual(
            report.out_of_sample.parameters,
            dict(report.best_parameters),
        )
        # Out-of-sample backtest must use dates from the out window only.
        out_dates = set(report.out_of_sample.result.dates)
        in_dates = set()
        for trial in report.in_sample.trials:
            in_dates.update(trial.result.dates)
        self.assertFalse(out_dates & in_dates)

    def test_walk_forward_rejects_overlapping_windows(self):
        # Out-of-sample reuses one in-sample date — must be rejected.
        contaminated = {
            "A": [
                PriceBar("2024-01-05", 104.0),  # ← overlaps in_history
                PriceBar("2024-02-01", 110.0),
                PriceBar("2024-02-02", 111.0),
            ],
        }
        optimizer = GridSearchOptimizer()
        with self.assertRaises(ValueError):
            optimizer.walk_forward(
                strategy_factory=_make_strategy,
                parameter_grid={"threshold": [0.0]},
                in_sample_price_data=self.in_history,
                out_of_sample_price_data=contaminated,
                metrics_provider=self.provider,
                config=self.config,
            )


if __name__ == "__main__":
    unittest.main()
