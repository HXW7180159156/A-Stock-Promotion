"""Built-in strategy templates derived from the product blueprint."""

from __future__ import annotations

from .models import StrategyProfile, StrategyRule


def default_stock_strategy() -> StrategyProfile:
    """Multi-factor A-share strategy for the MVP stage."""

    return StrategyProfile(
        name="A股多因子MVP策略",
        combine_mode="or",
        min_score=0.6,
        rules=(
            StrategyRule("ma_trend", ">=", 1, 1.2, True, "均线趋势向上"),
            StrategyRule("rsi", ">=", 45, 0.8, False, "RSI处于强势区间"),
            StrategyRule("roe", ">=", 10, 1.5, True, "ROE不低于10%"),
            StrategyRule("revenue_growth", ">=", 8, 1.0, False, "营收增速不低于8%"),
            StrategyRule("debt_ratio", "<=", 65, 0.8, False, "资产负债率不高于65%"),
            StrategyRule("northbound_inflow", ">", 0, 0.7, False, "北向资金净流入"),
        ),
    )


def default_etf_strategy() -> StrategyProfile:
    """ETF screening strategy template for the V1.0 stage."""

    return StrategyProfile(
        name="ETF质量筛选策略",
        combine_mode="and",
        min_score=0.0,
        rules=(
            StrategyRule("tracking_error", "<=", 0.02, 1.0, True, "跟踪误差不高于2%"),
            StrategyRule("daily_turnover", ">=", 50_000_000, 1.0, True, "日成交额不低于5000万"),
            StrategyRule("fund_size", ">=", 500_000_000, 1.0, True, "基金规模不低于5亿"),
            StrategyRule("expense_ratio", "<=", 0.006, 1.0, True, "综合费率不高于0.6%"),
            StrategyRule("premium_discount", "<=", 0.01, 1.0, True, "折溢价率不高于1%"),
        ),
    )
