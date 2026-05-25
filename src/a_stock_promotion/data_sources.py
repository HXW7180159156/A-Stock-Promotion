"""Fundamental and sentiment data providers for the MVP.

PRD §4.1 requires fundamental factors (PE / PB / ROE / 营收增速 / 负债率)
and sentiment factors (北向资金 / 龙虎榜 / 板块轮动 / 涨停强度).  This
module defines pluggable providers and a small in-memory sample dataset
that satisfies both requirements end to end.  Replace
``SampleFundamentalProvider`` / ``SampleSentimentProvider`` with real
backends in production while keeping the same protocol.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol


@dataclass(frozen=True)
class FundamentalSnapshot:
    """Latest fundamental snapshot for one listing."""

    symbol: str
    pe: float | None = None
    pb: float | None = None
    roe: float | None = None
    revenue_growth: float | None = None
    net_profit_growth: float | None = None
    debt_ratio: float | None = None
    dividend_yield: float | None = None

    def as_metrics(self) -> dict[str, float]:
        data = asdict(self)
        data.pop("symbol")
        return {key: value for key, value in data.items() if value is not None}


@dataclass(frozen=True)
class SentimentSnapshot:
    """Latest sentiment snapshot for one listing."""

    symbol: str
    northbound_inflow: float | None = None
    northbound_inflow_5d: float | None = None
    dragon_tiger_score: float | None = None
    limit_up_strength: float | None = None
    turnover_rate: float | None = None
    sector_momentum: float | None = None
    sector_inflow: float | None = None

    def as_metrics(self) -> dict[str, float]:
        data = asdict(self)
        data.pop("symbol")
        return {key: value for key, value in data.items() if value is not None}


class FundamentalProvider(Protocol):
    """Provider returning a fundamental snapshot for a symbol."""

    def get(self, symbol: str) -> FundamentalSnapshot | None: ...


class SentimentProvider(Protocol):
    """Provider returning a sentiment snapshot for a symbol."""

    def get(self, symbol: str) -> SentimentSnapshot | None: ...


class SampleFundamentalProvider:
    """In-memory provider used for tests, demos and the bundled API."""

    def __init__(self, data: dict[str, FundamentalSnapshot] | None = None) -> None:
        self._data = dict(data or _sample_fundamentals())

    def get(self, symbol: str) -> FundamentalSnapshot | None:
        return self._data.get(symbol)


class SampleSentimentProvider:
    """In-memory sentiment provider used for tests, demos and the bundled API."""

    def __init__(self, data: dict[str, SentimentSnapshot] | None = None) -> None:
        self._data = dict(data or _sample_sentiment())

    def get(self, symbol: str) -> SentimentSnapshot | None:
        return self._data.get(symbol)


def _sample_fundamentals() -> dict[str, FundamentalSnapshot]:
    rows = [
        FundamentalSnapshot("600519", 28.5, 9.1, 32.0, 18.0, 19.5, 18.0, 1.5),
        FundamentalSnapshot("000858", 21.0, 5.4, 24.0, 12.0, 14.0, 22.0, 2.1),
        FundamentalSnapshot("601318", 9.5, 1.0, 12.0, 6.5, 4.0, 88.0, 4.6),
        FundamentalSnapshot("600036", 6.8, 1.0, 16.5, 9.0, 8.5, 91.0, 5.2),
        FundamentalSnapshot("000333", 13.0, 2.5, 22.0, 10.0, 13.0, 64.0, 3.4),
        FundamentalSnapshot("300750", 26.0, 4.2, 21.0, 28.0, 31.0, 70.0, 0.6),
        FundamentalSnapshot("002594", 24.0, 5.0, 20.0, 35.0, 40.0, 75.0, 0.4),
        FundamentalSnapshot("600276", 45.0, 6.8, 11.0, 9.0, 12.0, 18.0, 0.8),
        FundamentalSnapshot("601012", 16.0, 3.0, 18.0, 22.0, 25.0, 58.0, 1.2),
        FundamentalSnapshot("600030", 14.5, 1.2, 8.5, 5.0, 4.5, 78.0, 3.1),
        FundamentalSnapshot("000725", 22.0, 1.5, 5.0, 7.0, -5.0, 60.0, 0.5),
        FundamentalSnapshot("688981", 55.0, 2.8, 6.0, 12.0, 10.0, 35.0, 0.0),
    ]
    return {row.symbol: row for row in rows}


def _sample_sentiment() -> dict[str, SentimentSnapshot]:
    rows = [
        SentimentSnapshot("600519", 1.2e8, 4.5e8, 78.0, 0.0, 1.5, 0.55, 5.0e7),
        SentimentSnapshot("000858", 6.0e7, 2.1e8, 62.0, 0.0, 1.8, 0.55, 5.0e7),
        SentimentSnapshot("601318", 2.0e7, -1.0e8, 45.0, 0.0, 1.2, 0.40, -2.0e7),
        SentimentSnapshot("600036", 9.0e7, 3.2e8, 70.0, 0.0, 1.0, 0.45, 1.0e7),
        SentimentSnapshot("000333", 5.0e7, 1.8e8, 60.0, 0.0, 2.0, 0.60, 3.0e7),
        SentimentSnapshot("300750", 1.5e8, 6.5e8, 85.0, 1.0, 4.5, 0.70, 1.2e8),
        SentimentSnapshot("002594", 1.0e8, 4.0e8, 80.0, 1.0, 3.8, 0.70, 1.0e8),
        SentimentSnapshot("600276", -3.0e7, -1.5e8, 40.0, 0.0, 1.0, 0.35, -4.0e7),
        SentimentSnapshot("601012", 4.0e7, 1.0e8, 65.0, 1.0, 3.2, 0.62, 5.0e7),
        SentimentSnapshot("600030", -1.0e7, -5.0e7, 50.0, 0.0, 2.5, 0.45, -1.5e7),
        SentimentSnapshot("000725", -2.0e7, -8.0e7, 42.0, 0.0, 5.0, 0.50, 2.0e7),
        SentimentSnapshot("688981", 8.0e7, 2.6e8, 72.0, 1.0, 4.0, 0.68, 9.0e7),
    ]
    return {row.symbol: row for row in rows}
