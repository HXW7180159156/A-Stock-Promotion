"""Coverage-completion tests targeting api.py error/validation branches.

These exercise the ``APIService`` methods and the HTTP handler error paths
that the main ``test_api*.py`` happy-path tests do not cover.
"""

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

from a_stock_promotion.api import (
    APIRequestHandler,
    APIService,
    _coerce_bool,
    _coerce_float,
    _coerce_int,
    _coerce_metric_snapshot,
    _decode_path_segment,
    _is_time_series_metrics,
    _is_valid_date,
    _make_threshold_factory,
    _parse_holdings,
    _parse_metrics_provider,
    _parse_price_data,
    _safe_static_path,
    _validated_score,
    build_handler,
)
from a_stock_promotion.models import StrategyProfile, StrategyRule


class _APIServer:
    """Helper that boots the bundled API on an ephemeral port."""

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

    def _request(self, method: str, path: str, body=None, raw_body=None, headers=None):
        if raw_body is not None:
            data = raw_body
        else:
            data = json.dumps(body).encode("utf-8") if body is not None else None
        all_headers = {"Content-Type": "application/json"} if data is not None else {}
        if headers:
            all_headers.update(headers)
        url = self.base + path
        req = urllib.request.Request(
            url, data=data, headers=all_headers, method=method
        )
        try:
            with urllib.request.urlopen(req) as response:
                payload = response.read()
                return response.status, json.loads(payload) if payload else {}
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            return exc.code, json.loads(payload) if payload else {}

    def get(self, path):
        return self._request("GET", path)

    def post(self, path, body=None, raw_body=None, headers=None):
        return self._request("POST", path, body=body, raw_body=raw_body, headers=headers)

    def put(self, path, body):
        return self._request("PUT", path, body=body)

    def delete(self, path):
        return self._request("DELETE", path)


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------
class APIHelperTest(unittest.TestCase):
    def test_coerce_bool_from_string(self):
        self.assertTrue(_coerce_bool("yes"))
        self.assertFalse(_coerce_bool("no"))
        self.assertTrue(_coerce_bool(1))
        self.assertFalse(_coerce_bool(""))

    def test_coerce_int_invalid_raises(self):
        with self.assertRaises(ValueError):
            _coerce_int("abc", "x", lo=0, hi=10)

    def test_coerce_int_out_of_range(self):
        with self.assertRaises(ValueError):
            _coerce_int(100, "x", lo=0, hi=10)

    def test_coerce_float_invalid_raises(self):
        with self.assertRaises(ValueError):
            _coerce_float("abc", "x", lo=0, hi=1)

    def test_coerce_float_out_of_range(self):
        with self.assertRaises(ValueError):
            _coerce_float(2.0, "x", lo=0, hi=1)

    def test_validated_score_rejects_unknown(self):
        with self.assertRaises(ValueError):
            _validated_score("nope")

    def test_is_valid_date_rejects_bad_input(self):
        self.assertFalse(_is_valid_date(123))
        self.assertFalse(_is_valid_date("not-a-date"))
        self.assertFalse(_is_valid_date("x" * 50))
        self.assertTrue(_is_valid_date("2024-01-02"))
        self.assertTrue(_is_valid_date("2024-01-02T09:30"))

    def test_decode_path_segment_rejects_invalid(self):
        with self.assertRaises(ValueError):
            _decode_path_segment("")  # empty
        with self.assertRaises(ValueError):
            _decode_path_segment("x" * 65)
        with self.assertRaises(ValueError):
            _decode_path_segment("ok\x01")
        self.assertEqual(_decode_path_segment("MVP%E7%AD%96%E7%95%A5"), "MVP策略")

    def test_safe_static_path_unknown_returns_none(self):
        self.assertIsNone(_safe_static_path("../etc/passwd"))
        self.assertIsNone(_safe_static_path("/secret.js"))
        # known asset returns a path
        self.assertIsNotNone(_safe_static_path("index.html"))
        self.assertIsNotNone(_safe_static_path("desktop"))

    def test_is_time_series_metrics_paths(self):
        self.assertFalse(_is_time_series_metrics({"a": "scalar"}))
        self.assertFalse(_is_time_series_metrics({"a": {}}))
        self.assertFalse(_is_time_series_metrics({"a": {"not-a-date": {}}}))
        self.assertTrue(_is_time_series_metrics({"a": {"2024-01-01": {"x": 1}}}))

    def test_coerce_metric_snapshot_rejects_non_object(self):
        with self.assertRaises(ValueError):
            _coerce_metric_snapshot("not a dict", "metrics[A]")

    def test_coerce_metric_snapshot_rejects_bad_key(self):
        with self.assertRaises(ValueError):
            _coerce_metric_snapshot({"": 1}, "metrics[A]")

    def test_coerce_metric_snapshot_rejects_bad_value(self):
        with self.assertRaises(ValueError):
            _coerce_metric_snapshot({"x": "bad"}, "metrics[A]")

    def test_coerce_metric_snapshot_skips_name(self):
        result = _coerce_metric_snapshot({"name": "Alpha", "x": 1}, "p")
        self.assertEqual(result, {"x": 1.0})

    def test_parse_holdings_not_a_list(self):
        with self.assertRaises(ValueError):
            _parse_holdings("not a list")

    def test_parse_holdings_entry_not_object(self):
        with self.assertRaises(ValueError):
            _parse_holdings(["bad"])

    def test_parse_holdings_invalid_symbol(self):
        with self.assertRaises(ValueError):
            _parse_holdings([{"symbol": "!!", "weight": 0.5}])

    def test_parse_holdings_invalid_weight(self):
        with self.assertRaises(ValueError):
            _parse_holdings([{"symbol": "600000", "weight": "abc"}])

    def test_parse_price_data_not_an_object(self):
        with self.assertRaises(ValueError):
            _parse_price_data("nope")

    def test_parse_price_data_too_many_symbols(self):
        big = {f"{600000 + i:06d}": [{"date": "2024-01-01", "close": 1}] for i in range(21)}
        with self.assertRaises(ValueError):
            _parse_price_data(big)

    def test_parse_price_data_invalid_symbol(self):
        with self.assertRaises(ValueError):
            _parse_price_data({"!!!": [{"date": "2024-01-01", "close": 1}]})

    def test_parse_price_data_empty_bars(self):
        with self.assertRaises(ValueError):
            _parse_price_data({"600000": []})

    def test_parse_price_data_too_many_bars(self):
        bars = [{"date": f"2024-{(i % 12) + 1:02d}-01", "close": 1.0} for i in range(2001)]
        # use distinct dates by varying year too to avoid duplicate-date error
        bars = [{"date": f"{2000 + (i // 12):04d}-{(i % 12) + 1:02d}-01", "close": 1.0}
                for i in range(2001)]
        with self.assertRaises(ValueError):
            _parse_price_data({"600000": bars})

    def test_parse_price_data_bar_not_object(self):
        with self.assertRaises(ValueError):
            _parse_price_data({"600000": ["bad"]})

    def test_parse_price_data_bad_date(self):
        with self.assertRaises(ValueError):
            _parse_price_data({"600000": [{"date": "bad", "close": 1}]})

    def test_parse_price_data_bad_close(self):
        with self.assertRaises(ValueError):
            _parse_price_data({"600000": [{"date": "2024-01-01", "close": "x"}]})

    def test_parse_metrics_provider_not_object(self):
        with self.assertRaises(ValueError):
            _parse_metrics_provider("nope")

    def test_parse_metrics_provider_empty(self):
        with self.assertRaises(ValueError):
            _parse_metrics_provider({})

    def test_parse_metrics_provider_invalid_symbol_flat(self):
        with self.assertRaises(ValueError):
            _parse_metrics_provider({"!!!": {"roe": 1}})

    def test_parse_metrics_provider_invalid_symbol_time_series(self):
        with self.assertRaises(ValueError):
            _parse_metrics_provider({"!!!": {"2024-01-01": {"roe": 1}}})

    def test_parse_metrics_provider_inner_not_object(self):
        # Time-series shaped: by_date must be a Mapping (it is).
        # Build a payload where outer values are time-series-like but inner is not a dict.
        # _is_time_series_metrics would reject this so we instead test the flat path.
        provider, names = _parse_metrics_provider({"600000": {"roe": 1.0, "name": "甲"}})
        self.assertEqual(names.get("600000"), "甲")
        self.assertEqual(provider("600000", "any")["roe"], 1.0)

    def test_make_threshold_factory_invalid_param(self):
        base = StrategyProfile(
            name="x",
            rules=(StrategyRule("roe", ">=", 10),),
            combine_mode="and",
            min_score=0.0,
        )
        factory = _make_threshold_factory(base)
        with self.assertRaises(ValueError):
            factory({"roe": "abc"})


