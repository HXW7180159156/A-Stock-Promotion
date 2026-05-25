"""A-Stock Promotion MVP strategy engine."""

from .models import SelectionResult, StockMetrics, StrategyProfile, StrategyRule
from .risk_metrics import (
    historical_var,
    max_drawdown,
    sharpe_ratio,
    to_returns,
    volatility,
)
from .selection_engine import SelectionEngine
from .strategies import (
    default_etf_strategy,
    default_stock_strategy,
    list_builtin_strategies,
)

__all__ = [
    "SelectionEngine",
    "SelectionResult",
    "StockMetrics",
    "StrategyProfile",
    "StrategyRule",
    "default_etf_strategy",
    "default_stock_strategy",
    "historical_var",
    "list_builtin_strategies",
    "max_drawdown",
    "sharpe_ratio",
    "to_returns",
    "volatility",
]
