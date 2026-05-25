"use strict";

// Desktop / admin SPA for the V1.0 scope.
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  strategies: [],          // strategy records (with is_builtin flag)
  etfResults: [],
  selectedAdmin: null,     // currently selected admin record (name)
};

function escapeHTML(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
function fmtNumber(value, digits = 3) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (typeof value !== "number") return String(value);
  if (Math.abs(value) >= 1e8) return (value / 1e8).toFixed(2) + " 亿";
  if (Math.abs(value) >= 1e4) return (value / 1e4).toFixed(2) + " 万";
  if (Math.abs(value) >= 100) return value.toFixed(1);
  return value.toFixed(digits);
}
function fmtPct(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return (v * 100).toFixed(2) + "%";
}
async function fetchJSON(path, options) {
  const response = await fetch(path, options);
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new Error(payload.error || response.statusText || ("HTTP " + response.status));
  }
  return payload;
}
function activateTab(name) {
  $$(".tab").forEach((tab) => tab.classList.toggle("is-active", tab.dataset.tab === name));
  $$(".panel").forEach((panel) => panel.classList.toggle("is-active", panel.dataset.panel === name));
}

// ---------- Strategy bootstrap ----------
async function loadStrategies() {
  const data = await fetchJSON("/api/admin/strategies");
  state.strategies = data.strategies || [];
  for (const select of ["#etf-strategy", "#pf-strategy", "#bt-strategy"]) {
    const target = $(select);
    target.innerHTML = state.strategies
      .map((s) => `<option value="${escapeHTML(s.name)}">${escapeHTML(s.name)}</option>`)
      .join("");
  }
  // Prefer an ETF template for the ETF screening selector if available.
  const etfDefault = state.strategies.find((s) => s.name.includes("ETF"));
  if (etfDefault) $("#etf-strategy").value = etfDefault.name;
  renderAdminList();
}

// ---------- ETF screening ----------
async function loadETFs() {
  const data = await fetchJSON("/api/etfs");
  const classes = Array.from(new Set((data.etfs || []).map((e) => e.asset_class))).sort();
  $("#etf-asset").innerHTML =
    `<option value="">不限</option>` +
    classes.map((c) => `<option value="${escapeHTML(c)}">${escapeHTML(c)}</option>`).join("");
}
async function runETFSelection() {
  const button = $("#etf-run");
  button.disabled = true; button.textContent = "计算中...";
  try {
    const payload = await fetchJSON("/api/etfs/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        strategy: $("#etf-strategy").value,
        filters: {
          exchange: $("#etf-exchange").value || undefined,
          asset_class: $("#etf-asset").value || undefined,
          only_tradable: true,
        },
      }),
    });
    state.etfResults = payload.results || [];
    const selected = state.etfResults.filter((r) => r.selected).length;
    $("#etf-summary").textContent =
      `共评估 ${state.etfResults.length} 只 ETF，命中 ${selected} 只。`;
    $("#etf-results").innerHTML = state.etfResults.map((r) => `
      <li class="result-item${r.selected ? " is-selected" : ""}" data-symbol="${escapeHTML(r.symbol)}">
        <header>
          <div><span class="symbol">${escapeHTML(r.symbol)}</span> · ${escapeHTML(r.name)}</div>
          <div class="score">${(r.score * 100).toFixed(0)}</div>
        </header>
        <div class="reasons">
          ${r.matched_rules.map((m) => `<span class="matched">✓ ${escapeHTML(m)}</span>`).join(" ")}
          ${r.missed_rules.map((m) => `<span class="missed">✗ ${escapeHTML(m)}</span>`).join(" ")}
        </div>
      </li>
    `).join("");
    $$("#etf-results .result-item").forEach((node) => {
      node.addEventListener("click", () => loadETFDetail(node.dataset.symbol));
    });
  } catch (err) {
    alert("ETF 筛选失败：" + err.message);
  } finally {
    button.disabled = false; button.textContent = "运行 ETF 筛选";
  }
}
async function loadETFDetail(symbol) {
  try {
    const data = await fetchJSON(`/api/etfs/${encodeURIComponent(symbol)}`);
    $("#etf-detail-placeholder").hidden = true;
    const card = $("#etf-detail-card");
    card.hidden = false;
    $("#etf-detail-title").textContent = `${data.listing.symbol} · ${data.listing.name}`;
    $("#etf-detail-subtitle").textContent =
      `${data.listing.exchange} · ${data.listing.asset_class} · 跟踪 ${data.listing.tracking_index}`;
    const rows = Object.entries(data.metrics)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([k, v]) => `<tr><td>${escapeHTML(k)}</td><td>${escapeHTML(fmtNumber(v))}</td></tr>`)
      .join("");
    $("#etf-detail-metrics").innerHTML = rows ||
      `<tr><td colspan="2" class="muted">暂无指标</td></tr>`;
    $("#etf-detail-risk").textContent = data.risk_disclosure || "";
  } catch (err) {
    alert("加载 ETF 详情失败：" + err.message);
  }
}