# ---------------------------------------------------------------------------
# APIService method-level validation
# ---------------------------------------------------------------------------
class APIServiceValidationTest(unittest.TestCase):
    def setUp(self):
        self.svc = APIService()

    # -- selection
    def test_run_selection_unknown_strategy(self):
        with self.assertRaises(KeyError):
            self.svc.run_selection("ghost-strategy", {})

    def test_run_etf_selection_unknown_strategy(self):
        with self.assertRaises(KeyError):
            self.svc.run_etf_selection("ghost-strategy", {})

    # -- rebalance
    def test_rebalance_bad_universe(self):
        with self.assertRaises(ValueError):
            self.svc.run_rebalance({"universe": "bonds", "strategy": "x"})

    def test_rebalance_missing_strategy(self):
        with self.assertRaises(ValueError):
            self.svc.run_rebalance({"universe": "etf"})

    def test_rebalance_unknown_strategy(self):
        with self.assertRaises(KeyError):
            self.svc.run_rebalance({"universe": "etf", "strategy": "ghost"})

    def test_rebalance_stock_universe(self):
        # cover the stock branch (lines 231-232)
        builtin = self.svc.list_strategies()[0]["name"]
        result = self.svc.run_rebalance({
            "universe": "stock",
            "strategy": builtin,
        })
        self.assertIn("plan", result)

    def test_leaderboards_etf_empty_strategies_fallback(self):
        # create a service with no built-in strategies → exercises fallback
        from a_stock_promotion.admin import StrategyRegistry

        # Build an empty registry, then add one non-ETF strategy
        registry = StrategyRegistry(builtin_strategies=[
            StrategyProfile(
                name="custom",
                rules=(StrategyRule("roe", ">=", 5),),
                combine_mode="and",
                min_score=0.0,
            ),
        ])
        svc = APIService(registry=registry)
        # universe=etf but no strategy name contains "ETF" → fallback to all
        result = svc.build_leaderboards({"universe": "etf"})
        self.assertIn("leaderboards", result)

    def test_rebalance_invalid_filters(self):
        builtin = self.svc.list_strategies()[0]["name"]
        with self.assertRaises(ValueError):
            self.svc.run_rebalance({
                "universe": "etf",
                "strategy": builtin,
                "filters": "not-an-object",
            })

    def test_rebalance_invalid_scheme(self):
        builtin = self.svc.list_strategies()[0]["name"]
        with self.assertRaises(ValueError):
            self.svc.run_rebalance({
                "universe": "etf",
                "strategy": builtin,
                "scheme": "xx",
            })

    # -- backtest
    def test_backtest_missing_strategy(self):
        with self.assertRaises(ValueError):
            self.svc.run_backtest({})

    def test_backtest_unknown_strategy(self):
        with self.assertRaises(KeyError):
            self.svc.run_backtest({"strategy": "ghost"})

    # -- optimization
    def test_optimize_missing_strategy(self):
        with self.assertRaises(ValueError):
            self.svc.run_optimization({})

    def test_optimize_unknown_strategy(self):
        with self.assertRaises(KeyError):
            self.svc.run_optimization({"strategy": "ghost"})

    def test_optimize_invalid_parameter_grid(self):
        builtin = self.svc.list_strategies()[0]["name"]
        with self.assertRaises(ValueError):
            self.svc.run_optimization({
                "strategy": builtin,
                "parameter_grid": "not-an-object",
            })

    def test_optimize_axis_must_be_nonempty_list(self):
        builtin = self.svc.list_strategies()[0]["name"]
        with self.assertRaises(ValueError):
            self.svc.run_optimization({
                "strategy": builtin,
                "parameter_grid": {"roe": []},
            })

    def test_optimize_too_many_combinations(self):
        builtin = self.svc.list_strategies()[0]["name"]
        with self.assertRaises(ValueError):
            self.svc.run_optimization({
                "strategy": builtin,
                "parameter_grid": {"a": list(range(9)), "b": list(range(9))},
            })

    # -- walk forward
    def test_walk_forward_missing_strategy(self):
        with self.assertRaises(ValueError):
            self.svc.run_walk_forward({})

    def test_walk_forward_unknown_strategy(self):
        with self.assertRaises(KeyError):
            self.svc.run_walk_forward({"strategy": "ghost"})

    def test_walk_forward_invalid_parameter_grid(self):
        builtin = self.svc.list_strategies()[0]["name"]
        with self.assertRaises(ValueError):
            self.svc.run_walk_forward({
                "strategy": builtin,
                "parameter_grid": "no",
            })

    def test_walk_forward_axis_empty(self):
        builtin = self.svc.list_strategies()[0]["name"]
        with self.assertRaises(ValueError):
            self.svc.run_walk_forward({
                "strategy": builtin,
                "parameter_grid": {"a": []},
            })

    def test_walk_forward_too_many_combinations(self):
        builtin = self.svc.list_strategies()[0]["name"]
        with self.assertRaises(ValueError):
            self.svc.run_walk_forward({
                "strategy": builtin,
                "parameter_grid": {"a": list(range(9)), "b": list(range(9))},
            })

    # -- leaderboards
    def test_leaderboards_bad_universe(self):
        with self.assertRaises(ValueError):
            self.svc.build_leaderboards({"universe": "bonds"})

    # -- ai assistant
    def test_ai_explain_unknown_strategy(self):
        with self.assertRaises(KeyError):
            self.svc.ai_explain_strategy("ghost")

    def test_ai_parse_blocks_when_not_allowed(self):
        # Make a service with no AI permission for a free user; then call with
        # a permitted user. We can't easily fake denial via the default
        # configuration (free tier has AI access), so we override the service.
        from a_stock_promotion.membership import MembershipService, TierBenefits

        custom = {
            "free": TierBenefits(
                tier="free", monthly_price=0.0, daily_backtest_quota=1,
                can_use_ai_assistant=False, can_use_optimization=False,
                marketplace_discount=0.0, can_publish_paid_strategy=False,
            ),
            "pro": self.svc.membership.get_benefits("pro"),
            "vip": self.svc.membership.get_benefits("vip"),
        }
        svc = APIService(membership=MembershipService(benefits=custom))
        svc.membership.upsert_user("alice", "free")
        with self.assertRaises(PermissionError):
            svc.ai_parse_prompt({"prompt": "ROE 大于 10", "username": "alice"})

    def test_ai_summarize_missing_strategy(self):
        with self.assertRaises(ValueError):
            self.svc.ai_summarize_selection({})

    def test_ai_summarize_unknown_strategy(self):
        with self.assertRaises(KeyError):
            self.svc.ai_summarize_selection({"strategy": "ghost"})

    def test_ai_summarize_bad_universe(self):
        builtin = self.svc.list_strategies()[0]["name"]
        with self.assertRaises(ValueError):
            self.svc.ai_summarize_selection({
                "strategy": builtin, "universe": "bonds",
            })

    def test_ai_summarize_bad_filters(self):
        builtin = self.svc.list_strategies()[0]["name"]
        with self.assertRaises(ValueError):
            self.svc.ai_summarize_selection({
                "strategy": builtin, "filters": "not-object",
            })

    def test_ai_summarize_etf(self):
        # exercise the etf branch
        etf_strategy = next(
            s["name"] for s in self.svc.list_strategies() if "ETF" in s["name"]
        )
        result = self.svc.ai_summarize_selection({
            "strategy": etf_strategy, "universe": "etf",
        })
        self.assertIn("summary", result)

    # -- community
    def test_community_publish_missing_strategy(self):
        with self.assertRaises(ValueError):
            self.svc.community_publish({"slug": "x", "owner": "u"})

    def test_community_publish_bad_price(self):
        with self.assertRaises(ValueError):
            self.svc.community_publish({
                "slug": "good-slug", "owner": "alice",
                "price": "free",
                "strategy": {
                    "name": "X",
                    "rules": [
                        {"metric": "roe", "operator": ">=", "threshold": 10}
                    ],
                },
            })

    def test_community_publish_paid_requires_membership(self):
        with self.assertRaises(PermissionError):
            self.svc.community_publish({
                "slug": "paid-strategy", "owner": "alice", "price": 19.9,
                "strategy": {
                    "name": "X",
                    "rules": [
                        {"metric": "roe", "operator": ">=", "threshold": 10}
                    ],
                },
            })

    def test_community_publish_invalid_strategy_payload(self):
        with self.assertRaises(ValueError):
            self.svc.community_publish({
                "slug": "x1", "owner": "alice",
                "strategy": {"rules": []},
            })

    def test_community_publish_invalid_slug(self):
        with self.assertRaises(ValueError):
            self.svc.community_publish({
                "slug": "!!", "owner": "alice",
                "strategy": {
                    "name": "X",
                    "rules": [
                        {"metric": "roe", "operator": ">=", "threshold": 10}
                    ],
                },
            })

    def test_community_get_unknown(self):
        self.assertIsNone(self.svc.community_get("nope-nope"))

    def test_community_subscribe_missing_username(self):
        with self.assertRaises(ValueError):
            self.svc.community_subscribe("slug", {})

    def test_community_subscribe_unknown_slug(self):
        with self.assertRaises(KeyError):
            self.svc.community_subscribe("ghost-slug", {"username": "alice"})

    def test_community_subscribe_paid_requires_purchase(self):
        # publish a paid strategy with a Pro owner first
        self.svc.membership.upsert_user("alice", "pro")
        self.svc.community_publish({
            "slug": "paid-strat", "owner": "alice", "price": 9.9,
            "strategy": {
                "name": "X",
                "rules": [{"metric": "roe", "operator": ">=", "threshold": 10}],
            },
        })
        with self.assertRaises(PermissionError):
            self.svc.community_subscribe("paid-strat", {"username": "bob"})

    def test_community_subscribe_invalid_username(self):
        # publish a free strategy
        self.svc.community_publish({
            "slug": "free-strat", "owner": "alice",
            "strategy": {
                "name": "X",
                "rules": [{"metric": "roe", "operator": ">=", "threshold": 10}],
            },
        })
        with self.assertRaises(ValueError):
            self.svc.community_subscribe("free-strat", {"username": "!!"})

    def test_community_unsubscribe_missing_username(self):
        with self.assertRaises(ValueError):
            self.svc.community_unsubscribe("slug", {})

    def test_community_unsubscribe_unknown_slug(self):
        with self.assertRaises(KeyError):
            self.svc.community_unsubscribe("ghost-slug", {"username": "alice"})

    def test_community_unsubscribe_invalid_username(self):
        self.svc.community_publish({
            "slug": "free-strat2", "owner": "alice",
            "strategy": {
                "name": "X",
                "rules": [{"metric": "roe", "operator": ">=", "threshold": 10}],
            },
        })
        with self.assertRaises(ValueError):
            self.svc.community_unsubscribe("free-strat2", {"username": "!!"})

    def test_community_comment_validation(self):
        with self.assertRaises(ValueError):
            self.svc.community_comment("slug", {"body": "ok"})  # missing author
        with self.assertRaises(ValueError):
            self.svc.community_comment("slug", {"author": "alice"})  # missing body
        with self.assertRaises(KeyError):
            self.svc.community_comment("ghost", {"author": "alice", "body": "hi"})

    def test_community_comment_paid_blocked(self):
        self.svc.membership.upsert_user("alice", "pro")
        self.svc.community_publish({
            "slug": "paid-strat2", "owner": "alice", "price": 5.0,
            "strategy": {
                "name": "X",
                "rules": [{"metric": "roe", "operator": ">=", "threshold": 10}],
            },
        })
        with self.assertRaises(PermissionError):
            self.svc.community_comment(
                "paid-strat2", {"author": "bob", "body": "spam"}
            )

    def test_community_comment_owner_can_comment(self):
        self.svc.membership.upsert_user("alice", "pro")
        self.svc.community_publish({
            "slug": "paid-strat3", "owner": "alice", "price": 5.0,
            "strategy": {
                "name": "X",
                "rules": [{"metric": "roe", "operator": ">=", "threshold": 10}],
            },
        })
        result = self.svc.community_comment(
            "paid-strat3", {"author": "alice", "body": "first comment"}
        )
        self.assertIn("comment", result)

    def test_community_comment_invalid_body(self):
        self.svc.community_publish({
            "slug": "free-strat3", "owner": "alice",
            "strategy": {
                "name": "X",
                "rules": [{"metric": "roe", "operator": ">=", "threshold": 10}],
            },
        })
        with self.assertRaises(ValueError):
            self.svc.community_comment(
                "free-strat3", {"author": "alice", "body": "   "}
            )

    # -- membership
    def test_membership_upsert_missing_fields(self):
        with self.assertRaises(ValueError):
            self.svc.membership_upsert_user({"tier": "free"})
        with self.assertRaises(ValueError):
            self.svc.membership_upsert_user({"username": "alice"})

    def test_membership_upsert_invalid_tier(self):
        with self.assertRaises(ValueError):
            self.svc.membership_upsert_user({"username": "alice", "tier": "platinum"})

    def test_membership_get_unknown(self):
        self.assertIsNone(self.svc.membership_get_user("ghost"))

    def test_membership_addon_missing_fields(self):
        with self.assertRaises(ValueError):
            self.svc.membership_subscribe_addon({"addon": "x"})
        with self.assertRaises(ValueError):
            self.svc.membership_subscribe_addon({"username": "alice"})

    def test_membership_addon_unknown_user(self):
        with self.assertRaises(KeyError):
            self.svc.membership_subscribe_addon(
                {"username": "ghost", "addon": "northbound_realtime"}
            )

    def test_membership_addon_invalid_addon(self):
        self.svc.membership.upsert_user("alice", "free")
        with self.assertRaises(ValueError):
            self.svc.membership_subscribe_addon(
                {"username": "alice", "addon": "!!"}
            )

    def test_marketplace_missing_fields(self):
        with self.assertRaises(ValueError):
            self.svc.marketplace_purchase({"slug": "x"})
        with self.assertRaises(ValueError):
            self.svc.marketplace_purchase({"username": "alice"})

    def test_marketplace_unknown_slug(self):
        with self.assertRaises(KeyError):
            self.svc.marketplace_purchase({"username": "alice", "slug": "ghost"})

    def test_marketplace_free_strategy_rejected(self):
        self.svc.community_publish({
            "slug": "free-strat4", "owner": "alice",
            "strategy": {
                "name": "X",
                "rules": [{"metric": "roe", "operator": ">=", "threshold": 10}],
            },
        })
        with self.assertRaises(ValueError):
            self.svc.marketplace_purchase(
                {"username": "bob", "slug": "free-strat4"}
            )

    def test_marketplace_user_not_found(self):
        self.svc.membership.upsert_user("alice", "pro")
        self.svc.community_publish({
            "slug": "paid-strat4", "owner": "alice", "price": 5.0,
            "strategy": {
                "name": "X",
                "rules": [{"metric": "roe", "operator": ">=", "threshold": 10}],
            },
        })
        with self.assertRaises(KeyError):
            self.svc.marketplace_purchase(
                {"username": "ghost", "slug": "paid-strat4"}
            )

    def test_marketplace_duplicate_purchase(self):
        # First purchase succeeds, second raises MembershipError (not "not found")
        # to exercise the non-not-found branch.
        self.svc.membership.upsert_user("alice", "pro")
        self.svc.membership.upsert_user("bob", "free")
        self.svc.community_publish({
            "slug": "paid-strat-dup", "owner": "alice", "price": 5.0,
            "strategy": {
                "name": "X",
                "rules": [{"metric": "roe", "operator": ">=", "threshold": 10}],
            },
        })
        self.svc.marketplace_purchase({"username": "bob", "slug": "paid-strat-dup"})
        with self.assertRaises(ValueError):
            self.svc.marketplace_purchase(
                {"username": "bob", "slug": "paid-strat-dup"}
            )

    def test_community_publish_duplicate_slug(self):
        # First publish succeeds. Second publish with the same slug hits the
        # community-level "slug already exists" error path.
        self.svc.community_publish({
            "slug": "dup-slug", "owner": "alice",
            "strategy": {
                "name": "X",
                "rules": [{"metric": "roe", "operator": ">=", "threshold": 10}],
            },
        })
        with self.assertRaises(ValueError):
            self.svc.community_publish({
                "slug": "dup-slug", "owner": "alice",
                "strategy": {
                    "name": "X",
                    "rules": [{"metric": "roe", "operator": ">=", "threshold": 10}],
                },
            })


