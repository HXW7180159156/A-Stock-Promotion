"""Feature aggregator turning multi-source data into ``StockMetrics``.

Glues together :mod:`indicators` (technical), :mod:`data_sources`
(fundamental + sentiment) and :mod:`stock_pool` so that the existing
:class:`~a_stock_promotion.selection_engine.SelectionEngine` can be fed
a single, complete view of every candidate.  This realises the “数据与
计算层” → “业务服务层” boundary described in
`docs/TECHNICAL_ARCHITECTURE.md` §1.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .data_sources import (
    FundamentalProvider,
    SampleFundamentalProvider,
    SampleSentimentProvider,
    SentimentProvider,
)
from .indicators import (
    bollinger_bands,
    kdj,
    ma_trend_score,
    macd,
    relative_strength_index,
    simple_moving_average,
    volume_ratio,
)
from .models import StockMetrics
from .stock_pool import StockListing, StockPool, sample_stock_pool


@dataclass(frozen=True)
class PriceHistory:
    """OHLCV history for a single symbol."""

    symbol: str
    closes: tuple[float, ...]
    highs: tuple[float, ...]
    lows: tuple[float, ...]
    volumes: tuple[float, ...]

    def __post_init__(self) -> None:
        n = len(self.closes)
        if not (n == len(self.highs) == len(self.lows) == len(self.volumes)):
            raise ValueError("OHLCV series must have equal length")
        if n == 0:
            raise ValueError("price history must not be empty")


def compute_technical_metrics(history: PriceHistory) -> dict[str, float]:
    """Compute the MVP technical factor set from one ``PriceHistory``."""

    closes = list(history.closes)
    highs = list(history.highs)
    lows = list(history.lows)
    volumes = list(history.volumes)
    last = len(closes) - 1
    metrics: dict[str, float] = {}

    last_close = closes[last]
    metrics["close"] = last_close

    trend = ma_trend_score(closes)
    if trend is not None:
        metrics["ma_trend"] = float(trend)

    ma20 = simple_moving_average(closes, 20)[last]
    if ma20:
        metrics["price_to_ma20"] = last_close / ma20
    ma60 = simple_moving_average(closes, 60)[last]
    if ma60:
        metrics["price_to_ma60"] = last_close / ma60

    macd_point = macd(closes)[last]
    if macd_point.dif is not None:
        metrics["macd_dif"] = macd_point.dif
    if macd_point.dea is not None:
        metrics["macd_dea"] = macd_point.dea
    if macd_point.hist is not None:
        metrics["macd_hist"] = macd_point.hist

    rsi_value = relative_strength_index(closes)[last]
    if rsi_value is not None:
        metrics["rsi"] = rsi_value

    kdj_point = kdj(highs, lows, closes)[last]
    if kdj_point.k is not None:
        metrics["kdj_k"] = kdj_point.k
        metrics["kdj_d"] = kdj_point.d or 0.0
        metrics["kdj_j"] = kdj_point.j or 0.0

    boll_point = bollinger_bands(closes)[last]
    if boll_point.upper:
        metrics["price_to_boll_upper"] = last_close / boll_point.upper
    if boll_point.lower:
        metrics["price_to_boll_lower"] = last_close / boll_point.lower

    vol_ratio = volume_ratio(volumes)[last]
    if vol_ratio is not None:
        metrics["volume_ratio"] = vol_ratio

    return metrics


class FeatureAggregator:
    """Build complete :class:`StockMetrics` instances for a stock pool."""

    def __init__(
        self,
        pool: StockPool | None = None,
        fundamental_provider: FundamentalProvider | None = None,
        sentiment_provider: SentimentProvider | None = None,
        price_history: dict[str, PriceHistory] | None = None,
    ) -> None:
        self.pool = pool or sample_stock_pool()
        self.fundamentals = fundamental_provider or SampleFundamentalProvider()
        self.sentiment = sentiment_provider or SampleSentimentProvider()
        self.price_history: dict[str, PriceHistory] = dict(price_history or {})

    def set_price_history(self, history: PriceHistory) -> None:
        self.price_history[history.symbol] = history

    def build(self, listing: StockListing) -> StockMetrics:
        metrics: dict[str, float] = {}
        history = self.price_history.get(listing.symbol)
        if history is not None:
            metrics.update(compute_technical_metrics(history))
        fundamental = self.fundamentals.get(listing.symbol)
        if fundamental is not None:
            metrics.update(fundamental.as_metrics())
        sentiment = self.sentiment.get(listing.symbol)
        if sentiment is not None:
            metrics.update(sentiment.as_metrics())
        return StockMetrics(symbol=listing.symbol, name=listing.name, metrics=metrics)

    def build_many(self, listings: Sequence[StockListing] | None = None) -> list[StockMetrics]:
        target = list(listings) if listings is not None else list(self.pool)
        return [self.build(listing) for listing in target]
