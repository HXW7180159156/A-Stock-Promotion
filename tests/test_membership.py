"""Tests for the V2.0 付费体系 module (MembershipService)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from a_stock_promotion.membership import MembershipError, MembershipService


class MembershipBenefitsTest(unittest.TestCase):
    def test_default_tiers_present(self) -> None:
        svc = MembershipService()
        tiers = [b.tier for b in svc.list_benefits()]
        self.assertEqual(tiers, ["free", "pro", "vip"])
        self.assertGreater(svc.get_benefits("vip").marketplace_discount, 0)
        self.assertFalse(svc.get_benefits("free").can_use_optimization)
        self.assertTrue(svc.get_benefits("pro").can_use_optimization)


class MembershipUserTest(unittest.TestCase):
    def test_upsert_and_get(self) -> None:
        svc = MembershipService(clock=lambda: 1234.0)
        user = svc.upsert_user("alice", "pro")
        self.assertEqual(user.tier, "pro")
        self.assertEqual(svc.get_user("alice"), user)

    def test_invalid_username(self) -> None:
        svc = MembershipService()
        with self.assertRaises(MembershipError):
            svc.upsert_user("a", "free")
        with self.assertRaises(MembershipError):
            svc.upsert_user("alice", "platinum")  # type: ignore[arg-type]

    def test_subscribe_addon(self) -> None:
        svc = MembershipService()
        with self.assertRaises(MembershipError):
            svc.subscribe_addon("ghost", "addon-x")
        svc.upsert_user("alice", "pro")
        updated = svc.subscribe_addon("alice", "premium-tape")
        self.assertIn("premium-tape", updated.addons)
        # tier-included addon is also present
        self.assertIn("northbound_realtime", updated.addons)
        self.assertTrue(svc.has_addon("alice", "premium-tape"))
        self.assertTrue(svc.has_addon("alice", "northbound_realtime"))

    def test_entitlement_helpers(self) -> None:
        svc = MembershipService()
        self.assertTrue(svc.can_use_ai_assistant(None))
        self.assertFalse(svc.can_use_optimization(None))
        svc.upsert_user("alice", "pro")
        self.assertTrue(svc.can_use_optimization("alice"))
        svc.upsert_user("bob", "free")
        self.assertFalse(svc.can_use_optimization("bob"))


class MarketplaceTest(unittest.TestCase):
    def test_purchase_applies_discount(self) -> None:
        svc = MembershipService(clock=lambda: 1.0)
        svc.upsert_user("alice", "vip")
        order = svc.purchase(username="alice", slug="strategy-x", list_price=100.0)
        self.assertEqual(order.list_price, 100.0)
        self.assertAlmostEqual(order.discount, 0.2)
        self.assertAlmostEqual(order.paid_amount, 80.0)
        self.assertTrue(svc.has_purchased("alice", "strategy-x"))

    def test_purchase_duplicate_rejected(self) -> None:
        svc = MembershipService()
        svc.upsert_user("alice", "pro")
        svc.purchase(username="alice", slug="abc", list_price=10.0)
        with self.assertRaises(MembershipError):
            svc.purchase(username="alice", slug="abc", list_price=10.0)

    def test_purchase_requires_user(self) -> None:
        svc = MembershipService()
        with self.assertRaises(MembershipError):
            svc.purchase(username="ghost", slug="abc", list_price=10.0)

    def test_purchase_validates_price(self) -> None:
        svc = MembershipService()
        svc.upsert_user("alice", "pro")
        with self.assertRaises(MembershipError):
            svc.purchase(username="alice", slug="abcx", list_price=-1)
        with self.assertRaises(MembershipError):
            svc.purchase(username="alice", slug="abcy", list_price=10**9)

    def test_list_orders(self) -> None:
        svc = MembershipService()
        svc.upsert_user("alice", "pro")
        svc.purchase(username="alice", slug="aa", list_price=10)
        svc.purchase(username="alice", slug="bb", list_price=20)
        orders = svc.list_orders("alice")
        self.assertEqual([o.slug for o in orders], ["aa", "bb"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
