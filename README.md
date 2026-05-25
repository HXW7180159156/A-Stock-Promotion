# A-Stock-Promotion

A cross-platform A股智能选股APP project blueprint and MVP strategy engine.

## Documents
- [PRD](docs/PRD.md)
- [技术架构及方案](docs/TECHNICAL_ARCHITECTURE.md)
- [代码实现方案](docs/IMPLEMENTATION_PLAN.md)
- [测试计划](docs/TEST_PLAN.md)

## MVP + V1.0 strategy engine
The current implementation covers PRD §4.1 (MVP) **and §4.2 (V1.0)** end to
end as a pure-Python, dependency-free service: stock pool, ETF pool,
technical indicators, fundamentals, sentiment factors, multi-rule scoring,
portfolio rebalancing, backtesting / parameter optimisation / walk-forward
validation, operational leaderboards, an admin strategy registry, REST API,
plus a mobile-friendly Web UI and a desktop / admin Web UI.

```bash
# Run the full test suite
python -m unittest discover -s tests

# Start the bundled REST API + Web UI on http://127.0.0.1:8080
PYTHONPATH=src python -m a_stock_promotion.api
```

Two SPAs are bundled:

* `/`        — mobile-friendly screening UI (MVP).
* `/desktop` — desktop / admin UI (V1.0): ETF screening & detail,
  portfolio rebalance, backtest & parameter optimisation, operational
  leaderboards, and strategy management.

## Compliance note
This project is for investment research tooling only. It does not provide
investment advice or guarantee returns. Sample fundamental and sentiment data
shipped with the MVP is for demonstration only and must be replaced with a
licensed data source before production use.
