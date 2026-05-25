"""Pure-Python backtest executor for the A-share / ETF strategy engine.

This module implements the backtesting capability described in
``docs/TECHNICAL_ARCHITECTURE.md`` §4.3 and ``docs/IMPLEMENTATION_PLAN.md`` §3.3.
It deliberately has no third-party dependencies so the MVP can be exercised in
any Python environment, mirroring the rest of the package.

Design notes
------------
* **No look-ahead bias.** On each rebalance bar ``t`` the engine asks the
  caller-supplied ``metrics_provider`` for the factor snapshot that is
  *available* at the close of ``t`` and then executes trades at the *next*
  bar's close price. Caller-supplied metrics should therefore never embed
  information that would only be known after ``t``.
* **停牌 / 涨跌停 handling.** ``PriceBar.tradable`` flags whether a bar can be
  used to enter or exit a position. Non-tradable bars are still used for
  mark-to-market so that drawdowns reflect the suspended price the user is
  actually exposed to.
* **Transaction costs and turnover.** Each rebalance applies a symmetric cost
  ``BacktestConfig.transaction_cost`` to the absolute change in target
  weights. Turnover is reported as the average per-rebalance one-way turnover
  so it is comparable to industry conventions.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from .models import StockMetrics, StrategyProfile
from .risk_metrics import (
    TRADING_DAYS_PER_YEAR,
    max_drawdown,
    sharpe_ratio,
    to_returns,
    volatility,
)
from .selection_engine import SelectionEngine

MetricsProvider = Callable[[str, str], Mapping[str, float] | None]


@dataclass(frozen=True)
class PriceBar:
    """One trading day for a single symbol."""

    date: str
    close: float
    tradable: bool = True

    def __post_init__(self) -> None:
        if self.close <= 0:
            raise ValueError("PriceBar.close must be strictly positive")


@dataclass(frozen=True)
class BacktestConfig:
    """Configuration knobs for :class:`BacktestEngine`.

    ``rebalance_every`` is expressed in trading bars between rebalances. A
    value of ``5`` therefore reproduces a weekly rebalance on daily bars.
    ``transaction_cost`` is a *one-way* fraction applied to every weight
    change (e.g. ``0.001`` = 10bps per side).
    """

    rebalance_every: int = 5
    transaction_cost: float = 0.001
    top_n: int = 5
    initial_capital: float = 1_000_000.0
    risk_free_rate: float = 0.0
    periods_per_year: int = TRADING_DAYS_PER_YEAR

    def __post_init__(self) -> None:
        if self.rebalance_every < 1:
            raise ValueError("rebalance_every must be >= 1")
        if not 0 <= self.transaction_cost < 1:
            raise ValueError("transaction_cost must be in [0, 1)")
        if self.top_n < 1:
            raise ValueError("top_n must be >= 1")
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be > 0")
        if self.periods_per_year <= 0:
            raise ValueError("periods_per_year must be > 0")


@dataclass(frozen=True)
class RebalanceEvent:
    """Audit record produced on every rebalance bar."""

    date: str
    holdings: tuple[str, ...]
    weights: tuple[float, ...]
    turnover: float
    cost: float


@dataclass(frozen=True)
class BacktestResult:
    """Outputs required by ``TECHNICAL_ARCHITECTURE.md`` §4.3."""

    dates: tuple[str, ...]
    equity_curve: tuple[float, ...]
    period_returns: tuple[float, ...]
    rebalances: tuple[RebalanceEvent, ...] = field(default_factory=tuple)

    @property
    def total_return(self) -> float:
        if len(self.equity_curve) < 2:
            return 0.0
        return self.equity_curve[-1] / self.equity_curve[0] - 1.0

    @property
    def annualized_return(self) -> float:
        if len(self.equity_curve) < 2:
            return 0.0
        bars = len(self.equity_curve) - 1
        if bars <= 0:
            return 0.0
        growth = self.equity_curve[-1] / self.equity_curve[0]
        if growth <= 0:
            return -1.0
        return growth ** (TRADING_DAYS_PER_YEAR / bars) - 1.0

    @property
    def max_drawdown(self) -> float:
        return max_drawdown(self.equity_curve)

    @property
    def annual_volatility(self) -> float:
        return volatility(self.period_returns, annualize=True)

    @property
    def sharpe_ratio(self) -> float:
        return sharpe_ratio(self.period_returns)

    @property
    def win_rate(self) -> float:
        if not self.period_returns:
            return 0.0
        wins = sum(1 for r in self.period_returns if r > 0)
        return wins / len(self.period_returns)

    @property
    def turnover(self) -> float:
        """Average one-way turnover per rebalance."""

        if not self.rebalances:
            return 0.0
        return sum(event.turnover for event in self.rebalances) / len(self.rebalances)

    @property
    def trade_count(self) -> int:
        """Number of rebalances that actually moved capital."""

        return sum(1 for event in self.rebalances if event.turnover > 0)


class BacktestEngine:
    """Vectorless, dependency-free backtester.

    The engine treats every input as a plain Python sequence so it can run in
    any Python environment. The implementation prefers clarity over raw speed
    because the MVP target is research correctness and explainability rather
    than production throughput.
    """

    def __init__(self, selection_engine: SelectionEngine | None = None) -> None:
        self._engine = selection_engine or SelectionEngine()

    def run(
        self,
        strategy: StrategyProfile,
        price_data: Mapping[str, Sequence[PriceBar]],
        metrics_provider: MetricsProvider,
        config: BacktestConfig | None = None,
        *,
        names: Mapping[str, str] | None = None,
    ) -> BacktestResult:
        cfg = config or BacktestConfig()
        names = names or {}
        if not price_data:
            return BacktestResult(dates=(), equity_curve=(), period_returns=())

        bar_index = self._build_bar_index(price_data)
        if not bar_index:
            return BacktestResult(dates=(), equity_curve=(), period_returns=())

        all_dates = tuple(date for date, _ in bar_index)
        weights: dict[str, float] = {}
        equity = cfg.initial_capital
        equity_curve = [equity]
        period_returns: list[float] = []
        rebalances: list[RebalanceEvent] = []

        for i in range(1, len(bar_index)):
            prev_date, prev_lookup = bar_index[i - 1]
            curr_date, curr_lookup = bar_index[i]

            # Mark-to-market: held positions float with today's close prices.
            bar_return = self._portfolio_return(weights, prev_lookup, curr_lookup)
            equity *= 1.0 + bar_return
            period_returns.append(bar_return)

            # Rebalance after marking-to-market so the new weights take effect
            # from the next bar — avoiding any look-ahead from today's prices
            # when scoring candidates.
            if self._should_rebalance(i, cfg.rebalance_every):
                new_weights, turnover = self._rebalance(
                    strategy=strategy,
                    rebalance_date=curr_date,
                    current_weights=weights,
                    current_lookup=curr_lookup,
                    metrics_provider=metrics_provider,
                    names=names,
                    cfg=cfg,
                )
                cost = turnover * cfg.transaction_cost
                equity *= 1.0 - cost
                # Reflect the cost in the period return so the equity curve and
                # returns series stay consistent for downstream metrics.
                period_returns[-1] = (1.0 + bar_return) * (1.0 - cost) - 1.0
                weights = new_weights
                rebalances.append(
                    RebalanceEvent(
                        date=curr_date,
                        holdings=tuple(sorted(new_weights)),
                        weights=tuple(new_weights[s] for s in sorted(new_weights)),
                        turnover=turnover,
                        cost=cost,
                    )
                )

            equity_curve.append(equity)

        return BacktestResult(
            dates=all_dates,
            equity_curve=tuple(equity_curve),
            period_returns=tuple(period_returns),
            rebalances=tuple(rebalances),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _build_bar_index(
        price_data: Mapping[str, Sequence[PriceBar]],
    ) -> list[tuple[str, dict[str, PriceBar]]]:
        """Build a sorted ``(date, {symbol: bar})`` index across all symbols."""

        per_date: dict[str, dict[str, PriceBar]] = {}
        for symbol, bars in price_data.items():
            seen: set[str] = set()
            for bar in bars:
                if bar.date in seen:
                    raise ValueError(
                        f"duplicate price bar for {symbol} on {bar.date}"
                    )
                seen.add(bar.date)
                per_date.setdefault(bar.date, {})[symbol] = bar
        return sorted(per_date.items(), key=lambda item: item[0])

    @staticmethod
    def _portfolio_return(
        weights: Mapping[str, float],
        prev_lookup: Mapping[str, PriceBar],
        curr_lookup: Mapping[str, PriceBar],
    ) -> float:
        if not weights:
            return 0.0
        total = 0.0
        for symbol, weight in weights.items():
            prev = prev_lookup.get(symbol)
            curr = curr_lookup.get(symbol)
            if prev is None or curr is None:
                # No price update on this bar — assume flat (e.g. suspended
                # before any quote was ever published in this window).
                continue
            total += weight * (curr.close / prev.close - 1.0)
        return total

    @staticmethod
    def _should_rebalance(bar_index: int, rebalance_every: int) -> bool:
        # First rebalance happens at bar_index == rebalance_every so we have
        # at least one bar of mark-to-market history before trading.
        return bar_index % rebalance_every == 0

    def _rebalance(
        self,
        *,
        strategy: StrategyProfile,
        rebalance_date: str,
        current_weights: Mapping[str, float],
        current_lookup: Mapping[str, PriceBar],
        metrics_provider: MetricsProvider,
        names: Mapping[str, str],
        cfg: BacktestConfig,
    ) -> tuple[dict[str, float], float]:
        scored: list[tuple[float, str]] = []
        for symbol, bar in current_lookup.items():
            if not bar.tradable:
                continue
            snapshot = metrics_provider(symbol, rebalance_date)
            if snapshot is None:
                continue
            candidate = StockMetrics(
                symbol=symbol,
                name=names.get(symbol, symbol),
                metrics=dict(snapshot),
            )
            result = self._engine.evaluate(candidate, strategy)
            if not result.selected:
                continue
            # Negate score so Python's sort puts the strongest scores first
            # while keeping symbol as a stable tie-breaker.
            scored.append((-result.score, symbol))

        scored.sort()
        chosen = [symbol for _, symbol in scored[: cfg.top_n]]
        if not chosen:
            # Liquidate everything that can be sold; keep suspended positions.
            new_weights = {
                s: w for s, w in current_weights.items()
                if not current_lookup.get(s, _UNTRADABLE).tradable
            }
        else:
            target = 1.0 / len(chosen)
            new_weights = {symbol: target for symbol in chosen}
            # Carry forward any suspended position we couldn't actually trade
            # out of; rescale so total exposure stays at <=1.
            for symbol, weight in current_weights.items():
                bar = current_lookup.get(symbol)
                if bar is None or not bar.tradable:
                    new_weights[symbol] = new_weights.get(symbol, 0.0) + weight
            total = sum(new_weights.values())
            if total > 1.0:
                new_weights = {s: w / total for s, w in new_weights.items()}

        turnover = _one_way_turnover(current_weights, new_weights)
        return new_weights, turnover


_UNTRADABLE = PriceBar(date="__sentinel__", close=1.0, tradable=False)


def _one_way_turnover(
    old_weights: Mapping[str, float],
    new_weights: Mapping[str, float],
) -> float:
    symbols = set(old_weights) | set(new_weights)
    diff = sum(abs(new_weights.get(s, 0.0) - old_weights.get(s, 0.0)) for s in symbols)
    # Divide by 2 so a 100% rotation reports as 1.0 (industry convention).
    return diff / 2.0


def constant_metrics_provider(
    snapshots: Mapping[str, Mapping[str, float]],
) -> MetricsProvider:
    """Return a :data:`MetricsProvider` that ignores ``date``.

    Useful for tests and for strategy templates that operate on slow-moving
    fundamentals where the same factor snapshot is valid across the backtest
    window.
    """

    frozen = {symbol: dict(metrics) for symbol, metrics in snapshots.items()}

    def _provider(symbol: str, _date: str) -> Mapping[str, float] | None:
        return frozen.get(symbol)

    return _provider


def time_series_metrics_provider(
    snapshots: Mapping[str, Mapping[str, Mapping[str, float]]],
) -> MetricsProvider:
    """Provider for symbol → date → metrics mappings.

    Returns ``None`` when no snapshot is available on a given date so the
    engine treats the candidate as ineligible at that rebalance.
    """

    frozen = {
        symbol: {date: dict(metrics) for date, metrics in by_date.items()}
        for symbol, by_date in snapshots.items()
    }

    def _provider(symbol: str, date: str) -> Mapping[str, float] | None:
        by_date = frozen.get(symbol)
        if by_date is None:
            return None
        return by_date.get(date)

    return _provider


def to_price_bars(
    series: Iterable[tuple[str, float]] | Iterable[tuple[str, float, bool]],
) -> list[PriceBar]:
    """Convenience helper to convert ``(date, close[, tradable])`` tuples."""

    bars: list[PriceBar] = []
    for row in series:
        if len(row) == 2:
            date, close = row  # type: ignore[misc]
            bars.append(PriceBar(date=date, close=float(close)))
        elif len(row) == 3:
            date, close, tradable = row  # type: ignore[misc]
            bars.append(PriceBar(date=date, close=float(close), tradable=bool(tradable)))
        else:  # pragma: no cover - defensive
            raise ValueError("price tuple must have 2 or 3 elements")
    return bars


__all__ = [
    "BacktestConfig",
    "BacktestEngine",
    "BacktestResult",
    "MetricsProvider",
    "PriceBar",
    "RebalanceEvent",
    "constant_metrics_provider",
    "time_series_metrics_provider",
    "to_price_bars",
]
