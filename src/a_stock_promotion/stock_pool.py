"""Stock pool management for the MVP.

Implements the PRD §4.1 “股票池管理”要求：A股基础股票池、行业/板块标签、
可交易状态。  Acts as the canonical universe consumed by the selection
engine and the REST API.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class StockListing:
    """One A-share listing record."""

    symbol: str
    name: str
    exchange: str  # "SH" / "SZ" / "BJ"
    industry: str
    sector: str
    is_tradable: bool = True
    is_st: bool = False
    list_date: str = ""

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol is required")
        if not self.name:
            raise ValueError("name is required")
        if self.exchange not in {"SH", "SZ", "BJ"}:
            raise ValueError(f"unsupported exchange: {self.exchange}")


@dataclass
class StockPool:
    """In-memory, filterable A-share universe."""

    listings: tuple[StockListing, ...] = field(default_factory=tuple)

    def __init__(self, listings: Iterable[StockListing] = ()) -> None:
        seen: dict[str, StockListing] = {}
        for listing in listings:
            if listing.symbol in seen:
                raise ValueError(f"duplicate symbol: {listing.symbol}")
            seen[listing.symbol] = listing
        self.listings = tuple(seen.values())

    def __iter__(self):
        return iter(self.listings)

    def __len__(self) -> int:
        return len(self.listings)

    def get(self, symbol: str) -> StockListing | None:
        for listing in self.listings:
            if listing.symbol == symbol:
                return listing
        return None

    def industries(self) -> list[str]:
        return sorted({listing.industry for listing in self.listings})

    def sectors(self) -> list[str]:
        return sorted({listing.sector for listing in self.listings})

    def filter(
        self,
        *,
        exchange: str | None = None,
        industry: str | None = None,
        sector: str | None = None,
        only_tradable: bool = True,
        include_st: bool = False,
    ) -> "StockPool":
        """Return a filtered copy of the pool."""

        def keep(listing: StockListing) -> bool:
            if exchange and listing.exchange != exchange:
                return False
            if industry and listing.industry != industry:
                return False
            if sector and listing.sector != sector:
                return False
            if only_tradable and not listing.is_tradable:
                return False
            if not include_st and listing.is_st:
                return False
            return True

        return StockPool(listing for listing in self.listings if keep(listing))


def sample_stock_pool() -> StockPool:
    """Return a small but representative sample A-share pool for the MVP.

    The sample contains 12 listings spanning multiple exchanges, industries
    and sectors so that strategy templates can demonstrate explainable
    results without external data access.  Replace this provider with a
    real data source (AkShare, exchange feed) in production.
    """

    return StockPool(
        [
            StockListing("600519", "贵州茅台", "SH", "白酒", "消费"),
            StockListing("000858", "五粮液", "SZ", "白酒", "消费"),
            StockListing("601318", "中国平安", "SH", "保险", "金融"),
            StockListing("600036", "招商银行", "SH", "银行", "金融"),
            StockListing("000333", "美的集团", "SZ", "家电", "消费"),
            StockListing("300750", "宁德时代", "SZ", "电池", "新能源"),
            StockListing("002594", "比亚迪", "SZ", "汽车", "新能源"),
            StockListing("600276", "恒瑞医药", "SH", "医药", "医药"),
            StockListing("601012", "隆基绿能", "SH", "光伏", "新能源"),
            StockListing("600030", "中信证券", "SH", "证券", "金融"),
            StockListing("000725", "京东方A", "SZ", "面板", "科技"),
            StockListing("688981", "中芯国际", "SH", "半导体", "科技"),
        ]
    )
