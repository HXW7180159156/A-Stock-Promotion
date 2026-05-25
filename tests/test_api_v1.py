"""End-to-end tests for the V1.0 REST API surface (ETF / portfolio /
backtest / leaderboards / admin / desktop UI)."""

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

    def put(self, path: str, body: dict):
        return self._request("PUT", path, body)

    def delete(self, path: str):
        return self._request("DELETE", path)

    def raw(self, path: str):
        try:
            with urllib.request.urlopen(self.base + path) as response:
                return (
                    response.status,
                    response.read(),
                    response.headers.get("Content-Type", ""),
                )
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), exc.headers.get("Content-Type", "")


def _demo_price_data():
    bars_a = [
        {"date": f"2024-01-{day:02d}", "close": 10.0 + day * 0.05} for day in range(1, 21)
    ]
    bars_b = [
        {"date": f"2024-01-{day:02d}", "close": 20.0 - day * 0.05} for day in range(1, 21)
    ]
    return {"510300": bars_a, "510500": bars_b}


def _demo_metrics():
    return {
        "510300": {
            "tracking_error": 0.004,
            "fund_size": 6.5e10,
            "daily_turnover": 1.2e9,
            "expense_ratio": 0.005,
            "premium_discount": 0.002,
        },
        "510500": {
            "tracking_error": 0.006,
            "fund_size": 1.2e10,
            "daily_turnover": 8.0e8,
            "expense_ratio": 0.005,
            "premium_discount": 0.003,
        },
    }


class ETFEndpointsTest(unittest.TestCase):
    def test_list_and_filter_etfs(self):
        with _APIServer() as server:
            _, all_etfs = server.get("/api/etfs")
            _, sh_only = server.get("/api/etfs?exchange=SH")
            _, bonds = server.get("/api/etfs?asset_class=债券")
        self.assertGreater(len(all_etfs["etfs"]), 0)
        for etf in sh_only["etfs"]:
            self.assertEqual(etf["exchange"], "SH")
        self.assertTrue(all(e["asset_class"] == "债券" for e in bonds["etfs"]))

    def test_etf_detail(self):
        with _APIServer() as server:
            status, payload = server.get("/api/etfs/510300")
        self.assertEqual(status, 200)
        self.assertEqual(payload["listing"]["symbol"], "510300")
        self.assertIn("tracking_error", payload["metrics"])

    def test_unknown_etf_returns_404(self):
        with _APIServer() as server:
            status, _ = server.get("/api/etfs/999999")
        self.assertEqual(status, 404)

    def test_etf_selection(self):
        with _APIServer() as server:
            status, payload = server.post(
                "/api/etfs/select",
                {"strategy": "ETF质量筛选策略", "filters": {"only_tradable": True}},
            )
        self.assertEqual(status, 200)
        self.assertGreater(len(payload["results"]), 0)
        self.assertIn("risk_disclosure", payload)


class PortfolioEndpointTest(unittest.TestCase):
    def test_rebalance_returns_plan(self):
        with _APIServer() as server:
            status, payload = server.post(
                "/api/portfolio/rebalance",
                {
                    "strategy": "ETF质量筛选策略",
                    "universe": "etf",
                    "top_n": 3,
                    "scheme": "equal",
                    "max_weight": 0.5,
                    "transaction_cost": 0.001,
                    "current": [{"symbol": "510300", "weight": 1.0}],
                },
            )
        self.assertEqual(status, 200)
        plan = payload["plan"]
        self.assertIn("trades", plan)
        self.assertIn("turnover", plan)
        self.assertGreaterEqual(plan["turnover"], 0.0)

    def test_invalid_scheme_400(self):
        with _APIServer() as server:
            status, _ = server.post(
                "/api/portfolio/rebalance",
                {"strategy": "ETF质量筛选策略", "scheme": "xyz"},
            )
        self.assertEqual(status, 400)


