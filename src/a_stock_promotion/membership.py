"""付费体系 module for PRD §4.3 V2.0.

Implements the V2.0 monetisation surface:

* **Membership tiers** (``free``/``pro``/``vip``) with explicit entitlements
  (回测次数、参数优化、AI 助手、社区付费策略折扣等).
* **Strategy marketplace orders** for paid shared strategies — orders are
  validated against pricing and tier discounts and persisted in memory.
* **Data add-on subscriptions** (e.g. 北向资金高频流、龙虎榜) that gate
  premium data providers.

The module is intentionally infrastructure-free (no real payments) — it
exposes a clean service interface that production deployments can back
with a real payment gateway by replacing :class:`MembershipService`.
"""

from __future__ import annotations

import itertools
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Literal

MembershipTier = Literal["free", "pro", "vip"]
_TIERS: tuple[MembershipTier, ...] = ("free", "pro", "vip")
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_\-]{2,32}$")
_ADDON_RE = re.compile(r"^[A-Za-z0-9_\-]{2,32}$")
_SLUG_RE = re.compile(r"^[A-Za-z0-9_\-]{2,64}$")


class MembershipError(Exception):
    """Raised for membership/marketplace validation errors."""


@dataclass(frozen=True)
class TierBenefits:
    """Concrete entitlements per membership tier."""

    tier: MembershipTier
    monthly_price: float
    daily_backtest_quota: int
    can_use_ai_assistant: bool
    can_use_optimization: bool
    marketplace_discount: float  # 0.0 - 1.0
    can_publish_paid_strategy: bool
    included_addons: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "tier": self.tier,
            "monthly_price": self.monthly_price,
            "daily_backtest_quota": self.daily_backtest_quota,
            "can_use_ai_assistant": self.can_use_ai_assistant,
            "can_use_optimization": self.can_use_optimization,
            "marketplace_discount": self.marketplace_discount,
            "can_publish_paid_strategy": self.can_publish_paid_strategy,
            "included_addons": list(self.included_addons),
        }


DEFAULT_BENEFITS: dict[MembershipTier, TierBenefits] = {
    "free": TierBenefits(
        tier="free",
        monthly_price=0.0,
        daily_backtest_quota=5,
        can_use_ai_assistant=True,
        can_use_optimization=False,
        marketplace_discount=0.0,
        can_publish_paid_strategy=False,
        included_addons=(),
    ),
    "pro": TierBenefits(
        tier="pro",
        monthly_price=39.0,
        daily_backtest_quota=50,
        can_use_ai_assistant=True,
        can_use_optimization=True,
        marketplace_discount=0.1,
        can_publish_paid_strategy=True,
        included_addons=("northbound_realtime",),
    ),
    "vip": TierBenefits(
        tier="vip",
        monthly_price=99.0,
        daily_backtest_quota=200,
        can_use_ai_assistant=True,
        can_use_optimization=True,
        marketplace_discount=0.2,
        can_publish_paid_strategy=True,
        included_addons=("northbound_realtime", "dragon_tiger_intraday"),
    ),
}


@dataclass(frozen=True)
class UserMembership:
    """User profile tracking membership tier + entitlements."""

    username: str
    tier: MembershipTier
    updated_at: float
    addons: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "username": self.username,
            "tier": self.tier,
            "updated_at": self.updated_at,
            "addons": list(self.addons),
        }


@dataclass(frozen=True)
class MarketplaceOrder:
    """Order record for a purchased shared strategy."""

    order_id: int
    username: str
    slug: str
    list_price: float
    discount: float
    paid_amount: float
    created_at: float

    def as_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "username": self.username,
            "slug": self.slug,
            "list_price": self.list_price,
            "discount": self.discount,
            "paid_amount": self.paid_amount,
            "created_at": self.created_at,
        }


