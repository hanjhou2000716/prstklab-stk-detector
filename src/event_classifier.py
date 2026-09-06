"""Shared, auditable event classification for news and live alerts.

Both the scheduled news report and the live monitor must evaluate the same
facts.  This module deliberately accepts a record rather than a single
headline so descriptions, impact notes and market quotes cannot be silently
ignored by the classifier.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_KEYWORD_PATH = Path(__file__).resolve().parents[1] / "config" / "event_keywords.json"


def _load_keywords() -> dict[str, Any]:
    try:
        return json.loads(_KEYWORD_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


KEYWORD_DATABASE = _load_keywords()
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    key: tuple(str(value) for value in values if str(value).strip())
    for key, values in (KEYWORD_DATABASE.get("categories") or {}).items()
    if isinstance(values, list)
}
# Additive runtime aliases keep a trimmed or stale deployment keyword file
# from silently missing common policy wording. Safety gates remain unchanged.
_POLICY_RUNTIME_ALIASES = (
    "steel", "steel imports", "steel import", "imports surge",
    "industrial policy", "executive order", "urges", "urge", "urged",
    "calls on", "call on", "asks", "asked", "presses", "pressured",
    "oil prices", "lower oil prices", "reduce oil prices",
    "要求", "呼籲", "敦促", "降低油價",
)
CATEGORY_KEYWORDS["policy"] = tuple(dict.fromkeys((*CATEGORY_KEYWORDS.get("policy", ()), *_POLICY_RUNTIME_ALIASES)))
BLACK_SWAN_TERMS = tuple(str(value) for value in KEYWORD_DATABASE.get("black_swan", ()) if str(value).strip())
MATERIAL_POSITIVE_TERMS = tuple(str(value) for value in KEYWORD_DATABASE.get("material_positive", ()) if str(value).strip())
ENERGY_PRODUCTION_TERMS = (
    "oil production", "crude production", "oil output", "production increase",
    "output increase", "output cut", "production cut", "石油產量", "石油产量", "原油產量", "原油产量",
    "產油量", "产油量", "增產", "增产", "減產", "减产", "提高產量", "提高产量",
)

# A story can mention a historical war without reporting a new attack. Keep
# those retrospective references in the energy/news path; only an active
# escalation should enter the strict black-swan gate.
ACTIVE_BLACK_SWAN_CONTEXT_TERMS = (
    "war begins", "war began", "war breaks out", "war erupted", "war escalates",
    "military escalation", "armed conflict", "airstrike", "missile attack",
    "invasion", "attack", "strike", "escalation", "major disaster",
    "戰爭爆發", "戰事升級", "重大攻擊", "軍事升級", "战争爆发", "战事升级",
    "重大攻击", "军事升级", "空襲", "空袭", "入侵", "攻擊", "攻击",
)


def normalize_text(value: Any) -> str:
    """Normalize multilingual text without losing CJK characters."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _iter_text(value: Any, key: str = "") -> Iterable[str]:
    if isinstance(value, dict):
        for child_key, child in value.items():
            yield from _iter_text(child, str(child_key))
    elif isinstance(value, (list, tuple, set)):
        for child in value:
            yield from _iter_text(child, key)
    elif isinstance(value, (str, int, float)) and value not in (None, ""):
        yield str(value)


_CLASSIFIER_CONTENT_FIELDS = frozenset({
    "title", "headline", "summary", "description", "brief_summary",
    "traditional_chinese_summary", "chinese_translation", "event",
    "what_happened", "impact", "market_impact", "possible_impact",
    "market_context", "watch", "follow_up", "follow_up_observation",
    "event_type", "category",
})


def _iter_classifier_content(record: dict[str, Any]) -> Iterable[str]:
    """Yield only bounded public content fields.

    Provider URLs, source labels, tracked tickers, interest graphs and nested
    diagnostics are routing/provenance metadata.  They must never turn an
    otherwise ordinary sentence into a market event classification.
    """
    for key in _CLASSIFIER_CONTENT_FIELDS:
        value = record.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, (dict, list, tuple, set)):
            yield from _iter_text(value)
        else:
            yield str(value)


