"""社区 module for PRD §4.3 V2.0.

Provides an in-memory, thread-safe registry for:

* **Strategy sharing**: 用户可以将自定义 :class:`StrategyProfile` 公开发布，
  附带描述、标签与定价（``price=0`` 即免费）。
* **Subscriptions**: 用户可订阅已发布的策略；收费策略需要预先持有有效订单
  （由 :mod:`membership` 模块校验，在 API 层组合）。
* **Comments**: 订阅者可以对已发布策略发表评论；评论按发布时间倒序输出。

设计原则：

* 与 :mod:`admin` 一样使用 ``threading.RLock`` 保证并发安全；
* 所有对外字典都返回拷贝，避免外部修改内部状态；
* 不持久化，生产部署可换成数据库实现，对外接口不变。
"""

from __future__ import annotations

import copy
import itertools
import re
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .models import StrategyProfile, StrategyRule

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_\-]{2,32}$")
_SLUG_RE = re.compile(r"^[A-Za-z0-9_\-]{2,64}$")


class CommunityError(Exception):
    """Raised for community-level errors (validation, not-found, etc.)."""


@dataclass(frozen=True)
class SharedStrategy:
    """A published strategy with community metadata."""

    slug: str
    strategy: StrategyProfile
    owner: str
    description: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
    price: float = 0.0  # 0 = free
    created_at: float = 0.0
    updated_at: float = 0.0
    subscriber_count: int = 0
    comment_count: int = 0

    @property
    def is_paid(self) -> bool:
        return self.price > 0

    def as_dict(self) -> dict:
        return {
            "slug": self.slug,
            "owner": self.owner,
            "description": self.description,
            "tags": list(self.tags),
            "price": self.price,
            "is_paid": self.is_paid,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "subscriber_count": self.subscriber_count,
            "comment_count": self.comment_count,
            "strategy": _strategy_to_dict(self.strategy),
        }


@dataclass(frozen=True)
class Comment:
    """One comment on a shared strategy."""

    comment_id: int
    slug: str
    author: str
    body: str
    created_at: float

    def as_dict(self) -> dict:
        return {
            "comment_id": self.comment_id,
            "slug": self.slug,
            "author": self.author,
            "body": self.body,
            "created_at": self.created_at,
        }


class CommunityHub:
    """Thread-safe in-memory community registry."""

    def __init__(self, *, clock=time.time) -> None:
        self._lock = threading.RLock()
        self._shares: dict[str, SharedStrategy] = {}
        self._subscriptions: dict[str, set[str]] = {}  # slug -> users
        self._comments: dict[str, list[Comment]] = {}  # slug -> ordered comments
        self._comment_id = itertools.count(1)
        self._clock = clock

    # ---- Share -------------------------------------------------------------

    def publish(
        self,
        *,
        slug: str,
        owner: str,
        strategy: StrategyProfile,
        description: str = "",
        tags: Iterable[str] = (),
        price: float = 0.0,
    ) -> SharedStrategy:
        slug = _validated_slug(slug)
        owner = _validated_username(owner)
        _validate_strategy(strategy)
        description = _validated_description(description)
        normalized_tags = _validated_tags(tags)
        price = _validated_price(price)
        now = self._clock()
        with self._lock:
            if slug in self._shares:
                raise CommunityError(f"slug already exists: {slug}")
            record = SharedStrategy(
                slug=slug,
                strategy=copy.deepcopy(strategy),
                owner=owner,
                description=description,
                tags=tuple(normalized_tags),
                price=price,
                created_at=now,
                updated_at=now,
                subscriber_count=0,
                comment_count=0,
            )
            self._shares[slug] = record
            self._subscriptions[slug] = set()
            self._comments[slug] = []
            return record

    def list_shares(
        self,
        *,
        owner: str | None = None,
        tag: str | None = None,
        only_free: bool = False,
    ) -> list[SharedStrategy]:
        with self._lock:
            items = list(self._shares.values())
        if owner:
            items = [item for item in items if item.owner == owner]
        if tag:
            tag_l = tag.lower()
            items = [item for item in items if tag_l in (t.lower() for t in item.tags)]
        if only_free:
            items = [item for item in items if not item.is_paid]
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items

    def get_share(self, slug: str) -> SharedStrategy | None:
        with self._lock:
            return self._shares.get(slug)

    def unpublish(self, slug: str, *, owner: str) -> None:
        with self._lock:
            record = self._shares.get(slug)
            if record is None:
                raise CommunityError(f"share not found: {slug}")
            if record.owner != owner:
                raise CommunityError("only the owner can unpublish a strategy")
            self._shares.pop(slug, None)
            self._subscriptions.pop(slug, None)
            self._comments.pop(slug, None)

    # ---- Subscriptions -----------------------------------------------------

    def subscribe(self, slug: str, user: str) -> SharedStrategy:
        user = _validated_username(user)
        with self._lock:
            record = self._shares.get(slug)
            if record is None:
                raise CommunityError(f"share not found: {slug}")
            subs = self._subscriptions.setdefault(slug, set())
            subs.add(user)
            updated = SharedStrategy(
                slug=record.slug,
                strategy=record.strategy,
                owner=record.owner,
                description=record.description,
                tags=record.tags,
                price=record.price,
                created_at=record.created_at,
                updated_at=record.updated_at,
                subscriber_count=len(subs),
                comment_count=record.comment_count,
            )
            self._shares[slug] = updated
            return updated

    def unsubscribe(self, slug: str, user: str) -> SharedStrategy:
        user = _validated_username(user)
        with self._lock:
            record = self._shares.get(slug)
            if record is None:
                raise CommunityError(f"share not found: {slug}")
            subs = self._subscriptions.setdefault(slug, set())
            subs.discard(user)
            updated = SharedStrategy(
                slug=record.slug,
                strategy=record.strategy,
                owner=record.owner,
                description=record.description,
                tags=record.tags,
                price=record.price,
                created_at=record.created_at,
                updated_at=record.updated_at,
                subscriber_count=len(subs),
                comment_count=record.comment_count,
            )
            self._shares[slug] = updated
            return updated

    def list_subscriptions(self, user: str) -> list[SharedStrategy]:
        user = _validated_username(user)
        with self._lock:
            return [
                self._shares[slug]
                for slug, subs in self._subscriptions.items()
                if user in subs and slug in self._shares
            ]

    def is_subscribed(self, slug: str, user: str) -> bool:
        with self._lock:
            return user in self._subscriptions.get(slug, set())

    # ---- Comments ----------------------------------------------------------

    def add_comment(self, slug: str, *, author: str, body: str) -> Comment:
        author = _validated_username(author)
        body = _validated_comment_body(body)
        with self._lock:
            record = self._shares.get(slug)
            if record is None:
                raise CommunityError(f"share not found: {slug}")
            comment = Comment(
                comment_id=next(self._comment_id),
                slug=slug,
                author=author,
                body=body,
                created_at=self._clock(),
            )
            self._comments.setdefault(slug, []).append(comment)
            updated = SharedStrategy(
                slug=record.slug,
                strategy=record.strategy,
                owner=record.owner,
                description=record.description,
                tags=record.tags,
                price=record.price,
                created_at=record.created_at,
                updated_at=record.updated_at,
                subscriber_count=record.subscriber_count,
                comment_count=len(self._comments[slug]),
            )
            self._shares[slug] = updated
            return comment

    def list_comments(self, slug: str, *, limit: int = 50) -> list[Comment]:
        if limit <= 0:
            raise CommunityError("limit must be positive")
        if limit > 200:
            limit = 200
        with self._lock:
            comments = list(self._comments.get(slug, ()))
        comments.sort(key=lambda c: c.created_at, reverse=True)
        return comments[:limit]


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def _validated_slug(slug: Any) -> str:
    if not isinstance(slug, str) or not _SLUG_RE.fullmatch(slug):
        raise CommunityError(
            "slug must be 2-64 chars of letters, digits, '-' or '_'"
        )
    return slug


