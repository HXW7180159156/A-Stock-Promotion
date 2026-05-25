"""Coverage-completion tests targeting validation/error branches across modules.

These tests exercise the defensive branches (input validation, edge cases,
empty inputs) that the main behavioural test suites do not cover, so the
full project reaches near-100% statement coverage.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from a_stock_promotion.admin import StrategyRegistry, StrategyRegistryError
from a_stock_promotion.ai_assistant import (
    AIAssistantError,
    explain_strategy,
    parse_prompt,
    summarize_results,
)
from a_stock_promotion.backtesting import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    PriceBar,
    constant_metrics_provider,
    time_series_metrics_provider,
    to_price_bars,
)
from a_stock_promotion.community import CommunityError, CommunityHub
from a_stock_promotion.etf_pool import ETFListing, ETFPool, sample_etf_pool
from a_stock_promotion.features import PriceHistory, compute_technical_metrics
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
from a_stock_promotion.membership import (
    DEFAULT_BENEFITS,
    MembershipError,
    MembershipService,
    TierBenefits,
)
from a_stock_promotion.models import StrategyProfile, StrategyRule
from a_stock_promotion.portfolio import (
    Holding,
    build_rebalance_plan,
    compute_target_weights,
    plan_from_selection,
)
from a_stock_promotion.risk_metrics import historical_var, max_drawdown
from a_stock_promotion.stock_pool import StockListing, StockPool


# ---------------------------------------------------------------------------
# indicators.py – validation branches
# ---------------------------------------------------------------------------
class IndicatorsValidationTest(unittest.TestCase):
    def test_check_series_rejects_none(self):
        with self.assertRaises(ValueError):
            simple_moving_average(None, 3)  # type: ignore[arg-type]

    def test_check_series_rejects_non_sequence(self):
        with self.assertRaises(TypeError):
            simple_moving_average("abc", 3)  # type: ignore[arg-type]

    def test_ema_window_must_be_positive(self):
        with self.assertRaises(ValueError):
            exponential_moving_average([1.0, 2.0], 0)

    def test_ema_empty_series(self):
        self.assertEqual(exponential_moving_average([], 5), [])

    def test_macd_rejects_fast_ge_slow(self):
        with self.assertRaises(ValueError):
            macd([1.0] * 30, fast=12, slow=12)

    def test_rsi_window_must_be_positive(self):
        with self.assertRaises(ValueError):
            relative_strength_index([1.0, 2.0], window=0)

    def test_kdj_window_must_be_positive(self):
        with self.assertRaises(ValueError):
            kdj([1.0, 2.0], [0.5, 1.5], [0.8, 1.8], window=0)

    def test_bollinger_window_must_be_at_least_two(self):
        with self.assertRaises(ValueError):
            bollinger_bands([1.0, 2.0, 3.0], window=1)

    def test_bollinger_num_std_must_be_positive(self):
        with self.assertRaises(ValueError):
            bollinger_bands([1.0, 2.0, 3.0], window=2, num_std=0)

    def test_volume_ratio_window_must_be_positive(self):
        with self.assertRaises(ValueError):
            volume_ratio([1.0, 2.0], window=0)

    def test_ma_trend_score_empty_series(self):
        self.assertIsNone(ma_trend_score([]))

    def test_ma_trend_score_insufficient_data(self):
        # too few samples so long SMA is None and trend is undefined
        self.assertIsNone(ma_trend_score([1.0, 2.0, 3.0]))


# ---------------------------------------------------------------------------
# features.py – validation branches
# ---------------------------------------------------------------------------
class FeaturesValidationTest(unittest.TestCase):
    def test_price_history_rejects_empty(self):
        with self.assertRaises(ValueError):
            PriceHistory(symbol="X", closes=(), highs=(), lows=(), volumes=())

    def test_price_history_rejects_mismatched_lengths(self):
        with self.assertRaises(ValueError):
            PriceHistory(
                symbol="X",
                closes=(1.0,),
                highs=(1.0, 2.0),
                lows=(1.0,),
                volumes=(1.0,),
            )

    def test_compute_technical_metrics_basic(self):
        closes = [10.0 + i * 0.1 for i in range(60)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        volumes = [1000.0 + i for i in range(60)]
        metrics = compute_technical_metrics(
            PriceHistory(
                symbol="X",
                closes=tuple(closes),
                highs=tuple(highs),
                lows=tuple(lows),
                volumes=tuple(volumes),
            )
        )
        self.assertIn("close", metrics)


# ---------------------------------------------------------------------------
# risk_metrics.py – validation branches
# ---------------------------------------------------------------------------
class RiskMetricsValidationTest(unittest.TestCase):
    def test_max_drawdown_rejects_non_positive(self):
        with self.assertRaises(ValueError):
            max_drawdown([1.0, 0.0, 0.5])

    def test_historical_var_exact_quantile_position(self):
        # Use confidence=0.5 with 21 returns so position lands exactly at
        # integer index 10 and the ``lower == upper`` branch fires.
        returns = [-0.05 * i for i in range(21)]
        value = historical_var(returns, confidence=0.5)
        self.assertLessEqual(value, 0.0)


# ---------------------------------------------------------------------------
# stock_pool.py – validation branches
# ---------------------------------------------------------------------------
class StockPoolValidationTest(unittest.TestCase):
    def test_listing_requires_symbol(self):
        with self.assertRaises(ValueError):
            StockListing(symbol="", name="名", exchange="SH", industry="i", sector="s")

    def test_listing_requires_name(self):
        with self.assertRaises(ValueError):
            StockListing(symbol="600000", name="", exchange="SH", industry="i", sector="s")

    def test_filter_by_industry(self):
        pool = StockPool(
            [
                StockListing("600000", "甲", "SH", "银行", "金融"),
                StockListing("600001", "乙", "SH", "保险", "金融"),
            ]
        )
        filtered = pool.filter(industry="银行")
        self.assertEqual(len(filtered), 1)


# ---------------------------------------------------------------------------
# etf_pool.py – validation branches
# ---------------------------------------------------------------------------
class ETFPoolValidationTest(unittest.TestCase):
    def test_listing_requires_symbol(self):
        with self.assertRaises(ValueError):
            ETFListing(
                symbol="",
                name="名",
                exchange="SH",
                asset_class="股票",
                tracking_index="HS300",
            )

    def test_listing_requires_name(self):
        with self.assertRaises(ValueError):
            ETFListing(
                symbol="510300",
                name="",
                exchange="SH",
                asset_class="股票",
                tracking_index="HS300",
            )

    def test_asset_classes_and_sectors(self):
        pool = sample_etf_pool()
        self.assertTrue(pool.asset_classes())
        # may or may not have sector strings, just exercise the path
        pool.sectors()

    def test_filter_by_sector_and_tracking_index(self):
        pool = ETFPool(
            [
                ETFListing("510300", "甲", "SH", "股票", "HS300", sector="宽基"),
                ETFListing("510500", "乙", "SH", "股票", "ZZ500", sector="行业"),
            ]
        )
        self.assertEqual(len(pool.filter(sector="宽基")), 1)
        self.assertEqual(len(pool.filter(tracking_index="HS300")), 1)


# ---------------------------------------------------------------------------
# portfolio.py – validation branches
# ---------------------------------------------------------------------------
class PortfolioValidationTest(unittest.TestCase):
    def test_holding_rejects_negative_weight(self):
        with self.assertRaises(ValueError):
            Holding("600000", -0.1)

    def test_compute_target_weights_top_n_must_be_positive(self):
        with self.assertRaises(ValueError):
            compute_target_weights([], top_n=0)

    def test_compute_target_weights_invalid_max_weight(self):
        with self.assertRaises(ValueError):
            compute_target_weights([], top_n=3, max_weight=1.5)
        with self.assertRaises(ValueError):
            compute_target_weights([], top_n=3, max_weight=0)

    def test_compute_target_weights_empty_returns_empty(self):
        self.assertEqual(compute_target_weights([], top_n=3), {})

    def test_compute_target_weights_score_scheme_all_zero(self):
        # When score-weighted but all eligible items have score 0 → empty
        from a_stock_promotion.models import SelectionResult, StockMetrics

        cand = StockMetrics(symbol="X", name="X", metrics={})
        results = [SelectionResult(candidate=cand, score=0.0, selected=True)]
        self.assertEqual(
            compute_target_weights(results, top_n=3, scheme="score"),
            {},
        )

    def test_build_rebalance_plan_rejects_invalid_transaction_cost(self):
        with self.assertRaises(ValueError):
            build_rebalance_plan(targets={"A": 0.5}, transaction_cost=1.5)

    def test_build_rebalance_plan_rejects_negative_min_trade(self):
        with self.assertRaises(ValueError):
            build_rebalance_plan(targets={"A": 0.5}, min_trade=-1)

    def test_normalise_current_rejects_negative_weights(self):
        with self.assertRaises(ValueError):
            build_rebalance_plan(
                current={"A": -0.1}, targets={"A": 0.5}
            )

    def test_normalise_current_rejects_oversum(self):
        with self.assertRaises(ValueError):
            build_rebalance_plan(
                current={"A": 0.6, "B": 0.6}, targets={"A": 0.5}
            )

    def test_apply_weight_cap_redistributes(self):
        # construct a weight map where one symbol breaches the cap and
        # excess gets redistributed via _apply_weight_cap (cap < 1.0)
        from a_stock_promotion.models import SelectionResult, StockMetrics

        results = [
            SelectionResult(
                candidate=StockMetrics(symbol=f"S{i}", name=f"S{i}", metrics={}),
                score=10.0 if i == 0 else 1.0,
                selected=True,
            )
            for i in range(4)
        ]
        weights = compute_target_weights(
            results, top_n=4, scheme="score", max_weight=0.3
        )
        # All weights must respect the cap
        self.assertTrue(all(w <= 0.3 + 1e-9 for w in weights.values()))
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=6)

    def test_plan_from_selection_smoke(self):
        from a_stock_promotion.models import SelectionResult, StockMetrics

        results = [
            SelectionResult(
                candidate=StockMetrics(symbol=f"S{i}", name=f"S{i}", metrics={}),
                score=1.0,
                selected=True,
            )
            for i in range(3)
        ]
        plan = plan_from_selection(results, top_n=2)
        self.assertGreater(len(plan.targets), 0)


# ---------------------------------------------------------------------------
# backtesting.py – validation branches
# ---------------------------------------------------------------------------
class BacktestingValidationTest(unittest.TestCase):
    def test_config_rejects_invalid_periods_per_year(self):
        with self.assertRaises(ValueError):
            BacktestConfig(periods_per_year=0)

    def test_result_with_single_bar_has_zero_returns(self):
        res = BacktestResult(dates=("d",), equity_curve=(1.0,), period_returns=())
        self.assertEqual(res.total_return, 0.0)
        self.assertEqual(res.annualized_return, 0.0)
        self.assertEqual(res.win_rate, 0.0)
        self.assertEqual(res.turnover, 0.0)

    def test_result_with_negative_growth_annualizes_to_minus_one(self):
        res = BacktestResult(
            dates=("d1", "d2"),
            equity_curve=(1.0, 0.0),
            period_returns=(-1.0,),
        )
        # equity ends at zero -> growth <= 0 path returns -1.0
        self.assertEqual(res.annualized_return, -1.0)

    def test_engine_returns_empty_for_empty_price_data(self):
        engine = BacktestEngine()
        strat = StrategyProfile(
            name="x",
            rules=(StrategyRule("roe", ">=", 5),),
            combine_mode="and",
            min_score=0.0,
        )
        res = engine.run(strat, {}, constant_metrics_provider({}))
        self.assertEqual(res.equity_curve, ())

    def test_engine_returns_empty_when_bar_index_empty(self):
        engine = BacktestEngine()
        strat = StrategyProfile(
            name="x",
            rules=(StrategyRule("roe", ">=", 5),),
            combine_mode="and",
            min_score=0.0,
        )
        # Provide a mapping with a symbol but no bars -> empty bar index
        res = engine.run(strat, {"AAA": []}, constant_metrics_provider({}))
        self.assertEqual(res.equity_curve, ())

    def test_engine_duplicate_bar_dates_raise(self):
        engine = BacktestEngine()
        strat = StrategyProfile(
            name="x",
            rules=(StrategyRule("roe", ">=", 5),),
            combine_mode="and",
            min_score=0.0,
        )
        bars = [PriceBar("2024-01-01", 1.0), PriceBar("2024-01-01", 1.05)]
        with self.assertRaises(ValueError):
            engine.run(strat, {"AAA": bars}, constant_metrics_provider({"AAA": {"roe": 10}}))

    def test_portfolio_return_skips_missing_lookups(self):
        # Suspended on day 2: missing curr bar -> contribution skipped.
        engine = BacktestEngine()
        strat = StrategyProfile(
            name="hold-all",
            rules=(StrategyRule("roe", ">=", 0),),
            combine_mode="and",
            min_score=0.0,
        )
        bars_a = [
            PriceBar("2024-01-01", 1.0),
            PriceBar("2024-01-02", 1.1),
            PriceBar("2024-01-03", 1.2),
        ]
        # Symbol B is missing on day 2 entirely
        bars_b = [PriceBar("2024-01-01", 1.0), PriceBar("2024-01-03", 1.5)]
        res = engine.run(
            strat,
            {"AAA": bars_a, "BBB": bars_b},
            constant_metrics_provider({"AAA": {"roe": 1.0}, "BBB": {"roe": 1.0}}),
            BacktestConfig(rebalance_every=1, top_n=2),
        )
        self.assertEqual(len(res.equity_curve), 3)

    def test_time_series_provider_returns_none_for_unknown(self):
        provider = time_series_metrics_provider({"AAA": {"2024-01-01": {"roe": 1}}})
        self.assertIsNone(provider("UNKNOWN", "2024-01-01"))
        self.assertIsNone(provider("AAA", "2099-01-01"))

    def test_to_price_bars_three_tuple(self):
        bars = to_price_bars([("2024-01-01", 1.0, False)])
        self.assertEqual(bars[0].tradable, False)


# ---------------------------------------------------------------------------
# admin.py – validation branches
# ---------------------------------------------------------------------------
class AdminValidationTest(unittest.TestCase):
    def setUp(self):
        self.registry = StrategyRegistry()

    def _base(self, **over):
        payload = {
            "name": "策略X",
            "combine_mode": "and",
            "min_score": 0.5,
            "rules": [
                {"metric": "roe", "operator": ">=", "threshold": 10, "weight": 1.0}
            ],
        }
        payload.update(over)
        return payload

    def test_list_strategies_returns_profiles(self):
        profiles = self.registry.list_strategies()
        self.assertGreater(len(profiles), 0)
        self.assertTrue(all(isinstance(p, StrategyProfile) for p in profiles))

    def test_update_not_found(self):
        with self.assertRaises(StrategyRegistryError):
            self.registry.update("不存在", self._base(name="不存在"))

    def test_update_rename_collision(self):
        self.registry.create(self._base(name="a1"))
        self.registry.create(self._base(name="a2"))
        with self.assertRaises(StrategyRegistryError):
            self.registry.update("a1", self._base(name="a2"))

    def test_delete_not_found(self):
        with self.assertRaises(StrategyRegistryError):
            self.registry.delete("ghost")

    def test_payload_not_a_mapping(self):
        with self.assertRaises(StrategyRegistryError):
            self.registry.create("not a dict")  # type: ignore[arg-type]

    def test_name_too_long(self):
        with self.assertRaises(StrategyRegistryError):
            self.registry.create(self._base(name="x" * 65))

    def test_min_score_not_a_number(self):
        with self.assertRaises(StrategyRegistryError):
            self.registry.create(self._base(min_score="abc"))

    def test_rules_too_many(self):
        rules = [
            {"metric": f"m{i}", "operator": ">=", "threshold": 0, "weight": 1.0}
            for i in range(33)
        ]
        with self.assertRaises(StrategyRegistryError):
            self.registry.create(self._base(rules=rules))

    def test_rule_not_a_mapping(self):
        with self.assertRaises(StrategyRegistryError):
            self.registry.create(self._base(rules=["bad"]))

    def test_rule_metric_required(self):
        with self.assertRaises(StrategyRegistryError):
            self.registry.create(
                self._base(rules=[{"metric": "", "operator": ">=", "threshold": 1}])
            )

    def test_rule_weight_not_a_number(self):
        with self.assertRaises(StrategyRegistryError):
            self.registry.create(
                self._base(
                    rules=[
                        {
                            "metric": "x",
                            "operator": ">=",
                            "threshold": 1,
                            "weight": "abc",
                        }
                    ]
                )
            )

    def test_rule_weight_negative(self):
        with self.assertRaises(StrategyRegistryError):
            self.registry.create(
                self._base(
                    rules=[
                        {
                            "metric": "x",
                            "operator": ">=",
                            "threshold": 1,
                            "weight": -0.5,
                        }
                    ]
                )
            )

    def test_rule_description_too_long(self):
        with self.assertRaises(StrategyRegistryError):
            self.registry.create(
                self._base(
                    rules=[
                        {
                            "metric": "x",
                            "operator": ">=",
                            "threshold": 1,
                            "description": "x" * 201,
                        }
                    ]
                )
            )


# ---------------------------------------------------------------------------
# ai_assistant.py – validation branches
# ---------------------------------------------------------------------------
class AIAssistantValidationTest(unittest.TestCase):
    def test_prompt_must_be_string(self):
        with self.assertRaises(AIAssistantError):
            parse_prompt(123)  # type: ignore[arg-type]

    def test_truncates_overlong_name(self):
        result = parse_prompt("ROE 大于 10", name="名" * 100)
        self.assertEqual(len(result.strategy.name), 64)

    def test_summarize_results_rejects_non_positive_top_n(self):
        with self.assertRaises(AIAssistantError):
            summarize_results([], top_n=0)

    def test_default_combine_unknown_falls_back_to_and(self):
        result = parse_prompt("ROE 大于 10", default_combine="invalid")
        self.assertEqual(result.strategy.combine_mode, "and")

    def test_min_score_percentage_value_is_normalized(self):
        # "最低评分 60" should become 0.6 via /100
        result = parse_prompt("ROE 大于 10 最低评分 60")
        self.assertAlmostEqual(result.strategy.min_score, 0.6, places=4)

    def test_min_score_negative_clamped_to_zero(self):
        # "最低评分 -5" should clamp to 0.0; -5 is negative so the /100 branch
        # is skipped (value <= 1), then clamped to 0.
        result = parse_prompt("ROE 大于 10 最低评分 -5")
        self.assertEqual(result.strategy.min_score, 0.0)

    def test_min_score_over_100_caps_at_one(self):
        result = parse_prompt("ROE 大于 10 最低评分 250")
        self.assertEqual(result.strategy.min_score, 1.0)

    def test_explain_strategy_or_combine(self):
        strat = StrategyProfile(
            name="x",
            rules=(StrategyRule("roe", ">=", 10, required=True),),
            combine_mode="or",
            min_score=0.3,
        )
        text = explain_strategy(strat)
        self.assertIn("任意满足", text)
        self.assertIn("必选", text)


# ---------------------------------------------------------------------------
# community.py – validation branches
# ---------------------------------------------------------------------------
class CommunityValidationTest(unittest.TestCase):
    def setUp(self):
        self.hub = CommunityHub()
        self.strategy = StrategyProfile(
            name="s",
            rules=(StrategyRule("roe", ">=", 10),),
            combine_mode="and",
            min_score=0.0,
        )
        self.hub.publish(
            slug="my-strategy", owner="alice", strategy=self.strategy
        )

    def test_unpublish_not_found(self):
        with self.assertRaises(CommunityError):
            self.hub.unpublish("ghost", owner="alice")

    def test_unsubscribe_not_found(self):
        with self.assertRaises(CommunityError):
            self.hub.unsubscribe("ghost", "bob")

    def test_list_comments_limit_must_be_positive(self):
        with self.assertRaises(CommunityError):
            self.hub.list_comments("my-strategy", limit=0)

    def test_list_comments_clamps_high_limit(self):
        # Just exercises the high-limit branch (limit > 200 -> 200).
        result = self.hub.list_comments("my-strategy", limit=500)
        self.assertEqual(result, [])

    def test_validated_slug_rejects_invalid(self):
        with self.assertRaises(CommunityError):
            self.hub.publish(slug="!!", owner="alice", strategy=self.strategy)

    def test_validated_description_rejects_non_string(self):
        with self.assertRaises(CommunityError):
            self.hub.publish(
                slug="x1", owner="alice", strategy=self.strategy, description=123
            )

    def test_validated_description_too_long(self):
        with self.assertRaises(CommunityError):
            self.hub.publish(
                slug="x2",
                owner="alice",
                strategy=self.strategy,
                description="x" * 501,
            )

    def test_validated_tags_must_be_list(self):
        with self.assertRaises(CommunityError):
            self.hub.publish(
                slug="x3", owner="alice", strategy=self.strategy, tags="not-list"
            )

    def test_validated_tags_too_many(self):
        with self.assertRaises(CommunityError):
            self.hub.publish(
                slug="x4",
                owner="alice",
                strategy=self.strategy,
                tags=[f"t{i}" for i in range(17)],
            )

    def test_validated_tags_item_must_be_string(self):
        with self.assertRaises(CommunityError):
            self.hub.publish(
                slug="x5", owner="alice", strategy=self.strategy, tags=[1, 2, 3]
            )

    def test_validated_tags_item_too_long(self):
        with self.assertRaises(CommunityError):
            self.hub.publish(
                slug="x6",
                owner="alice",
                strategy=self.strategy,
                tags=["x" * 33],
            )

    def test_validated_tags_skips_empty(self):
        share = self.hub.publish(
            slug="x7",
            owner="alice",
            strategy=self.strategy,
            tags=["", "real-tag", "   "],
        )
        self.assertEqual(list(share.tags), ["real-tag"])

    def test_validated_price_not_a_number(self):
        with self.assertRaises(CommunityError):
            self.hub.publish(
                slug="x8", owner="alice", strategy=self.strategy, price="free"
            )

    def test_validated_price_negative(self):
        with self.assertRaises(CommunityError):
            self.hub.publish(
                slug="x9", owner="alice", strategy=self.strategy, price=-1
            )

    def test_validated_price_too_high(self):
        with self.assertRaises(CommunityError):
            self.hub.publish(
                slug="x10",
                owner="alice",
                strategy=self.strategy,
                price=10**6,
            )

    def test_comment_body_must_be_string(self):
        with self.assertRaises(CommunityError):
            self.hub.add_comment("my-strategy", author="alice", body=123)

    def test_comment_body_must_not_be_empty(self):
        with self.assertRaises(CommunityError):
            self.hub.add_comment("my-strategy", author="alice", body="   ")

    def test_comment_body_too_long(self):
        with self.assertRaises(CommunityError):
            self.hub.add_comment(
                "my-strategy", author="alice", body="x" * 2001
            )

    def test_strategy_validation_requires_profile(self):
        with self.assertRaises(CommunityError):
            self.hub.publish(slug="bad", owner="alice", strategy="not-a-profile")

    def test_strategy_validation_requires_rules(self):
        empty = StrategyProfile(name="e", rules=())
        with self.assertRaises(CommunityError):
            self.hub.publish(slug="empty", owner="alice", strategy=empty)

    def test_strategy_validation_rejects_non_strategy_rule(self):
        bad = StrategyProfile(name="bad", rules=("not-a-rule",))  # type: ignore[arg-type]
        with self.assertRaises(CommunityError):
            self.hub.publish(slug="badrules", owner="alice", strategy=bad)

    def test_publish_with_none_description_and_tags(self):
        share = self.hub.publish(
            slug="defaults1",
            owner="alice",
            strategy=self.strategy,
            description=None,
            tags=None,
        )
        self.assertEqual(share.description, "")
        self.assertEqual(list(share.tags), [])

    def test_indicators_kdj_returns_zero_when_unranked(self):
        # mid==short==long → returns 0 from ma_trend_score
        score = ma_trend_score([1.0] * 80)
        self.assertEqual(score, 0)

    def test_indicators_macd_rejects_zero_period(self):
        with self.assertRaises(ValueError):
            macd([1.0] * 30, fast=0, slow=12, signal=9)


# ---------------------------------------------------------------------------
# membership.py – validation branches
# ---------------------------------------------------------------------------
class MembershipValidationTest(unittest.TestCase):
    def test_missing_tier_in_benefits_raises(self):
        incomplete = {"free": DEFAULT_BENEFITS["free"]}
        with self.assertRaises(MembershipError):
            MembershipService(benefits=incomplete)

    def test_list_users(self):
        svc = MembershipService()
        svc.upsert_user("alice", "pro")
        svc.upsert_user("bob", "vip")
        users = svc.list_users()
        self.assertEqual({u.username for u in users}, {"alice", "bob"})

    def test_list_addons_unknown_user(self):
        svc = MembershipService()
        self.assertEqual(svc.list_addons("ghost"), [])

    def test_list_addons_known_user(self):
        svc = MembershipService()
        svc.upsert_user("alice", "pro")
        svc.subscribe_addon("alice", "northbound_realtime")
        addons = svc.list_addons("alice")
        self.assertIn("northbound_realtime", addons)

    def test_has_addon_unknown_user(self):
        svc = MembershipService()
        self.assertFalse(svc.has_addon("ghost", "northbound_realtime"))

    def test_has_addon_via_tier(self):
        svc = MembershipService()
        svc.upsert_user("alice", "pro")
        # pro includes northbound_realtime
        self.assertTrue(svc.has_addon("alice", "northbound_realtime"))

    def test_can_use_ai_assistant_for_user(self):
        svc = MembershipService()
        svc.upsert_user("alice", "free")
        self.assertTrue(svc.can_use_ai_assistant("alice"))

    def test_can_use_optimization_for_user(self):
        svc = MembershipService()
        svc.upsert_user("alice", "free")
        self.assertFalse(svc.can_use_optimization("alice"))
        svc.upsert_user("alice", "pro")
        self.assertTrue(svc.can_use_optimization("alice"))

    def test_can_use_optimization_anonymous(self):
        svc = MembershipService()
        self.assertFalse(svc.can_use_optimization(None))

    def test_purchase_list_price_not_a_number(self):
        svc = MembershipService()
        svc.upsert_user("alice", "free")
        with self.assertRaises(MembershipError):
            svc.purchase(username="alice", slug="strat-1", list_price="free")

    def test_addon_validation_rejects_bad_id(self):
        svc = MembershipService()
        svc.upsert_user("alice", "free")
        with self.assertRaises(MembershipError):
            svc.subscribe_addon("alice", "!!")

    def test_purchase_invalid_slug(self):
        svc = MembershipService()
        svc.upsert_user("alice", "free")
        with self.assertRaises(MembershipError):
            svc.purchase(username="alice", slug="!!", list_price=10)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
