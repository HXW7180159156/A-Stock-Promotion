"""Zero-dependency REST API exposing the MVP selection engine.

Wraps :mod:`a_stock_promotion` with a small ``http.server`` based service
that satisfies PRD §4.1 (API surface for strategy configuration, candidate
ranking and stock detail) without introducing any third-party runtime
dependencies.  Serves the static mobile-friendly UI bundled under
``src/a_stock_promotion/web/``.

Run with ``python -m a_stock_promotion.api`` to start the bundled service
on ``http://localhost:8080``.  The handler is exposed as a class so it
can also be embedded in production servers (e.g. behind gunicorn) later.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .data_sources import SampleFundamentalProvider, SampleSentimentProvider
from .features import FeatureAggregator
from .models import StrategyProfile
from .selection_engine import SelectionEngine
from .stock_pool import StockListing, StockPool, sample_stock_pool
from .strategies import list_builtin_strategies

logger = logging.getLogger(__name__)

WEB_ROOT = Path(__file__).resolve().parent / "web"
RISK_DISCLOSURE = (
    "本服务仅用于投资研究，所有结果不构成任何投资建议或收益承诺，"
    "投资有风险，入市需谨慎。"
)

# Symbols are A-share style codes (digits, optionally exchange prefix).
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{1,16}$")


class APIService:
    """Application service backing the HTTP handler."""

    def __init__(
        self,
        aggregator: FeatureAggregator | None = None,
        strategies: Iterable[StrategyProfile] | None = None,
    ) -> None:
        self.aggregator = aggregator or FeatureAggregator(
            pool=sample_stock_pool(),
            fundamental_provider=SampleFundamentalProvider(),
            sentiment_provider=SampleSentimentProvider(),
        )
        templates = list(strategies) if strategies is not None else list_builtin_strategies()
        self._strategies: dict[str, StrategyProfile] = {
            strategy.name: strategy for strategy in templates
        }
        self.engine = SelectionEngine()

    # ---- Strategy catalogue ------------------------------------------------

    def list_strategies(self) -> list[dict]:
        return [_strategy_to_dict(strategy) for strategy in self._strategies.values()]

    def get_strategy(self, name: str) -> StrategyProfile | None:
        return self._strategies.get(name)

    # ---- Stock pool --------------------------------------------------------

    def list_stocks(self, filters: dict) -> list[dict]:
        pool = self._apply_pool_filters(self.aggregator.pool, filters)
        return [_listing_to_dict(listing) for listing in pool]

    def get_stock_detail(self, symbol: str) -> dict | None:
        listing = self.aggregator.pool.get(symbol)
        if listing is None:
            return None
        metrics = self.aggregator.build(listing)
        return {
            "listing": _listing_to_dict(listing),
            "metrics": metrics.metrics,
            "risk_disclosure": RISK_DISCLOSURE,
        }

    # ---- Selection ---------------------------------------------------------

    def run_selection(self, strategy_name: str, filters: dict) -> dict:
        strategy = self.get_strategy(strategy_name)
        if strategy is None:
            raise KeyError(strategy_name)
        pool = self._apply_pool_filters(self.aggregator.pool, filters)
        candidates = self.aggregator.build_many(list(pool))
        ranked = self.engine.rank(candidates, strategy)
        return {
            "strategy": _strategy_to_dict(strategy),
            "results": [_result_to_dict(item) for item in ranked],
            "risk_disclosure": RISK_DISCLOSURE,
        }

    # ---- Internal helpers --------------------------------------------------

    @staticmethod
    def _apply_pool_filters(pool: StockPool, filters: dict) -> StockPool:
        kwargs = {}
        for key in ("exchange", "industry", "sector"):
            value = filters.get(key)
            if value:
                kwargs[key] = value
        only_tradable = filters.get("only_tradable")
        if only_tradable is not None:
            kwargs["only_tradable"] = _coerce_bool(only_tradable)
        include_st = filters.get("include_st")
        if include_st is not None:
            kwargs["include_st"] = _coerce_bool(include_st)
        return pool.filter(**kwargs)


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


def _listing_to_dict(listing: StockListing) -> dict:
    return {
        "symbol": listing.symbol,
        "name": listing.name,
        "exchange": listing.exchange,
        "industry": listing.industry,
        "sector": listing.sector,
        "is_tradable": listing.is_tradable,
        "is_st": listing.is_st,
        "list_date": listing.list_date,
    }


def _result_to_dict(item) -> dict:
    return {
        "symbol": item.candidate.symbol,
        "name": item.candidate.name,
        "score": item.score,
        "selected": item.selected,
        "matched_rules": list(item.matched_rules),
        "missed_rules": list(item.missed_rules),
        "metrics": item.candidate.metrics,
    }


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


_STATIC_ASSETS: dict[str, Path] = {
    "index.html": WEB_ROOT / "index.html",
    "app.js": WEB_ROOT / "app.js",
    "styles.css": WEB_ROOT / "styles.css",
}


def _safe_static_path(rel_path: str) -> Path | None:
    """Return the static asset for ``rel_path``, or ``None`` if not allowed.

    Uses an explicit allow-list of bundled assets keyed by their basename so
    that user-controlled path components never reach the filesystem layer.
    """

    rel = rel_path.lstrip("/") or "index.html"
    return _STATIC_ASSETS.get(rel)


class APIRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler exposing JSON endpoints and the static UI."""

    service: APIService | None = None  # injected by ``run`` / tests
    server_version = "AStockPromotionMVP/1.0"

    # Disable noisy default logging unless explicitly enabled.
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        logger.debug("%s - %s", self.address_string(), format % args)

    # ---- Dispatch ----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        if self.service is None:
            self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "service not configured"})
            return
        url = urlsplit(self.path)
        path = url.path.rstrip("/") or "/"
        query = {key: values[-1] for key, values in parse_qs(url.query).items()}
        try:
            if path == "/api/health":
                self._send_json(HTTPStatus.OK, {"status": "ok"})
                return
            if path == "/api/strategies":
                self._send_json(HTTPStatus.OK, {"strategies": self.service.list_strategies()})
                return
            if path == "/api/stocks":
                self._send_json(HTTPStatus.OK, {"stocks": self.service.list_stocks(query)})
                return
            stock_match = re.fullmatch(r"/api/stocks/([A-Za-z0-9]+)", path)
            if stock_match:
                symbol = stock_match.group(1).upper()
                if not _SYMBOL_RE.fullmatch(symbol):
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid symbol"})
                    return
                detail = self.service.get_stock_detail(symbol)
                if detail is None:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "stock not found"})
                    return
                self._send_json(HTTPStatus.OK, detail)
                return
            # Fall back to static file serving for the SPA.
            self._serve_static(url.path)
        except Exception:  # pragma: no cover - defensive
            logger.exception("unhandled GET error for %s", self.path)
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal error"})

    def do_POST(self) -> None:  # noqa: N802
        if self.service is None:
            self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "service not configured"})
            return
        url = urlsplit(self.path)
        path = url.path.rstrip("/") or "/"
        try:
            if path == "/api/select":
                payload = self._read_json()
                strategy_name = payload.get("strategy")
                if not strategy_name or not isinstance(strategy_name, str):
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "strategy is required"})
                    return
                filters = payload.get("filters") or {}
                if not isinstance(filters, dict):
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "filters must be an object"})
                    return
                try:
                    result = self.service.run_selection(strategy_name, filters)
                except KeyError:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "strategy not found"})
                    return
                self._send_json(HTTPStatus.OK, result)
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception:  # pragma: no cover - defensive
            logger.exception("unhandled POST error for %s", self.path)
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal error"})

    # ---- Helpers -----------------------------------------------------------

    def _read_json(self) -> dict:
        length_header = self.headers.get("Content-Length")
        try:
            length = int(length_header or "0")
        except ValueError as exc:
            raise ValueError("invalid Content-Length header") from exc
        # Cap payload at 64KB; strategy requests are tiny.
        if length < 0 or length > 64 * 1024:
            raise ValueError("payload too large")
        body = self.rfile.read(length) if length else b""
        if not body:
            return {}
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid JSON body") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _send_json(self, status: HTTPStatus, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _serve_static(self, raw_path: str) -> None:
        path = _safe_static_path(raw_path)
        if path is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        content_type = _content_type_for(path)
        data = path.read_bytes()
        self.send_response(int(HTTPStatus.OK))
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        # Static assets are versioned together with the package; allow short caching.
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)


def _content_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".ico": "image/x-icon",
    }.get(suffix, "application/octet-stream")


def build_handler(service: APIService) -> type[APIRequestHandler]:
    """Return a handler subclass with the service injected."""

    return type("BoundAPIRequestHandler", (APIRequestHandler,), {"service": service})


def run(host: str = "127.0.0.1", port: int = 8080) -> None:  # pragma: no cover - entry
    """Start the bundled HTTP server (blocking)."""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    handler_cls = build_handler(APIService())
    with ThreadingHTTPServer((host, port), handler_cls) as server:
        logger.info("serving on http://%s:%s", host, port)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            logger.info("shutting down")


if __name__ == "__main__":  # pragma: no cover
    run()
