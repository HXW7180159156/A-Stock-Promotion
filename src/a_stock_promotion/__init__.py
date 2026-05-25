"""A-Stock Promotion MVP strategy engine."""

from .backtesting import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    PriceBar,
    RebalanceEvent,
    constant_metrics_provider,
    time_series_metrics_provider,
    to_price_bars,
)
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
    "BacktestConfig",
    "BacktestEngine",
    "BacktestResult",
    "PriceBar",
    "RebalanceEvent",
    "SelectionEngine",
    "SelectionResult",
    "StockMetrics",
    "StrategyProfile",
    "StrategyRule",
    "constant_metrics_provider",
    "default_etf_strategy",
    "default_stock_strategy",
    "historical_var",
    "list_builtin_strategies",
    "max_drawdown",
    "sharpe_ratio",
    "time_series_metrics_provider",
    "to_price_bars",
    "to_returns",
    "volatility",
]