class MembershipService:
    """Thread-safe in-memory membership + marketplace service."""

    def __init__(
        self,
        *,
        benefits: dict[MembershipTier, TierBenefits] | None = None,
        clock=time.time,
    ) -> None:
        self._lock = threading.RLock()
        self._benefits: dict[MembershipTier, TierBenefits] = dict(
            benefits or DEFAULT_BENEFITS
        )
        for tier in _TIERS:
            if tier not in self._benefits:
                raise MembershipError(f"missing benefits for tier {tier!r}")
        self._users: dict[str, UserMembership] = {}
        self._orders: dict[int, MarketplaceOrder] = {}
        self._orders_by_user: dict[str, list[int]] = {}
        self._purchased: dict[tuple[str, str], int] = {}  # (user,slug) → order_id
        self._addons: dict[str, set[str]] = {}  # username -> addon ids
        self._order_id = itertools.count(1)
        self._clock = clock

    # ---- Benefits ----------------------------------------------------------

    def list_benefits(self) -> list[TierBenefits]:
        with self._lock:
            return [self._benefits[t] for t in _TIERS]

    def get_benefits(self, tier: MembershipTier) -> TierBenefits:
        _validated_tier(tier)
        with self._lock:
            return self._benefits[tier]

    # ---- Membership --------------------------------------------------------

    def upsert_user(self, username: str, tier: MembershipTier) -> UserMembership:
        username = _validated_username(username)
        _validated_tier(tier)
        with self._lock:
            existing = self._users.get(username)
            addons = existing.addons if existing else ()
            record = UserMembership(
                username=username,
                tier=tier,
                updated_at=self._clock(),
                addons=addons,
            )
            self._users[username] = record
            return record

    def get_user(self, username: str) -> UserMembership | None:
        with self._lock:
            return self._users.get(username)

    def list_users(self) -> list[UserMembership]:
        with self._lock:
            return list(self._users.values())

    # ---- Add-ons -----------------------------------------------------------

    def subscribe_addon(self, username: str, addon: str) -> UserMembership:
        username = _validated_username(username)
        addon = _validated_addon(addon)
        with self._lock:
            user = self._users.get(username)
            if user is None:
                raise MembershipError(f"user not found: {username}")
            addons = self._addons.setdefault(username, set())
            addons.add(addon)
            tier_addons = set(self._benefits[user.tier].included_addons)
            merged = tuple(sorted(addons | tier_addons))
            updated = UserMembership(
                username=user.username,
                tier=user.tier,
                updated_at=self._clock(),
                addons=merged,
            )
            self._users[username] = updated
            return updated

    def list_addons(self, username: str) -> list[str]:
        with self._lock:
            user = self._users.get(username)
            if user is None:
                return []
            return list(user.addons)

    def has_addon(self, username: str, addon: str) -> bool:
        with self._lock:
            user = self._users.get(username)
            if user is None:
                return False
            if addon in self._benefits[user.tier].included_addons:
                return True
            return addon in self._addons.get(username, set())

    # ---- Entitlement checks -----------------------------------------------

    def can_use_ai_assistant(self, username: str | None) -> bool:
        if username is None:
            return True  # default behaviour: AI helper is free-tier accessible
        tier = self._tier_of(username)
        return self._benefits[tier].can_use_ai_assistant

    def can_use_optimization(self, username: str | None) -> bool:
        if username is None:
            return False
        tier = self._tier_of(username)
        return self._benefits[tier].can_use_optimization

    # ---- Marketplace orders -----------------------------------------------

    def purchase(
        self,
        *,
        username: str,
        slug: str,
        list_price: float,
    ) -> MarketplaceOrder:
        username = _validated_username(username)
        slug = _validated_slug(slug)
        try:
            list_price = float(list_price)
        except (TypeError, ValueError) as exc:
            raise MembershipError("list_price must be a number") from exc
        if list_price < 0:
            raise MembershipError("list_price must be non-negative")
        if list_price > 100000:
            raise MembershipError("list_price must be at most 100000")
        list_price = round(list_price, 2)
        with self._lock:
            user = self._users.get(username)
            if user is None:
                raise MembershipError(f"user not found: {username}")
            key = (username, slug)
            if key in self._purchased:
                raise MembershipError("strategy already purchased")
            benefits = self._benefits[user.tier]
            discount = benefits.marketplace_discount
            paid = round(list_price * (1.0 - discount), 2)
            order = MarketplaceOrder(
                order_id=next(self._order_id),
                username=username,
                slug=slug,
                list_price=list_price,
                discount=discount,
                paid_amount=paid,
                created_at=self._clock(),
            )
            self._orders[order.order_id] = order
            self._orders_by_user.setdefault(username, []).append(order.order_id)
            self._purchased[key] = order.order_id
            return order

    def has_purchased(self, username: str, slug: str) -> bool:
        with self._lock:
            return (username, slug) in self._purchased

    def list_orders(self, username: str) -> list[MarketplaceOrder]:
        username = _validated_username(username)
        with self._lock:
            ids = list(self._orders_by_user.get(username, ()))
            return [self._orders[oid] for oid in ids]

    # ---- Internal ----------------------------------------------------------

    def _tier_of(self, username: str) -> MembershipTier:
        with self._lock:
            user = self._users.get(username)
            return user.tier if user else "free"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def _validated_username(name: Any) -> str:
    if not isinstance(name, str) or not _USERNAME_RE.fullmatch(name):
        raise MembershipError(
            "username must be 2-32 chars of letters, digits, '-' or '_'"
        )
    return name


def _validated_tier(tier: Any) -> str:
    if tier not in _TIERS:
        raise MembershipError(f"tier must be one of {list(_TIERS)}")
    return str(tier)


def _validated_addon(addon: Any) -> str:
    if not isinstance(addon, str) or not _ADDON_RE.fullmatch(addon):
        raise MembershipError(
            "addon must be 2-32 chars of letters, digits, '-' or '_'"
        )
    return addon


def _validated_slug(slug: Any) -> str:
    if not isinstance(slug, str) or not _SLUG_RE.fullmatch(slug):
        raise MembershipError(
            "slug must be 2-64 chars of letters, digits, '-' or '_'"
        )
    return slug


__all__ = [
    "DEFAULT_BENEFITS",
    "MarketplaceOrder",
    "MembershipError",
    "MembershipService",
    "MembershipTier",
    "TierBenefits",
    "UserMembership",
]
