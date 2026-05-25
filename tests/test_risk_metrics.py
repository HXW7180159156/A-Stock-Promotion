"""Unit tests for the risk metrics module."""

import math
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from a_stock_promotion.risk_metrics import (
    TRADING_DAYS_PER_YEAR,
    historical_var,
    max_drawdown,
    sharpe_ratio,
    to_returns,
    volatility,
)


class RiskMetricsTest(unittest.TestCase):
    def test_to_returns_basic(self):
        result = to_returns([100, 110, 99])
        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(result[0], 0.1)
        self.assertAlmostEqual(result[1], -0.1)

    def test_to_returns_empty_or_single(self):
        self.assertEqual(to_returns([]), [])
        self.assertEqual(to_returns([100]), [])

    def test_to_returns_rejects_non_positive(self):
        with self.assertRaises(ValueError):
            to_returns([100, 0, 90])

    def test_max_drawdown_simple_peak_trough(self):
        # peak 120 → trough 80 → drawdown = -1/3
        self.assertAlmostEqual(max_drawdown([100, 120, 80, 110]), -1 / 3)

    def test_max_drawdown_monotonic_returns_zero(self):
        self.assertEqual(max_drawdown([100, 101, 102, 103]), 0.0)

    def test_max_drawdown_short_input(self):
        self.assertEqual(max_drawdown([]), 0.0)
        self.assertEqual(max_drawdown([100]), 0.0)

    def test_volatility_annualised(self):
        returns = [0.01, -0.01, 0.02, -0.02]
        annual = volatility(returns, annualize=True)
        period = volatility(returns, annualize=False)
        self.assertAlmostEqual(annual, period * math.sqrt(TRADING_DAYS_PER_YEAR))
        self.assertGreater(period, 0)

    def test_volatility_short_input(self):
        self.assertEqual(volatility([0.01]), 0.0)

    def test_sharpe_ratio_positive_for_positive_excess(self):
        returns = [0.01, 0.012, 0.008, 0.011, 0.009]
        self.assertGreater(sharpe_ratio(returns, risk_free_rate=0.0), 0)

    def test_sharpe_ratio_zero_when_std_is_zero(self):
        returns = [0.01, 0.01, 0.01]
        self.assertEqual(sharpe_ratio(returns), 0.0)

    def test_sharpe_ratio_rejects_bad_periods(self):
        with self.assertRaises(ValueError):
            sharpe_ratio([0.01, 0.02], periods_per_year=0)

    def test_historical_var_is_non_positive(self):
        returns = [-0.05, -0.02, 0.0, 0.01, 0.03]
        var95 = historical_var(returns, confidence=0.95)
        self.assertLessEqual(var95, 0.0)
        # 95% confidence on 5 points → quantile at position 0.2,
        # i.e. interpolate between -0.05 and -0.02 with weight 0.2.
        self.assertAlmostEqual(var95, -0.05 + 0.2 * 0.03)

    def test_historical_var_rejects_bad_confidence(self):
        with self.assertRaises(ValueError):
            historical_var([0.01, -0.01], confidence=1.5)

    def test_historical_var_empty(self):
        self.assertEqual(historical_var([]), 0.0)

    def test_historical_var_all_positive_returns_zero(self):
        # No losses observed ⇒ VaR clamped to 0.
        self.assertEqual(historical_var([0.01, 0.02, 0.03]), 0.0)


if __name__ == "__main__":
    unittest.main()
