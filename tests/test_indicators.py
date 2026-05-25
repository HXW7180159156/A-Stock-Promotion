"""Tests for the pure-Python technical indicator module."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from a_stock_promotion.indicators import (
    bollinger_bands,
    exponential_moving_average,
    kdj,
    ma_trend_score,
    macd,
    relative_strength_index,
    simple_moving_average,
    volume_ratio,
)


class SimpleMovingAverageTest(unittest.TestCase):
    def test_basic_rolling_window(self) -> None:
        result = simple_moving_average([1.0, 2.0, 3.0, 4.0, 5.0], window=3)
        self.assertEqual(result[:2], [None, None])
        self.assertAlmostEqual(result[2], 2.0)
        self.assertAlmostEqual(result[3], 3.0)
        self.assertAlmostEqual(result[4], 4.0)

    def test_invalid_window_rejected(self) -> None:
        with self.assertRaises(ValueError):
            simple_moving_average([1.0, 2.0], window=0)


class ExponentialMovingAverageTest(unittest.TestCase):
    def test_ema_converges_to_constant(self) -> None:
        series = [10.0] * 30
        result = exponential_moving_average(series, window=5)
        self.assertAlmostEqual(result[-1], 10.0, places=6)

    def test_ema_skipped_before_window(self) -> None:
        result = exponential_moving_average([1.0, 2.0, 3.0, 4.0, 5.0], window=4)
        self.assertEqual(result[:3], [None, None, None])
        self.assertIsNotNone(result[3])


class MACDTest(unittest.TestCase):
    def test_positive_trend_yields_positive_histogram(self) -> None:
        series = [10 + i * 0.5 for i in range(80)]
        last = macd(series)[-1]
        self.assertIsNotNone(last.hist)
        self.assertGreater(last.hist, 0)
        self.assertGreater(last.dif, last.dea)

    def test_periods_validation(self) -> None:
        with self.assertRaises(ValueError):
            macd([1.0] * 50, fast=26, slow=12)


class RSITest(unittest.TestCase):
    def test_uptrending_series_rsi_above_70(self) -> None:
        series = [10 + i for i in range(40)]
        last = relative_strength_index(series, window=14)[-1]
        self.assertGreater(last, 70.0)

    def test_downtrending_series_rsi_below_30(self) -> None:
        series = [100 - i for i in range(40)]
        last = relative_strength_index(series, window=14)[-1]
        self.assertLess(last, 30.0)

    def test_short_series_returns_none(self) -> None:
        result = relative_strength_index([1.0, 2.0, 3.0], window=14)
        self.assertEqual(result, [None, None, None])


class KDJTest(unittest.TestCase):
    def test_high_low_close_must_match(self) -> None:
        with self.assertRaises(ValueError):
            kdj([1.0], [1.0, 2.0], [1.0])

    def test_kdj_within_expected_range_when_at_high(self) -> None:
        closes = [10 + i for i in range(20)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        last = kdj(highs, lows, closes, window=9)[-1]
        # Price ends at a fresh high → K and J should be high.
        self.assertGreater(last.k, 70.0)
        self.assertGreater(last.j, last.d)


class BollingerTest(unittest.TestCase):
    def test_bands_widen_with_volatility(self) -> None:
        flat = [10.0] * 25
        volatile = [10.0 + (i % 2) * 4 for i in range(25)]
        flat_band = bollinger_bands(flat, window=20)[-1]
        volatile_band = bollinger_bands(volatile, window=20)[-1]
        self.assertEqual(flat_band.upper, flat_band.lower)
        self.assertGreater(volatile_band.upper - volatile_band.lower, 0.5)

    def test_window_must_be_at_least_two(self) -> None:
        with self.assertRaises(ValueError):
            bollinger_bands([1.0, 2.0], window=1)


class VolumeAndTrendTest(unittest.TestCase):
    def test_volume_ratio_growth(self) -> None:
        volumes = [100.0] * 5 + [200.0]
        ratio = volume_ratio(volumes, window=5)[-1]
        self.assertAlmostEqual(ratio, 2.0)

    def test_volume_ratio_handles_zero_baseline(self) -> None:
        volumes = [0.0] * 5 + [100.0]
        self.assertIsNone(volume_ratio(volumes, window=5)[-1])

    def test_ma_trend_bullish_alignment(self) -> None:
        series = [10 + i * 0.5 for i in range(80)]
        self.assertEqual(ma_trend_score(series), 1)

    def test_ma_trend_bearish_alignment(self) -> None:
        series = [100 - i * 0.5 for i in range(80)]
        self.assertEqual(ma_trend_score(series), -1)

    def test_ma_trend_insufficient_data(self) -> None:
        self.assertIsNone(ma_trend_score([1.0, 2.0, 3.0]))


if __name__ == "__main__":
    unittest.main()
