# A-Stock-Promotion

A股智能选股策略引擎 — 纯 Python、零第三方依赖的 A 股 / ETF 多因子选股服务，涵盖策略筛选、回测优化、组合再平衡、运营榜单、管理端、AI 选股助手、社区与付费体系，并内置移动端和桌面端 Web UI。

## 文档
- [产品需求文档 (PRD)](docs/PRD.md)
- [技术架构及方案](docs/TECHNICAL_ARCHITECTURE.md)
- [代码实现方案](docs/IMPLEMENTATION_PLAN.md)
- [测试计划](docs/TEST_PLAN.md)

## 快速开始

```bash
# 运行完整测试套件
python -m unittest discover -s tests

# 在 http://127.0.0.1:8080 启动内置 REST API + Web UI
PYTHONPATH=src python -m a_stock_promotion.api
```

内置两个单页应用：

* `/`        — 移动端股票筛选 UI（MVP）
* `/desktop` — 桌面端 / 管理端 UI（V1.0）：ETF 筛选与详情、组合再平衡、回测与参数优化、运营榜单、策略管理

---

## 模块概览

| 模块 | 功能 |
|---|---|
| `models.py` | 核心领域模型：`StockMetrics`、`StrategyRule`、`StrategyProfile`、`SelectionResult` |
| `selection_engine.py` | 可解释多规则评分引擎，支持 `and` / `or` 组合模式与必填规则 |
| `stock_pool.py` | A 股股票池管理（沪 SH / 深 SZ / 北交所 BJ），支持交易所、行业、板块、ST 过滤 |
| `etf_pool.py` | ETF 股票池、因子快照（跟踪误差、规模、费率、折溢价、夏普等）及特征聚合 |
| `indicators.py` | 纯 Python 技术指标：SMA / EMA、MACD、RSI(14)、KDJ(9)、布林带(20,2σ)、量比 |
| `features.py` | 特征聚合器，将技术 / 基本面 / 情绪数据合并为 `StockMetrics` |
| `data_sources.py` | 基本面（PE / PB / ROE / 营收增速 / 净利润增速 / 负债率 / 股息率）与情绪（北向资金 / 龙虎榜 / 板块动量 / 涨停强度）数据提供者协议及样本实现 |
| `strategies.py` | 12 个内置选股策略模板（见下方列表） |
| `backtesting.py` | 回测引擎：无未来函数、停牌 / 涨跌停标记、交易成本、换手率统计、净值曲线 |
| `optimization.py` | 网格搜索参数优化 + 样本外走前验证（Walk-Forward），支持 Sharpe / 总收益 / Calmar 评分 |
| `portfolio.py` | 组合再平衡规划，支持等权 / 评分加权、持仓上限、最小调仓阈值 |
| `risk_metrics.py` | 风险指标：最大回撤、年化波动率、年化夏普比率、历史 VaR |
| `leaderboards.py` | 运营榜单：按策略对全股票 / ETF 池打分排名（成长榜 / 蓝筹榜 / ETF 低波动榜等） |
| `admin.py` | 策略注册表 CRUD，支持内置（只读）与自定义策略并存，线程安全 |
| `ai_assistant.py` | **V2.0** — 中文自然语言 → 策略解析、策略解释、选股结果摘要 |
| `community.py` | **V2.0** — 策略分享 / 订阅 / 评论的线程安全内存仓储 |
| `membership.py` | **V2.0** — 会员等级、数据增值订阅、策略市场订单 |
| `api.py` | 基于 `http.server` 的零依赖 REST API + 静态 Web UI 服务 |

---

## 内置策略模板（12 个）