// ---------- Portfolio rebalance ----------
async function runRebalance() {
  const button = $("#pf-run");
  button.disabled = true; button.textContent = "计算中...";
  try {
    let current = [];
    const raw = $("#pf-current").value.trim();
    if (raw) {
      try { current = JSON.parse(raw); } catch (_) {
        throw new Error("当前持仓 JSON 解析失败");
      }
      if (!Array.isArray(current)) throw new Error("当前持仓必须是数组");
    }
    const payload = await fetchJSON("/api/portfolio/rebalance", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        strategy: $("#pf-strategy").value,
        universe: $("#pf-universe").value,
        scheme: $("#pf-scheme").value,
        top_n: Number($("#pf-topn").value) || 5,
        max_weight: Number($("#pf-cap").value) || 1,
        transaction_cost: Number($("#pf-fee").value) || 0,
        current,
      }),
    });
    const plan = payload.plan;
    $("#pf-summary").textContent =
      `换手率 ${fmtPct(plan.turnover)} · 交易成本 ${fmtPct(plan.transaction_cost)} · 现金 ${fmtPct(plan.cash_weight)}`;
    const tbody = $("#pf-table tbody");
    tbody.innerHTML = plan.trades.map((t) => `
      <tr>
        <td>${escapeHTML(t.symbol)}</td>
        <td>${escapeHTML(t.action)}</td>
        <td class="num">${fmtPct(t.current_weight)}</td>
        <td class="num">${fmtPct(t.target_weight)}</td>
        <td class="num">${fmtPct(t.delta_weight)}</td>
      </tr>
    `).join("");
    $("#pf-table").hidden = plan.trades.length === 0;
    $("#pf-notes").textContent = plan.notes.join(" / ");
  } catch (err) {
    alert("再平衡失败：" + err.message);
  } finally {
    button.disabled = false; button.textContent = "生成再平衡计划";
  }
}

