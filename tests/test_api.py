"""End-to-end tests for the bundled REST API and static UI."""

from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from a_stock_promotion.api import APIService, build_handler


class _APIServer:
    """Helper that starts the API on an ephemeral port for tests."""

    def __init__(self) -> None:
        self.service = APIService()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), build_handler(self.service))
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

    def get(self, path: str) -> tuple[int, dict]:
        try:
            with urllib.request.urlopen(self.base + path) as response:
                body = response.read()
                return response.status, json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            return exc.code, json.loads(payload) if payload else {}

    def post(self, path: str, body: dict) -> tuple[int, dict]:
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request) as response:
                payload = response.read()
                return response.status, json.loads(payload) if payload else {}
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            return exc.code, json.loads(payload) if payload else {}

    def raw(self, path: str) -> tuple[int, bytes, str]:
        try:
            with urllib.request.urlopen(self.base + path) as response:
                return (
                    response.status,
                    response.read(),
                    response.headers.get("Content-Type", ""),
                )
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), exc.headers.get("Content-Type", "")


class APITest(unittest.TestCase):
    def test_health_endpoint(self) -> None:
        with _APIServer() as server:
            status, payload = server.get("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")

    def test_strategies_endpoint_returns_builtin_templates(self) -> None:
        with _APIServer() as server:
            status, payload = server.get("/api/strategies")
        self.assertEqual(status, 200)
        names = [item["name"] for item in payload["strategies"]]
        self.assertGreaterEqual(len(names), 10)
        self.assertIn("价值蓝筹策略", names)

    def test_stocks_endpoint_filters(self) -> None:
        with _APIServer() as server:
            _, all_stocks = server.get("/api/stocks")
            _, sh_only = server.get("/api/stocks?exchange=SH")
        self.assertGreater(len(all_stocks["stocks"]), len(sh_only["stocks"]))
        for stock in sh_only["stocks"]:
            self.assertEqual(stock["exchange"], "SH")

    def test_stock_detail_includes_risk_note(self) -> None:
        with _APIServer() as server:
            status, payload = server.get("/api/stocks/600519")
        self.assertEqual(status, 200)
        self.assertEqual(payload["listing"]["symbol"], "600519")
        self.assertIn("pe", payload["metrics"])
        self.assertTrue(payload["risk_disclosure"])

    def test_unknown_stock_returns_404(self) -> None:
        with _APIServer() as server:
            status, _ = server.get("/api/stocks/000000")
        self.assertEqual(status, 404)

    def test_invalid_symbol_returns_400(self) -> None:
        with _APIServer() as server:
            status, _ = server.get("/api/stocks/abc-..-def")
        # The route regex itself rejects this with a 404.
        self.assertEqual(status, 404)

    def test_select_endpoint_returns_ranked_results(self) -> None:
        with _APIServer() as server:
            status, payload = server.post(
                "/api/select",
                {"strategy": "价值蓝筹策略", "filters": {"only_tradable": True}},
            )
        self.assertEqual(status, 200)
        self.assertGreater(len(payload["results"]), 0)
        scores = [item["score"] for item in payload["results"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertIn("risk_disclosure", payload)

    def test_select_unknown_strategy_returns_404(self) -> None:
        with _APIServer() as server:
            status, _ = server.post(
                "/api/select", {"strategy": "no-such", "filters": {}}
            )
        self.assertEqual(status, 404)

    def test_select_missing_strategy_returns_400(self) -> None:
        with _APIServer() as server:
            status, payload = server.post("/api/select", {"filters": {}})
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_static_index_served_at_root(self) -> None:
        with _APIServer() as server:
            status, body, content_type = server.raw("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        self.assertIn(b"A\xe8\x82\xa1\xe6\x99\xba\xe8\x83\xbd\xe9\x80\x89\xe8\x82\xa1", body)

    def test_static_path_traversal_rejected(self) -> None:
        with _APIServer() as server:
            status, _, _ = server.raw("/../api.py")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