### A 股策略（9 个）
| 策略名称 | 类型 | 核心规则 |
|---|---|---|
| A股多因子MVP策略 | 多因子 | 均线趋势 + RSI + ROE + 营收增速 + 负债率 + 北向资金 |
| 技术趋势跟随策略 | 技术 | 均线多头排列 + MACD 红柱 + 量比放大 |
| 超跌反转策略 | 技术 | RSI ≤ 30 + KDJ J 值低位 + 价格跌破60日均线 |
| 布林带突破策略 | 技术 | 突破布林上轨 + 成交量放大 1.5 倍 |
| 价值蓝筹策略 | 基本面 | PE ≤ 20 + PB ≤ 3 + ROE ≥ 12% + 低负债 + 股息率 |
| 高成长策略 | 基本面 | 营收增速 ≥ 25% + 净利润增速 ≥ 30% + ROE ≥ 15% |
| 北向资金跟随策略 | 情绪 | 北向资金当日 + 5 日净流入 + 均线不空头 |
| 龙虎榜强势策略 | 情绪 | 龙虎榜评分 ≥ 60 + 涨停强度 + 换手率 |
| 板块轮动策略 | 情绪 | 板块动量强 + 板块主力净流入 + 价格站上20日均线 |

### ETF 策略（3 个）
| 策略名称 | 核心规则 |
|---|---|
| ETF质量筛选策略 | 跟踪误差 ≤ 2% + 日成交额 ≥ 5000万 + 规模 ≥ 5亿 + 费率 ≤ 0.6% + 折溢价 ≤ 1% |
| ETF低波动稳健策略 | 年化波动率 ≤ 18% + 最大回撤 ≥ −20% + 夏普 ≥ 0.8 + 规模 ≥ 10亿 |
| 行业ETF轮动策略 | 行业动量 ≥ 0.6 + 日成交额 ≥ 3000万 + 低折溢价 + 低费率 |

---

## REST API 端点

### GET 端点

| 端点 | 说明 |
|---|---|
| `GET /api/health` | 服务健康检查 |
| `GET /api/strategies` | 列出所有可用策略（名称 + 规则） |
| `GET /api/stocks` | 列出股票池（支持 `exchange` / `industry` / `sector` / `only_tradable` / `include_st` 过滤） |
| `GET /api/stocks/{symbol}` | 股票详情 + 当前因子快照 |
| `GET /api/etfs` | 列出 ETF 池（支持 `exchange` / `asset_class` / `sector` / `tracking_index` 过滤） |
| `GET /api/etfs/{symbol}` | ETF 详情 + 因子快照 |
| `GET /api/leaderboards` | 运营榜单（`universe=stock\|etf`、`top_n`、`only_selected`） |
| `GET /api/admin/strategies` | 管理端策略列表（含内置标记） |
| `GET /api/community/shares` | **V2.0** — 已发布社区策略列表（`owner` / `tag` / `only_free` 过滤） |
| `GET /api/community/shares/{slug}` | **V2.0** — 社区策略详情 + 评论 |
| `GET /api/ai/strategies/{name}/explain` | **V2.0** — 给定策略名生成中文解释 |
| `GET /api/membership/benefits` | **V2.0** — free / pro / vip 会员权益对比 |
| `GET /api/membership/users/{username}` | **V2.0** — 用户会员信息 + 历史订单 |

### POST 端点