def build_haystack(record: dict[str, Any] | str) -> str:
    """Combine only explicit content fields into one classifier input."""
    values = [record] if isinstance(record, str) else list(_iter_classifier_content(record))
    return normalize_text(" ".join(values))


def _contains(term: str, haystack: str) -> bool:
    candidate = normalize_text(term)
    if not candidate:
        return False
    # Short English indicators such as ``ppi`` or ``ai`` must be complete
    # tokens.  Substring matching turns ordinary words such as "top pick"
    # into false macro/AI classifications.
    if re.fullmatch(r"[a-z0-9]+", candidate):
        return re.search(rf"(?<![a-z0-9]){re.escape(candidate)}(?![a-z0-9])", haystack) is not None
    if candidate in haystack:
        return True
    # CJK aliases and English phrases are both commonly split by punctuation.
    compact_candidate = re.sub(r"[\s\-_/|:：,，。.!！?？]+", "", candidate)
    compact_haystack = re.sub(r"[\s\-_/|:：,，。.!！?？]+", "", haystack)
    return len(compact_candidate) >= 3 and compact_candidate in compact_haystack


def _first_hit(terms: Iterable[str], haystack: str) -> str:
    return next((str(term) for term in terms if _contains(str(term), haystack)), "")


def has_active_black_swan_context(haystack: str) -> bool:
    """Return whether a story describes an active escalation, not history."""
    normalized = normalize_text(haystack)
    for term in ACTIVE_BLACK_SWAN_CONTEXT_TERMS:
        candidate = normalize_text(term)
        if not candidate:
            continue
        start = 0
        while True:
            index = normalized.find(candidate, start)
            if index < 0:
                break
            # Historical or explicitly negated mentions ("since the war
            # began", "not a new attack") describe context, not a new
            # black-swan escalation. Keep the active-event gate conservative.
            prefix = normalized[max(0, index - 36):index]
            if not re.search(r"\b(?:since|after|before|not|no|without|historical|former)\b|(?:自從|自…以來|自…以後|歷史|历史|不是|並非|并非|未有)", prefix):
                return True
            start = index + max(1, len(candidate))
    return False


