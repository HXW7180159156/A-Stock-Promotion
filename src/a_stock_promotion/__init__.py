"""A-Stock Promotion MVP strategy engine."""

from .models import SelectionResult, StockMetrics, StrategyProfile, StrategyRule
from .selection_engine import SelectionEngine
from .strategies import default_etf_strategy, default_stock_strategy

__all__ = [
    "SelectionEngine",
    "SelectionResult",
    "StockMetrics",
    "StrategyProfile",
    "StrategyRule",
    "default_etf_strategy",
    "default_stock_strategy",
]
