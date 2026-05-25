"""Parameter-grid optimisation and walk-forward validation.

Implements the follow-up item in ``docs/IMPLEMENTATION_PLAN.md`` §3.3 and the
testing target in ``docs/TEST_PLAN.md`` §4.3:

* Exhaustive grid search over user-defined strategy parameter spaces.
* Pluggable scoring functions (Sharpe, total return, Calmar-style …).
* Walk-forward / out-of-sample validation that fits parameters on an
  in-sample window and verifies them on a disjoint out-of-sample window —
  the standard guard against in-sample overfit highlighted in
  ``docs/PRD.md`` §3.5.

The module is dependency-free so it can run in the same minimal Python
environment as the rest of the MVP.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import product
from typing import Any

from .backtesting import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    MetricsProvider,
    PriceBar,
)
from .models import StrategyProfile

# A strategy factory turns a parameter assignment into a concrete strategy.
StrategyFactory = Callable[[Mapping[str, Any]], StrategyProfile]

# A score function reduces a backtest result to a single comparable number
# (higher is better). ``float("-inf")`` is reserved for "ineligible" trials.
ScoreFunction = Callable[[BacktestResult], float]


# ---------------------------------------------------------------------------
# Built-in scoring functions
# ---------------------------------------------------------------------------
def score_sharpe(result: BacktestResult) -> float:
    """Annualised Sharpe ratio — the default optimisation objective."""

    return result.sharpe_ratio


def score_total_return(result: BacktestResult) -> float:
    """Cumulative total return of the backtest."""

    return result.total_return


def score_calmar(result: BacktestResult) -> float:
    """Annualised return divided by the absolute max drawdown.

    Returns ``float("-inf")`` when there is no drawdown to normalise by, so
    flat curves never win an optimisation over real strategies.
    """

    dd = result.max_drawdown
    if dd >= 0:
        return float("-inf")
    return result.annualized_return / abs(dd)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class OptimizationTrial:
    """One evaluated point in the parameter grid."""

    parameters: Mapping[str, Any]
    result: BacktestResult
    score: float


@dataclass(frozen=True)
class OptimizationReport:
    """All trials produced by a single :class:`GridSearchOptimizer` run."""

    trials: tuple[OptimizationTrial, ...] = field(default_factory=tuple)
    score_name: str = ""

    @property
    def ranked(self) -> tuple[OptimizationTrial, ...]:
        """Trials sorted by score descending (NaN/-inf last)."""

        return tuple(
            sorted(
                self.trials,
                key=lambda t: (
                    # Put -inf / NaN at the bottom by sorting on a (is_finite, score) tuple.
                    not _is_finite(t.score),
                    -t.score if _is_finite(t.score) else 0.0,
                ),
            )
        )

    @property
    def best(self) -> OptimizationTrial:
        """Best trial. Raises ``ValueError`` if the report is empty."""

        if not self.trials:
            raise ValueError("optimization report has no trials")
        return self.ranked[0]


@dataclass(frozen=True)
class WalkForwardReport:
    """Outputs of a single walk-forward validation pass."""

    in_sample: OptimizationReport
    out_of_sample: OptimizationTrial

    @property
    def best_parameters(self) -> Mapping[str, Any]:
        return self.in_sample.best.parameters


# ---------------------------------------------------------------------------
# Grid expansion
# ---------------------------------------------------------------------------
def expand_grid(grid: Mapping[str, Sequence[Any]]) -> list[dict[str, Any]]:
    """Cartesian-product expansion of ``{param: [values]}`` into trial dicts.

    Empty grids yield a single empty assignment so callers can run a baseline
    backtest with no overrides through the same code path.
    """

    if not grid:
        return [dict()]
    if any(len(values) == 0 for values in grid.values()):
        raise ValueError("each parameter grid axis must have at least one value")
    keys = list(grid.keys())
    combos = product(*(grid[k] for k in keys))
    return [dict(zip(keys, combo)) for combo in combos]


# ---------------------------------------------------------------------------
# Optimizer
# ---------------------------------------------------------------------------
class GridSearchOptimizer:
    """Exhaustive grid search over a strategy parameter space."""

    def __init__(self, backtest_engine: BacktestEngine | None = None) -> None:
        self._engine = backtest_engine or BacktestEngine()

    def run(
        self,
        *,
        strategy_factory: StrategyFactory,
        parameter_grid: Mapping[str, Sequence[Any]],
        price_data: Mapping[str, Sequence[PriceBar]],
        metrics_provider: MetricsProvider,
        config: BacktestConfig | None = None,
        score_fn: ScoreFunction = score_sharpe,
        names: Mapping[str, str] | None = None,
    ) -> OptimizationReport:
        """Run a backtest for every parameter combination in ``parameter_grid``.

        ``strategy_factory`` is invoked once per trial to materialise the
        :class:`StrategyProfile` for that parameter assignment. This keeps the
        optimizer decoupled from how callers express their parameter space —
        thresholds, weights, rule selection, etc. are all expressible.
        """

        cfg = config or BacktestConfig()
        trials: list[OptimizationTrial] = []
        for params in expand_grid(parameter_grid):
            strategy = strategy_factory(params)
            if not isinstance(strategy, StrategyProfile):  # pragma: no cover - defensive
                raise TypeError("strategy_factory must return a StrategyProfile")
            result = self._engine.run(
                strategy=strategy,
                price_data=price_data,
                metrics_provider=metrics_provider,
                config=cfg,
                names=names,
            )
            score = float(score_fn(result))
            trials.append(
                OptimizationTrial(
                    parameters=dict(params),
                    result=result,
                    score=score,
                )
            )
        return OptimizationReport(
            trials=tuple(trials),
            score_name=getattr(score_fn, "__name__", "score"),
        )

    def walk_forward(
        self,
        *,
        strategy_factory: StrategyFactory,
        parameter_grid: Mapping[str, Sequence[Any]],
        in_sample_price_data: Mapping[str, Sequence[PriceBar]],
        out_of_sample_price_data: Mapping[str, Sequence[PriceBar]],
        metrics_provider: MetricsProvider,
        config: BacktestConfig | None = None,
        score_fn: ScoreFunction = score_sharpe,
        names: Mapping[str, str] | None = None,
    ) -> WalkForwardReport:
        """Optimise on in-sample data then verify on out-of-sample data.

        The two price-data maps must not share any dates — otherwise the
        out-of-sample evaluation is contaminated by the data the parameters
        were tuned on. This guard implements TEST_PLAN §4.3.
        """

        _ensure_disjoint_dates(in_sample_price_data, out_of_sample_price_data)

        in_report = self.run(
            strategy_factory=strategy_factory,
            parameter_grid=parameter_grid,
            price_data=in_sample_price_data,
            metrics_provider=metrics_provider,
            config=config,
            score_fn=score_fn,
            names=names,
        )

        best_params = in_report.best.parameters
        cfg = config or BacktestConfig()
        out_strategy = strategy_factory(best_params)
        out_result = self._engine.run(
            strategy=out_strategy,
            price_data=out_of_sample_price_data,
            metrics_provider=metrics_provider,
            config=cfg,
            names=names,
        )
        out_trial = OptimizationTrial(
            parameters=dict(best_params),
            result=out_result,
            score=float(score_fn(out_result)),
        )
        return WalkForwardReport(in_sample=in_report, out_of_sample=out_trial)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _is_finite(value: float) -> bool:
    # ``math.isfinite`` would do, but avoids importing math just for this and
    # keeps the helper trivially inlinable.
    return value == value and value not in (float("inf"), float("-inf"))


def _ensure_disjoint_dates(
    a: Mapping[str, Sequence[PriceBar]],
    b: Mapping[str, Sequence[PriceBar]],
) -> None:
    a_dates = _collect_dates(a)
    b_dates = _collect_dates(b)
    overlap = a_dates & b_dates
    if overlap:
        sample = sorted(overlap)[:3]
        raise ValueError(
            "in-sample and out-of-sample windows must not share dates; "
            f"overlapping dates include: {sample}"
        )


def _collect_dates(price_data: Mapping[str, Sequence[PriceBar]]) -> set[str]:
    dates: set[str] = set()
    for bars in price_data.values():
        for bar in bars:
            dates.add(bar.date)
    return dates


__all__ = [
    "GridSearchOptimizer",
    "OptimizationReport",
    "OptimizationTrial",
    "ScoreFunction",
    "StrategyFactory",
    "WalkForwardReport",
    "expand_grid",
    "score_calmar",
    "score_sharpe",
    "score_total_return",
]
