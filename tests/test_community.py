"""Tests for the V2.0 社区 module (CommunityHub)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from a_stock_promotion.community import CommunityError, CommunityHub
from a_stock_promotion.models import StrategyProfile, StrategyRule


def _sample_strategy(name: str = "示例策略") -> StrategyProfile:
    return StrategyProfile(
        name=name,
        rules=(StrategyRule("roe", ">=", 10, 1.0, True, "ROE≥10"),),
        combine_mode="and",
        min_score=0.5,
    )


class PublishTest(unittest.TestCase):
    def test_publish_round_trip(self) -> None:
        hub = CommunityHub(clock=lambda: 100.0)
        record = hub.publish(
            slug="momentum-v1",
            owner="alice",
            strategy=_sample_strategy(),
            description="动量策略",
            tags=["技术面", "trend"],
            price=0,
        )
        self.assertEqual(record.slug, "momentum-v1")
        self.assertFalse(record.is_paid)
        self.assertEqual(record.subscriber_count, 0)
        self.assertEqual(record.comment_count, 0)
        listed = hub.list_shares()
        self.assertEqual(len(listed), 1)
        self.assertEqual(hub.get_share("momentum-v1"), record)

    def test_publish_validation(self) -> None:
        hub = CommunityHub()
        with self.assertRaises(CommunityError):
            hub.publish(slug="bad slug", owner="alice", strategy=_sample_strategy())
        with self.assertRaises(CommunityError):
            hub.publish(slug="valid", owner="!", strategy=_sample_strategy())
        with self.assertRaises(CommunityError):
            hub.publish(slug="valid", owner="alice", strategy="not a strategy")  # type: ignore[arg-type]
        with self.assertRaises(CommunityError):
            hub.publish(slug="valid", owner="alice", strategy=_sample_strategy(), price=-1)

    def test_duplicate_slug_rejected(self) -> None:
        hub = CommunityHub()
        hub.publish(slug="abc", owner="alice", strategy=_sample_strategy())
        with self.assertRaises(CommunityError):
            hub.publish(slug="abc", owner="bob", strategy=_sample_strategy())

    def test_unpublish_only_owner(self) -> None:
        hub = CommunityHub()
        hub.publish(slug="abc", owner="alice", strategy=_sample_strategy())
        with self.assertRaises(CommunityError):
            hub.unpublish("abc", owner="bob")
        hub.unpublish("abc", owner="alice")
        self.assertIsNone(hub.get_share("abc"))


class SubscriptionTest(unittest.TestCase):
    def test_subscribe_increments_count(self) -> None:
        hub = CommunityHub()
        hub.publish(slug="abc", owner="alice", strategy=_sample_strategy())
        updated = hub.subscribe("abc", "bob")
        self.assertEqual(updated.subscriber_count, 1)
        self.assertTrue(hub.is_subscribed("abc", "bob"))
        self.assertEqual(len(hub.list_subscriptions("bob")), 1)
        hub.subscribe("abc", "bob")  # idempotent
        self.assertEqual(hub.get_share("abc").subscriber_count, 1)

    def test_unsubscribe(self) -> None:
        hub = CommunityHub()
        hub.publish(slug="abc", owner="alice", strategy=_sample_strategy())
        hub.subscribe("abc", "bob")
        updated = hub.unsubscribe("abc", "bob")
        self.assertEqual(updated.subscriber_count, 0)
        self.assertFalse(hub.is_subscribed("abc", "bob"))

    def test_subscribe_invalid_slug(self) -> None:
        hub = CommunityHub()
        with self.assertRaises(CommunityError):
            hub.subscribe("missing", "bob")


class CommentTest(unittest.TestCase):
    def test_comments_round_trip(self) -> None:
        clock = iter([1.0, 2.0, 3.0, 4.0])
        hub = CommunityHub(clock=lambda: next(clock))
        hub.publish(slug="abc", owner="alice", strategy=_sample_strategy())
        first = hub.add_comment("abc", author="bob", body="不错的策略")
        second = hub.add_comment("abc", author="carol", body="可以测试一下")
        comments = hub.list_comments("abc")
        self.assertEqual([c.comment_id for c in comments], [second.comment_id, first.comment_id])
        self.assertEqual(hub.get_share("abc").comment_count, 2)

    def test_comment_validation(self) -> None:
        hub = CommunityHub()
        hub.publish(slug="abc", owner="alice", strategy=_sample_strategy())
        with self.assertRaises(CommunityError):
            hub.add_comment("abc", author="bob", body="   ")
        with self.assertRaises(CommunityError):
            hub.add_comment("missing", author="bob", body="hi")

    def test_list_filtering(self) -> None:
        hub = CommunityHub()
        hub.publish(slug="aa", owner="alice", strategy=_sample_strategy(), tags=["技术面"])
        hub.publish(slug="bb", owner="alice", strategy=_sample_strategy(), price=9.9)
        self.assertEqual(len(hub.list_shares(owner="alice")), 2)
        self.assertEqual(len(hub.list_shares(tag="技术面")), 1)
        self.assertEqual(len(hub.list_shares(only_free=True)), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
