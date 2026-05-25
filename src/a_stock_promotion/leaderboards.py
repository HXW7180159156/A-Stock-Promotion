"""Operational leaderboards for the V1.0 desktop / admin module.

PRD §4.2 V1.0 lists 运营榜单 as a desktop / admin deliverable.  A
leaderboard ranks the top-scoring candidates across one or more
strategy templates so that 投研 / 运营 teams can curate themed
listicles ("成长榜", "蓝筹榜", "ETF低波动榜" …).

This module is intentionally a pure aggregation layer over the
existing :class:`~a_stock_promotion.selection_engine.SelectionEngine`
output — it does not add new ranking logic, so all rankings remain
fully explainable through the candidate's matched/missed rule trail.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from .models import SelectionResult, StockMetrics, StrategyProfile
from .selection_engine import SelectionEngine


@dataclass(frozen=True)
class LeaderboardEntry:
    """One ranked entry in a leaderboard."""

    rank: int
    symbol: str
    name: str
    score: float
    selected: bool
    matched_rules: tuple[str, ...] = field(default_factory=tuple)
    missed_rules: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "rank": self.rank,
            "symbol": self.symbol,
            "name": self.name,
            "score": self.score,
            "selected": self.selected,
            "matched_rules": list(self.matched_rules),
            "missed_rules": list(self.missed_rules),
        }


@dataclass(frozen=True)
class Leaderboard:
    """A leaderboard for one strategy template."""

    strategy: str
    entries: tuple[LeaderboardEntry, ...]
    universe: str = ""  # e.g. "stocks", "etfs"

    def as_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "universe": self.universe,
            "entries": [entry.as_dict() for entry in self.entries],
        }


class LeaderboardBuilder:
    """Build :class:`Leaderboard` objects from candidates and strategies."""

    def __init__(self, engine: SelectionEngine | None = None) -> None:
        self._engine = engine or SelectionEngine()

    def build(
        self,
        *,
        strategy: StrategyProfile,
        candidates: Iterable[StockMetrics],
        top_n: int = 10,
        only_selected: bool = False,
        universe: str = "",
    ) -> Leaderboard:
        if top_n < 1:
            raise ValueError("top_n must be >= 1")
        ranked = self._engine.rank(list(candidates), strategy)
        if only_selected:
            ranked = [item for item in ranked if item.selected]
        entries = tuple(
            _to_entry(rank, item) for rank, item in enumerate(ranked[:top_n], start=1)
        )
        return Leaderboard(strategy=strategy.name, entries=entries, universe=universe)

    def build_many(
        self,
        *,
        strategies: Sequence[StrategyProfile],
        candidates: Iterable[StockMetrics],
        top_n: int = 10,
        only_selected: bool = False,
        universe: str = "",
    ) -> list[Leaderboard]:
        """Build one leaderboard per strategy from the same candidate pool."""

        materialised = list(candidates)
        return [
            self.build(
                strategy=strategy,
                candidates=materialised,
                top_n=top_n,
                only_selected=only_selected,
                universe=universe,
            )
            for strategy in strategies
        ]


def _to_entry(rank: int, item: SelectionResult) -> LeaderboardEntry:
    return LeaderboardEntry(
        rank=rank,
        symbol=item.candidate.symbol,
        name=item.candidate.name,
        score=item.score,
        selected=item.selected,
        matched_rules=item.matched_rules,
        missed_rules=item.missed_rules,
    )


__all__ = [
    "Leaderboard",
    "LeaderboardBuilder",
    "LeaderboardEntry",
]