_FED_SUBJECTS = (
    "federal reserve", "fed", "fomc", "powell", "jerome powell",
    "央行", "聯準會", "联准会", "美聯儲", "美联储", "鮑威爾", "鲍威尔",
    "日本央行", "日本銀行", "日本银行", "boj", "bank of japan",
)
_FED_ACTIONS = (
    "rate", "rates", "rate decision", "monetary policy", "policy statement",
    "balance sheet", "liquidity", "hawkish", "dovish", "reprice", "repricing",
    "bets", "pricing", "利率", "決策", "政策", "聲明", "聲明", "升息", "降息",
    "資產負債表", "流動性", "偏鷹", "偏鴿", "押注", "預期",
)
_MACRO_SUBJECTS = (
    "cpi", "pce", "ppi", "gdp", "payroll", "nonfarm payrolls",
    "jobs", "employment", "inflation", "unemployment rate", "employment situation", "consumer price",
    "producer price", "非農", "非农", "失業率", "失业率", "就業報告", "就业报告",
    "消費者物價", "消费者物价", "生產者物價", "生产者物价", "國內生產毛額", "国内生产总值",
    "通膨", "通胀", "零售銷售", "零售销售",
)
_MACRO_ACTIONS = (
    "report", "reported", "release", "released", "data", "公布", "發布", "发布",
    "上升", "下降", "變化", "變動", "高於", "低於", "較前", "月增", "年增",
    "公布值", "數據", "数据", "預期", "預測", "forecast",
)
_CURRENCY_SUBJECTS = ("yen", "japanese yen", "日圓", "日元", "dollar", "美元", "usd")
_CURRENCY_ACTIONS = (
    "intervention", "fx intervention", "currency intervention", "exchange rate",
    "currency", "strengthens", "weakens", "rises", "falls", "匯率", "汇率",
    "升值", "貶值", "贬值", "干預", "干预", "央行",
)
_ENERGY_SUBJECTS = (
    "wti", "brent", "crude oil", "oil", "opec", "hormuz", "persian gulf",
    "原油", "油價", "油价", "石油", "能源", "荷姆茲", "霍尔木兹",
)
_ENERGY_ACTIONS = (
    "supply", "production", "output", "shipping", "tanker", "transport", "disruption",
    "supply cut", "oil price", "attack", "blockade", "interrupt", "供應", "供应", "產量",
    "产量", "航運", "航运", "運輸", "运输", "中斷", "中断", "油價", "油价", "封鎖", "封锁",
)
_CONFLICT_SUBJECTS = (
    "iran", "iranian", "israel", "ukraine", "russia", "middle east", "hormuz",
    "伊朗", "以色列", "烏克蘭", "乌克兰", "俄羅斯", "俄罗斯", "中東", "中东", "荷姆茲", "霍尔木兹",
)
_CONFLICT_ACTIONS = (
    "war", "conflict", "attack", "airstrike", "missile", "invasion", "escalation",
    "ceasefire", "truce", "talks", "negotiation", "agreement", "blockade",
    "戰爭", "战争", "衝突", "冲突", "攻擊", "攻击", "空襲", "空袭", "入侵", "升級", "升级",
    "停火", "談判", "谈判", "協議", "协议", "封鎖", "封锁",
)
_POLICY_SUBJECTS = (
    "trump", "donald trump", "white house", "administration", "tariff", "tariffs",
    "sanction", "sanctions", "export control", "export controls", "關稅", "关税",
    "制裁", "出口管制", "禁令", "政策",
)
_POLICY_ACTIONS = (
    "tariff", "tariffs", "sanction", "sanctions", "export control", "export controls",
    "duty", "duties", "ban", "restriction", "announces", "announced", "imposes", "raises",
    "pauses", "backs down", "walks back", "宣布", "加徵", "加征", "實施", "实施", "暫緩", "暂缓",
    "延後", "延后", "取消", "撤回",
)
_SEMICONDUCTOR_SUBJECTS = (
    "nvidia", "nvda", "tsmc", "tsm", "asml", "semiconductor", "chip", "ai",
    "輝達", "台積電", "臺積電", "半導體", "半导体", "晶片", "芯片", "人工智慧",
)
_SEMICONDUCTOR_ACTIONS = (
    "earnings", "guidance", "outlook", "capex", "export control", "restriction", "forecast",
    "production", "supply", "demand", "orders", "revenue", "profit", "財報", "財測", "展望",
    "資本支出", "出口管制", "限制", "產能", "产能", "供應", "供应", "需求", "訂單", "订单", "營收", "营收",
)
_MARKET_SUBJECTS = ("nasdaq", "s&p 500", "sp500", "sox", "nyse", "dow jones", "那斯達克", "標普", "費半", "道瓊")
_MARKET_ACTIONS = (
    "rise", "rises", "fell", "fall", "higher", "lower", "surge", "drop", "rally", "selloff",
    "record", "volatile", "futures", "上漲", "下跌", "暴漲", "暴跌", "創高", "創低", "期貨",
)


def _pair(haystack: str, subjects: Iterable[str], actions: Iterable[str]) -> tuple[str, str] | None:
    subject = _first_hit(subjects, haystack)
    action = _first_hit(actions, haystack)
    # A repeated noun such as "tariff" is not an action.  Require the
    # second token to contribute a distinct fact/action so a lone entity or
    # topic cannot qualify a public story.
    return (subject, action) if subject and action and normalize_text(subject) != normalize_text(action) else None