class BacktestEndpointsTest(unittest.TestCase):
    def test_run_backtest(self):
        with _APIServer() as server:
            status, payload = server.post(
                "/api/backtest/run",
                {
                    "strategy": "ETF质量筛选策略",
                    "price_data": _demo_price_data(),
                    "metrics": _demo_metrics(),
                    "config": {"rebalance_every": 3, "top_n": 1},
                },
            )
        self.assertEqual(status, 200)
        self.assertIn("summary", payload)
        self.assertIn("equity_curve", payload)
        self.assertGreater(len(payload["equity_curve"]), 0)

    def test_optimize(self):
        with _APIServer() as server:
            status, payload = server.post(
                "/api/backtest/optimize",
                {
                    "strategy": "ETF质量筛选策略",
                    "price_data": _demo_price_data(),
                    "metrics": _demo_metrics(),
                    "config": {"rebalance_every": 3, "top_n": 1},
                    "parameter_grid": {"tracking_error": [0.003, 0.005, 0.01]},
                    "score": "sharpe",
                },
            )
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["trials"]), 3)
        self.assertIsNotNone(payload["best"])

    def test_walk_forward(self):
        in_sample = _demo_price_data()
        # Build a disjoint out-of-sample window in February.
        out_of_sample = {
            sym: [{"date": f"2024-02-{d:02d}", "close": bars[-1]["close"] + d * 0.01}
                  for d in range(1, 11)]
            for sym, bars in in_sample.items()
        }
        with _APIServer() as server:
            status, payload = server.post(
                "/api/backtest/walk-forward",
                {
                    "strategy": "ETF质量筛选策略",
                    "in_sample_price_data": in_sample,
                    "out_of_sample_price_data": out_of_sample,
                    "metrics": _demo_metrics(),
                    "config": {"rebalance_every": 3, "top_n": 1},
                    "parameter_grid": {"tracking_error": [0.003, 0.005]},
                },
            )
        self.assertEqual(status, 200)
        self.assertIn("best_parameters", payload)
        self.assertIn("out_of_sample", payload)

    def test_grid_too_large(self):
        with _APIServer() as server:
            status, payload = server.post(
                "/api/backtest/optimize",
                {
                    "strategy": "ETF质量筛选策略",
                    "price_data": _demo_price_data(),
                    "metrics": _demo_metrics(),
                    "parameter_grid": {
                        "tracking_error": list(range(10)),
                        "fund_size": list(range(10)),
                    },
                },
            )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)


class LeaderboardEndpointTest(unittest.TestCase):
    def test_stock_leaderboards(self):
        with _APIServer() as server:
            status, payload = server.get("/api/leaderboards?universe=stock&top_n=3")
        self.assertEqual(status, 200)
        self.assertEqual(payload["universe"], "stock")
        self.assertGreater(len(payload["leaderboards"]), 0)
        for board in payload["leaderboards"]:
            self.assertLessEqual(len(board["entries"]), 3)

    def test_etf_leaderboards(self):
        with _APIServer() as server:
            status, payload = server.get("/api/leaderboards?universe=etf&top_n=2")
        self.assertEqual(status, 200)
        self.assertEqual(payload["universe"], "etf")
        self.assertGreater(len(payload["leaderboards"]), 0)


class AdminEndpointsTest(unittest.TestCase):
    def _custom_payload(self, name="api测试策略"):
        return {
            "name": name,
            "combine_mode": "and",
            "min_score": 0.3,
            "rules": [
                {"metric": "roe", "operator": ">=", "threshold": 12, "weight": 1.0,
                 "required": True, "description": "ROE≥12%"},
                {"metric": "pe", "operator": "<=", "threshold": 25, "weight": 0.8,
                 "required": False, "description": "PE≤25"},
            ],
        }

    def test_list_includes_builtin_flag(self):
        with _APIServer() as server:
            status, payload = server.get("/api/admin/strategies")
        self.assertEqual(status, 200)
        self.assertTrue(any(s["is_builtin"] for s in payload["strategies"]))

    def test_crud_cycle(self):
        with _APIServer() as server:
            # Create
            status, payload = server.post(
                "/api/admin/strategies", self._custom_payload()
            )
            self.assertEqual(status, 201)
            self.assertFalse(payload["strategy"]["is_builtin"])
            # Duplicate -> 400
            status, _ = server.post(
                "/api/admin/strategies", self._custom_payload()
            )
            self.assertEqual(status, 400)
            # Update
            updated = self._custom_payload()
            updated["min_score"] = 0.7
            status, payload = server.put(
                "/api/admin/strategies/api测试策略", updated
            )
            self.assertEqual(status, 200)
            self.assertAlmostEqual(payload["strategy"]["min_score"], 0.7)
            # Delete
            status, _ = server.delete("/api/admin/strategies/api测试策略")
            self.assertEqual(status, 200)
            # Delete again -> 404
            status, _ = server.delete("/api/admin/strategies/api测试策略")
            self.assertEqual(status, 404)

    def test_cannot_modify_builtin(self):
        with _APIServer() as server:
            status, _ = server.put(
                "/api/admin/strategies/价值蓝筹策略",
                self._custom_payload("价值蓝筹策略"),
            )
            self.assertEqual(status, 403)
            status, _ = server.delete("/api/admin/strategies/价值蓝筹策略")
            self.assertEqual(status, 403)

    def test_invalid_payload_400(self):
        with _APIServer() as server:
            status, _ = server.post("/api/admin/strategies", {"name": ""})
        self.assertEqual(status, 400)


class DesktopUITest(unittest.TestCase):
    def test_desktop_html_served(self):
        with _APIServer() as server:
            status, body, content_type = server.raw("/desktop")
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        self.assertIn(b"V1.0", body)

    def test_desktop_assets_served(self):
        with _APIServer() as server:
            for asset, ctype in [
                ("/desktop.js", "javascript"),
                ("/desktop.css", "text/css"),
            ]:
                status, _, content_type = server.raw(asset)
                self.assertEqual(status, 200, msg=asset)
                self.assertIn(ctype, content_type, msg=asset)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
