"""Tests for the operational leaderboard builder (V1.0)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from a_stock_promotion.features import FeatureAggregator
from a_stock_promotion.leaderboards import LeaderboardBuilder
from a_stock_promotion.strategies import (
    default_stock_strategy,
    value_blue_chip_strategy,
)


class LeaderboardTest(unittest.TestCase):
    def setUp(self):
        self.aggregator = FeatureAggregator()
        self.candidates = self.aggregator.build_many()
        self.builder = LeaderboardBuilder()

    def test_single_leaderboard_returns_top_n(self):
        board = self.builder.build(
            strategy=default_stock_strategy(),
            candidates=self.candidates,
            top_n=3,
            universe="stocks",
        )
        self.assertEqual(len(board.entries), 3)
        ranks = [e.rank for e in board.entries]
        self.assertEqual(ranks, [1, 2, 3])
        scores = [e.score for e in board.entries]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_only_selected_filters_non_passers(self):
        board = self.builder.build(
            strategy=value_blue_chip_strategy(),
            candidates=self.candidates,
            top_n=10,
            only_selected=True,
        )
        for entry in board.entries:
            self.assertTrue(entry.selected)

    def test_build_many_runs_per_strategy(self):
        boards = self.builder.build_many(
            strategies=[default_stock_strategy(), value_blue_chip_strategy()],
            candidates=self.candidates,
            top_n=5,
        )
        self.assertEqual(len(boards), 2)
        self.assertEqual({b.strategy for b in boards},
                         {"A股多因子MVP策略", "价值蓝筹策略"})

    def test_as_dict_is_json_safe(self):
        board = self.builder.build(
            strategy=default_stock_strategy(),
            candidates=self.candidates,
            top_n=2,
            universe="stocks",
        )
        payload = board.as_dict()
        self.assertEqual(payload["strategy"], "A股多因子MVP策略")
        self.assertEqual(payload["universe"], "stocks")
        self.assertEqual(len(payload["entries"]), 2)
        self.assertIn("matched_rules", payload["entries"][0])

    def test_invalid_top_n_rejected(self):
        with self.assertRaises(ValueError):
            self.builder.build(
                strategy=default_stock_strategy(),
                candidates=self.candidates,
                top_n=0,
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
