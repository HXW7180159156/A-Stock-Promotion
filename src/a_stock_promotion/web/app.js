"use strict";

// Minimal SPA powering the MVP mobile-friendly UI. Talks to /api/* only.
const state = {
  strategies: [],
  selectedStrategy: null,
  results: [],
  detailSymbol: null,
};

const $ = (sel) => document.querySelector(sel);

function fmtNumber(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value !== "number") return String(value);
  if (Math.abs(value) >= 1e8) return (value / 1e8).toFixed(2) + " 亿";
  if (Math.abs(value) >= 1e4) return (value / 1e4).toFixed(2) + " 万";
  if (Math.abs(value) >= 100) return value.toFixed(1);
  return value.toFixed(3);
}

function escapeHTML(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function activateTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("is-active", tab.dataset.tab === name);
  });
  document.querySelectorAll(".panel").forEach((panel) => {
    panel.classList.toggle("is-active", panel.dataset.panel === name);
  });
}

async function fetchJSON(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status} ${text || response.statusText}`);
  }
  return response.json();
}

function renderStrategies() {
  const select = $("#strategy-select");
  select.innerHTML = state.strategies
    .map((s) => `<option value="${escapeHTML(s.name)}">${escapeHTML(s.name)}</option>`)
    .join("");
  select.value = state.strategies[0]?.name || "";
  state.selectedStrategy = state.strategies[0] || null;
  renderStrategySummary();
}

function renderStrategySummary() {
  const summary = $("#strategy-summary");
  const s = state.selectedStrategy;
  if (!s) { summary.textContent = ""; return; }
  const rules = s.rules
    .map((r) => `<li>${escapeHTML(r.description || `${r.metric} ${r.operator} ${r.threshold}`)}${r.required ? " · 必选" : ""}</li>`)
    .join("");
  summary.innerHTML = `组合模式：${s.combine_mode.toUpperCase()} · 最低分：${s.min_score}<ul>${rules}</ul>`;
}

function renderFilters(stocks) {
  const sectors = Array.from(new Set(stocks.map((s) => s.sector))).sort();
  const industries = Array.from(new Set(stocks.map((s) => s.industry))).sort();
  const sectorSelect = $("#filter-sector");
  const industrySelect = $("#filter-industry");
  sectorSelect.innerHTML = `<option value="">不限</option>` +
    sectors.map((s) => `<option value="${escapeHTML(s)}">${escapeHTML(s)}</option>`).join("");
  industrySelect.innerHTML = `<option value="">不限</option>` +
    industries.map((s) => `<option value="${escapeHTML(s)}">${escapeHTML(s)}</option>`).join("");
}

function collectFilters() {
  return {
    exchange: $("#filter-exchange").value || undefined,
    sector: $("#filter-sector").value || undefined,
    industry: $("#filter-industry").value || undefined,
    only_tradable: $("#filter-tradable").checked,
    include_st: $("#filter-include-st").checked,
  };
}

function renderResults(payload) {
  state.results = payload.results || [];
  const summary = $("#results-summary");
  const selectedCount = state.results.filter((r) => r.selected).length;
  summary.textContent = `共评估 ${state.results.length} 只标的，命中 ${selectedCount} 只。`;
  const list = $("#result-list");
  list.innerHTML = state.results
    .map((r) => {
      const matched = r.matched_rules.map((m) => `<span class="matched">✓ ${escapeHTML(m)}</span>`).join(" ");
      const missed = r.missed_rules.map((m) => `<span class="missed">✗ ${escapeHTML(m)}</span>`).join(" ");
      const cls = r.selected ? "result-item is-selected" : "result-item";
      return `<li class="${cls}" data-symbol="${escapeHTML(r.symbol)}">
        <header>
          <div><span class="symbol">${escapeHTML(r.symbol)}</span> · ${escapeHTML(r.name)}</div>
          <div class="score">${(r.score * 100).toFixed(0)}</div>
        </header>
        <div class="reasons">${matched} ${missed}</div>
      </li>`;
    })
    .join("");
  list.querySelectorAll(".result-item").forEach((node) => {
    node.addEventListener("click", () => loadDetail(node.dataset.symbol));
  });
}

async function loadStrategies() {
  const data = await fetchJSON("/api/strategies");
  state.strategies = data.strategies || [];
  renderStrategies();
}

async function loadStocks() {
  const data = await fetchJSON("/api/stocks");
  renderFilters(data.stocks || []);
}

async function runSelection() {
  const button = $("#run-button");
  button.disabled = true;
  button.textContent = "计算中...";
  try {
    const payload = await fetchJSON("/api/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        strategy: state.selectedStrategy?.name,
        filters: collectFilters(),
      }),
    });
    renderResults(payload);
    activateTab("results");
  } catch (err) {
    alert("选股失败：" + err.message);
  } finally {
    button.disabled = false;
    button.textContent = "运行选股";
  }
}

async function loadDetail(symbol) {
  try {
    const data = await fetchJSON(`/api/stocks/${encodeURIComponent(symbol)}`);
    state.detailSymbol = symbol;
    $("#detail-placeholder").hidden = true;
    const card = $("#detail-card");
    card.hidden = false;
    $("#detail-title").textContent = `${data.listing.symbol} · ${data.listing.name}`;
    $("#detail-subtitle").textContent =
      `${data.listing.exchange} · ${data.listing.industry} / ${data.listing.sector}` +
      (data.listing.is_st ? " · ST" : "");
    const rows = Object.entries(data.metrics)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, value]) =>
        `<tr><td>${escapeHTML(key)}</td><td>${escapeHTML(fmtNumber(value))}</td></tr>`
      )
      .join("");
    $("#detail-metrics").innerHTML = rows || `<tr><td colspan="2" class="muted">暂无指标</td></tr>`;
    $("#detail-risk").textContent = data.risk_disclosure || "";
    activateTab("detail");
  } catch (err) {
    alert("加载详情失败：" + err.message);
  }
}

function bindEvents() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => activateTab(tab.dataset.tab));
  });
  $("#strategy-select").addEventListener("change", (event) => {
    state.selectedStrategy = state.strategies.find((s) => s.name === event.target.value) || null;
    renderStrategySummary();
  });
  $("#run-button").addEventListener("click", runSelection);
}

async function bootstrap() {
  bindEvents();
  try {
    await Promise.all([loadStrategies(), loadStocks()]);
  } catch (err) {
    alert("初始化失败：" + err.message);
  }
}

bootstrap();
