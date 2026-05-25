"""Tests for the ETF pool, snapshots and feature aggregator (V1.0)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from a_stock_promotion.etf_pool import (
    ETFFeatureAggregator,
    ETFListing,
    ETFPool,
    ETFSnapshot,
    SampleETFProvider,
    sample_etf_pool,
)
from a_stock_promotion.selection_engine import SelectionEngine
from a_stock_promotion.strategies import default_etf_strategy


class ETFListingTest(unittest.TestCase):
    def test_rejects_invalid_exchange(self):
        with self.assertRaises(ValueError):
            ETFListing("510300", "x", "NY", "股票", "Nasdaq")

    def test_requires_name(self):
        with self.assertRaises(ValueError):
            ETFListing("510300", "", "SH", "股票", "沪深300")


class ETFPoolTest(unittest.TestCase):
    def test_filters_by_exchange_and_asset_class(self):
        pool = sample_etf_pool()
        sh = pool.filter(exchange="SH")
        for listing in sh:
            self.assertEqual(listing.exchange, "SH")
        bonds = pool.filter(asset_class="债券")
        self.assertTrue(all(l.asset_class == "债券" for l in bonds))
        self.assertGreater(len(bonds), 0)

    def test_rejects_duplicate_symbols(self):
        with self.assertRaises(ValueError):
            ETFPool([
                ETFListing("510300", "a", "SH", "股票", "沪深300"),
                ETFListing("510300", "b", "SH", "股票", "沪深300"),
            ])

    def test_only_tradable_filter(self):
        pool = ETFPool([
            ETFListing("510300", "a", "SH", "股票", "沪深300"),
            ETFListing("510500", "b", "SH", "股票", "中证500", is_tradable=False),
        ])
        tradable = pool.filter(only_tradable=True)
        self.assertEqual([l.symbol for l in tradable], ["510300"])


class ETFFeatureAggregatorTest(unittest.TestCase):
    def test_build_includes_snapshot_metrics(self):
        agg = ETFFeatureAggregator()
        listing = agg.pool.get("510300")
        candidate = agg.build(listing)
        self.assertIn("tracking_error", candidate.metrics)
        self.assertIn("fund_size", candidate.metrics)

    def test_default_etf_strategy_screens_pool(self):
        agg = ETFFeatureAggregator()
        candidates = agg.build_many()
        engine = SelectionEngine()
        ranked = engine.rank(candidates, default_etf_strategy())
        # At least one ETF should pass the default ETF screening template
        # because the sample provider includes several large/liquid ETFs.
        self.assertTrue(any(r.selected for r in ranked))

    def test_snapshot_as_metrics_drops_nones(self):
        snap = ETFSnapshot("510300", tracking_error=0.005, fund_size=None)
        metrics = snap.as_metrics()
        self.assertIn("tracking_error", metrics)
        self.assertNotIn("fund_size", metrics)

    def test_sample_provider_lookup(self):
        provider = SampleETFProvider()
        self.assertIsNotNone(provider.get("510300"))
        self.assertIsNone(provider.get("000000"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