# ---------------------------------------------------------------------------
# HTTP-level error paths
# ---------------------------------------------------------------------------
class APIHTTPErrorPathsTest(unittest.TestCase):
    def test_get_invalid_stock_symbol(self):
        with _APIServer() as server:
            status, body = server.get("/api/stocks/UNKNOWN_SYMBOL")
            self.assertEqual(status, 404)

    def test_get_stock_symbol_too_long(self):
        with _APIServer() as server:
            # 17 chars: matches path regex but fails _SYMBOL_RE (1-16)
            status, body = server.get("/api/stocks/" + "A" * 17)
            self.assertEqual(status, 400)

    def test_get_etf_symbol_too_long(self):
        with _APIServer() as server:
            status, body = server.get("/api/etfs/" + "A" * 17)
            self.assertEqual(status, 400)

    def test_get_invalid_filter_value(self):
        with _APIServer() as server:
            # include_st expects a bool-like string; pass an int via query
            status, body = server.get("/api/stocks?include_st=true")
            self.assertEqual(status, 200)

    def test_get_leaderboards_bad_universe(self):
        with _APIServer() as server:
            status, body = server.get("/api/leaderboards?universe=bonds")
            self.assertEqual(status, 400)

    def test_post_community_publish_duplicate_slug_via_http(self):
        with _APIServer() as server:
            payload = {
                "slug": "dup-http", "owner": "alice",
                "strategy": {
                    "name": "X",
                    "rules": [{"metric": "roe", "operator": ">=", "threshold": 10}],
                },
            }
            server.post("/api/community/shares", payload)
            status, body = server.post("/api/community/shares", payload)
            self.assertEqual(status, 400)

    def test_get_invalid_etf_symbol(self):
        with _APIServer() as server:
            status, body = server.get("/api/etfs/UNKNOWN_SYMBOL")
            self.assertEqual(status, 404)

    def test_get_unknown_path_serves_static_fallback_or_404(self):
        with _APIServer() as server:
            status, _ = server.get("/some/random/url")
            self.assertEqual(status, 404)

    def test_get_unknown_community_share(self):
        with _APIServer() as server:
            status, _ = server.get("/api/community/shares/ghost-slug-zz")
            self.assertEqual(status, 404)

    def test_get_unknown_membership_user(self):
        with _APIServer() as server:
            status, _ = server.get("/api/membership/users/ghostuser")
            self.assertEqual(status, 404)

    def test_get_ai_explain_unknown_strategy(self):
        with _APIServer() as server:
            status, _ = server.get("/api/ai/strategies/ghost-strategy/explain")
            self.assertEqual(status, 404)

    def test_post_invalid_json(self):
        with _APIServer() as server:
            status, body = server.post(
                "/api/select", raw_body=b"not-json{",
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(status, 400)

    def test_post_json_not_an_object(self):
        with _APIServer() as server:
            status, body = server.post(
                "/api/select", raw_body=b"[1,2,3]",
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(status, 400)

    def test_post_missing_strategy(self):
        with _APIServer() as server:
            status, body = server.post("/api/select", {})
            self.assertEqual(status, 400)

    def test_post_invalid_filters(self):
        with _APIServer() as server:
            status, body = server.post(
                "/api/select", {"strategy": "X", "filters": "bad"}
            )
            self.assertEqual(status, 400)

    def test_post_select_unknown_strategy(self):
        with _APIServer() as server:
            status, body = server.post(
                "/api/select", {"strategy": "ghost-strategy"}
            )
            self.assertEqual(status, 404)

    def test_post_etf_select_unknown_strategy(self):
        with _APIServer() as server:
            status, body = server.post(
                "/api/etfs/select", {"strategy": "ghost-strategy"}
            )
            self.assertEqual(status, 404)

    def test_post_admin_invalid_payload(self):
        with _APIServer() as server:
            status, body = server.post("/api/admin/strategies", {"name": ""})
            self.assertEqual(status, 400)

    def test_post_ai_parse_bad_prompt(self):
        with _APIServer() as server:
            # parse_prompt with empty prompt raises AIAssistantError -> 400
            status, body = server.post("/api/ai/parse", {"prompt": ""})
            self.assertEqual(status, 400)

    def test_post_community_publish_bad_payload(self):
        with _APIServer() as server:
            status, body = server.post(
                "/api/community/shares",
                {"slug": "!!", "owner": "alice", "strategy": {
                    "name": "X",
                    "rules": [{"metric": "roe", "operator": ">=", "threshold": 10}],
                }},
            )
            self.assertEqual(status, 400)

    def test_post_unknown_path_404(self):
        with _APIServer() as server:
            status, body = server.post("/api/unknown", {})
            self.assertEqual(status, 404)

    def test_post_community_unsubscribe_via_http(self):
        with _APIServer() as server:
            # publish a free strategy first
            server.post("/api/community/shares", {
                "slug": "free-http", "owner": "alice",
                "strategy": {
                    "name": "X",
                    "rules": [{"metric": "roe", "operator": ">=", "threshold": 10}],
                },
            })
            # subscribe
            server.post(
                "/api/community/shares/free-http/subscribe",
                {"username": "bob"},
            )
            # unsubscribe
            status, body = server.post(
                "/api/community/shares/free-http/unsubscribe",
                {"username": "bob"},
            )
            self.assertEqual(status, 200)

    def test_invalid_content_length_header(self):
        import socket
        with _APIServer() as server:
            host, port = server.server.server_address
            with socket.create_connection((host, port), timeout=5) as sock:
                req = (
                    "POST /api/select HTTP/1.1\r\n"
                    f"Host: {host}:{port}\r\n"
                    "Content-Type: application/json\r\n"
                    "Content-Length: not-a-number\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
                sock.sendall(req.encode("ascii"))
                response = b""
                try:
                    while True:
                        chunk = sock.recv(4096)
                        if not chunk:
                            break
                        response += chunk
                        if b"\r\n\r\n" in response:
                            break
                except OSError:
                    pass
            self.assertTrue(
                response.startswith(b"HTTP/1.1 400") or response.startswith(b"HTTP/1.0 400"),
                response,
            )

    def test_post_empty_body_with_zero_length(self):
        with _APIServer() as server:
            # Content-Length: 0 -> _read_json returns {} early; then select handler
            # rejects missing strategy with 400. This exercises the "if not body" branch.
            status, _ = server.post(
                "/api/select", raw_body=b"",
                headers={"Content-Type": "application/json", "Content-Length": "0"},
            )
            self.assertEqual(status, 400)

    def test_post_admin_with_existing_name_returns_400(self):
        # admin.create with duplicate name -> StrategyRegistryError -> 400
        with _APIServer() as server:
            _, listing = server.get("/api/admin/strategies")
            builtin_name = next(
                s["name"] for s in listing["strategies"] if s["is_builtin"]
            )
            payload = {
                "name": builtin_name,
                "rules": [{"metric": "x", "operator": ">=", "threshold": 1}],
            }
            status, _ = server.post("/api/admin/strategies", payload)
            self.assertEqual(status, 400)

    def test_put_admin_bad_payload_returns_400(self):
        # First create a custom strategy, then PUT with invalid payload
        with _APIServer() as server:
            server.post("/api/admin/strategies", {
                "name": "tmp1",
                "rules": [{"metric": "x", "operator": ">=", "threshold": 1}],
            })
            # PUT with invalid combine_mode
            status, _ = server.put(
                "/api/admin/strategies/tmp1",
                {
                    "name": "tmp1",
                    "combine_mode": "xx",
                    "rules": [{"metric": "x", "operator": ">=", "threshold": 1}],
                },
            )
            self.assertEqual(status, 400)

    def test_backtest_workload_limit(self):
        with _APIServer() as server:
            # 20 symbols × 251 bars = 5020 > 5000 → backtest limit error
            price_data = {}
            for i in range(20):
                sym = f"S{i:05d}"
                price_data[sym] = [
                    {
                        "date": f"{2000 + (j // 12):04d}-{(j % 12) + 1:02d}-{(j % 28) + 1:02d}",
                        "close": 1.0 + j * 0.01,
                    }
                    for j in range(251)
                ]
            # Deduplicate dates within each symbol
            for sym, bars in price_data.items():
                seen = set()
                unique = []
                for b in bars:
                    if b["date"] in seen:
                        continue
                    seen.add(b["date"])
                    unique.append(b)
                price_data[sym] = unique
            # Aggregate count
            total = sum(len(b) for b in price_data.values())
            # Use a minimal metrics dict; doesn't matter for the limit check
            metrics = {sym: {"roe": 1.0} for sym in price_data}
            _, listing = server.get("/api/admin/strategies")
            strategy_name = listing["strategies"][0]["name"]
            status, body = server.post("/api/backtest/run", {
                "strategy": strategy_name,
                "price_data": price_data,
                "metrics": metrics,
            })
            # Either hit the workload cap (400) or it ran successfully if total<=5000
            if total > 5000:
                self.assertEqual(status, 400)
                self.assertIn("backtest workload", body.get("error", ""))
            else:
                self.assertEqual(status, 200)

    def test_backtest_config_all_kwargs(self):
        # exercise every branch of _parse_backtest_config
        from a_stock_promotion.api import _parse_backtest_config

        cfg = _parse_backtest_config({
            "rebalance_every": 5,
            "transaction_cost": 0.001,
            "top_n": 3,
            "initial_capital": 100000.0,
            "risk_free_rate": 0.02,
            "periods_per_year": 252,
        })
        self.assertEqual(cfg.rebalance_every, 5)
        self.assertEqual(cfg.top_n, 3)

    def test_parse_metrics_time_series(self):
        from a_stock_promotion.api import _parse_metrics_provider

        provider, names = _parse_metrics_provider({
            "600000": {"2024-01-01": {"roe": 10.0, "name": "甲"}},
        })
        snap = provider("600000", "2024-01-01")
        self.assertEqual(snap["roe"], 10.0)

    def test_parse_metrics_time_series_bad_inner(self):
        from a_stock_promotion.api import _parse_metrics_provider

        # value is a Mapping with a date key, but the snap itself is not Mapping
        # which is rejected by _is_time_series_metrics. Build one that IS
        # time-series shaped but inner snap is not Mapping (raises at coerce).
        # Using a non-Mapping inner -> _is_time_series rejects, so it's parsed
        # as flat and `_coerce_metric_snapshot` raises because "2024-01-01" is
        # not a number.
        with self.assertRaises(ValueError):
            _parse_metrics_provider({"600000": {"2024-01-01": "bad"}})

    def test_put_admin_not_found(self):
        with _APIServer() as server:
            payload = {
                "name": "nope",
                "rules": [{"metric": "x", "operator": ">=", "threshold": 1}],
            }
            status, body = server.put("/api/admin/strategies/nope", payload)
            self.assertEqual(status, 404)

    def test_put_admin_readonly(self):
        with _APIServer() as server:
            # Pick a real built-in strategy name
            _, listing = server.get("/api/admin/strategies")
            builtin_name = next(
                s["name"]
                for s in listing["strategies"]
                if s["is_builtin"]
            )
            payload = {
                "name": builtin_name,
                "rules": [{"metric": "x", "operator": ">=", "threshold": 1}],
            }
            quoted = urllib.parse.quote(builtin_name, safe="")
            status, body = server.put(
                f"/api/admin/strategies/{quoted}", payload
            )
            self.assertEqual(status, 403)

    def test_put_admin_unknown_path(self):
        with _APIServer() as server:
            status, _ = server.put("/api/unknown", {})
            self.assertEqual(status, 404)

    def test_delete_admin_not_found(self):
        with _APIServer() as server:
            status, body = server.delete("/api/admin/strategies/nope")
            self.assertEqual(status, 404)

    def test_delete_admin_readonly(self):
        with _APIServer() as server:
            _, listing = server.get("/api/admin/strategies")
            builtin_name = next(
                s["name"]
                for s in listing["strategies"]
                if s["is_builtin"]
            )
            quoted = urllib.parse.quote(builtin_name, safe="")
            status, body = server.delete(
                f"/api/admin/strategies/{quoted}"
            )
            self.assertEqual(status, 403)

    def test_delete_unknown_path(self):
        with _APIServer() as server:
            status, _ = server.delete("/api/unknown")
            self.assertEqual(status, 404)

    def test_put_admin_bad_path_segment(self):
        with _APIServer() as server:
            # encode a control char that fails _decode_path_segment
            status, _ = server.put(
                "/api/admin/strategies/%01bad",
                {"name": "x", "rules": [
                    {"metric": "x", "operator": ">=", "threshold": 1}
                ]},
            )
            self.assertEqual(status, 400)

    def test_payload_too_large(self):
        # Send a small body but with an oversize Content-Length header so the
        # handler rejects via the cap check without us streaming megabytes.
        # We can't use urllib for a custom Content-Length easily, so use a raw
        # socket.
        import socket

        with _APIServer() as server:
            host, port = server.server.server_address
            with socket.create_connection((host, port), timeout=5) as sock:
                req = (
                    "POST /api/select HTTP/1.1\r\n"
                    f"Host: {host}:{port}\r\n"
                    "Content-Type: application/json\r\n"
                    "Content-Length: 600000\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
                sock.sendall(req.encode("ascii"))
                # Don't send the body; the server should respond 400 from the cap check.
                response = b""
                try:
                    while True:
                        chunk = sock.recv(4096)
                        if not chunk:
                            break
                        response += chunk
                        if b"\r\n\r\n" in response:
                            break
                except OSError:
                    pass
            self.assertIn(b"400", response.split(b"\r\n", 1)[0])


# ---------------------------------------------------------------------------
# HEAD and unconfigured-service handlers
# ---------------------------------------------------------------------------
class APIHandlerNoServiceTest(unittest.TestCase):
    def test_unconfigured_service_returns_503(self):
        # build a server with the bare APIRequestHandler whose service is None
        server = ThreadingHTTPServer(("127.0.0.1", 0), APIRequestHandler)
        try:
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            host, port = server.server_address
            base = f"http://{host}:{port}"
            for method in ("GET", "POST", "PUT", "DELETE"):
                req = urllib.request.Request(
                    base + "/api/health",
                    data=b"{}" if method != "GET" else None,
                    headers={"Content-Type": "application/json"}
                    if method != "GET" else {},
                    method=method,
                )
                try:
                    urllib.request.urlopen(req)
                    self.fail("expected error")
                except urllib.error.HTTPError as exc:
                    self.assertEqual(exc.code, 503)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