// ---------- Backtest demo dataset ----------
function buildDemoBacktestDataset() {
  // Synthetic deterministic price series for 3 ETF-like symbols spanning 60 bars.
  const symbols = ["510300", "510500", "518880"];
  const trends = { "510300": 0.0004, "510500": 0.0007, "518880": 0.0002 };
  const seasonal = { "510300": 0.01, "510500": 0.014, "518880": 0.006 };
  const isDate = (i) => {
    const d = new Date(2024, 0, 1 + i);
    return d.toISOString().slice(0, 10);
  };
  const price_data = {};
  for (const sym of symbols) {
    const bars = [];
    let price = 10;
    for (let i = 0; i < 60; i++) {
      const drift = trends[sym];
      const wave = Math.sin(i / 5) * seasonal[sym];
      price *= 1 + drift + wave * 0.1;
      bars.push({ date: isDate(i), close: Number(price.toFixed(4)) });
    }
    price_data[sym] = bars;
  }
  const metrics = {
    "510300": { sharpe_ratio: 0.65, max_drawdown: -0.32, tracking_error: 0.004, fund_size: 6.5e10, daily_turnover: 1.2e9, expense_ratio: 0.005, premium_discount: 0.002 },
    "510500": { sharpe_ratio: 0.45, max_drawdown: -0.36, tracking_error: 0.006, fund_size: 1.2e10, daily_turnover: 8.0e8, expense_ratio: 0.005, premium_discount: 0.003 },
    "518880": { sharpe_ratio: 0.80, max_drawdown: -0.18, tracking_error: 0.003, fund_size: 1.0e10, daily_turnover: 6.0e8, expense_ratio: 0.006, premium_discount: 0.002 },
  };
  return { price_data, metrics };
}
function buildBacktestRequest() {
  const ds = buildDemoBacktestDataset();
  return {
    strategy: $("#bt-strategy").value,
    price_data: ds.price_data,
    metrics: ds.metrics,
    config: {
      rebalance_every: Number($("#bt-rebalance").value) || 5,
      top_n: Number($("#bt-topn").value) || 3,
      transaction_cost: Number($("#bt-fee").value) || 0,
    },
  };
}
function renderBacktestSummary(summary) {
  const tbody = $("#bt-table tbody");
  const rows = [
    ["累计收益", fmtPct(summary.total_return)],
    ["年化收益", fmtPct(summary.annualized_return)],
    ["年化波动", fmtPct(summary.annual_volatility)],
    ["夏普比率", summary.sharpe_ratio.toFixed(3)],
    ["最大回撤", fmtPct(summary.max_drawdown)],
    ["胜率", fmtPct(summary.win_rate)],
    ["换手率(均)", fmtPct(summary.turnover)],
    ["调仓次数", String(summary.trade_count)],
    ["回测周期", `${summary.bars} 个交易日`],
  ];
  tbody.innerHTML = rows.map(([k, v]) =>
    `<tr><td>${escapeHTML(k)}</td><td class="num">${escapeHTML(v)}</td></tr>`).join("");
  $("#bt-table").hidden = false;
}
async function runBacktest() {
  const button = $("#bt-run");
  button.disabled = true; button.textContent = "回测中...";
  try {
    const payload = await fetchJSON("/api/backtest/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildBacktestRequest()),
    });
    $("#bt-summary").textContent = `策略：${payload.strategy.name}`;
    renderBacktestSummary(payload.summary);
    $("#bt-trials").hidden = true;
    $("#bt-trials-title").hidden = true;
  } catch (err) {
    alert("回测失败：" + err.message);
  } finally {
    button.disabled = false; button.textContent = "执行历史回测";
  }
}
async function runOptimisation() {
  const button = $("#bt-opt");
  button.disabled = true; button.textContent = "搜索中...";
  try {
    const req = buildBacktestRequest();
    const payload = await fetchJSON("/api/backtest/optimize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...req,
        score: "sharpe",
        parameter_grid: { tracking_error: [0.003, 0.005, 0.008], fund_size: [1e9, 5e9, 1e10] },
      }),
    });
    if (payload.best) {
      $("#bt-summary").textContent =
        `最优参数：${JSON.stringify(payload.best.parameters)} · Sharpe ${payload.best.score.toFixed(3)}`;
      renderBacktestSummary(payload.best.summary);
    }
    const tbody = $("#bt-trials tbody");
    tbody.innerHTML = payload.trials.map((t) => `
      <tr>
        <td>${escapeHTML(JSON.stringify(t.parameters))}</td>
        <td class="num">${t.score.toFixed(3)}</td>
        <td class="num">${fmtPct(t.summary.annualized_return)}</td>
        <td class="num">${fmtPct(t.summary.max_drawdown)}</td>
      </tr>
    `).join("");
    $("#bt-trials").hidden = false;
    $("#bt-trials-title").hidden = false;
  } catch (err) {
    alert("参数优化失败：" + err.message);
  } finally {
    button.disabled = false; button.textContent = "参数网格优化";
  }
}
async function runWalkForward() {
  const button = $("#bt-wf");
  button.disabled = true; button.textContent = "验证中...";
  try {
    const base = buildBacktestRequest();
    const isBars = (start, count) =>
      base.price_data["510300"].slice(start, start + count).map((b) => b.date);
    // Split the demo dataset in half: first 30 bars in-sample, last 30 out-of-sample.
    const split = 30;
    const sliceData = (start, end) => {
      const out = {};
      for (const [sym, bars] of Object.entries(base.price_data)) {
        out[sym] = bars.slice(start, end);
      }
      return out;
    };
    const payload = await fetchJSON("/api/backtest/walk-forward", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        strategy: base.strategy,
        metrics: base.metrics,
        config: base.config,
        score: "sharpe",
        parameter_grid: { tracking_error: [0.003, 0.005, 0.008] },
        in_sample_price_data: sliceData(0, split),
        out_of_sample_price_data: sliceData(split, base.price_data["510300"].length),
      }),
    });
    $("#bt-summary").textContent =
      `最优参数：${JSON.stringify(payload.best_parameters)} · 样本内 ${payload.in_sample_best.score.toFixed(3)} · 样本外 ${payload.out_of_sample.score.toFixed(3)}`;
    renderBacktestSummary(payload.out_of_sample.summary);
    $("#bt-trials").hidden = true;
    $("#bt-trials-title").hidden = true;
    isBars; // placeholder to silence unused warning if linted
  } catch (err) {
    alert("样本外验证失败：" + err.message);
  } finally {
    button.disabled = false; button.textContent = "样本外验证";
  }
}

// ---------- Leaderboards ----------
async function runLeaderboards() {
  const button = $("#lb-run");
  button.disabled = true; button.textContent = "生成中...";
  try {
    const query = new URLSearchParams({
      universe: $("#lb-universe").value,
      top_n: $("#lb-topn").value || "5",
      only_selected: $("#lb-selected").checked ? "true" : "false",
    });
    const payload = await fetchJSON("/api/leaderboards?" + query.toString());
    $("#lb-results").innerHTML = (payload.leaderboards || []).map((board) => `
      <div class="leaderboard">
        <h3>${escapeHTML(board.strategy)}</h3>
        <ol>
          ${(board.entries || []).map((e) => `
            <li>
              <span>${escapeHTML(e.symbol)} · ${escapeHTML(e.name)}</span>
              <span class="score">${(e.score * 100).toFixed(0)}</span>
            </li>
          `).join("")}
        </ol>
      </div>
    `).join("");
  } catch (err) {
    alert("榜单生成失败：" + err.message);
  } finally {
    button.disabled = false; button.textContent = "生成榜单";
  }
}

