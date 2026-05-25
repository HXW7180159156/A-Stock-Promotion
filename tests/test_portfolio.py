"""Tests for the portfolio rebalancing engine (V1.0)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from a_stock_promotion.models import SelectionResult, StockMetrics
from a_stock_promotion.portfolio import (
    Holding,
    build_rebalance_plan,
    compute_target_weights,
    plan_from_selection,
)


def _mk(symbol: str, score: float, selected: bool = True) -> SelectionResult:
    return SelectionResult(
        candidate=StockMetrics(symbol=symbol, name=symbol, metrics={}),
        score=score,
        selected=selected,
    )


class TargetWeightTest(unittest.TestCase):
    def test_equal_weight(self):
        weights = compute_target_weights(
            [_mk("A", 0.9), _mk("B", 0.8), _mk("C", 0.5)], top_n=2
        )
        self.assertEqual(weights, {"A": 0.5, "B": 0.5})

    def test_score_weighted_normalised(self):
        weights = compute_target_weights(
            [_mk("A", 0.6), _mk("B", 0.4)], top_n=2, scheme="score"
        )
        self.assertAlmostEqual(sum(weights.values()), 1.0)
        self.assertAlmostEqual(weights["A"], 0.6)
        self.assertAlmostEqual(weights["B"], 0.4)

    def test_only_selected_filters(self):
        results = [_mk("A", 0.8, True), _mk("B", 0.7, False)]
        weights = compute_target_weights(results, top_n=5)
        self.assertEqual(set(weights), {"A"})

    def test_max_weight_cap_redistributes(self):
        weights = compute_target_weights(
            [_mk("A", 0.9), _mk("B", 0.1)],
            top_n=2,
            scheme="score",
            max_weight=0.5,
        )
        self.assertLessEqual(weights["A"], 0.5 + 1e-9)
        # Remaining mass after cap goes to B.
        self.assertGreater(weights["B"], 0.1)


class RebalancePlanTest(unittest.TestCase):
    def test_plan_emits_buy_sell_and_hold(self):
        plan = build_rebalance_plan(
            current=[Holding("A", 0.4), Holding("C", 0.6)],
            targets={"A": 0.4, "B": 0.6},
            min_trade=0.005,
        )
        actions = {trade.symbol: trade.action for trade in plan.trades}
        self.assertEqual(actions["A"], "hold")
        self.assertEqual(actions["B"], "buy")
        self.assertEqual(actions["C"], "sell")
        # Turnover = (|0.6| + |0.6|) / 2 = 0.6 (B bought, C sold)
        self.assertAlmostEqual(plan.turnover, 0.6, places=6)

    def test_min_trade_suppression_in_notes(self):
        plan = build_rebalance_plan(
            current=[Holding("A", 0.50)],
            targets={"A": 0.502},
            min_trade=0.01,
        )
        self.assertTrue(plan.notes)
        trade = next(t for t in plan.trades if t.symbol == "A")
        self.assertEqual(trade.action, "hold")
        self.assertEqual(trade.target_weight, 0.50)

    def test_transaction_cost_scales_with_turnover(self):
        plan = build_rebalance_plan(
            current={"A": 1.0},
            targets={"B": 1.0},
            transaction_cost=0.001,
            min_trade=0.0,
        )
        self.assertAlmostEqual(plan.turnover, 1.0)
        self.assertAlmostEqual(plan.transaction_cost, 0.001)

    def test_cash_weight_when_targets_underfilled(self):
        plan = build_rebalance_plan(targets={"A": 0.4})
        self.assertAlmostEqual(plan.cash_weight, 0.6)

    def test_rejects_oversubscribed_targets(self):
        with self.assertRaises(ValueError):
            build_rebalance_plan(targets={"A": 0.7, "B": 0.7})

    def test_plan_from_selection_end_to_end(self):
        plan = plan_from_selection(
            [_mk("A", 0.9), _mk("B", 0.8)],
            current=[Holding("A", 1.0)],
            top_n=2,
            transaction_cost=0.0,
            min_trade=0.0,
        )
        targets = dict(plan.targets)
        self.assertEqual(targets, {"A": 0.5, "B": 0.5})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
