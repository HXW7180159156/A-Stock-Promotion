"""Rule-based AI 选股助手 for PRD §4.3 V2.0.

This module turns short Chinese / English natural-language prompts into
:class:`~a_stock_promotion.models.StrategyProfile` instances and produces
human-readable explanations and result summaries.  It uses a
deterministic phrase-matching parser so the implementation stays within
the project's zero-dependency, fully-tested philosophy and avoids any
external LLM calls.

Supported pattern families (extensible):

* 技术面:    "均线多头"、"MACD 金叉"、"RSI 强势"、"放量"
* 基本面:    "ROE 大于 12"、"PE 低于 30"、"营收增速大于 8"、"负债率不超过 60"
* 情绪面:    "北向资金净流入"、"龙虎榜"、"涨停强度高"
* 组合控制:  "AND" / "OR" / "并且" / "或者"、"最低评分 0.6"

The parser is intentionally conservative: unknown phrases are ignored
(rather than raising) and reported back as ``unmatched`` tokens so that
the UI can hint the user about the supported vocabulary.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .models import SelectionResult, StrategyProfile, StrategyRule

# ---------------------------------------------------------------------------
# Phrase dictionary
# ---------------------------------------------------------------------------
# Each entry maps a (lower-cased) keyword to a StrategyRule template.  The
# template's threshold/operator describe the default condition; the parser
# may override the threshold when the prompt contains an explicit number
# (see ``_NUMERIC_PATTERNS``).
@dataclass(frozen=True)
class _Pattern:
    keywords: tuple[str, ...]
    rule: StrategyRule


_KEYWORD_PATTERNS: tuple[_Pattern, ...] = (
    # Technical
    _Pattern(
        keywords=("均线多头", "ma trend", "均线趋势", "ma_trend"),
        rule=StrategyRule(
            "ma_trend", ">=", 1, 1.0, True, "均线多头排列",
        ),
    ),
    _Pattern(
        keywords=("macd 金叉", "macd金叉", "macd红柱", "macd hist", "macd_hist"),
        rule=StrategyRule(
            "macd_hist", ">", 0, 1.0, False, "MACD 红柱放大",
        ),
    ),
    _Pattern(
        keywords=("rsi 强势", "rsi强势", "rsi"),
        rule=StrategyRule(
            "rsi", ">=", 50, 0.8, False, "RSI 处于强势区间",
        ),
    ),
    _Pattern(
        keywords=("放量", "量比", "volume_ratio", "volume ratio"),
        rule=StrategyRule(
            "volume_ratio", ">=", 1.2, 0.8, False, "成交量放大",
        ),
    ),
    _Pattern(
        keywords=("布林", "boll", "bollinger"),
        rule=StrategyRule(
            "boll_position", ">=", 0.5, 0.6, False, "处于布林带上轨上方",
        ),
    ),
    # Fundamental
    _Pattern(
        keywords=("roe", "净资产收益率"),
        rule=StrategyRule(
            "roe", ">=", 10, 1.2, False, "ROE 不低于阈值",
        ),
    ),
    _Pattern(
        keywords=("pe", "市盈率"),
        rule=StrategyRule(
            "pe", "<=", 30, 1.0, False, "PE 不高于阈值",
        ),
    ),
    _Pattern(
        keywords=("pb", "市净率"),
        rule=StrategyRule(
            "pb", "<=", 3, 0.8, False, "PB 不高于阈值",
        ),
    ),
    _Pattern(
        keywords=("营收增速", "营收增长", "revenue_growth", "revenue growth"),
        rule=StrategyRule(
            "revenue_growth", ">=", 8, 1.0, False, "营收增速不低于阈值",
        ),
    ),
    _Pattern(
        keywords=("负债率", "资产负债率", "debt_ratio", "debt ratio"),
        rule=StrategyRule(
            "debt_ratio", "<=", 60, 0.8, False, "资产负债率不高于阈值",
        ),
    ),
    _Pattern(
        keywords=("股息率", "dividend_yield", "dividend yield"),
        rule=StrategyRule(
            "dividend_yield", ">=", 2, 0.7, False, "股息率不低于阈值",
        ),
    ),
    # Sentiment
    _Pattern(
        keywords=("北向", "北向资金", "northbound", "northbound_inflow"),
        rule=StrategyRule(
            "northbound_inflow", ">", 0, 0.9, False, "北向资金净流入",
        ),
    ),
    _Pattern(
        keywords=("龙虎榜", "lhb", "dragon_tiger"),
        rule=StrategyRule(
            "dragon_tiger", ">=", 1, 0.7, False, "登上龙虎榜",
        ),
    ),
    _Pattern(
        keywords=("涨停强度", "limit_up_strength", "limit up"),
        rule=StrategyRule(
            "limit_up_strength", ">=", 1, 0.7, False, "涨停强度较高",
        ),
    ),
    _Pattern(
        keywords=("板块轮动", "sector_rotation"),
        rule=StrategyRule(
            "sector_rotation", ">", 0, 0.6, False, "所在板块处于轮动上行",
        ),
    ),
)

# Operator overrides expressed in natural language.
_OPERATOR_PHRASES: tuple[tuple[str, str], ...] = (
    ("大于等于", ">="),
    ("不低于", ">="),
    ("不少于", ">="),
    ("至少", ">="),
    ("≥", ">="),
    (">=", ">="),
    ("大于", ">"),
    ("超过", ">"),
    ("高于", ">"),
    (">", ">"),
    ("小于等于", "<="),
    ("不高于", "<="),
    ("不超过", "<="),
    ("最多", "<="),
    ("≤", "<="),
    ("<=", "<="),
    ("小于", "<"),
    ("低于", "<"),
    ("<", "<"),
    ("等于", "=="),
    ("==", "=="),
)

_NUMERIC_RE = re.compile(r"(-?\d+(?:\.\d+)?)")


class AIAssistantError(ValueError):
    """Raised when AI assistant input is invalid."""


@dataclass(frozen=True)
class AIParseResult:
    """Outcome of parsing a natural-language prompt."""

    strategy: StrategyProfile
    matched_phrases: tuple[str, ...]
    unmatched_tokens: tuple[str, ...]
    explanation: str

    def as_dict(self) -> dict:
        return {
            "strategy": _strategy_to_dict(self.strategy),
            "matched_phrases": list(self.matched_phrases),
            "unmatched_tokens": list(self.unmatched_tokens),
            "explanation": self.explanation,
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def parse_prompt(
    prompt: str,
    *,
    name: str | None = None,
    default_combine: str = "and",
) -> AIParseResult:
    """Parse a natural-language prompt into a :class:`StrategyProfile`."""

    if not isinstance(prompt, str):
        raise AIAssistantError("prompt must be a string")
    text = prompt.strip()
    if not text:
        raise AIAssistantError("prompt must not be empty")
    if len(text) > 1000:
        raise AIAssistantError("prompt must be at most 1000 characters")

    lower = text.lower()
    combine_mode = _detect_combine_mode(lower, default_combine)
    min_score = _detect_min_score(lower)

    matched: list[str] = []
    rules: list[StrategyRule] = []
    consumed_spans: list[tuple[int, int]] = []

    for pattern in _KEYWORD_PATTERNS:
        for keyword in pattern.keywords:
            idx = lower.find(keyword)
            if idx == -1:
                continue
            consumed_spans.append((idx, idx + len(keyword)))
            rule = _apply_local_overrides(text, idx, idx + len(keyword), pattern.rule)
            rules.append(rule)
            matched.append(keyword)
            break  # only one occurrence per pattern

    if not rules:
        raise AIAssistantError(
            "未识别到任何选股条件；请尝试提及如 ROE、PE、均线、北向资金等关键词。"
        )

    rules = _dedupe_rules(rules)

    strategy_name = (name or "AI 生成策略").strip() or "AI 生成策略"
    if len(strategy_name) > 64:
        strategy_name = strategy_name[:64]

    strategy = StrategyProfile(
        name=strategy_name,
        rules=tuple(rules),
        combine_mode=combine_mode,
        min_score=min_score,
    )

    unmatched = _extract_unmatched_tokens(text, consumed_spans)
    explanation = explain_strategy(strategy)
    return AIParseResult(
        strategy=strategy,
        matched_phrases=tuple(matched),
        unmatched_tokens=tuple(unmatched),
        explanation=explanation,
    )


def explain_strategy(strategy: StrategyProfile) -> str:
    """Return a Chinese, human-readable explanation of ``strategy``."""

    if not isinstance(strategy, StrategyProfile):
        raise AIAssistantError("strategy must be a StrategyProfile")
    parts: list[str] = []
    parts.append(f"策略 “{strategy.name}” 使用 {len(strategy.rules)} 条规则。")
    mode_text = "全部满足 (AND)" if strategy.combine_mode == "and" else "任意满足 (OR)"
    parts.append(f"组合方式：{mode_text}；最低评分阈值：{strategy.min_score:.2f}。")
    for index, rule in enumerate(strategy.rules, start=1):
        flag = "必选" if rule.required else "可选"
        desc = rule.description or f"{rule.metric} {rule.operator} {rule.threshold}"
        parts.append(
            f"{index}. {desc} ({flag}, 指标={rule.metric}, "
            f"条件={rule.operator}{rule.threshold}, 权重={rule.weight:g})"
        )
    parts.append("提示：本策略仅作研究参考，投资有风险，入市需谨慎。")
    return "\n".join(parts)


def summarize_results(
    results: Sequence[SelectionResult], *, top_n: int = 5
) -> str:
    """Return a short Chinese summary for ``results``."""

    if top_n <= 0:
        raise AIAssistantError("top_n must be positive")
    if not results:
        return "没有候选标的可供总结。建议放宽筛选条件或更换策略模板。"

    selected = [item for item in results if item.selected]
    avg_score = sum(item.score for item in results) / len(results)
    parts: list[str] = []
    parts.append(
        f"共评估 {len(results)} 个标的，命中 {len(selected)} 个；"
        f"平均评分 {avg_score:.2f}。"
    )
    top = results[:top_n]
    if top:
        parts.append("Top 列表：")
        for index, item in enumerate(top, start=1):
            tag = "✅" if item.selected else "·"
            reasons = "; ".join(item.matched_rules[:3]) or "无匹配规则"
            parts.append(
                f"  {index}. {tag} {item.candidate.name} ({item.candidate.symbol}) "
                f"评分 {item.score:.2f} — {reasons}"
            )
    if not selected:
        parts.append("当前没有标的同时满足必选条件，建议适当下调阈值或权重。")
    parts.append("本摘要不构成投资建议，决策请结合自身风险偏好。")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _detect_combine_mode(lower: str, default: str) -> str:
    if any(token in lower for token in ("或者", " or ", "/", "任意")):
        return "or"
    if any(token in lower for token in ("并且", " and ", "同时", "且")):
        return "and"
    if default not in {"and", "or"}:
        return "and"
    return default


_MIN_SCORE_RE = re.compile(
    r"(?:最低评分|最小评分|min[_ ]?score|评分至少|评分不低于)\s*[:=]?\s*"
    r"(-?\d+(?:\.\d+)?)"
)


def _detect_min_score(lower: str) -> float:
    match = _MIN_SCORE_RE.search(lower)
    if not match:
        return 0.5
    value = float(match.group(1))
    if value > 1:
        # Accept "60" meaning 60% → 0.6 for friendlier UX.
        value = value / 100
    if value < 0:
        value = 0.0
    if value > 1:
        value = 1.0
    return round(value, 4)


def _apply_local_overrides(
    text: str, start: int, end: int, base: StrategyRule
) -> StrategyRule:
    """Apply operator / numeric overrides found in a small window around the keyword."""

    tail = text[end : min(len(text), end + 24)].lower()
    head = text[max(0, start - 12) : start].lower()

    operator_ = base.operator
    # Prefer operator phrases that appear AFTER the keyword (typical syntax
    # in both Chinese and English: "ROE 大于 10" / "PE <= 25").
    # Sort by length descending so "不超过" wins over "超过".
    for phrase, op in sorted(_OPERATOR_PHRASES, key=lambda kv: -len(kv[0])):
        if phrase in tail:
            operator_ = op
            break
    else:
        for phrase, op in sorted(_OPERATOR_PHRASES, key=lambda kv: -len(kv[0])):
            if phrase in head:
                operator_ = op
                break

    threshold = base.threshold
    number_match = _NUMERIC_RE.search(tail) or _NUMERIC_RE.search(head)
    if number_match:
        try:
            threshold = float(number_match.group(1))
        except ValueError:
            threshold = base.threshold

    return StrategyRule(
        metric=base.metric,
        operator=operator_,
        threshold=threshold,
        weight=base.weight,
        required=base.required,
        description=base.description,
    )


def _dedupe_rules(rules: Iterable[StrategyRule]) -> list[StrategyRule]:
    seen: dict[str, StrategyRule] = {}
    for rule in rules:
        # Keep the last occurrence — later phrases tend to be more specific.
        seen[rule.metric] = rule
    return list(seen.values())


def _extract_unmatched_tokens(text: str, spans: list[tuple[int, int]]) -> list[str]:
    if not spans:
        return _split_tokens(text)
    spans = sorted(spans)
    merged: list[tuple[int, int]] = []
    for span in spans:
        if merged and span[0] <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], span[1]))
        else:
            merged.append(span)
    pieces: list[str] = []
    cursor = 0
    for s, e in merged:
        if cursor < s:
            pieces.append(text[cursor:s])
        cursor = e
    if cursor < len(text):
        pieces.append(text[cursor:])
    tokens: list[str] = []
    for piece in pieces:
        tokens.extend(_split_tokens(piece))
    return tokens


_TOKEN_SPLIT_RE = re.compile(r"[\s，。,.；;、:：!！?？“”\"'()（）/\\\-]+")


def _split_tokens(text: str) -> list[str]:
    return [tok for tok in _TOKEN_SPLIT_RE.split(text) if tok and len(tok) >= 2]


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


__all__ = [
    "AIAssistantError",
    "AIParseResult",
    "explain_strategy",
    "parse_prompt",
    "summarize_results",
]
