"""Tests for the in-memory strategy registry (V1.0 admin module)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from a_stock_promotion.admin import StrategyRegistry, StrategyRegistryError


def _valid_payload(name: str = "我的策略") -> dict:
    return {
        "name": name,
        "combine_mode": "and",
        "min_score": 0.5,
        "rules": [
            {
                "metric": "roe",
                "operator": ">=",
                "threshold": 15,
                "weight": 1.2,
                "required": True,
                "description": "ROE≥15%",
            },
            {
                "metric": "pe",
                "operator": "<=",
                "threshold": 20,
                "weight": 1.0,
                "required": False,
                "description": "PE≤20",
            },
        ],
    }


class StrategyRegistryTest(unittest.TestCase):
    def setUp(self):
        self.registry = StrategyRegistry()

    def test_lists_builtin_strategies(self):
        records = self.registry.list()
        self.assertGreaterEqual(len(records), 10)
        self.assertTrue(all(r.is_builtin for r in records))

    def test_create_and_get(self):
        record = self.registry.create(_valid_payload())
        self.assertFalse(record.is_builtin)
        self.assertEqual(record.strategy.name, "我的策略")
        self.assertIsNotNone(self.registry.get("我的策略"))

    def test_cannot_create_duplicate(self):
        self.registry.create(_valid_payload("dup"))
        with self.assertRaises(StrategyRegistryError):
            self.registry.create(_valid_payload("dup"))

    def test_cannot_update_builtin(self):
        any_builtin = self.registry.list()[0].strategy.name
        with self.assertRaises(StrategyRegistryError):
            self.registry.update(any_builtin, _valid_payload(any_builtin))

    def test_cannot_delete_builtin(self):
        any_builtin = self.registry.list()[0].strategy.name
        with self.assertRaises(StrategyRegistryError):
            self.registry.delete(any_builtin)

    def test_update_custom_strategy(self):
        self.registry.create(_valid_payload("editme"))
        payload = _valid_payload("editme")
        payload["min_score"] = 0.8
        updated = self.registry.update("editme", payload)
        self.assertAlmostEqual(updated.strategy.min_score, 0.8)

    def test_rename_via_update(self):
        self.registry.create(_valid_payload("oldname"))
        payload = _valid_payload("newname")
        record = self.registry.update("oldname", payload)
        self.assertEqual(record.strategy.name, "newname")
        self.assertIsNone(self.registry.get("oldname"))

    def test_delete_custom(self):
        self.registry.create(_valid_payload("temp"))
        self.registry.delete("temp")
        self.assertIsNone(self.registry.get("temp"))

    def test_rejects_invalid_payload(self):
        cases = [
            {},
            {"name": "", "rules": [{"metric": "a", "operator": ">=", "threshold": 1}]},
            {"name": "a", "rules": []},
            {"name": "a", "rules": [{"metric": "x", "operator": "??", "threshold": 1}]},
            {"name": "a", "min_score": 2.0, "rules": [
                {"metric": "x", "operator": ">=", "threshold": 1}
            ]},
            {"name": "a", "combine_mode": "xor", "rules": [
                {"metric": "x", "operator": ">=", "threshold": 1}
            ]},
            {"name": "a", "rules": [
                {"metric": "x", "operator": ">=", "threshold": "abc"}
            ]},
        ]
        for case in cases:
            with self.assertRaises(StrategyRegistryError, msg=str(case)):
                self.registry.create(case)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
