"""End-to-end tests for the V2.0 REST API surface (AI / community / membership)."""

from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from a_stock_promotion.api import APIService, build_handler


class _APIServer:
    def __init__(self) -> None:
        self.service = APIService()
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), build_handler(self.service)
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "_APIServer":
        self.thread.start()
        host, port = self.server.server_address
        self.base = f"http://{host}:{port}"
        return self

    def __exit__(self, *_exc) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _request(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"} if data else {}
        url = self.base + urllib.parse.quote(path, safe="/?&=")
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as response:
                payload = response.read()
                return response.status, json.loads(payload) if payload else {}
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            return exc.code, json.loads(payload) if payload else {}

    def get(self, path: str):
        return self._request("GET", path)

    def post(self, path: str, body: dict):
        return self._request("POST", path, body)


class AIAssistantAPITest(unittest.TestCase):
    def test_parse_prompt(self) -> None:
        with _APIServer() as server:
            status, payload = server.post(
                "/api/ai/parse",
                {"prompt": "ROE 大于 12 同时 PE 不超过 25 同时北向资金净流入"},
            )
        self.assertEqual(status, 200)
        metrics = [r["metric"] for r in payload["strategy"]["rules"]]
        self.assertIn("roe", metrics)
        self.assertIn("pe", metrics)
        self.assertIn("northbound_inflow", metrics)
        self.assertIn("risk_disclosure", payload)

    def test_parse_prompt_validation(self) -> None:
        with _APIServer() as server:
            status, payload = server.post("/api/ai/parse", {"prompt": ""})
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_explain_known_strategy(self) -> None:
        with _APIServer() as server:
            _, catalogue = server.get("/api/strategies")
            name = catalogue["strategies"][0]["name"]
            status, payload = server.get(
                f"/api/ai/strategies/{name}/explain"
            )
        self.assertEqual(status, 200)
        self.assertIn("explanation", payload)
        self.assertIn(name, payload["explanation"])

    def test_explain_unknown_strategy(self) -> None:
        with _APIServer() as server:
            status, _ = server.get("/api/ai/strategies/不存在的策略/explain")
        self.assertEqual(status, 404)

    def test_summarize_selection(self) -> None:
        with _APIServer() as server:
            _, catalogue = server.get("/api/strategies")
            name = catalogue["strategies"][0]["name"]
            status, payload = server.post(
                "/api/ai/summarize",
                {"strategy": name, "universe": "stock", "top_n": 3},
            )
        self.assertEqual(status, 200)
        self.assertIn("summary", payload)
        self.assertLessEqual(len(payload["results"]), 3)


class CommunityAPITest(unittest.TestCase):
    @staticmethod
    def _strategy_payload(name: str = "测试策略") -> dict:
        return {
            "name": name,
            "combine_mode": "and",
            "min_score": 0.5,
            "rules": [
                {
                    "metric": "roe",
                    "operator": ">=",
                    "threshold": 10,
                    "weight": 1.0,
                    "required": True,
                    "description": "ROE≥10",
                }
            ],
        }

    def test_publish_and_get(self) -> None:
        with _APIServer() as server:
            status, payload = server.post(
                "/api/community/shares",
                {
                    "slug": "trend-v1",
                    "owner": "alice",
                    "description": "趋势策略",
                    "tags": ["技术面"],
                    "price": 0,
                    "strategy": self._strategy_payload(),
                },
            )
            self.assertEqual(status, 201, payload)
            status, listed = server.get("/api/community/shares")
            self.assertEqual(status, 200)
            self.assertEqual(len(listed["shares"]), 1)
            status, detail = server.get("/api/community/shares/trend-v1")
            self.assertEqual(status, 200)
            self.assertEqual(detail["share"]["slug"], "trend-v1")
            self.assertEqual(detail["comments"], [])

    def test_subscribe_and_comment_flow(self) -> None:
        with _APIServer() as server:
            server.post(
                "/api/community/shares",
                {
                    "slug": "value-v1",
                    "owner": "alice",
                    "strategy": self._strategy_payload("价值策略示例"),
                },
            )
            status, payload = server.post(
                "/api/community/shares/value-v1/subscribe",
                {"username": "bob"},
            )
            self.assertEqual(status, 200, payload)
            self.assertEqual(payload["share"]["subscriber_count"], 1)
            status, payload = server.post(
                "/api/community/shares/value-v1/comments",
                {"author": "bob", "body": "策略很棒"},
            )
            self.assertEqual(status, 201, payload)
            self.assertEqual(payload["comment"]["author"], "bob")
            status, detail = server.get("/api/community/shares/value-v1")
            self.assertEqual(status, 200)
            self.assertEqual(detail["share"]["comment_count"], 1)
            self.assertEqual(len(detail["comments"]), 1)

    def test_publish_validation_error(self) -> None:
        with _APIServer() as server:
            status, payload = server.post(
                "/api/community/shares",
                {"slug": "ok", "owner": "alice", "strategy": {"name": "", "rules": []}},
            )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_subscribe_missing_share(self) -> None:
        with _APIServer() as server:
            status, _ = server.post(
                "/api/community/shares/ghost-slug/subscribe",
                {"username": "bob"},
            )
        self.assertEqual(status, 404)


class MembershipAPITest(unittest.TestCase):
    def test_benefits_listed(self) -> None:
        with _APIServer() as server:
            status, payload = server.get("/api/membership/benefits")
        self.assertEqual(status, 200)
        self.assertEqual([t["tier"] for t in payload["tiers"]], ["free", "pro", "vip"])

    def test_upsert_user_and_addon(self) -> None:
        with _APIServer() as server:
            status, payload = server.post(
                "/api/membership/users", {"username": "alice", "tier": "pro"}
            )
            self.assertEqual(status, 200, payload)
            self.assertEqual(payload["user"]["tier"], "pro")
            status, payload = server.post(
                "/api/membership/addons",
                {"username": "alice", "addon": "premium-tape"},
            )
            self.assertEqual(status, 200, payload)
            self.assertIn("premium-tape", payload["user"]["addons"])
            status, payload = server.get("/api/membership/users/alice")
            self.assertEqual(status, 200)
            self.assertEqual(payload["user"]["username"], "alice")
            self.assertEqual(payload["orders"], [])

    def test_get_unknown_user(self) -> None:
        with _APIServer() as server:
            status, _ = server.get("/api/membership/users/missing")
        self.assertEqual(status, 404)

    def test_upsert_invalid_tier(self) -> None:
        with _APIServer() as server:
            status, payload = server.post(
                "/api/membership/users", {"username": "alice", "tier": "platinum"}
            )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_marketplace_purchase_flow(self) -> None:
        with _APIServer() as server:
            # Need a paid share — publisher must be pro/vip
            server.post(
                "/api/membership/users", {"username": "alice", "tier": "pro"}
            )
            status, payload = server.post(
                "/api/community/shares",
                {
                    "slug": "paid-v1",
                    "owner": "alice",
                    "price": 50,
                    "strategy": CommunityAPITest._strategy_payload("付费策略"),
                },
            )
            self.assertEqual(status, 201, payload)
            # Buyer must exist
            server.post(
                "/api/membership/users", {"username": "bob", "tier": "vip"}
            )
            status, payload = server.post(
                "/api/marketplace/purchase",
                {"username": "bob", "slug": "paid-v1"},
            )
            self.assertEqual(status, 201, payload)
            self.assertAlmostEqual(payload["order"]["paid_amount"], 40.0)
            # Now bob can subscribe to the paid strategy
            status, _ = server.post(
                "/api/community/shares/paid-v1/subscribe",
                {"username": "bob"},
            )
            self.assertEqual(status, 200)

    def test_marketplace_purchase_blocks_unknown_share(self) -> None:
        with _APIServer() as server:
            server.post(
                "/api/membership/users", {"username": "bob", "tier": "pro"}
            )
            status, _ = server.post(
                "/api/marketplace/purchase",
                {"username": "bob", "slug": "ghost"},
            )
        self.assertEqual(status, 404)

    def test_paid_share_subscribe_requires_purchase(self) -> None:
        with _APIServer() as server:
            server.post(
                "/api/membership/users", {"username": "alice", "tier": "pro"}
            )
            server.post(
                "/api/community/shares",
                {
                    "slug": "paid-v2",
                    "owner": "alice",
                    "price": 12,
                    "strategy": CommunityAPITest._strategy_payload("付费2"),
                },
            )
            server.post(
                "/api/membership/users", {"username": "bob", "tier": "free"}
            )
            status, payload = server.post(
                "/api/community/shares/paid-v2/subscribe",
                {"username": "bob"},
            )
        self.assertEqual(status, 403)
        self.assertIn("error", payload)

    def test_free_share_blocks_purchase(self) -> None:
        with _APIServer() as server:
            server.post(
                "/api/membership/users", {"username": "alice", "tier": "pro"}
            )
            server.post(
                "/api/community/shares",
                {
                    "slug": "free-v1",
                    "owner": "alice",
                    "strategy": CommunityAPITest._strategy_payload("免费策略"),
                },
            )
            server.post(
                "/api/membership/users", {"username": "bob", "tier": "free"}
            )
            status, payload = server.post(
                "/api/marketplace/purchase",
                {"username": "bob", "slug": "free-v1"},
            )
        self.assertEqual(status, 400)
        self.assertIn("free", payload["error"])

    def test_free_user_cannot_publish_paid(self) -> None:
        with _APIServer() as server:
            server.post(
                "/api/membership/users", {"username": "alice", "tier": "free"}
            )
            status, payload = server.post(
                "/api/community/shares",
                {
                    "slug": "blocked",
                    "owner": "alice",
                    "price": 10,
                    "strategy": CommunityAPITest._strategy_payload("收费1"),
                },
            )
        self.assertEqual(status, 403)
        self.assertIn("error", payload)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
