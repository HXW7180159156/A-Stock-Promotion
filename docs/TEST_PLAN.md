# 测试计划

## 1. 测试目标
验证A股智能选股APP在策略评分、ETF筛选、回测、行情接入、端侧体验、安全合规方面满足PRD要求。

## 2. 单元测试
- 策略规则比较符：`>`、`>=`、`<`、`<=`、`==`、`!=`。
- AND/OR组合逻辑。
- 权重归一化和排序稳定性。
- 必选规则未命中时的剔除行为。
- 空数据、缺失指标、负权重和非法比较符处理。

## 3. 集成测试
- 行情/财务/情绪数据接入到因子计算链路。
- 策略配置保存、执行、结果查询全流程。
- WebSocket行情推送和任务状态推送。
- ETF筛选、组合配置和风控指标联动。

## 4. 回测测试
- 固定样本数据下结果可复现。（`tests/test_backtesting.py::test_reproducible_on_fixed_sample`）
- 交易成本、调仓频率、停牌、涨跌停处理。（`test_transaction_cost_reduces_equity`、`test_rebalance_frequency_changes_trade_count`、`test_non_tradable_bar_is_not_bought`）
- 参数优化和样本外验证隔离。（`test_sample_split_isolation`）
- 防止未来函数和幸存者偏差。（`test_no_lookahead_uses_rebalance_date_metrics_only`）

## 5. 移动端测试
- 策略配置表单校验。
- 选股结果排序、筛选、解释展示。
- 自选股、本地缓存和弱网重试。
- iOS、Android、Web多端兼容。

## 6. 安全与合规测试
- 鉴权、越权访问和接口限流。
- 敏感配置不落库、不入仓库。
- 风险提示、免责声明和数据版权声明覆盖核心页面。
- 日志不记录用户敏感信息。

## 7. 当前仓库验证命令
```bash
python -m unittest discover -s tests
```
