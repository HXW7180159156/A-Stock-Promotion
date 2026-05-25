"""Zero-dependency REST API exposing the MVP + V1.0 surface.

Wraps :mod:`a_stock_promotion` with a small ``http.server`` based service
that satisfies PRD §4.1 (MVP) and §4.2 (V1.0: ETF module, 组合再平衡,
桌面端/管理端, 回测/参数优化/样本外验证, 运营榜单) without introducing
any third-party runtime dependencies.

Endpoints
---------
* Strategy catalogue & screening (MVP)
* Stock pool listing / detail (MVP)
* ETF pool listing / detail / screening (V1.0)
* Portfolio rebalance planner (V1.0)
* Backtest / grid optimisation / walk-forward (V1.0)
* Operational leaderboards (V1.0)
* Admin strategy registry (V1.0)
* Mobile SPA at ``/`` and desktop SPA at ``/desktop``

Run with ``python -m a_stock_promotion.api`` to start the bundled
service on ``http://127.0.0.1:8080``.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .admin import StrategyRegistry, StrategyRegistryError
from .ai_assistant import (
    AIAssistantError,
    explain_strategy,
    parse_prompt,
    summarize_results,
)
from .community import CommunityError, CommunityHub
from .membership import MembershipError, MembershipService
from .backtesting import (
    BacktestConfig,
    BacktestEngine,
    PriceBar,
    constant_metrics_provider,
    time_series_metrics_provider,
)
from .data_sources import SampleFundamentalProvider, SampleSentimentProvider
from .etf_pool import ETFFeatureAggregator, ETFListing, ETFPool, sample_etf_pool
from .features import FeatureAggregator
from .leaderboards import LeaderboardBuilder
from .models import StrategyProfile
from .optimization import (
    GridSearchOptimizer,
    score_calmar,
    score_sharpe,
    score_total_return,
)
from .portfolio import Holding, build_rebalance_plan, plan_from_selection
from .selection_engine import SelectionEngine
from .stock_pool import StockListing, StockPool, sample_stock_pool

logger = logging.getLogger(__name__)

WEB_ROOT = Path(__file__).resolve().parent / "web"
RISK_DISCLOSURE = (
    "本服务仅用于投资研究，所有结果不构成任何投资建议或收益承诺，"
    "投资有风险，入市需谨慎。"
)

# Symbols are A-share / ETF style codes (digits, optionally exchange prefix).
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{1,16}$")
_NAME_RE = re.compile(r"^[^\x00-\x1f]{1,64}$")  # printable, ≤64 chars
_SCORE_FUNCTIONS = {
    "sharpe": score_sharpe,
    "total_return": score_total_return,
    "calmar": score_calmar,
}


class APIService:
    """Application service backing the HTTP handler."""

    def __init__(
        self,
        aggregator: FeatureAggregator | None = None,
        strategies: Iterable[StrategyProfile] | None = None,
        etf_aggregator: ETFFeatureAggregator | None = None,
        registry: StrategyRegistry | None = None,
        community: CommunityHub | None = None,
        membership: MembershipService | None = None,
    ) -> None:
        self.aggregator = aggregator or FeatureAggregator(
            pool=sample_stock_pool(),
            fundamental_provider=SampleFundamentalProvider(),
            sentiment_provider=SampleSentimentProvider(),
        )
        self.etf_aggregator = etf_aggregator or ETFFeatureAggregator(
            pool=sample_etf_pool(),
        )
        self.registry = registry or StrategyRegistry(
            builtin_strategies=list(strategies) if strategies is not None else None,
        )
        self.community = community or CommunityHub()
        self.membership = membership or MembershipService()
        self.engine = SelectionEngine()
        self.backtest_engine = BacktestEngine(self.engine)
        self.optimizer = GridSearchOptimizer(self.backtest_engine)
        self.leaderboards = LeaderboardBuilder(self.engine)

    # ---- Strategy catalogue ------------------------------------------------

    def list_strategies(self) -> list[dict]:
        return [_strategy_to_dict(record.strategy) for record in self.registry.list()]

    def list_strategy_records(self) -> list[dict]:
        return [record.as_dict() for record in self.registry.list()]

    def get_strategy(self, name: str) -> StrategyProfile | None:
        record = self.registry.get(name)
        return record.strategy if record else None

    # ---- Stock pool --------------------------------------------------------

    def list_stocks(self, filters: Mapping[str, Any]) -> list[dict]:
        pool = self._apply_stock_filters(self.aggregator.pool, filters)
        return [_listing_to_dict(listing) for listing in pool]

    def get_stock_detail(self, symbol: str) -> dict | None:
        listing = self.aggregator.pool.get(symbol)
        if listing is None:
            return None
        metrics = self.aggregator.build(listing)
        return {
            "listing": _listing_to_dict(listing),
            "metrics": metrics.metrics,
            "risk_disclosure": RISK_DISCLOSURE,
        }

    # ---- ETF pool ----------------------------------------------------------

    def list_etfs(self, filters: Mapping[str, Any]) -> list[dict]:
        pool = self._apply_etf_filters(self.etf_aggregator.pool, filters)
        return [_etf_listing_to_dict(listing) for listing in pool]

    def get_etf_detail(self, symbol: str) -> dict | None:
        listing = self.etf_aggregator.pool.get(symbol)
        if listing is None:
            return None
        metrics = self.etf_aggregator.build(listing)
        return {
            "listing": _etf_listing_to_dict(listing),
            "metrics": metrics.metrics,
            "risk_disclosure": RISK_DISCLOSURE,
        }

    # ---- Selection ---------------------------------------------------------

    def run_selection(
        self, strategy_name: str, filters: Mapping[str, Any]
    ) -> dict:
        strategy = self.get_strategy(strategy_name)
        if strategy is None:
            raise KeyError(strategy_name)
        pool = self._apply_stock_filters(self.aggregator.pool, filters)
        candidates = self.aggregator.build_many(list(pool))
        ranked = self.engine.rank(candidates, strategy)
        return {
            "strategy": _strategy_to_dict(strategy),
            "results": [_result_to_dict(item) for item in ranked],
            "risk_disclosure": RISK_DISCLOSURE,
        }

    def run_etf_selection(
        self, strategy_name: str, filters: Mapping[str, Any]
    ) -> dict:
        strategy = self.get_strategy(strategy_name)
        if strategy is None:
            raise KeyError(strategy_name)
        pool = self._apply_etf_filters(self.etf_aggregator.pool, filters)
        candidates = self.etf_aggregator.build_many(list(pool))
        ranked = self.engine.rank(candidates, strategy)
        return {
            "strategy": _strategy_to_dict(strategy),
            "results": [_result_to_dict(item) for item in ranked],
            "risk_disclosure": RISK_DISCLOSURE,
        }

    # ---- Portfolio rebalance ----------------------------------------------

    def run_rebalance(self, payload: Mapping[str, Any]) -> dict:
        universe = str(payload.get("universe", "etf")).lower()
        if universe not in {"etf", "stock"}:
            raise ValueError("universe must be 'etf' or 'stock'")
        strategy_name = payload.get("strategy")
        if not isinstance(strategy_name, str) or not strategy_name:
            raise ValueError("strategy is required")
        strategy = self.get_strategy(strategy_name)
        if strategy is None:
            raise KeyError(strategy_name)
        filters = payload.get("filters") or {}
        if not isinstance(filters, Mapping):
            raise ValueError("filters must be an object")
        top_n = _coerce_int(payload.get("top_n", 5), "top_n", lo=1, hi=50)
        scheme = str(payload.get("scheme", "equal"))
        if scheme not in {"equal", "score"}:
            raise ValueError("scheme must be 'equal' or 'score'")
        max_weight = _coerce_float(
            payload.get("max_weight", 1.0), "max_weight", lo=0.01, hi=1.0
        )
        transaction_cost = _coerce_float(
            payload.get("transaction_cost", 0.001),
            "transaction_cost",
            lo=0.0,
            hi=0.5,
        )
        min_trade = _coerce_float(
            payload.get("min_trade", 0.005), "min_trade", lo=0.0, hi=1.0
        )
        only_selected = _coerce_bool(payload.get("only_selected", True))

        current_holdings = _parse_holdings(payload.get("current") or [])

        if universe == "etf":
            pool = self._apply_etf_filters(self.etf_aggregator.pool, filters)
            candidates = self.etf_aggregator.build_many(list(pool))
        else:
            pool = self._apply_stock_filters(self.aggregator.pool, filters)
            candidates = self.aggregator.build_many(list(pool))

        ranked = self.engine.rank(candidates, strategy)
        plan = plan_from_selection(
            ranked,
            current=current_holdings,
            top_n=top_n,
            scheme=scheme,
            max_weight=max_weight,
            transaction_cost=transaction_cost,
            min_trade=min_trade,
            only_selected=only_selected,
        )
        return {
            "strategy": _strategy_to_dict(strategy),
            "universe": universe,
            "plan": plan.as_dict(),
            "candidates": [_result_to_dict(item) for item in ranked[:top_n]],
            "risk_disclosure": RISK_DISCLOSURE,
        }

    # ---- Backtest / optimisation ------------------------------------------

    def run_backtest(self, payload: Mapping[str, Any]) -> dict:
        strategy_name = payload.get("strategy")
        if not isinstance(strategy_name, str) or not strategy_name:
            raise ValueError("strategy is required")
        strategy = self.get_strategy(strategy_name)
        if strategy is None:
            raise KeyError(strategy_name)
        price_data = _parse_price_data(payload.get("price_data"))
        metrics_provider, names = _parse_metrics_provider(payload.get("metrics"))
        cfg = _parse_backtest_config(payload.get("config") or {})
        # Validation: cap workload to keep the API bounded.
        _enforce_backtest_limits(price_data, cfg)

        result = self.backtest_engine.run(
            strategy=strategy,
            price_data=price_data,
            metrics_provider=metrics_provider,
            config=cfg,
            names=names,
        )
        return {
            "strategy": _strategy_to_dict(strategy),
            "summary": _backtest_summary(result),
            "equity_curve": [
                {"date": date, "equity": equity}
                for date, equity in zip(result.dates, result.equity_curve, strict=True)
            ],
            "rebalances": [
                {
                    "date": event.date,
                    "holdings": list(event.holdings),
                    "weights": list(event.weights),
                    "turnover": event.turnover,
                    "cost": event.cost,
                }
                for event in result.rebalances
            ],
            "risk_disclosure": RISK_DISCLOSURE,
        }

    def run_optimization(self, payload: Mapping[str, Any]) -> dict:
        strategy_name = payload.get("strategy")
        if not isinstance(strategy_name, str) or not strategy_name:
            raise ValueError("strategy is required")
        base_strategy = self.get_strategy(strategy_name)
        if base_strategy is None:
            raise KeyError(strategy_name)
        parameter_grid = payload.get("parameter_grid") or {}
        if not isinstance(parameter_grid, Mapping):
            raise ValueError("parameter_grid must be an object")
        # Bound the grid to prevent runaway combinatorics.
        total = 1
        for axis_values in parameter_grid.values():
            if not isinstance(axis_values, list) or not axis_values:
                raise ValueError(
                    "each parameter axis must be a non-empty list"
                )
            total *= len(axis_values)
        if total > 64:
            raise ValueError("parameter grid has too many combinations (max 64)")

        price_data = _parse_price_data(payload.get("price_data"))
        metrics_provider, names = _parse_metrics_provider(payload.get("metrics"))
        cfg = _parse_backtest_config(payload.get("config") or {})
        _enforce_backtest_limits(price_data, cfg)
        score_fn = _SCORE_FUNCTIONS[_validated_score(payload.get("score", "sharpe"))]

        factory = _make_threshold_factory(base_strategy)
        report = self.optimizer.run(
            strategy_factory=factory,
            parameter_grid=parameter_grid,
            price_data=price_data,
            metrics_provider=metrics_provider,
            config=cfg,
            score_fn=score_fn,
            names=names,
        )
        return {
            "strategy": _strategy_to_dict(base_strategy),
            "score": getattr(score_fn, "__name__", "score"),
            "trials": [
                {
                    "parameters": dict(trial.parameters),
                    "score": trial.score,
                    "summary": _backtest_summary(trial.result),
                }
                for trial in report.ranked
            ],
            "best": (
                {
                    "parameters": dict(report.best.parameters),
                    "score": report.best.score,
                    "summary": _backtest_summary(report.best.result),
                }
                if report.trials
                else None
            ),
            "risk_disclosure": RISK_DISCLOSURE,
        }

    def run_walk_forward(self, payload: Mapping[str, Any]) -> dict:
        strategy_name = payload.get("strategy")
        if not isinstance(strategy_name, str) or not strategy_name:
            raise ValueError("strategy is required")
        base_strategy = self.get_strategy(strategy_name)
        if base_strategy is None:
            raise KeyError(strategy_name)
        parameter_grid = payload.get("parameter_grid") or {}
        if not isinstance(parameter_grid, Mapping):
            raise ValueError("parameter_grid must be an object")
        total = 1
        for axis_values in parameter_grid.values():
            if not isinstance(axis_values, list) or not axis_values:
                raise ValueError(
                    "each parameter axis must be a non-empty list"
                )
            total *= len(axis_values)
        if total > 64:
            raise ValueError("parameter grid has too many combinations (max 64)")

        in_sample = _parse_price_data(payload.get("in_sample_price_data"))
        out_sample = _parse_price_data(payload.get("out_of_sample_price_data"))
        metrics_provider, names = _parse_metrics_provider(payload.get("metrics"))
        cfg = _parse_backtest_config(payload.get("config") or {})
        _enforce_backtest_limits(in_sample, cfg)
        _enforce_backtest_limits(out_sample, cfg)
        score_fn = _SCORE_FUNCTIONS[_validated_score(payload.get("score", "sharpe"))]

        factory = _make_threshold_factory(base_strategy)
        report = self.optimizer.walk_forward(
            strategy_factory=factory,
            parameter_grid=parameter_grid,
            in_sample_price_data=in_sample,
            out_of_sample_price_data=out_sample,
            metrics_provider=metrics_provider,
            config=cfg,
            score_fn=score_fn,
            names=names,
        )
        return {
            "strategy": _strategy_to_dict(base_strategy),
            "score": getattr(score_fn, "__name__", "score"),
            "best_parameters": dict(report.best_parameters),
            "in_sample_best": {
                "parameters": dict(report.in_sample.best.parameters),
                "score": report.in_sample.best.score,
                "summary": _backtest_summary(report.in_sample.best.result),
            },
            "out_of_sample": {
                "parameters": dict(report.out_of_sample.parameters),
                "score": report.out_of_sample.score,
                "summary": _backtest_summary(report.out_of_sample.result),
            },
            "risk_disclosure": RISK_DISCLOSURE,
        }

    # ---- Leaderboards ------------------------------------------------------

    def build_leaderboards(self, params: Mapping[str, Any]) -> dict:
        universe = str(params.get("universe", "stock")).lower()
        if universe not in {"stock", "etf"}:
            raise ValueError("universe must be 'stock' or 'etf'")
        top_n = _coerce_int(params.get("top_n", 5), "top_n", lo=1, hi=20)
        only_selected = _coerce_bool(params.get("only_selected", False))
        if universe == "etf":
            candidates = self.etf_aggregator.build_many()
            strategies = [
                record.strategy
                for record in self.registry.list()
                if record.strategy.name.startswith("ETF")
                or "ETF" in record.strategy.name
            ]
        else:
            candidates = self.aggregator.build_many()
            strategies = [
                record.strategy
                for record in self.registry.list()
                if "ETF" not in record.strategy.name
            ]
        if not strategies:
            strategies = self.registry.list_strategies()
        boards = self.leaderboards.build_many(
            strategies=strategies,
            candidates=candidates,
            top_n=top_n,
            only_selected=only_selected,
            universe=universe,
        )
        return {
            "universe": universe,
            "leaderboards": [board.as_dict() for board in boards],
            "risk_disclosure": RISK_DISCLOSURE,
        }

    # ---- AI assistant (V2.0) ----------------------------------------------

    def ai_parse_prompt(self, payload: Mapping[str, Any]) -> dict:
        prompt = payload.get("prompt")
        name = payload.get("name")
        default_combine = str(payload.get("default_combine", "and"))
        username = payload.get("username")
        if username is not None and not self.membership.can_use_ai_assistant(
            str(username)
        ):
            raise PermissionError("AI 助手不可用，请升级会员")
        result = parse_prompt(
            prompt if isinstance(prompt, str) else "",
            name=name if isinstance(name, str) else None,
            default_combine=default_combine,
        )
        return {
            **result.as_dict(),
            "risk_disclosure": RISK_DISCLOSURE,
        }

    def ai_explain_strategy(self, name: str) -> dict:
        strategy = self.get_strategy(name)
        if strategy is None:
            raise KeyError(name)
        return {
            "strategy": _strategy_to_dict(strategy),
            "explanation": explain_strategy(strategy),
            "risk_disclosure": RISK_DISCLOSURE,
        }

    def ai_summarize_selection(self, payload: Mapping[str, Any]) -> dict:
        strategy_name = payload.get("strategy")
        if not isinstance(strategy_name, str) or not strategy_name:
            raise ValueError("strategy is required")
        strategy = self.get_strategy(strategy_name)
        if strategy is None:
            raise KeyError(strategy_name)
        universe = str(payload.get("universe", "stock")).lower()
        if universe not in {"stock", "etf"}:
            raise ValueError("universe must be 'stock' or 'etf'")
        filters = payload.get("filters") or {}
        if not isinstance(filters, Mapping):
            raise ValueError("filters must be an object")
        top_n = _coerce_int(payload.get("top_n", 5), "top_n", lo=1, hi=20)
        if universe == "etf":
            pool = self._apply_etf_filters(self.etf_aggregator.pool, filters)
            candidates = self.etf_aggregator.build_many(list(pool))
        else:
            pool = self._apply_stock_filters(self.aggregator.pool, filters)
            candidates = self.aggregator.build_many(list(pool))
        ranked = self.engine.rank(candidates, strategy)
        summary = summarize_results(ranked, top_n=top_n)
        return {
            "strategy": _strategy_to_dict(strategy),
            "universe": universe,
            "summary": summary,
            "results": [_result_to_dict(item) for item in ranked[:top_n]],
            "risk_disclosure": RISK_DISCLOSURE,
        }

    # ---- Community (V2.0) -------------------------------------------------

    def community_list(self, query: Mapping[str, Any]) -> dict:
        owner = query.get("owner") if query.get("owner") else None
        tag = query.get("tag") if query.get("tag") else None
        only_free = _coerce_bool(query.get("only_free", False))
        shares = self.community.list_shares(
            owner=str(owner) if owner else None,
            tag=str(tag) if tag else None,
            only_free=only_free,
        )
        return {"shares": [item.as_dict() for item in shares]}

    def community_publish(self, payload: Mapping[str, Any]) -> dict:
        slug = payload.get("slug")
        owner = payload.get("owner")
        description = payload.get("description", "")
        tags = payload.get("tags") or []
        price = payload.get("price", 0.0)
        strategy_payload = payload.get("strategy")
        if strategy_payload is None:
            raise ValueError("strategy is required")
        # Reuse admin validation so the API surface is uniform.
        from .admin import _strategy_from_payload  # local import to avoid cycle

        try:
            try:
                price_value = float(price)
            except (TypeError, ValueError) as exc:
                raise CommunityError("price must be a number") from exc
            if price_value > 0 and isinstance(owner, str):
                user = self.membership.get_user(owner)
                if user is None or not self.membership.get_benefits(
                    user.tier
                ).can_publish_paid_strategy:
                    raise PermissionError(
                        "只有 Pro/VIP 会员可以发布付费策略"
                    )
            try:
                strategy = _strategy_from_payload(strategy_payload)
            except StrategyRegistryError as exc:
                raise CommunityError(str(exc)) from exc
            record = self.community.publish(
                slug=str(slug) if slug is not None else "",
                owner=str(owner) if owner is not None else "",
                strategy=strategy,
                description=str(description) if description else "",
                tags=tags,
                price=price_value,
            )
        except CommunityError as exc:
            raise ValueError(str(exc)) from exc
        return {"share": record.as_dict()}

    def community_get(self, slug: str) -> dict | None:
        record = self.community.get_share(slug)
        if record is None:
            return None
        comments = self.community.list_comments(slug)
        return {
            "share": record.as_dict(),
            "comments": [comment.as_dict() for comment in comments],
        }

    def community_subscribe(self, slug: str, payload: Mapping[str, Any]) -> dict:
        user = payload.get("username")
        if not isinstance(user, str):
            raise ValueError("username is required")
        record = self.community.get_share(slug)
        if record is None:
            raise KeyError(slug)
        if record.is_paid and not self.membership.has_purchased(user, slug):
            raise PermissionError("付费策略需先在策略市场购买")
        try:
            updated = self.community.subscribe(slug, user)
        except CommunityError as exc:
            raise ValueError(str(exc)) from exc
        return {"share": updated.as_dict()}

    def community_unsubscribe(self, slug: str, payload: Mapping[str, Any]) -> dict:
        user = payload.get("username")
        if not isinstance(user, str):
            raise ValueError("username is required")
        try:
            updated = self.community.unsubscribe(slug, user)
        except CommunityError as exc:
            if "not found" in str(exc):
                raise KeyError(slug) from exc
            raise ValueError(str(exc)) from exc
        return {"share": updated.as_dict()}

    def community_comment(self, slug: str, payload: Mapping[str, Any]) -> dict:
        author = payload.get("author")
        body = payload.get("body")
        if not isinstance(author, str):
            raise ValueError("author is required")
        if not isinstance(body, str):
            raise ValueError("body is required")
        record = self.community.get_share(slug)
        if record is None:
            raise KeyError(slug)
        if record.is_paid and not (
            self.membership.has_purchased(author, slug)
            or record.owner == author
        ):
            raise PermissionError("仅订阅或购买后可评论付费策略")
        try:
            comment = self.community.add_comment(slug, author=author, body=body)
        except CommunityError as exc:
            raise ValueError(str(exc)) from exc
        return {"comment": comment.as_dict()}

    # ---- Membership (V2.0) ------------------------------------------------

    def membership_benefits(self) -> dict:
        return {
            "tiers": [item.as_dict() for item in self.membership.list_benefits()],
        }

    def membership_upsert_user(self, payload: Mapping[str, Any]) -> dict:
        username = payload.get("username")
        tier = payload.get("tier")
        if not isinstance(username, str):
            raise ValueError("username is required")
        if not isinstance(tier, str):
            raise ValueError("tier is required")
        try:
            user = self.membership.upsert_user(username, tier)  # type: ignore[arg-type]
        except MembershipError as exc:
            raise ValueError(str(exc)) from exc
        return {"user": user.as_dict()}

    def membership_get_user(self, username: str) -> dict | None:
        user = self.membership.get_user(username)
        if user is None:
            return None
        orders = self.membership.list_orders(username)
        return {
            "user": user.as_dict(),
            "orders": [order.as_dict() for order in orders],
        }

    def membership_subscribe_addon(self, payload: Mapping[str, Any]) -> dict:
        username = payload.get("username")
        addon = payload.get("addon")
        if not isinstance(username, str):
            raise ValueError("username is required")
        if not isinstance(addon, str):
            raise ValueError("addon is required")
        try:
            user = self.membership.subscribe_addon(username, addon)
        except MembershipError as exc:
            msg = str(exc)
            if "not found" in msg:
                raise KeyError(username) from exc
            raise ValueError(msg) from exc
        return {"user": user.as_dict()}

    def marketplace_purchase(self, payload: Mapping[str, Any]) -> dict:
        username = payload.get("username")
        slug = payload.get("slug")
        if not isinstance(username, str):
            raise ValueError("username is required")
        if not isinstance(slug, str):
            raise ValueError("slug is required")
        share = self.community.get_share(slug)
        if share is None:
            raise KeyError(slug)
        if not share.is_paid:
            raise ValueError("strategy is free; no purchase required")
        try:
            order = self.membership.purchase(
                username=username, slug=slug, list_price=share.price
            )
        except MembershipError as exc:
            msg = str(exc)
            if "not found" in msg:
                raise KeyError(username) from exc
            raise ValueError(msg) from exc
        return {"order": order.as_dict(), "share": share.as_dict()}

    # ---- Internal helpers --------------------------------------------------

    @staticmethod
    def _apply_stock_filters(pool: StockPool, filters: Mapping[str, Any]) -> StockPool:
        kwargs: dict[str, Any] = {}
        for key in ("exchange", "industry", "sector"):
            value = filters.get(key)
            if value:
                kwargs[key] = value
        only_tradable = filters.get("only_tradable")
        if only_tradable is not None:
            kwargs["only_tradable"] = _coerce_bool(only_tradable)
        include_st = filters.get("include_st")
        if include_st is not None:
            kwargs["include_st"] = _coerce_bool(include_st)
        return pool.filter(**kwargs)

    @staticmethod
    def _apply_etf_filters(pool: ETFPool, filters: Mapping[str, Any]) -> ETFPool:
        kwargs: dict[str, Any] = {}
        for key in ("exchange", "asset_class", "sector", "tracking_index"):
            value = filters.get(key)
            if value:
                kwargs[key] = value
        only_tradable = filters.get("only_tradable")
        if only_tradable is not None:
            kwargs["only_tradable"] = _coerce_bool(only_tradable)
        return pool.filter(**kwargs)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def _strategy_to_dict(strategy: StrategyProfile) -> dict:
    return {
        "name": strategy.name,
        "combine_mode": strategy.combine_mode,
        "min_score": strategy.min_score,
        "rules": [
            {
                "metric": rule.metric,
                "operator": rule.operator,
                "threshold": rule.threshold,
                "weight": rule.weight,
                "required": rule.required,
                "description": rule.description,
            }
            for rule in strategy.rules
        ],
    }


def _listing_to_dict(listing: StockListing) -> dict:
    return {
        "symbol": listing.symbol,
        "name": listing.name,
        "exchange": listing.exchange,
        "industry": listing.industry,
        "sector": listing.sector,
        "is_tradable": listing.is_tradable,
        "is_st": listing.is_st,
        "list_date": listing.list_date,
    }


def _etf_listing_to_dict(listing: ETFListing) -> dict:
    return {
        "symbol": listing.symbol,
        "name": listing.name,
        "exchange": listing.exchange,
        "asset_class": listing.asset_class,
        "tracking_index": listing.tracking_index,
        "sector": listing.sector,
        "manager": listing.manager,
        "inception_date": listing.inception_date,
        "is_tradable": listing.is_tradable,
    }


def _result_to_dict(item) -> dict:
    return {
        "symbol": item.candidate.symbol,
        "name": item.candidate.name,
        "score": item.score,
        "selected": item.selected,
        "matched_rules": list(item.matched_rules),
        "missed_rules": list(item.missed_rules),
        "metrics": item.candidate.metrics,
    }


def _backtest_summary(result) -> dict:
    return {
        "total_return": result.total_return,
        "annualized_return": result.annualized_return,
        "annual_volatility": result.annual_volatility,
        "sharpe_ratio": result.sharpe_ratio,
        "max_drawdown": result.max_drawdown,
        "win_rate": result.win_rate,
        "turnover": result.turnover,
        "trade_count": result.trade_count,
        "bars": len(result.equity_curve),
    }


# ---------------------------------------------------------------------------
# Payload coercion helpers
# ---------------------------------------------------------------------------
def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _coerce_int(value: Any, name: str, *, lo: int, hi: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not lo <= result <= hi:
        raise ValueError(f"{name} must be between {lo} and {hi}")
    return result


def _coerce_float(value: Any, name: str, *, lo: float, hi: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not lo <= result <= hi:
        raise ValueError(f"{name} must be between {lo} and {hi}")
    return result


def _validated_score(name: Any) -> str:
    if name not in _SCORE_FUNCTIONS:
        raise ValueError(
            f"score must be one of {sorted(_SCORE_FUNCTIONS)}"
        )
    return str(name)


def _parse_holdings(payload: Any) -> list[Holding]:
    if not isinstance(payload, list):
        raise ValueError("current holdings must be a list")
    result: list[Holding] = []
    for index, entry in enumerate(payload):
        if not isinstance(entry, Mapping):
            raise ValueError(f"holding #{index} must be an object")
        symbol = entry.get("symbol")
        if not isinstance(symbol, str) or not _SYMBOL_RE.fullmatch(symbol.upper()):
            raise ValueError(f"holding #{index}: invalid symbol")
        try:
            weight = float(entry.get("weight", 0.0))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"holding #{index}: weight must be a number"
            ) from exc
        result.append(Holding(symbol=symbol.upper(), weight=weight))
    return result


def _parse_price_data(payload: Any) -> dict[str, list[PriceBar]]:
    if not isinstance(payload, Mapping) or not payload:
        raise ValueError("price_data must be a non-empty object")
    if len(payload) > 20:
        raise ValueError("price_data must contain at most 20 symbols")
    result: dict[str, list[PriceBar]] = {}
    for symbol, bars in payload.items():
        if not isinstance(symbol, str) or not _SYMBOL_RE.fullmatch(symbol.upper()):
            raise ValueError(f"invalid price_data symbol: {symbol!r}")
        if not isinstance(bars, list) or not bars:
            raise ValueError(f"price_data[{symbol}] must be a non-empty list")
        if len(bars) > 2000:
            raise ValueError(
                f"price_data[{symbol}] must contain at most 2000 bars"
            )
        parsed: list[PriceBar] = []
        for index, bar in enumerate(bars):
            if not isinstance(bar, Mapping):
                raise ValueError(
                    f"price_data[{symbol}][{index}] must be an object"
                )
            date = bar.get("date")
            if not isinstance(date, str) or not _is_valid_date(date):
                raise ValueError(
                    f"price_data[{symbol}][{index}]: invalid date"
                )
            try:
                close = float(bar.get("close"))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"price_data[{symbol}][{index}]: close must be a number"
                ) from exc
            tradable = _coerce_bool(bar.get("tradable", True))
            parsed.append(PriceBar(date=date, close=close, tradable=tradable))
        result[symbol.upper()] = parsed
    return result


def _parse_metrics_provider(payload: Any):
    """Accept either a flat {symbol: metrics} or {symbol: {date: metrics}} map.

    Returns ``(provider, names)`` where ``names`` is the symbol → display
    name mapping pulled from the optional ``name`` field on each metrics
    entry (when present).
    """

    if not isinstance(payload, Mapping) or not payload:
        raise ValueError("metrics must be a non-empty object")
    names: dict[str, str] = {}
    is_time_series = _is_time_series_metrics(payload)
    if is_time_series:
        snapshots: dict[str, dict[str, dict[str, float]]] = {}
        for symbol, by_date in payload.items():
            if not isinstance(symbol, str) or not _SYMBOL_RE.fullmatch(symbol.upper()):
                raise ValueError(f"invalid metrics symbol: {symbol!r}")
            if not isinstance(by_date, Mapping):
                raise ValueError(f"metrics[{symbol}] must be an object")
            inner: dict[str, dict[str, float]] = {}
            for date, snap in by_date.items():
                if not _is_valid_date(date):
                    raise ValueError(f"metrics[{symbol}]: invalid date {date!r}")
                inner[date] = _coerce_metric_snapshot(snap, f"metrics[{symbol}][{date}]")
            snapshots[symbol.upper()] = inner
        provider = time_series_metrics_provider(snapshots)
    else:
        snapshots_flat: dict[str, dict[str, float]] = {}
        for symbol, snap in payload.items():
            if not isinstance(symbol, str) or not _SYMBOL_RE.fullmatch(symbol.upper()):
                raise ValueError(f"invalid metrics symbol: {symbol!r}")
            name = None
            if isinstance(snap, Mapping):
                name = snap.get("name")
            if isinstance(name, str) and _NAME_RE.fullmatch(name):
                names[symbol.upper()] = name
            snapshots_flat[symbol.upper()] = _coerce_metric_snapshot(
                snap, f"metrics[{symbol}]"
            )
        provider = constant_metrics_provider(snapshots_flat)
    return provider, names


def _is_time_series_metrics(payload: Mapping[str, Any]) -> bool:
    """True iff every leaf is itself a mapping keyed by ISO date strings."""

    for snap in payload.values():
        if not isinstance(snap, Mapping):
            return False
        if not snap:
            return False
        for key in snap.keys():
            if not isinstance(key, str) or not _is_valid_date(key):
                return False
    return True


def _coerce_metric_snapshot(snap: Any, path: str) -> dict[str, float]:
    if not isinstance(snap, Mapping):
        raise ValueError(f"{path} must be an object")
    out: dict[str, float] = {}
    for key, value in snap.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{path}: metric name must be a non-empty string")
        if key == "name":
            continue  # display name, handled separately
        try:
            out[key] = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{path}.{key} must be a number") from exc
    return out


def _is_valid_date(value: Any) -> bool:
    if not isinstance(value, str) or len(value) > 32:
        return False
    # Accept ISO-like calendar/date-time strings using a conservative pattern.
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?)?", value))


def _parse_backtest_config(payload: Mapping[str, Any]) -> BacktestConfig:
    if not isinstance(payload, Mapping):
        raise ValueError("config must be an object")
    kwargs: dict[str, Any] = {}
    if "rebalance_every" in payload:
        kwargs["rebalance_every"] = _coerce_int(
            payload["rebalance_every"], "rebalance_every", lo=1, hi=252
        )
    if "transaction_cost" in payload:
        kwargs["transaction_cost"] = _coerce_float(
            payload["transaction_cost"], "transaction_cost", lo=0.0, hi=0.5
        )
    if "top_n" in payload:
        kwargs["top_n"] = _coerce_int(payload["top_n"], "top_n", lo=1, hi=50)
    if "initial_capital" in payload:
        kwargs["initial_capital"] = _coerce_float(
            payload["initial_capital"],
            "initial_capital",
            lo=1.0,
            hi=1e12,
        )
    if "risk_free_rate" in payload:
        kwargs["risk_free_rate"] = _coerce_float(
            payload["risk_free_rate"], "risk_free_rate", lo=-1.0, hi=1.0
        )
    if "periods_per_year" in payload:
        kwargs["periods_per_year"] = _coerce_int(
            payload["periods_per_year"], "periods_per_year", lo=1, hi=400
        )
    return BacktestConfig(**kwargs)


def _enforce_backtest_limits(
    price_data: Mapping[str, Sequence[PriceBar]], cfg: BacktestConfig
) -> None:
    # Total bars across symbols × top_n bounds the engine cost.
    total_bars = sum(len(bars) for bars in price_data.values())
    if total_bars > 5000:
        raise ValueError("backtest workload exceeds limit (max 5000 total bars)")


def _make_threshold_factory(base: StrategyProfile):
    """Build a strategy factory that overrides rule thresholds by metric.

    The optimization endpoint exposes a constrained search over per-metric
    thresholds for the supplied template — this keeps the public surface
    safe (callers cannot inject arbitrary rules) while still satisfying
    PRD §4.2 V1.0 参数优化 / 样本外验证 requirements.
    """

    def factory(params: Mapping[str, Any]) -> StrategyProfile:
        new_rules = []
        for rule in base.rules:
            if rule.metric in params:
                try:
                    threshold = float(params[rule.metric])
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"parameter {rule.metric!r} must be a number"
                    ) from exc
                new_rules.append(
                    type(rule)(
                        metric=rule.metric,
                        operator=rule.operator,
                        threshold=threshold,
                        weight=rule.weight,
                        required=rule.required,
                        description=rule.description,
                    )
                )
            else:
                new_rules.append(rule)
        return StrategyProfile(
            name=base.name,
            rules=tuple(new_rules),
            combine_mode=base.combine_mode,
            min_score=base.min_score,
        )

    return factory


# ---------------------------------------------------------------------------
# Static assets
# ---------------------------------------------------------------------------
_STATIC_ASSETS: dict[str, Path] = {
    "index.html": WEB_ROOT / "index.html",
    "app.js": WEB_ROOT / "app.js",
    "styles.css": WEB_ROOT / "styles.css",
    "desktop.html": WEB_ROOT / "desktop.html",
    "desktop.js": WEB_ROOT / "desktop.js",
    "desktop.css": WEB_ROOT / "desktop.css",
}


def _safe_static_path(rel_path: str) -> Path | None:
    """Return the static asset for ``rel_path``, or ``None`` if not allowed.

    Uses an explicit allow-list of bundled assets keyed by their basename so
    that user-controlled path components never reach the filesystem layer.
    """

    rel = rel_path.lstrip("/") or "index.html"
    if rel == "desktop":
        rel = "desktop.html"
    return _STATIC_ASSETS.get(rel)


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
class APIRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler exposing JSON endpoints and the static UI."""

    service: APIService | None = None  # injected by ``run`` / tests
    server_version = "AStockPromotion/1.0"

    # Disable noisy default logging unless explicitly enabled.
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        logger.debug("%s - %s", self.address_string(), format % args)

    # ---- Dispatch ----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        if self.service is None:
            self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "service not configured"})
            return
        url = urlsplit(self.path)
        path = url.path.rstrip("/") or "/"
        query = {key: values[-1] for key, values in parse_qs(url.query).items()}
        try:
            if path == "/api/health":
                self._send_json(HTTPStatus.OK, {"status": "ok"})
                return
            if path == "/api/strategies":
                self._send_json(
                    HTTPStatus.OK,
                    {"strategies": self.service.list_strategies()},
                )
                return
            if path == "/api/admin/strategies":
                self._send_json(
                    HTTPStatus.OK,
                    {"strategies": self.service.list_strategy_records()},
                )
                return
            if path == "/api/stocks":
                self._send_json(HTTPStatus.OK, {"stocks": self.service.list_stocks(query)})
                return
            if path == "/api/etfs":
                self._send_json(HTTPStatus.OK, {"etfs": self.service.list_etfs(query)})
                return
            if path == "/api/leaderboards":
                self._send_json(
                    HTTPStatus.OK, self.service.build_leaderboards(query)
                )
                return
            if path == "/api/membership/benefits":
                self._send_json(HTTPStatus.OK, self.service.membership_benefits())
                return
            if path == "/api/community/shares":
                self._send_json(
                    HTTPStatus.OK, self.service.community_list(query)
                )
                return
            membership_user_match = re.fullmatch(
                r"/api/membership/users/([A-Za-z0-9_\-]{2,32})", path
            )
            if membership_user_match:
                username = membership_user_match.group(1)
                detail = self.service.membership_get_user(username)
                if detail is None:
                    self._send_json(
                        HTTPStatus.NOT_FOUND, {"error": "user not found"}
                    )
                    return
                self._send_json(HTTPStatus.OK, detail)
                return
            community_get_match = re.fullmatch(
                r"/api/community/shares/([A-Za-z0-9_\-]{2,64})", path
            )
            if community_get_match:
                slug = community_get_match.group(1)
                detail = self.service.community_get(slug)
                if detail is None:
                    self._send_json(
                        HTTPStatus.NOT_FOUND, {"error": "share not found"}
                    )
                    return
                self._send_json(HTTPStatus.OK, detail)
                return
            ai_explain_match = re.fullmatch(
                r"/api/ai/strategies/([^/]+)/explain", path
            )
            if ai_explain_match:
                name = _decode_path_segment(ai_explain_match.group(1))
                try:
                    self._send_json(
                        HTTPStatus.OK, self.service.ai_explain_strategy(name)
                    )
                except KeyError:
                    self._send_json(
                        HTTPStatus.NOT_FOUND, {"error": "strategy not found"}
                    )
                return
            stock_match = re.fullmatch(r"/api/stocks/([A-Za-z0-9]+)", path)
            if stock_match:
                symbol = stock_match.group(1).upper()
                if not _SYMBOL_RE.fullmatch(symbol):
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid symbol"})
                    return
                detail = self.service.get_stock_detail(symbol)
                if detail is None:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "stock not found"})
                    return
                self._send_json(HTTPStatus.OK, detail)
                return
            etf_match = re.fullmatch(r"/api/etfs/([A-Za-z0-9]+)", path)
            if etf_match:
                symbol = etf_match.group(1).upper()
                if not _SYMBOL_RE.fullmatch(symbol):
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid symbol"})
                    return
                detail = self.service.get_etf_detail(symbol)
                if detail is None:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "etf not found"})
                    return
                self._send_json(HTTPStatus.OK, detail)
                return
            # Fall back to static file serving for the SPAs.
            self._serve_static(url.path)
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception:  # pragma: no cover - defensive
            logger.exception("unhandled GET error for %s", self.path)
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal error"})

    def do_POST(self) -> None:  # noqa: N802
        if self.service is None:
            self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "service not configured"})
            return
        url = urlsplit(self.path)
        path = url.path.rstrip("/") or "/"
        try:
            payload = self._read_json() if self.headers.get("Content-Length") else {}
            if path == "/api/select":
                self._handle_selection(payload, etf=False)
                return
            if path == "/api/etfs/select":
                self._handle_selection(payload, etf=True)
                return
            if path == "/api/portfolio/rebalance":
                self._send_json(HTTPStatus.OK, self.service.run_rebalance(payload))
                return
            if path == "/api/backtest/run":
                self._send_json(HTTPStatus.OK, self.service.run_backtest(payload))
                return
            if path == "/api/backtest/optimize":
                self._send_json(HTTPStatus.OK, self.service.run_optimization(payload))
                return
            if path == "/api/backtest/walk-forward":
                self._send_json(HTTPStatus.OK, self.service.run_walk_forward(payload))
                return
            if path == "/api/admin/strategies":
                try:
                    record = self.service.registry.create(payload)
                except StrategyRegistryError as exc:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                self._send_json(HTTPStatus.CREATED, {"strategy": record.as_dict()})
                return
            if path == "/api/ai/parse":
                try:
                    self._send_json(
                        HTTPStatus.OK, self.service.ai_parse_prompt(payload)
                    )
                except AIAssistantError as exc:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            if path == "/api/ai/summarize":
                self._send_json(
                    HTTPStatus.OK, self.service.ai_summarize_selection(payload)
                )
                return
            if path == "/api/community/shares":
                try:
                    result = self.service.community_publish(payload)
                except CommunityError as exc:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                self._send_json(HTTPStatus.CREATED, result)
                return
            community_sub_match = re.fullmatch(
                r"/api/community/shares/([A-Za-z0-9_\-]{2,64})/subscribe", path
            )
            if community_sub_match:
                slug = community_sub_match.group(1)
                self._send_json(
                    HTTPStatus.OK,
                    self.service.community_subscribe(slug, payload),
                )
                return
            community_unsub_match = re.fullmatch(
                r"/api/community/shares/([A-Za-z0-9_\-]{2,64})/unsubscribe", path
            )
            if community_unsub_match:
                slug = community_unsub_match.group(1)
                self._send_json(
                    HTTPStatus.OK,
                    self.service.community_unsubscribe(slug, payload),
                )
                return
            community_comment_match = re.fullmatch(
                r"/api/community/shares/([A-Za-z0-9_\-]{2,64})/comments", path
            )
            if community_comment_match:
                slug = community_comment_match.group(1)
                result = self.service.community_comment(slug, payload)
                self._send_json(HTTPStatus.CREATED, result)
                return
            if path == "/api/membership/users":
                self._send_json(
                    HTTPStatus.OK, self.service.membership_upsert_user(payload)
                )
                return
            if path == "/api/membership/addons":
                self._send_json(
                    HTTPStatus.OK,
                    self.service.membership_subscribe_addon(payload),
                )
                return
            if path == "/api/marketplace/purchase":
                self._send_json(
                    HTTPStatus.CREATED,
                    self.service.marketplace_purchase(payload),
                )
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except KeyError:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except PermissionError as exc:
            self._send_json(HTTPStatus.FORBIDDEN, {"error": str(exc)})
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception:  # pragma: no cover - defensive
            logger.exception("unhandled POST error for %s", self.path)
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal error"})

    def do_PUT(self) -> None:  # noqa: N802
        if self.service is None:
            self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "service not configured"})
            return
        url = urlsplit(self.path)
        path = url.path.rstrip("/") or "/"
        try:
            payload = self._read_json() if self.headers.get("Content-Length") else {}
            admin_match = re.fullmatch(
                r"/api/admin/strategies/([^/]+)", path
            )
            if admin_match:
                name = _decode_path_segment(admin_match.group(1))
                try:
                    record = self.service.registry.update(name, payload)
                except StrategyRegistryError as exc:
                    msg = str(exc)
                    if "not found" in msg:
                        self._send_json(HTTPStatus.NOT_FOUND, {"error": msg})
                    elif "read-only" in msg:
                        self._send_json(HTTPStatus.FORBIDDEN, {"error": msg})
                    else:
                        self._send_json(HTTPStatus.BAD_REQUEST, {"error": msg})
                    return
                self._send_json(HTTPStatus.OK, {"strategy": record.as_dict()})
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception:  # pragma: no cover - defensive
            logger.exception("unhandled PUT error for %s", self.path)
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal error"})

    def do_DELETE(self) -> None:  # noqa: N802
        if self.service is None:
            self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "service not configured"})
            return
        url = urlsplit(self.path)
        path = url.path.rstrip("/") or "/"
        try:
            admin_match = re.fullmatch(
                r"/api/admin/strategies/([^/]+)", path
            )
            if admin_match:
                name = _decode_path_segment(admin_match.group(1))
                try:
                    self.service.registry.delete(name)
                except StrategyRegistryError as exc:
                    msg = str(exc)
                    if "not found" in msg:
                        self._send_json(HTTPStatus.NOT_FOUND, {"error": msg})
                    elif "read-only" in msg:
                        self._send_json(HTTPStatus.FORBIDDEN, {"error": msg})
                    else:
                        self._send_json(HTTPStatus.BAD_REQUEST, {"error": msg})
                    return
                self._send_json(HTTPStatus.OK, {"status": "deleted", "name": name})
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except Exception:  # pragma: no cover - defensive
            logger.exception("unhandled DELETE error for %s", self.path)
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal error"})

    # ---- Helpers -----------------------------------------------------------

    def _handle_selection(self, payload: Mapping[str, Any], *, etf: bool) -> None:
        strategy_name = payload.get("strategy")
        if not strategy_name or not isinstance(strategy_name, str):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "strategy is required"})
            return
        filters = payload.get("filters") or {}
        if not isinstance(filters, dict):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "filters must be an object"})
            return
        try:
            if etf:
                result = self.service.run_etf_selection(strategy_name, filters)
            else:
                result = self.service.run_selection(strategy_name, filters)
        except KeyError:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "strategy not found"})
            return
        self._send_json(HTTPStatus.OK, result)

    def _read_json(self) -> dict:
        length_header = self.headers.get("Content-Length")
        try:
            length = int(length_header or "0")
        except ValueError as exc:
            raise ValueError("invalid Content-Length header") from exc
        # Cap payload at 512KB; backtest requests carry price/metric arrays.
        if length < 0 or length > 512 * 1024:
            raise ValueError("payload too large")
        body = self.rfile.read(length) if length else b""
        if not body:
            return {}
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid JSON body") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _send_json(self, status: HTTPStatus, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _serve_static(self, raw_path: str) -> None:
        path = _safe_static_path(raw_path)
        if path is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        content_type = _content_type_for(path)
        data = path.read_bytes()
        self.send_response(int(HTTPStatus.OK))
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        # Static assets are versioned together with the package; allow short caching.
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)


def _content_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".ico": "image/x-icon",
    }.get(suffix, "application/octet-stream")


def _decode_path_segment(raw: str) -> str:
    from urllib.parse import unquote

    value = unquote(raw)
    if not value or len(value) > 64 or any(ord(ch) < 0x20 for ch in value):
        raise ValueError("invalid strategy name")
    return value


def build_handler(service: APIService) -> type[APIRequestHandler]:
    """Return a handler subclass with the service injected."""

    return type("BoundAPIRequestHandler", (APIRequestHandler,), {"service": service})


def run(host: str = "127.0.0.1", port: int = 8080) -> None:  # pragma: no cover - entry
    """Start the bundled HTTP server (blocking)."""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    handler_cls = build_handler(APIService())
    with ThreadingHTTPServer((host, port), handler_cls) as server:
        logger.info("serving on http://%s:%s", host, port)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            logger.info("shutting down")


if __name__ == "__main__":  # pragma: no cover
    import os

    host = os.environ.get("HOST", "0.0.0.0")
    try:
        port = int(os.environ.get("PORT", "8080"))
    except ValueError:
        port = 8080
    run(host=host, port=port)
