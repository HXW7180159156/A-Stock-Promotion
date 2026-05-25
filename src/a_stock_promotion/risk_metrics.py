"""Risk-control metrics used by the ETF and 组合配置 modules.

This module implements the indicators called out in ``docs/PRD.md`` §3.4 and
``docs/TECHNICAL_ARCHITECTURE.md`` §4.2: 最大回撤、年化波动率、夏普比率、历史 VaR.

The functions are dependency-free so the MVP can run in any Python environment.
All inputs are plain sequences of floats representing either price levels or
periodic returns, depending on the helper.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

# Trading days per year — used to annualise daily statistics.
TRADING_DAYS_PER_YEAR = 252


def to_returns(prices: Sequence[float]) -> list[float]:
    """Convert a price series into simple period returns.

    Returns an empty list if fewer than two prices are provided.
    Raises ``ValueError`` if any price is non-positive, since a zero/negative
    price cannot produce a meaningful simple return.
    """

    if len(prices) < 2:
        return []
    if any(p <= 0 for p in prices):
        raise ValueError("prices must be strictly positive")
    return [prices[i] / prices[i - 1] - 1.0 for i in range(1, len(prices))]


def max_drawdown(prices: Sequence[float]) -> float:
    """Return the maximum drawdown of a price series as a non-positive float.

    A drawdown of ``-0.25`` means the series fell 25% from a prior peak.
    Empty or single-point inputs return ``0.0``.
    """

    if len(prices) < 2:
        return 0.0
    if any(p <= 0 for p in prices):
        raise ValueError("prices must be strictly positive")
    peak = prices[0]
    worst = 0.0
    for price in prices:
        if price > peak:
            peak = price
        drawdown = price / peak - 1.0
        if drawdown < worst:
            worst = drawdown
    return worst


def volatility(returns: Sequence[float], annualize: bool = True) -> float:
    """Sample standard deviation of returns, optionally annualised."""

    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(variance)
    if annualize:
        std *= math.sqrt(TRADING_DAYS_PER_YEAR)
    return std


def sharpe_ratio(
    returns: Sequence[float],
    risk_free_rate: float = 0.0,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """Annualised Sharpe ratio for a series of periodic returns.

    ``risk_free_rate`` is expressed as an annualised rate; it is converted to
    the period frequency implied by ``periods_per_year``.
    Returns ``0.0`` when the input has insufficient data or zero volatility.
    """

    if len(returns) < 2:
        return 0.0
    if periods_per_year <= 0:
        raise ValueError("periods_per_year must be positive")
    period_rf = risk_free_rate / periods_per_year
    excess = [r - period_rf for r in returns]
    mean = sum(excess) / len(excess)
    std = volatility(returns, annualize=False)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(periods_per_year)


def historical_var(returns: Sequence[float], confidence: float = 0.95) -> float:
    """Historical Value-at-Risk at ``confidence`` (e.g. 0.95 for 95%).

    Returned as a non-positive number representing the loss threshold for one
    period at the given confidence level. Linear interpolation is used between
    adjacent observations so results behave smoothly for small samples.
    """

    if not returns:
        return 0.0
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")
    sorted_returns = sorted(returns)
    quantile = 1 - confidence
    position = quantile * (len(sorted_returns) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        value = sorted_returns[int(position)]
    else:
        weight = position - lower
        value = sorted_returns[lower] * (1 - weight) + sorted_returns[upper] * weight
    return min(value, 0.0)


__all__ = [
    "TRADING_DAYS_PER_YEAR",
    "historical_var",
    "max_drawdown",
    "sharpe_ratio",
    "to_returns",
    "volatility",
]