def _classified(category: str, reason: str, terms: Iterable[str], haystack: str, pair: tuple[str, str] | None) -> dict[str, Any]:
    subject, action = pair or ("", "")
    return {
        "category": category,
        "reason": reason,
        "matched_terms": [str(term) for term in terms if str(term).strip()],
        "text": haystack,
        "decision_value_eligible": True,
        "classification_evidence": [item for item in (subject, action) if item],
        "matched_subject": subject,
        "matched_action": action,
        "matched_market_object": subject,
    }


def _unclassified(reason: str, haystack: str, terms: Iterable[str] = ()) -> dict[str, Any]:
    return {
        "category": None,
        "reason": reason,
        "matched_terms": [str(term) for term in terms if str(term).strip()],
        "text": haystack,
        "decision_value_eligible": False,
        "classification_evidence": [],
        "matched_subject": "",
        "matched_action": "",
        "matched_market_object": "",
    }


def classify_event_fields(record: dict[str, Any] | str) -> dict[str, Any]:
    """Classify an event only when a subject is paired with a concrete fact/action."""
    haystack = build_haystack(record)
    # De-escalation must win over generic war/attack aliases.
    positive = _first_hit(MATERIAL_POSITIVE_TERMS, haystack)
    if positive:
        return _classified("material_positive", "material_positive_keyword", [positive], haystack, None)
    black = _first_hit(BLACK_SWAN_TERMS, haystack)
    black_pair = _pair(haystack, _CONFLICT_SUBJECTS, ACTIVE_BLACK_SWAN_CONTEXT_TERMS)
    if black and black_pair and has_active_black_swan_context(haystack):
        return _classified("black_swan", "black_swan_subject_action", [black, *black_pair], haystack, black_pair)
    # A Trump mention becomes actionable only with a policy or de-escalation
    # action; the dedicated aliases are kept in the JSON database.
    trump = KEYWORD_DATABASE.get("trump") or {}
    entities = tuple(str(item) for item in trump.get("entities", ()) if str(item).strip())
    policy_actions = tuple(str(item) for item in trump.get("policy_actions", ()) if str(item).strip())
    taco = tuple(str(item) for item in trump.get("taco", ()) if str(item).strip())
    if _first_hit(taco, haystack):
        hit = _first_hit(taco, haystack)
        return _classified("policy", "trump_taco_keyword", [hit], haystack, (_first_hit(entities, haystack), hit))
    trump_pair = _pair(haystack, entities, policy_actions)
    if trump_pair:
        hit = _first_hit(policy_actions, haystack)
        return _classified("policy", "trump_policy_keyword", [*trump_pair], haystack, trump_pair)

    pairs: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
        ("conflict", _CONFLICT_SUBJECTS, _CONFLICT_ACTIONS),
        ("policy", _POLICY_SUBJECTS, _POLICY_ACTIONS),
        ("fed", _FED_SUBJECTS, _FED_ACTIONS),
        ("macro", _MACRO_SUBJECTS, _MACRO_ACTIONS),
        ("macro", _CURRENCY_SUBJECTS, _CURRENCY_ACTIONS),
        ("energy", _ENERGY_SUBJECTS, _ENERGY_ACTIONS),
        ("semiconductor", _SEMICONDUCTOR_SUBJECTS, _SEMICONDUCTOR_ACTIONS),
        ("market", _MARKET_SUBJECTS, _MARKET_ACTIONS),
    )
    for category, subjects, actions in pairs:
        matched = _pair(haystack, subjects, actions)
        if matched:
            return _classified(category, f"{category}_subject_action", matched, haystack, matched)
    return _unclassified("keyword_no_match", haystack)


def notification_gate(category: str | None, *, official_confirmed: bool, market_sync_confirmed: bool) -> dict[str, Any]:
    """Return a transparent notification state for strict geopolitical events."""
    strict = category in {"black_swan", "conflict"}
    if not strict:
        return {"status": "eligible", "reasons": []}
    reasons: list[str] = []
    if not official_confirmed:
        reasons.append("等待官方核對")
    if not market_sync_confirmed:
        reasons.append("等待市場同步")
    return {"status": "ready" if not reasons else "pending", "reasons": reasons}