| 端点 | 说明 |
|---|---|
| `POST /api/select` | A 股选股（`strategy`、`filters`） |
| `POST /api/etfs/select` | ETF 筛选（`strategy`、`filters`） |
| `POST /api/portfolio/rebalance` | 组合再平衡（`strategy`、`universe`、`top_n`、`scheme`、`current` 持仓、`transaction_cost`） |
| `POST /api/backtest/run` | 回测运行（`strategy`、`price_data`、`metrics`、`config`） |
| `POST /api/backtest/optimize` | 网格参数优化（`parameter_grid`、`score=sharpe\|total_return\|calmar`，上限 64 个组合） |
| `POST /api/backtest/walk-forward` | 走前验证（`in_sample_price_data`、`out_of_sample_price_data`） |
| `POST /api/admin/strategies` | 创建自定义策略 |
| `POST /api/ai/parse` | **V2.0** — 自然语言 → 策略 + 解释（`prompt`，可选 `name` / `username`） |
| `POST /api/ai/summarize` | **V2.0** — 选股 + 中文摘要（`strategy` / `universe` / `top_n`） |
| `POST /api/community/shares` | **V2.0** — 发布策略到社区（`slug` / `owner` / `price` / `tags` / `strategy`） |
| `POST /api/community/shares/{slug}/subscribe` | **V2.0** — 订阅策略；付费策略需先购买 |
| `POST /api/community/shares/{slug}/unsubscribe` | **V2.0** — 取消订阅 |
| `POST /api/community/shares/{slug}/comments` | **V2.0** — 评论策略 |
| `POST /api/membership/users` | **V2.0** — 创建 / 升级用户会员（`username` / `tier`） |
| `POST /api/membership/addons` | **V2.0** — 订阅数据增值服务（`username` / `addon`） |
| `POST /api/marketplace/purchase` | **V2.0** — 购买付费策略（按会员等级自动折扣） |

### PUT / DELETE 端点

| 端点 | 说明 |
|---|---|
| `PUT /api/admin/strategies/{name}` | 更新自定义策略（内置策略不可修改） |
| `DELETE /api/admin/strategies/{name}` | 删除自定义策略（内置策略不可删除） |

---

## 技术因子参考

技术指标由 `indicators.py` 计算，特征聚合后以如下字段名输入规则引擎：

| 字段名 | 说明 |
|---|---|
| `close` | 最新收盘价 |
| `ma_trend` | 均线趋势评分（1=多头排列，−1=空头排列，0=中性） |
| `price_to_ma20` | 收盘价 / 20日均线 |
| `price_to_ma60` | 收盘价 / 60日均线 |
| `macd_dif` | MACD DIF 线 |
| `macd_dea` | MACD DEA 线 |
| `macd_hist` | MACD 柱（2×(DIF−DEA)） |
| `rsi` | RSI(14)，0–100 |
| `kdj_k` / `kdj_d` / `kdj_j` | KDJ(9) 指标 |
| `price_to_boll_upper` | 收盘价 / 布林上轨 |
| `price_to_boll_lower` | 收盘价 / 布林下轨 |
| `volume_ratio` | 量比（当日量 / 5日均量） |
| `pe` / `pb` / `roe` | 市盈率 / 市净率 / 净资产收益率 |
| `revenue_growth` | 营收同比增速（%） |
| `net_profit_growth` | 净利润同比增速（%） |
| `debt_ratio` | 资产负债率（%） |
| `dividend_yield` | 股息率（%） |
| `northbound_inflow` | 北向资金当日净流入 |
| `northbound_inflow_5d` | 北向资金5日累计净流入 |
| `dragon_tiger_score` | 龙虎榜热度评分 |
| `limit_up_strength` | 涨停强度 |
| `turnover_rate` | 换手率（%） |
| `sector_momentum` | 板块动量评分 |
| `sector_inflow` | 板块主力净流入 |

ETF 专属字段：`tracking_error`、`fund_size`、`daily_turnover`、`expense_ratio`、`premium_discount`、`annual_volatility`、`max_drawdown`、`sharpe_ratio`、`nav`、`price`

---

## 样本数据

内置样本数据供演示和测试，**不得用于实盘**。生产环境请替换为授权数据源（如 AkShare 或交易所数据）。

- **股票池**：12 只 A 股（贵州茅台、五粮液、中国平安、招商银行、美的集团、宁德时代、比亚迪、恒瑞医药、隆基绿能、中信证券、京东方A、中芯国际）
- **ETF 池**：12 只 ETF（沪深300、中证500、创业板、科创50、证券、医疗、新能源车、酒、十年国债、黄金、纳指、恒生）

---

## 合规声明

本项目仅用于投资研究工具开发，所有结果不构成任何投资建议或收益承诺。内置样本基本面与情绪数据仅供演示，投资有风险，入市需谨慎。
