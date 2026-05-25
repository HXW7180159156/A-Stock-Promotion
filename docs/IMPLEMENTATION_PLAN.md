# 代码实现方案

## 1. 当前实现范围
本仓库已交付 PRD §4.1 MVP **和 §4.2 V1.0** 的端到端可运行版本。

### 1.1 MVP（PRD §4.1）
- 股票池管理（A股基础股票池、行业/板块标签、可交易/ST 状态）。
- 技术指标计算（均线、MACD、KDJ、RSI、布林带、量价）。
- 基本面数据模型（PE、PB、ROE、营收增速、负债率、股息率等）。
- 市场情绪因子（北向资金、龙虎榜、板块轮动、涨停强度）。
- 股票多因子规则评分、AND/OR 组合、必选规则与权重评分。
- ETF 筛选策略模板。
- 可解释的命中/未命中原因。
- 零依赖 REST API 与移动端友好的 Web SPA（策略配置、选股结果、个股详情、风险提示）。

### 1.2 V1.0（PRD §4.2）
- **ETF 模块**：`etf_pool.py` 提供 `ETFListing` / `ETFPool` / `ETFSnapshot` / `SampleETFProvider` / `ETFFeatureAggregator`，并通过 `/api/etfs`、`/api/etfs/{symbol}`、`/api/etfs/select` 暴露筛选 / 详情。
- **组合再平衡**：`portfolio.py` 提供等权 / 评分加权目标权重、单标的上限、最小换手阈值、交易成本估算，并通过 `/api/portfolio/rebalance` 暴露端到端再平衡计划。
- **回测 / 参数优化 / 样本外验证**：`backtesting.py` + `optimization.py` 通过 `/api/backtest/run`、`/api/backtest/optimize`、`/api/backtest/walk-forward` 暴露给桌面端 / 管理端，并对网格规模和数据量做了输入校验。
- **运营榜单**：`leaderboards.py` + `/api/leaderboards` 输出多策略多榜单聚合结果。
- **策略管理（管理端）**：`admin.py` 提供线程安全的内存 CRUD 注册表，通过 `/api/admin/strategies` 支持 GET/POST/PUT/DELETE，内置模板只读。
- **桌面端 / 管理端 Web UI**：`web/desktop.html` + `web/desktop.js` + `web/desktop.css` 提供 ETF 筛选 / 组合再平衡 / 回测 / 运营榜单 / 策略管理 五个面板，部署在 `/desktop`。

## 2. 分层设计
- `models.py`：股票指标、策略规则、策略配置和结果对象。
- `selection_engine.py`：执行规则匹配、评分归一化和候选排序。
- `strategies.py`：默认股票/ETF 策略模板（≥10 套，满足 PRD §7）。
- `stock_pool.py`：A股股票池模型与示例数据；支持按交易所/行业/板块/可交易状态/ST 过滤。
- `etf_pool.py`：ETF 池、ETF 因子快照与聚合器（V1.0）。
- `indicators.py`：均线、MACD、KDJ、RSI、布林带、量比和均线趋势评分。
- `data_sources.py`：基本面/情绪数据 Provider 协议与示例数据集（可替换为 AkShare 等真实源）。
- `features.py`：聚合股票池、行情、基本面、情绪为 `StockMetrics`，供策略引擎消费。
- `risk_metrics.py`：最大回撤、年化波动、夏普、历史 VaR 等风控指标。
- `backtesting.py`：纯 Python 回测执行器。
- `optimization.py`：参数网格搜索与样本外（walk-forward）验证。
- `portfolio.py`：组合再平衡计划生成器（V1.0）。
- `leaderboards.py`：运营榜单聚合器（V1.0）。
- `admin.py`：策略管理 CRUD 注册表（V1.0）。
- `api.py` + `web/`：基于 stdlib `http.server` 的零依赖 REST 服务，配套移动端 SPA 与桌面端 / 管理端 SPA。
- `tests/`：核心引擎、指标、聚合器、API、回测、参数优化、ETF、组合、榜单、管理端等共 150+ 用例。

## 3. 启动方式
```bash
# 运行测试
python -m unittest discover -s tests
# 启动后端 + Web UI（默认 http://127.0.0.1:8080）
# - 移动端：    http://127.0.0.1:8080/
# - 桌面 / 管理端：http://127.0.0.1:8080/desktop
PYTHONPATH=src python -m a_stock_promotion.api
```

## 4. 后续工程化演进
1. ~~封装后端服务 API~~（已完成，见 `api.py`）。
2. 替换示例 Provider 为真实数据源（AkShare/Wind/同花顺）。
3. ~~回测执行器~~（已完成）、~~参数优化网格~~（已完成）；后续将回测排入异步队列。
4. ~~ETF 模块 / 组合再平衡 / 桌面端管理端 / 运营榜单~~（V1.0 已完成）。
5. 移动端原生工程（Flutter）：复用现有 REST API；当前 Web SPA 已覆盖 MVP 必需的“策略配置 / 选股结果 / 个股详情 / 风险提示”页面。
6. 增加用户、策略保存、自选股、通知和订阅模块（V1.5+）。
7. 接入鉴权、限流、审计与监控（生产化）。

## 5. 关键边界
- 当前实现不连接真实交易系统。
- 不承诺收益，只输出研究辅助结果。
- 默认策略仅作为模板，生产环境应允许用户调整阈值与权重。
- 示例数据集仅用于演示，正式上线前必须替换为合规授权的数据源。
- 管理端策略注册表为内存实现；生产环境需替换为持久化存储并接入鉴权。
