# A-Stock-Promotion

A cross-platform A股智能选股APP project blueprint and MVP strategy engine.

## Documents
- [PRD](docs/PRD.md)
- [技术架构及方案](docs/TECHNICAL_ARCHITECTURE.md)
- [代码实现方案](docs/IMPLEMENTATION_PLAN.md)
- [测试计划](docs/TEST_PLAN.md)

## MVP strategy engine
The current implementation provides a pure-Python, dependency-free MVP that
covers PRD §4.1 end to end: stock pool, technical indicators, fundamentals,
sentiment factors, multi-rule scoring, REST API and a mobile-friendly Web UI.

```bash
# Run the full test suite
python -m unittest discover -s tests

# Start the bundled REST API + Web UI on http://127.0.0.1:8080
PYTHONPATH=src python -m a_stock_promotion.api
```

The Web UI ships the four MVP screens — strategy configuration, screening
results, stock detail and the regulatory risk disclosure banner — and is
responsive for both mobile and desktop browsers.

## Compliance note
This project is for investment research tooling only. It does not provide
investment advice or guarantee returns. Sample fundamental and sentiment data
shipped with the MVP is for demonstration only and must be replaced with a
licensed data source before production use.
