"""Portfolio composition and rebalancing for the V1.0 ETF module.

PRD §4.2 V1.0 lists 组合再平衡 as a deliverable.  This module turns a
ranked list of :class:`~a_stock_promotion.models.SelectionResult` (the
output of the existing rule engine) into:

* Target weights (equal-weight or score-weighted), capped per holding.
* Concrete rebalancing trades against an existing holdings book, with
  symmetric transaction costs and a min-trade threshold to avoid noise.

The implementation is dependency-free so it composes naturally with
the rest of the MVP / V1.0 stack.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from .models import SelectionResult

WeightScheme = Literal["equal", "score"]


@dataclass(frozen=True)
class Holding:
    """Current position in the portfolio."""

    symbol: str
    weight: float

    def __post_init__(self) -> None:
        if self.weight < 0:
            raise ValueError("holding weight must be non-negative")


@dataclass(frozen=True)
class RebalanceTrade:
    """One trade emitted by the rebalance planner."""

    symbol: str
    action: Literal["buy", "sell", "hold"]
    current_weight: float
    target_weight: float
    delta_weight: float


@dataclass(frozen=True)
class RebalancePlan:
    """Audit-friendly output of :func:`build_rebalance_plan`."""

    targets: tuple[tuple[str, float], ...]
    trades: tuple[RebalanceTrade, ...]
    turnover: float
    transaction_cost: float
    cash_weight: float = 0.0
    notes: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "targets": [{"symbol": s, "weight": w} for s, w in self.targets],
            "trades": [
                {
                    "symbol": t.symbol,
                    "action": t.action,
                    "current_weight": t.current_weight,
                    "target_weight": t.target_weight,
                    "delta_weight": t.delta_weight,
                }
                for t in self.trades
            ],
            "turnover": self.turnover,
            "transaction_cost": self.transaction_cost,
            "cash_weight": self.cash_weight,
            "notes": list(self.notes),
        }


def compute_target_weights(
    selections: Sequence[SelectionResult],
    *,
    top_n: int = 5,
    scheme: WeightScheme = "equal",
    max_weight: float = 1.0,
    only_selected: bool = True,
) -> dict[str, float]:
    """Turn ranked selection results into a target weight map.

    * ``only_selected``: when ``True`` (default), only candidates whose
      ``selected`` flag is truthy are eligible — this honours the rule
      engine's required-rule and ``min_score`` gating.
    * ``scheme="equal"`` allocates ``1/N`` per holding.  ``scheme="score"``
      allocates proportional to the candidate score (with a floor of 0).
    * ``max_weight`` caps any single-holding weight before normalisation;
      residual cash is returned via :func:`build_rebalance_plan`.
    """

    if top_n < 1:
        raise ValueError("top_n must be >= 1")
    if not 0 < max_weight <= 1:
        raise ValueError("max_weight must be in (0, 1]")

    eligible = [item for item in selections if (item.selected or not only_selected)]
    if scheme == "score":
        eligible = [item for item in eligible if item.score > 0]

    chosen = eligible[:top_n]
    if not chosen:
        return {}

    if scheme == "equal":
        raw = {item.candidate.symbol: 1.0 for item in chosen}
    elif scheme == "score":
        raw = {item.candidate.symbol: float(item.score) for item in chosen}
    else:  # pragma: no cover - defensive
        raise ValueError(f"unknown weight scheme: {scheme!r}")

    total = sum(raw.values())
    if total <= 0:
        return {}
    weights = {symbol: value / total for symbol, value in raw.items()}

    # Apply per-holding cap with simple iterative re-normalisation.
    weights = _apply_weight_cap(weights, max_weight)
    return weights


def build_rebalance_plan(
    *,
    current: Iterable[Holding] | Mapping[str, float] = (),
    targets: Mapping[str, float],
    transaction_cost: float = 0.001,
    min_trade: float = 0.005,
) -> RebalancePlan:
    """Build a rebalance plan from current holdings and target weights.

    ``transaction_cost`` is a *one-way* fraction (e.g. ``0.001`` = 10bps).
    Trades below ``min_trade`` (absolute weight delta) are suppressed and
    reported in ``notes`` to avoid churn on rounding noise.
    """

    if not 0 <= transaction_cost < 1:
        raise ValueError("transaction_cost must be in [0, 1)")
    if min_trade < 0:
        raise ValueError("min_trade must be non-negative")

    current_map = _normalise_current(current)
    target_map = {symbol: float(weight) for symbol, weight in targets.items()}
    target_sum = sum(target_map.values())
    if target_sum < 0 or target_sum > 1.0 + 1e-9:
        raise ValueError("target weights must sum to a value in [0, 1]")

    universe = sorted(set(current_map) | set(target_map))
    trades: list[RebalanceTrade] = []
    notes: list[str] = []
    turnover = 0.0

    for symbol in universe:
        current_weight = current_map.get(symbol, 0.0)
        target_weight = target_map.get(symbol, 0.0)
        delta = target_weight - current_weight
        if abs(delta) < min_trade:
            if delta != 0:
                notes.append(
                    f"{symbol} 调仓幅度 {delta:+.4f} 低于阈值 {min_trade}，本次不交易"
                )
                # Hold at current weight; keep target the same as current so
                # downstream code sees a self-consistent plan.
                target_weight = current_weight
                delta = 0.0
            action: Literal["buy", "sell", "hold"] = "hold"
        elif delta > 0:
            action = "buy"
        else:
            action = "sell"
        trades.append(
            RebalanceTrade(
                symbol=symbol,
                action=action,
                current_weight=current_weight,
                target_weight=target_weight,
                delta_weight=delta,
            )
        )
        turnover += abs(delta)

    turnover /= 2.0  # industry convention: one-way turnover
    cost = turnover * transaction_cost

    cash_weight = max(0.0, 1.0 - sum(t.target_weight for t in trades))
    sorted_targets = tuple(
        sorted(
            ((t.symbol, t.target_weight) for t in trades if t.target_weight > 0),
            key=lambda item: (-item[1], item[0]),
        )
    )
    return RebalancePlan(
        targets=sorted_targets,
        trades=tuple(trades),
        turnover=turnover,
        transaction_cost=cost,
        cash_weight=cash_weight,
        notes=tuple(notes),
    )


def plan_from_selection(
    selections: Sequence[SelectionResult],
    *,
    current: Iterable[Holding] | Mapping[str, float] = (),
    top_n: int = 5,
    scheme: WeightScheme = "equal",
    max_weight: float = 1.0,
    transaction_cost: float = 0.001,
    min_trade: float = 0.005,
    only_selected: bool = True,
) -> RebalancePlan:
    """Convenience: target weights + rebalance trades in one call."""

    targets = compute_target_weights(
        selections,
        top_n=top_n,
        scheme=scheme,
        max_weight=max_weight,
        only_selected=only_selected,
    )
    return build_rebalance_plan(
        current=current,
        targets=targets,
        transaction_cost=transaction_cost,
        min_trade=min_trade,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _normalise_current(
    current: Iterable[Holding] | Mapping[str, float],
) -> dict[str, float]:
    result: dict[str, float] = {}
    if isinstance(current, Mapping):
        items = current.items()
    else:
        items = ((h.symbol, h.weight) for h in current)
    for symbol, weight in items:
        if weight < 0:
            raise ValueError("current weights must be non-negative")
        result[symbol] = result.get(symbol, 0.0) + float(weight)
    total = sum(result.values())
    if total > 1.0 + 1e-9:
        raise ValueError("current weights must sum to a value in [0, 1]")
    return result


def _apply_weight_cap(weights: Mapping[str, float], cap: float) -> dict[str, float]:
    """Cap any weight above ``cap``, redistributing excess proportionally."""

    if cap >= 1.0:
        return dict(weights)
    capped = {s: min(w, cap) for s, w in weights.items()}
    # Iterate a few times to absorb redistribution overflow.
    for _ in range(10):
        excess = sum(weights[s] for s in weights) - sum(capped.values())
        if excess <= 1e-12:
            break
        uncapped = [s for s, w in capped.items() if w < cap]
        if not uncapped:
            break
        share = excess / len(uncapped)
        new_capped = dict(capped)
        for symbol in uncapped:
            new_capped[symbol] = min(capped[symbol] + share, cap)
        if new_capped == capped:
            break
        capped = new_capped
    return capped


__all__ = [
    "Holding",
    "RebalancePlan",
    "RebalanceTrade",
    "WeightScheme",
    "build_rebalance_plan",
    "compute_target_weights",
    "plan_from_selection",
]