// ---------- Admin: strategies ----------
function renderAdminList() {
  const list = $("#admin-list");
  list.innerHTML = state.strategies.map((s) => `
    <li data-name="${escapeHTML(s.name)}" class="${state.selectedAdmin === s.name ? "is-active" : ""}">
      <span>${escapeHTML(s.name)}</span>
      <span class="tag ${s.is_builtin ? "" : "custom"}">${s.is_builtin ? "内置" : "自定义"}</span>
    </li>
  `).join("");
  list.querySelectorAll("li").forEach((node) => {
    node.addEventListener("click", () => {
      state.selectedAdmin = node.dataset.name;
      const record = state.strategies.find((s) => s.name === state.selectedAdmin);
      if (record) loadAdminForm(record);
      renderAdminList();
    });
  });
}
function loadAdminForm(record) {
  $("#admin-name").value = record.name;
  $("#admin-mode").value = record.combine_mode;
  $("#admin-minscore").value = record.min_score;
  $("#admin-rules").value = JSON.stringify(record.rules, null, 2);
  $("#admin-status").textContent = record.is_builtin
    ? "该策略为内置模板，只读。可复制内容到新名称下保存为自定义策略。"
    : "";
}
function clearAdminForm() {
  state.selectedAdmin = null;
  $("#admin-name").value = "";
  $("#admin-mode").value = "and";
  $("#admin-minscore").value = "0";
  $("#admin-rules").value = "";
  $("#admin-status").textContent = "";
  renderAdminList();
}
async function saveAdminStrategy() {
  let rules;
  try {
    rules = JSON.parse($("#admin-rules").value);
  } catch (_) {
    alert("规则 JSON 解析失败");
    return;
  }
  const payload = {
    name: $("#admin-name").value.trim(),
    combine_mode: $("#admin-mode").value,
    min_score: Number($("#admin-minscore").value) || 0,
    rules,
  };
  if (!payload.name) {
    alert("请输入策略名称");
    return;
  }
  const existing = state.strategies.find((s) => s.name === payload.name);
  try {
    if (existing && !existing.is_builtin) {
      await fetchJSON(`/api/admin/strategies/${encodeURIComponent(payload.name)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      $("#admin-status").textContent = "已更新自定义策略。";
    } else if (existing && existing.is_builtin) {
      alert("内置策略不可修改，请改用新的名称。");
      return;
    } else {
      await fetchJSON("/api/admin/strategies", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      $("#admin-status").textContent = "已新建自定义策略。";
    }
    state.selectedAdmin = payload.name;
    await loadStrategies();
  } catch (err) {
    alert("保存失败：" + err.message);
  }
}
async function deleteAdminStrategy() {
  if (!state.selectedAdmin) return;
  const record = state.strategies.find((s) => s.name === state.selectedAdmin);
  if (!record || record.is_builtin) {
    alert("内置策略不可删除");
    return;
  }
  if (!confirm(`确认删除策略「${record.name}」？`)) return;
  try {
    await fetchJSON(`/api/admin/strategies/${encodeURIComponent(record.name)}`, {
      method: "DELETE",
    });
    $("#admin-status").textContent = "已删除。";
    clearAdminForm();
    await loadStrategies();
  } catch (err) {
    alert("删除失败：" + err.message);
  }
}

// ---------- Bootstrap ----------
function bindEvents() {
  $$(".tab").forEach((tab) =>
    tab.addEventListener("click", () => activateTab(tab.dataset.tab))
  );
  $("#etf-run").addEventListener("click", runETFSelection);
  $("#pf-run").addEventListener("click", runRebalance);
  $("#bt-run").addEventListener("click", runBacktest);
  $("#bt-opt").addEventListener("click", runOptimisation);
  $("#bt-wf").addEventListener("click", runWalkForward);
  $("#lb-run").addEventListener("click", runLeaderboards);
  $("#admin-refresh").addEventListener("click", loadStrategies);
  $("#admin-save").addEventListener("click", saveAdminStrategy);
  $("#admin-new").addEventListener("click", clearAdminForm);
  $("#admin-delete").addEventListener("click", deleteAdminStrategy);
}
async function bootstrap() {
  bindEvents();
  try {
    await Promise.all([loadStrategies(), loadETFs()]);
  } catch (err) {
    alert("初始化失败：" + err.message);
  }
}
bootstrap();
