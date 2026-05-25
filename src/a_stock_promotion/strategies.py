"""Built-in strategy templates derived from the product blueprint.

These templates satisfy PRD §7 acceptance criterion of providing at least 10
built-in screening templates and cover the technical, fundamental, sentiment
and ETF dimensions described in `docs/PRD.md` §4 and
`docs/TECHNICAL_ARCHITECTURE.md` §4.
"""

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


def trend_following_strategy() -> StrategyProfile:
    """Technical trend-following template (均线 + MACD + 量能)."""

    return StrategyProfile(
        name="技术趋势跟随策略",
        combine_mode="and",
        min_score=0.0,
        rules=(
            StrategyRule("ma_trend", ">=", 1, 1.0, True, "均线多头排列"),
            StrategyRule("macd_hist", ">", 0, 1.0, True, "MACD红柱放大"),
            StrategyRule("volume_ratio", ">=", 1.2, 0.8, False, "量比放大"),
        ),
    )


def momentum_reversal_strategy() -> StrategyProfile:
    """Oversold reversal template (RSI + KDJ)."""

    return StrategyProfile(
        name="超跌反转策略",
        combine_mode="and",
        min_score=0.0,
        rules=(
            StrategyRule("rsi", "<=", 30, 1.0, True, "RSI进入超卖区"),
            StrategyRule("kdj_j", "<=", 20, 1.0, True, "KDJ的J值低位"),
            StrategyRule("price_to_ma60", "<=", 0.9, 0.8, False, "股价跌破60日均线10%"),
        ),
    )


def bollinger_breakout_strategy() -> StrategyProfile:
    """Bollinger band breakout template."""

    return StrategyProfile(
        name="布林带突破策略",
        combine_mode="and",
        min_score=0.0,
        rules=(
            StrategyRule("price_to_boll_upper", ">=", 1.0, 1.0, True, "股价突破布林上轨"),
            StrategyRule("volume_ratio", ">=", 1.5, 1.0, True, "成交量放大1.5倍"),
            StrategyRule("ma_trend", ">=", 1, 0.8, False, "均线趋势向上"),
        ),
    )


def value_blue_chip_strategy() -> StrategyProfile:
    """Fundamental value blue-chip template."""

    return StrategyProfile(
        name="价值蓝筹策略",
        combine_mode="and",
        min_score=0.0,
        rules=(
            StrategyRule("pe", "<=", 20, 1.0, True, "PE不高于20"),
            StrategyRule("pb", "<=", 3, 1.0, True, "PB不高于3"),
            StrategyRule("roe", ">=", 12, 1.2, True, "ROE不低于12%"),
            StrategyRule("debt_ratio", "<=", 60, 0.8, False, "资产负债率不高于60%"),
            StrategyRule("dividend_yield", ">=", 2, 0.8, False, "股息率不低于2%"),
        ),
    )


def growth_stock_strategy() -> StrategyProfile:
    """High growth template."""

    return StrategyProfile(
        name="高成长策略",
        combine_mode="and",
        min_score=0.0,
        rules=(
            StrategyRule("revenue_growth", ">=", 25, 1.2, True, "营收增速不低于25%"),
            StrategyRule("net_profit_growth", ">=", 30, 1.2, True, "净利润增速不低于30%"),
            StrategyRule("roe", ">=", 15, 1.0, False, "ROE不低于15%"),
            StrategyRule("debt_ratio", "<=", 70, 0.6, False, "资产负债率可控"),
        ),
    )


def northbound_capital_strategy() -> StrategyProfile:
    """Sentiment template tracking northbound capital inflows."""

    return StrategyProfile(
        name="北向资金跟随策略",
        combine_mode="and",
        min_score=0.0,
        rules=(
            StrategyRule("northbound_inflow", ">", 0, 1.0, True, "北向资金当日净流入"),
            StrategyRule("northbound_inflow_5d", ">", 0, 1.0, True, "北向资金5日累计净流入"),
            StrategyRule("ma_trend", ">=", 0, 0.6, False, "均线不空头"),
        ),
    )


def dragon_tiger_strategy() -> StrategyProfile:
    """Sentiment template tracking 龙虎榜 strong stocks."""

    return StrategyProfile(
        name="龙虎榜强势策略",
        combine_mode="and",
        min_score=0.0,
        rules=(
            StrategyRule("dragon_tiger_score", ">=", 60, 1.0, True, "龙虎榜热度评分≥60"),
            StrategyRule("limit_up_strength", ">=", 1, 1.0, True, "涨停强度≥1"),
            StrategyRule("turnover_rate", ">=", 3, 0.6, False, "换手率不低于3%"),
        ),
    )


def sector_rotation_strategy() -> StrategyProfile:
    """Sector rotation template based on momentum scores."""

    return StrategyProfile(
        name="板块轮动策略",
        combine_mode="or",
        min_score=0.5,
        rules=(
            StrategyRule("sector_momentum", ">=", 0.6, 1.2, False, "所属板块动量强"),
            StrategyRule("sector_inflow", ">", 0, 1.0, False, "板块主力净流入"),
            StrategyRule("price_to_ma20", ">=", 1.02, 0.8, False, "股价站上20日均线2%"),
            StrategyRule("ma_trend", ">=", 1, 0.6, False, "均线趋势向上"),
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


def low_volatility_etf_strategy() -> StrategyProfile:
    """ETF template emphasising risk control."""

    return StrategyProfile(
        name="ETF低波动稳健策略",
        combine_mode="and",
        min_score=0.0,
        rules=(
            StrategyRule("annual_volatility", "<=", 0.18, 1.0, True, "年化波动率不高于18%"),
            StrategyRule("max_drawdown", ">=", -0.2, 1.0, True, "最大回撤不深于-20%"),
            StrategyRule("sharpe_ratio", ">=", 0.8, 1.0, True, "夏普比率不低于0.8"),
            StrategyRule("fund_size", ">=", 1_000_000_000, 0.8, False, "基金规模不低于10亿"),
        ),
    )


def industry_etf_rotation_strategy() -> StrategyProfile:
    """ETF rotation template combining momentum and liquidity filters."""

    return StrategyProfile(
        name="行业ETF轮动策略",
        combine_mode="and",
        min_score=0.0,
        rules=(
            StrategyRule("sector_momentum", ">=", 0.6, 1.0, True, "行业动量评分≥0.6"),
            StrategyRule("daily_turnover", ">=", 30_000_000, 1.0, True, "日成交额不低于3000万"),
            StrategyRule("premium_discount", "<=", 0.01, 0.8, False, "折溢价率不高于1%"),
            StrategyRule("expense_ratio", "<=", 0.008, 0.6, False, "综合费率不高于0.8%"),
        ),
    )


_BUILTIN_FACTORIES = (
    default_stock_strategy,
    trend_following_strategy,
    momentum_reversal_strategy,
    bollinger_breakout_strategy,
    value_blue_chip_strategy,
    growth_stock_strategy,
    northbound_capital_strategy,
    dragon_tiger_strategy,
    sector_rotation_strategy,
    default_etf_strategy,
    low_volatility_etf_strategy,
    industry_etf_rotation_strategy,
)


def list_builtin_strategies() -> list[StrategyProfile]:
    """Return all built-in strategy templates as fresh instances."""

    return [factory() for factory in _BUILTIN_FACTORIES]
