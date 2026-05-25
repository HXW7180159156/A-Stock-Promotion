"""Tests for stock pool management and feature aggregation."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from a_stock_promotion.data_sources import (
    FundamentalSnapshot,
    SampleFundamentalProvider,
    SampleSentimentProvider,
    SentimentSnapshot,
)
from a_stock_promotion.features import FeatureAggregator, PriceHistory
from a_stock_promotion.stock_pool import StockListing, StockPool, sample_stock_pool


class StockPoolTest(unittest.TestCase):
    def test_sample_pool_has_diverse_listings(self) -> None:
        pool = sample_stock_pool()
        self.assertGreaterEqual(len(pool), 10)
        self.assertGreaterEqual(len(pool.industries()), 5)
        self.assertGreaterEqual(len(pool.sectors()), 3)

    def test_filter_by_sector_and_exchange(self) -> None:
        pool = sample_stock_pool().filter(exchange="SH", sector="金融")
        self.assertGreater(len(pool), 0)
        for listing in pool:
            self.assertEqual(listing.exchange, "SH")
            self.assertEqual(listing.sector, "金融")

    def test_only_tradable_excludes_suspended(self) -> None:
        pool = StockPool([
            StockListing("000001", "Foo", "SZ", "Tech", "Tech", is_tradable=True),
            StockListing("000002", "Bar", "SZ", "Tech", "Tech", is_tradable=False),
        ])
        self.assertEqual(len(pool.filter()), 1)
        self.assertEqual(len(pool.filter(only_tradable=False)), 2)

    def test_st_listings_excluded_by_default(self) -> None:
        pool = StockPool([
            StockListing("000001", "Foo", "SZ", "Tech", "Tech"),
            StockListing("000002", "Bar", "SZ", "Tech", "Tech", is_st=True),
        ])
        self.assertEqual(len(pool.filter()), 1)
        self.assertEqual(len(pool.filter(include_st=True)), 2)

    def test_duplicate_symbol_rejected(self) -> None:
        with self.assertRaises(ValueError):
            StockPool([
                StockListing("000001", "A", "SZ", "Tech", "Tech"),
                StockListing("000001", "B", "SZ", "Tech", "Tech"),
            ])

    def test_unknown_exchange_rejected(self) -> None:
        with self.assertRaises(ValueError):
            StockListing("000001", "A", "XX", "Tech", "Tech")


class SampleProvidersTest(unittest.TestCase):
    def test_fundamental_metrics_strip_none(self) -> None:
        snapshot = FundamentalSnapshot(symbol="X", pe=10.0, pb=None, roe=15.0)
        self.assertEqual(snapshot.as_metrics(), {"pe": 10.0, "roe": 15.0})

    def test_sentiment_metrics_round_trip(self) -> None:
        snapshot = SentimentSnapshot(symbol="X", northbound_inflow=1.0)
        self.assertEqual(snapshot.as_metrics(), {"northbound_inflow": 1.0})

    def test_sample_provider_covers_sample_pool(self) -> None:
        fundamentals = SampleFundamentalProvider()
        sentiment = SampleSentimentProvider()
        for listing in sample_stock_pool():
            self.assertIsNotNone(fundamentals.get(listing.symbol), listing.symbol)
            self.assertIsNotNone(sentiment.get(listing.symbol), listing.symbol)


class FeatureAggregatorTest(unittest.TestCase):
    def test_build_includes_fundamental_and_sentiment(self) -> None:
        agg = FeatureAggregator()
        metrics = agg.build(agg.pool.get("600519"))
        self.assertIn("pe", metrics.metrics)
        self.assertIn("northbound_inflow", metrics.metrics)

    def test_build_with_price_history_adds_technical(self) -> None:
        agg = FeatureAggregator()
        closes = tuple(10 + i * 0.2 for i in range(80))
        highs = tuple(c + 0.3 for c in closes)
        lows = tuple(c - 0.3 for c in closes)
        volumes = tuple(1000 + i * 5 for i in range(80))
        agg.set_price_history(PriceHistory("600519", closes, highs, lows, volumes))
        metrics = agg.build(agg.pool.get("600519"))
        self.assertIn("ma_trend", metrics.metrics)
        self.assertIn("rsi", metrics.metrics)
        self.assertIn("macd_hist", metrics.metrics)
        self.assertIn("price_to_boll_upper", metrics.metrics)

    def test_build_many_returns_one_per_listing(self) -> None:
        agg = FeatureAggregator()
        metrics = agg.build_many()
        self.assertEqual(len(metrics), len(agg.pool))

    def test_price_history_validates_lengths(self) -> None:
        with self.assertRaises(ValueError):
            PriceHistory("X", (1.0, 2.0), (1.0,), (1.0, 2.0), (1.0, 2.0))


if __name__ == "__main__":
    unittest.main()
