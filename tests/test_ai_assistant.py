"""Tests for the V2.0 AI 选股助手 module."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from a_stock_promotion.ai_assistant import (
    AIAssistantError,
    explain_strategy,
    parse_prompt,
    summarize_results,
)
from a_stock_promotion.models import SelectionResult, StockMetrics, StrategyProfile, StrategyRule


class ParsePromptTest(unittest.TestCase):
    def test_parses_chinese_multi_factor_prompt(self) -> None:
        result = parse_prompt(
            "我想找 ROE 大于等于 15 并且 PE 不超过 25 同时北向资金净流入的标的，"
            "最低评分 0.6",
        )
        metrics = {rule.metric for rule in result.strategy.rules}
        self.assertIn("roe", metrics)
        self.assertIn("pe", metrics)
        self.assertIn("northbound_inflow", metrics)
        roe_rule = next(r for r in result.strategy.rules if r.metric == "roe")
        self.assertEqual(roe_rule.operator, ">=")
        self.assertEqual(roe_rule.threshold, 15.0)
        pe_rule = next(r for r in result.strategy.rules if r.metric == "pe")
        self.assertEqual(pe_rule.operator, "<=")
        self.assertEqual(pe_rule.threshold, 25.0)
        self.assertEqual(result.strategy.combine_mode, "and")
        self.assertAlmostEqual(result.strategy.min_score, 0.6)

    def test_or_mode_and_default_thresholds(self) -> None:
        result = parse_prompt("均线多头 或者 MACD 金叉")
        self.assertEqual(result.strategy.combine_mode, "or")
        self.assertGreaterEqual(len(result.strategy.rules), 2)

    def test_unmatched_tokens_reported(self) -> None:
        result = parse_prompt("ROE 大于 12 同时考虑 quantum_field 因子")
        self.assertTrue(
            any("quantum" in tok or "因子" in tok for tok in result.unmatched_tokens)
        )

    def test_empty_prompt_raises(self) -> None:
        with self.assertRaises(AIAssistantError):
            parse_prompt("   ")

    def test_unknown_prompt_raises(self) -> None:
        with self.assertRaises(AIAssistantError):
            parse_prompt("xyz only and no recognized terms")

    def test_prompt_size_limit(self) -> None:
        with self.assertRaises(AIAssistantError):
            parse_prompt("a" * 1001)

    def test_explanation_included(self) -> None:
        result = parse_prompt("ROE 大于 12 并且 PE 低于 30")
        self.assertIn("ROE", result.explanation)
        self.assertIn("策略", result.explanation)

    def test_as_dict_round_trip(self) -> None:
        result = parse_prompt("ROE 大于 10")
        as_dict = result.as_dict()
        self.assertIn("strategy", as_dict)
        self.assertIn("explanation", as_dict)
        self.assertEqual(as_dict["strategy"]["rules"][0]["metric"], "roe")


class ExplainStrategyTest(unittest.TestCase):
    def test_explain_uses_descriptions(self) -> None:
        strategy = StrategyProfile(
            name="测试",
            rules=(
                StrategyRule("roe", ">=", 10, 1.0, True, "ROE≥10"),
                StrategyRule("pe", "<=", 25, 0.8, False, "PE≤25"),
            ),
            combine_mode="and",
            min_score=0.5,
        )
        text = explain_strategy(strategy)
        self.assertIn("ROE≥10", text)
        self.assertIn("必选", text)
        self.assertIn("可选", text)
        self.assertIn("0.50", text)

    def test_explain_rejects_non_strategy(self) -> None:
        with self.assertRaises(AIAssistantError):
            explain_strategy("not a strategy")  # type: ignore[arg-type]


class SummarizeResultsTest(unittest.TestCase):
    def _make_result(self, symbol: str, score: float, selected: bool) -> SelectionResult:
        candidate = StockMetrics(symbol=symbol, name=symbol, metrics={"roe": 12.0})
        return SelectionResult(
            candidate=candidate,
            score=score,
            selected=selected,
            matched_rules=("ROE≥10",),
            missed_rules=(),
        )

    def test_empty_results(self) -> None:
        text = summarize_results([])
        self.assertIn("没有候选标的", text)

    def test_summary_lists_top_n(self) -> None:
        results = [
            self._make_result("000001", 0.9, True),
            self._make_result("000002", 0.7, True),
            self._make_result("000003", 0.4, False),
        ]
        text = summarize_results(results, top_n=2)
        self.assertIn("共评估 3", text)
        self.assertIn("000001", text)
        self.assertIn("000002", text)
        self.assertNotIn("000003", text)

    def test_summary_no_selection_hint(self) -> None:
        results = [self._make_result("000001", 0.2, False)]
        text = summarize_results(results)
        self.assertIn("没有标的同时满足", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
