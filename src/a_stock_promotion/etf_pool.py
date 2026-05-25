"""ETF universe, snapshot data and feature aggregation for V1.0.

PRD §4.2 V1.0 introduces an ETF module covering ETF筛选 / ETF详情 /
组合再平衡.  This module supplies the data layer for that work:

* :class:`ETFListing` and :class:`ETFPool` mirror the stock universe but
  carry ETF-specific descriptors (tracking index, asset class, listing
  exchange, fund manager, inception date, listing status).
* :class:`ETFSnapshot` captures the metrics consumed by the existing
  selection engine — tracking error, fund size, daily turnover, expense
  ratio, premium/discount, annual volatility, max drawdown, Sharpe ratio
  and sector momentum.  All ETF strategy templates in
  :mod:`a_stock_promotion.strategies` reference these factor names.
* :class:`SampleETFProvider` ships a curated demo dataset so the REST API
  and tests can exercise the ETF screening flow end-to-end without any
  external data dependency.
* :class:`ETFFeatureAggregator` glues listings + snapshots into the
  :class:`~a_stock_promotion.models.StockMetrics` instances expected by
  :class:`~a_stock_promotion.selection_engine.SelectionEngine`, so ETF
  screening reuses the same explainable rule engine as stocks.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Protocol

from .models import StockMetrics


@dataclass(frozen=True)
class ETFListing:
    """One ETF listing record."""

    symbol: str
    name: str
    exchange: str  # "SH" / "SZ"
    asset_class: str  # 例如 "股票" / "债券" / "商品" / "海外" / "跨境"
    tracking_index: str
    sector: str = ""
    manager: str = ""
    inception_date: str = ""
    is_tradable: bool = True

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol is required")
        if not self.name:
            raise ValueError("name is required")
        if self.exchange not in {"SH", "SZ"}:
            raise ValueError(f"unsupported exchange: {self.exchange}")


@dataclass(frozen=True)
class ETFSnapshot:
    """Latest factor snapshot for one ETF."""

    symbol: str
    tracking_error: float | None = None
    fund_size: float | None = None
    daily_turnover: float | None = None
    expense_ratio: float | None = None
    premium_discount: float | None = None
    annual_volatility: float | None = None
    max_drawdown: float | None = None
    sharpe_ratio: float | None = None
    sector_momentum: float | None = None
    nav: float | None = None
    price: float | None = None

    def as_metrics(self) -> dict[str, float]:
        data = asdict(self)
        data.pop("symbol")
        return {key: value for key, value in data.items() if value is not None}


class ETFProvider(Protocol):
    """Provider returning an ETF factor snapshot for a symbol."""

    def get(self, symbol: str) -> ETFSnapshot | None: ...


@dataclass
class ETFPool:
    """In-memory, filterable ETF universe."""

    listings: tuple[ETFListing, ...] = field(default_factory=tuple)

    def __init__(self, listings: Iterable[ETFListing] = ()) -> None:
        seen: dict[str, ETFListing] = {}
        for listing in listings:
            if listing.symbol in seen:
                raise ValueError(f"duplicate ETF symbol: {listing.symbol}")
            seen[listing.symbol] = listing
        self.listings = tuple(seen.values())

    def __iter__(self):
        return iter(self.listings)

    def __len__(self) -> int:
        return len(self.listings)

    def get(self, symbol: str) -> ETFListing | None:
        for listing in self.listings:
            if listing.symbol == symbol:
                return listing
        return None

    def asset_classes(self) -> list[str]:
        return sorted({listing.asset_class for listing in self.listings})

    def sectors(self) -> list[str]:
        return sorted({listing.sector for listing in self.listings if listing.sector})

    def filter(
        self,
        *,
        exchange: str | None = None,
        asset_class: str | None = None,
        sector: str | None = None,
        tracking_index: str | None = None,
        only_tradable: bool = True,
    ) -> "ETFPool":
        """Return a filtered copy of the ETF pool."""

        def keep(listing: ETFListing) -> bool:
            if exchange and listing.exchange != exchange:
                return False
            if asset_class and listing.asset_class != asset_class:
                return False
            if sector and listing.sector != sector:
                return False
            if tracking_index and listing.tracking_index != tracking_index:
                return False
            if only_tradable and not listing.is_tradable:
                return False
            return True

        return ETFPool(listing for listing in self.listings if keep(listing))


class SampleETFProvider:
    """In-memory ETF provider used for tests, demos and the bundled API."""

    def __init__(self, data: dict[str, ETFSnapshot] | None = None) -> None:
        self._data = dict(data or _sample_snapshots())

    def get(self, symbol: str) -> ETFSnapshot | None:
        return self._data.get(symbol)


def sample_etf_pool() -> ETFPool:
    """Return a representative sample ETF universe for the V1.0 demo."""

    return ETFPool(
        [
            ETFListing("510300", "沪深300ETF", "SH", "股票", "沪深300", "宽基", "华泰柏瑞", "2012-05-04"),
            ETFListing("510500", "中证500ETF", "SH", "股票", "中证500", "宽基", "南方基金", "2013-02-06"),
            ETFListing("159915", "创业板ETF", "SZ", "股票", "创业板指", "成长", "易方达", "2011-09-20"),
            ETFListing("588000", "科创50ETF", "SH", "股票", "科创50", "科技", "华夏基金", "2020-11-16"),
            ETFListing("512880", "证券ETF", "SH", "股票", "中证全指证券", "金融", "国泰基金", "2016-07-26"),
            ETFListing("512170", "医疗ETF", "SH", "股票", "中证医疗", "医药", "华宝基金", "2019-05-31"),
            ETFListing("515030", "新能源车ETF", "SH", "股票", "中证新能源汽车", "新能源", "华夏基金", "2020-02-26"),
            ETFListing("512690", "酒ETF", "SH", "股票", "中证酒", "消费", "鹏华基金", "2019-05-27"),
            ETFListing("511260", "十年国债ETF", "SH", "债券", "上证10年国债", "债券", "国泰基金", "2017-08-04"),
            ETFListing("518880", "黄金ETF", "SH", "商品", "黄金现货", "商品", "华安基金", "2013-07-29"),
            ETFListing("513100", "纳指ETF", "SH", "海外", "纳斯达克100", "海外", "国泰基金", "2013-05-15"),
            ETFListing("159920", "恒生ETF", "SZ", "海外", "恒生指数", "海外", "华夏基金", "2012-08-09"),
        ]
    )


def _sample_snapshots() -> dict[str, ETFSnapshot]:
    rows = [
        ETFSnapshot("510300", 0.004, 6.5e10, 1.2e9, 0.005, 0.002, 0.18, -0.32, 0.65, 0.58, 4.20, 4.21),
        ETFSnapshot("510500", 0.006, 1.2e10, 8.0e8, 0.005, 0.003, 0.22, -0.36, 0.45, 0.61, 6.10, 6.12),
        ETFSnapshot("159915", 0.008, 8.0e9, 1.5e9, 0.005, 0.004, 0.28, -0.42, 0.30, 0.66, 2.10, 2.11),
        ETFSnapshot("588000", 0.009, 5.0e9, 6.0e8, 0.005, 0.005, 0.32, -0.45, 0.10, 0.70, 1.05, 1.06),
        ETFSnapshot("512880", 0.012, 3.0e9, 4.0e8, 0.005, 0.006, 0.30, -0.40, 0.20, 0.55, 1.30, 1.32),
        ETFSnapshot("512170", 0.010, 2.5e9, 3.5e8, 0.005, 0.005, 0.26, -0.50, 0.05, 0.50, 0.50, 0.51),
        ETFSnapshot("515030", 0.011, 1.8e9, 3.0e8, 0.005, 0.007, 0.34, -0.48, 0.25, 0.72, 1.60, 1.62),
        ETFSnapshot("512690", 0.009, 2.2e9, 2.5e8, 0.005, 0.004, 0.27, -0.40, 0.40, 0.62, 1.10, 1.11),
        ETFSnapshot("511260", 0.002, 1.5e10, 5.0e8, 0.004, 0.001, 0.04, -0.05, 1.20, 0.10, 115.5, 115.6),
        ETFSnapshot("518880", 0.003, 1.0e10, 6.0e8, 0.006, 0.002, 0.14, -0.18, 0.80, 0.65, 4.80, 4.81),
        ETFSnapshot("513100", 0.005, 2.0e9, 4.0e8, 0.008, 0.008, 0.24, -0.30, 1.10, 0.78, 1.50, 1.52),
        ETFSnapshot("159920", 0.007, 1.0e9, 2.0e8, 0.008, 0.006, 0.22, -0.38, 0.10, 0.40, 1.20, 1.21),
    ]
    return {row.symbol: row for row in rows}


class ETFFeatureAggregator:
    """Build :class:`StockMetrics` instances for an ETF universe.

    The selection engine is universe-agnostic — it consumes a
    ``StockMetrics`` candidate regardless of whether the underlying
    instrument is a stock or an ETF.  This aggregator therefore mirrors
    :class:`~a_stock_promotion.features.FeatureAggregator` so that ETF
    screening reuses the same code path.
    """

    def __init__(
        self,
        pool: ETFPool | None = None,
        provider: ETFProvider | None = None,
    ) -> None:
        self.pool = pool or sample_etf_pool()
        self.provider = provider or SampleETFProvider()

    def build(self, listing: ETFListing) -> StockMetrics:
        snapshot = self.provider.get(listing.symbol)
        metrics: dict[str, float] = {}
        if snapshot is not None:
            metrics.update(snapshot.as_metrics())
        return StockMetrics(symbol=listing.symbol, name=listing.name, metrics=metrics)

    def build_many(self, listings: Sequence[ETFListing] | None = None) -> list[StockMetrics]:
        target = list(listings) if listings is not None else list(self.pool)
        return [self.build(listing) for listing in target]


__all__ = [
    "ETFFeatureAggregator",
    "ETFListing",
    "ETFPool",
    "ETFProvider",
    "ETFSnapshot",
    "SampleETFProvider",
    "sample_etf_pool",
]