def _validated_username(name: Any) -> str:
    if not isinstance(name, str) or not _USERNAME_RE.fullmatch(name):
        raise CommunityError(
            "username must be 2-32 chars of letters, digits, '-' or '_'"
        )
    return name


def _validated_description(description: Any) -> str:
    if description is None:
        return ""
    if not isinstance(description, str):
        raise CommunityError("description must be a string")
    description = description.strip()
    if len(description) > 500:
        raise CommunityError("description must be at most 500 characters")
    return description


def _validated_tags(tags: Any) -> list[str]:
    if tags is None:
        return []
    if not isinstance(tags, (list, tuple)):
        raise CommunityError("tags must be a list")
    if len(tags) > 16:
        raise CommunityError("tags must contain at most 16 entries")
    out: list[str] = []
    for tag in tags:
        if not isinstance(tag, str):
            raise CommunityError("each tag must be a string")
        tag = tag.strip()
        if not tag:
            continue
        if len(tag) > 32:
            raise CommunityError("each tag must be at most 32 characters")
        out.append(tag)
    return out


def _validated_price(price: Any) -> float:
    try:
        value = float(price)
    except (TypeError, ValueError) as exc:
        raise CommunityError("price must be a number") from exc
    if value < 0:
        raise CommunityError("price must be non-negative")
    if value > 100000:
        raise CommunityError("price must be at most 100000")
    return round(value, 2)


def _validated_comment_body(body: Any) -> str:
    if not isinstance(body, str):
        raise CommunityError("body must be a string")
    body = body.strip()
    if not body:
        raise CommunityError("body must not be empty")
    if len(body) > 2000:
        raise CommunityError("body must be at most 2000 characters")
    return body


def _validate_strategy(strategy: Any) -> None:
    if not isinstance(strategy, StrategyProfile):
        raise CommunityError("strategy must be a StrategyProfile")
    if not strategy.rules:
        raise CommunityError("strategy must contain at least one rule")
    for rule in strategy.rules:
        if not isinstance(rule, StrategyRule):
            raise CommunityError("strategy rules must be StrategyRule instances")


def _strategy_to_dict(strategy: StrategyProfile) -> dict:
    return {
        "name": strategy.name,
        "combine_mode": strategy.combine_mode,
        "min_score": strategy.min_score,
        "rules": [
            {
                "metric": rule.metric,
                "operator": rule.operator,
                "threshold": rule.threshold,
                "weight": rule.weight,
                "required": rule.required,
                "description": rule.description,
            }
            for rule in strategy.rules
        ],
    }


__all__ = [
    "Comment",
    "CommunityError",
    "CommunityHub",
    "SharedStrategy",
]
