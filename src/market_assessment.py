"""Deterministic market-context synthesis for scheduled briefings.

This module is intentionally small and side-effect free.  It turns already
validated event/quote observations into a bounded public projection; it does
not fetch data, classify a source by its URL, or make an investment claim.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

TOPIC_LABELS: dict[str, str] = {
    "taiwan_market": "台股行情、廣度與籌碼",
    "semiconductor_ai": "台積電、半導體與 AI 供應鏈",
    "global_market": "美國與全球股市",
    "rates_fx": "利率、通膨、美元與匯率",
    "energy_geopolitics": "能源、航運與地緣風險",
    "company_industry": "公司、產業與監管事件",
}

_TOPIC_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("semiconductor_ai", ("半導體", "晶片", "芯片", "台積電", "臺積電", "tsmc", "nvidia", "輝達", "ai", "人工智慧", "矽光子")),
    ("rates_fx", ("fed", "fomc", "聯準會", "央行", "利率", "通膨", "通胀", "cpi", "ppi", "pce", "gdp", "非農", "殖利率", "美元", "日圓", "匯率")),
    ("energy_geopolitics", ("原油", "油價", "石油", "能源", "荷姆茲", "霍爾木茲", "hormuz", "opec", "航運", "制裁", "攻擊", "封鎖", "伊朗", "以色列")),
    ("taiwan_market", ("台股", "加權指數", "櫃買", "外資", "投信", "融資", "廣度", "籌碼")),
    ("global_market", ("nasdaq", "那斯達克", "s&p", "標普", "sox", "費半", "道瓊", "美股", "全球股市")),
)

_ROLE_NAMES: dict[str, str] = {
    "沃勒": "Fed官員",
    "waller": "Fed官員",
    "鮑威爾": "Fed主席",
    "鲍威尔": "Fed主席",
    "powell": "Fed主席",
    "貝森特": "美國財長",
    "贝森特": "美國財長",
    "bessent": "美國財長",
}

_PUBLISHER_TAIL_RE = re.compile(
    r"\s*(?:[｜|]\s*)?(?:[^｜|]{0,60}\s+)?(?:新聞|報導|記者|作者|編輯|編譯)\s*[-–—:]?\s*"
    r"(?:Storm\.mg|Storm|Reuters|Bloomberg|Yahoo Finance|Google News)?\s*$",
    re.IGNORECASE,
)
_MEDIA_TAIL_RE = re.compile(
    r"\s*[-–—]\s*(?:Storm\.mg|Reuters|Bloomberg|Yahoo Finance|Google News|CNBC|Financial Times)\.?\s*$",
    re.IGNORECASE,
)
_BYLINE_MARKER_RE = re.compile(r"(?:記者|作者|編輯|編譯|新聞\s*[-–—:]|\b(?:by|reporting by)\b)", re.IGNORECASE)
_ROLE_PREFIX_RE = re.compile(
    r"(?P<name>沃勒|鮑威爾|鲍威尔|貝森特|贝森特|Waller|Powell|Bessent)\s*(?P<delimiter>[:：]|表示|指出|稱|称|說|说)",
    re.IGNORECASE,
)
_ACTION_RE = re.compile(
    r"(?:表示|指出|宣稱|帶來|宣布|公布|發布|更新|完成|等待|組成|共組|影響|上漲|下跌|升息|降息|干預|供應|中斷|"
    r"said|says|announc|report|release|rise|fall|jump|drop|increase|decrease|disrupt|supply|rate|outlook|earnings|guidance|forecast|profit|revenue|policy|statement)",
    re.IGNORECASE,
)


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _term_in_text(haystack: str, term: str) -> bool:
    normalized = term.casefold()
    if re.fullmatch(r"[a-z0-9]+", normalized):
        return re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", haystack) is not None
    return normalized in haystack


def _strip_tail(title: str) -> tuple[str, bool, bool]:
    value = _text(title)
    byline_removed = False
    publisher_removed = False
    # The pipe is a transport separator in the observed news feeds.  Only
    # remove a suffix when it carries an attribution marker, never a normal
    # fact separated by punctuation.
    parts = re.split(r"[｜|]", value)
    if len(parts) > 1 and _BYLINE_MARKER_RE.search(parts[-1]):
        value = "｜".join(parts[:-1]).strip()
        byline_removed = True
        publisher_removed = True
    before = value
    value = _PUBLISHER_TAIL_RE.sub("", value).strip(" ｜|:：,，")
    if value != before:
        byline_removed = True
        publisher_removed = True
    before = value
    value = _MEDIA_TAIL_RE.sub("", value).strip(" ｜|:：,，")
    if value != before:
        publisher_removed = True
    return value, byline_removed, publisher_removed


def _role_normalize(value: str, event: dict[str, Any]) -> tuple[str, str, str]:
    actor_name = _text(event.get("actor_name") or event.get("person_name"))
    actor_role = _text(event.get("actor_role") or event.get("role"))
    result = value
    match = _ROLE_PREFIX_RE.search(result)
    if match:
        raw_name = match.group("name")
        replacement = _ROLE_NAMES.get(raw_name.casefold(), _ROLE_NAMES.get(raw_name, ""))
        if replacement:
            actor_name = actor_name or raw_name
            actor_role = actor_role or replacement
            delimiter = match.group("delimiter")
            delimiter = "表示" if delimiter in {":", "："} else delimiter
            result = f"{result[:match.start()]}{replacement}{delimiter}" + result[match.end():]
    elif actor_name and actor_role and actor_name in result:
        result = result.replace(actor_name, actor_role, 1)
    return result, actor_role, actor_name if actor_name else ""


def normalize_headline(event: dict[str, Any], fact: str | None = None) -> dict[str, Any]:
    """Return a public-safe fact while keeping the original title untouched."""
    raw_title = _text(
        event.get("raw_title") or event.get("headline") or event.get("title")
        or event.get("event") or event.get("what_happened") or fact
    )
    source = _text(fact or event.get("event") or event.get("summary") or raw_title)
    source, byline_removed, publisher_removed = _strip_tail(source)
    source, actor_role, actor_name = _role_normalize(source, event)
    # These are editorial transport artefacts, not facts.  Keep attribution
    # institutions (e.g. 經濟部) and replace sensational wording conservatively.
    normalized = source.replace("！", "，").replace("!", ",")
    normalized = normalized.replace("「", "").replace("」", "")
    normalized = re.sub(r"等\s*\d+\s*家(?:巨頭|企業|公司|廠商)", "等業者", normalized)
    normalized = normalized.replace("共組", "組成")
    normalized = re.sub(r"(經濟部|政府|公司管理層)\s*[:：]\s*", r"\1表示", normalized)
    normalized = re.sub(r"供應鏈完全掌握在台灣手上", "供應鏈涵蓋台灣廠商", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip(" ｜|:：,，")
    normalized = normalized.rstrip("。！？.!?，,") + "。" if normalized else ""
    complete = bool(normalized and _ACTION_RE.search(normalized) and len(normalized.rstrip("。")) >= 8)
    topic = classify_market_topic(event, normalized)
    return {
        "raw_title": raw_title,
        "normalized_fact": normalized,
        "market_topic": topic,
        "actor_role": actor_role,
        "actor_name": actor_name,
        "headline_actor": _text(event.get("headline_actor") or actor_role),
        "byline_removed": byline_removed,
        "publisher_removed": publisher_removed,
        "normalization_ruleset": "market_headline_normalizer_v1",
        "normalization_complete": complete,
    }


def classify_market_topic(event: dict[str, Any], fact: str = "") -> str:
    """Map an event to one of the six stable investor-facing topics."""
    category = _text((event.get("event_classification") or {}).get("category") if isinstance(event.get("event_classification"), dict) else event.get("category")).casefold()
    category_map = {
        "semiconductor": "semiconductor_ai", "ai": "semiconductor_ai",
        "macro": "rates_fx", "fed": "rates_fx", "currency": "rates_fx",
        "energy": "energy_geopolitics", "conflict": "energy_geopolitics", "black_swan": "energy_geopolitics",
        "market": "global_market", "taiwan_market": "taiwan_market",
        "policy": "company_industry", "earnings": "company_industry", "guidance": "company_industry",
    }
    if category in category_map:
        return category_map[category]
    haystack = f"{_text(event.get('title'))} {_text(event.get('event'))} {fact}".casefold()
    for topic, terms in _TOPIC_TERMS:
        if any(_term_in_text(haystack, term) for term in terms):
            return topic
    return "company_industry"


def topic_label(topic: str | None) -> str:
    return TOPIC_LABELS.get(str(topic or "company_industry"), TOPIC_LABELS["company_industry"])


def _quote_move(item: dict[str, Any]) -> float | None:
    raw_value = item.get("change_percent")
    if raw_value is None:
        return None
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None
    return value if value == value and abs(value) != float("inf") else None


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)


def _quote_factors(quotes: Iterable[dict[str, Any]]) -> tuple[dict[str, float], set[str], set[str]]:
    factors: dict[str, float] = {}
    dimensions: set[str] = set()
    positive: set[str] = set()
    negative: set[str] = set()
    for item in quotes:
        ticker = _text(item.get("ticker")).upper()
        move = _quote_move(item)
        if not ticker or move is None:
            continue
        if ticker in {"TAIEX", "NASDAQ", "SOX", "DJIA", "NIKKEI", "KOSPI"}:
            factors[f"equity:{ticker}"] = 1.0 if move > 0.25 else -1.0 if move < -0.25 else 0.0
            dimensions.add("equity")
        elif ticker in {"US10Y", "DXY"}:
            # Rising rates/USD are treated as a defensive valuation pressure
            # in this descriptive score; the raw quote remains the evidence.
            factors[f"macro:{ticker}"] = -1.0 if move > 0.25 else 1.0 if move < -0.25 else 0.0
            dimensions.add("rates_fx")
        elif ticker in {"WTI", "BRENT", "GOLD"}:
            factors[f"commodity:{ticker}"] = -1.0 if move > 0.75 else 1.0 if move < -0.75 else 0.0
            dimensions.add("commodity")
        value = factors.get(f"equity:{ticker}", factors.get(f"macro:{ticker}", factors.get(f"commodity:{ticker}")))
        if value is not None:
            (positive if value > 0 else negative if value < 0 else set()).add(ticker)
    return factors, dimensions, positive | negative


def _stance(score: float, factor_count: int, dimensions: set[str], conflict: bool) -> tuple[str, str, str]:
    if conflict or factor_count < 3 or len(dimensions) < 2:
        return "divergent", "分歧", "low" if factor_count < 3 or len(dimensions) < 2 else "medium"
    if score >= 2:
        return "bullish", "偏多", "high" if factor_count >= 4 else "medium"
    if score >= 0.5:
        return "mildly_bullish", "中性偏多", "medium"
    if score > -0.5:
        return "divergent", "分歧", "medium"
    if score > -2:
        return "cautious", "中性偏謹慎", "medium"
    return "bearish", "偏空", "high" if factor_count >= 4 else "medium"


def _topic_driver(theme: dict[str, Any] | None) -> str:
    if not isinstance(theme, dict):
        return "市場主因仍待價格確認"
    topic = str(theme.get("market_topic") or "company_industry")
    return {
        "taiwan_market": "台股行情待確認",
        "semiconductor_ai": "半導體題材待價格確認",
        "global_market": "外圍股市訊號",
        "rates_fx": "利率與美元仍待價格確認",
        "energy_geopolitics": "能源風險待價格確認",
        "company_industry": "公司事件待價格確認",
    }.get(topic, "市場主因仍待價格確認")


def _quote_highlights(quotes: list[dict[str, Any]]) -> str:
    names = {"TAIEX": "台指", "NASDAQ": "Nasdaq", "SOX": "費半", "DJIA": "道瓊", "NIKKEI": "日經", "KOSPI": "韓股"}
    parts: list[str] = []
    for item in quotes:
        move = _quote_move(item)
        ticker = _text(item.get("ticker")).upper()
        if move is None or ticker not in names:
            continue
        freshness = _text(item.get("freshness") or item.get("data_status")).casefold()
        prefix = "最近收盤" if freshness in {"recent_close", "stale", "delayed"} else ""
        parts.append(f"{prefix}{names[ticker]}{move:+.2f}%")
    return "、".join(parts[:3]) or "目前缺乏可用行情證據"


def build_market_assessment(
    *,
    slot: str,
    as_of: datetime,
    quotes: list[dict[str, Any]],
    themes: list[dict[str, Any]],
    intelligence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a five-level stance with explicit evidence sufficiency."""
    supplied = intelligence.get("market_assessment") if isinstance(intelligence, dict) else None
    factors, dimensions, directional = _quote_factors(quotes)
    score = sum(factors.values())
    pos = sum(1 for value in factors.values() if value > 0)
    neg = sum(1 for value in factors.values() if value < 0)
    conflict = pos > 0 and neg > 0
    factor_source = "quote_factors"
    if isinstance(intelligence, dict):
        regime = intelligence.get("market_regime")
        if isinstance(regime, dict) and isinstance(regime.get("score"), (int, float)):
            score = float(regime["score"])
            factor_source = "market_regime"
            conflict = conflict or bool(regime.get("conflict_flags"))
            factor_count = int(regime.get("factor_count") or len(factors))
        else:
            factor_count = len(factors)
    else:
        factor_count = len(factors)
    if isinstance(supplied, dict) and supplied.get("stance") in {"bullish", "mildly_bullish", "divergent", "cautious", "bearish"}:
        stance = str(supplied["stance"])
        labels = {"bullish": "偏多", "mildly_bullish": "中性偏多", "divergent": "分歧", "cautious": "中性偏謹慎", "bearish": "偏空"}
        stance_label = str(supplied.get("stance_label") or labels[stance])
        confidence = str(supplied.get("confidence") or "low")
    else:
        stance, stance_label, confidence = _stance(score, factor_count, dimensions, conflict)
    taipei = as_of.astimezone(timezone(timedelta(hours=8)))
    weekend = taipei.weekday() >= 5
    taiwan_slot = slot in {"pre_open", "intraday", "midday", "afternoon", "post_close"}
    if taiwan_slot:
        market_scope = "台股"
    elif slot in {"us_premarket", "us_open"}:
        market_scope = "美股"
    else:
        market_scope = "台美市場"
    if taiwan_slot and weekend:
        market_summary = "台股休市、外圍訊號分歧"
    else:
        market_summary = f"{market_scope}{stance_label}"
    dominant = next((theme for theme in themes if theme.get("normalization_complete", True)), themes[0] if themes else None)
    driver = _topic_driver(dominant)
    highlights = _quote_highlights(quotes)
    risk = "行情與事件證據仍待後續核對。" if conflict or confidence == "low" else "留意利率、能源與外圍市場變化。"
    if dominant and not dominant.get("quote_evidence"):
        risk = f"{driver}。"
    return {
        "stance": stance,
        "stance_label": stance_label,
        "confidence": confidence,
        "market_scope": market_scope,
        "dominant_driver": driver,
        "dominant_driver_key": dominant.get("canonical_event_key") if isinstance(dominant, dict) else None,
        "supporting_theme_keys": [str(theme.get("canonical_event_key") or theme.get("event_key")) for theme in themes if theme.get("canonical_event_key") or theme.get("event_key")],
        "conflict_flags": ["directional_quote_conflict"] if conflict else [],
        "summary_sections": {
            "summary": market_summary,
            "market_highlights": highlights,
            "risk": risk,
        },
        "evidence_as_of": as_of.isoformat(),
        "factor_count": factor_count,
        "evidence_dimensions": sorted(dimensions),
        "score": round(score, 3),
        "factor_source": factor_source,
        "weekend_market": weekend and taiwan_slot,
        "directional_quote_count": len(directional),
    }


def _overview_clause(value: Any) -> str:
    return _text(value).rstrip("。！？.!?；;，,")


def project_overview(assessment: dict[str, Any], limit: int = 140) -> str:
    raw_sections = assessment.get("summary_sections")
    sections: dict[str, Any] = raw_sections if isinstance(raw_sections, dict) else {}
    summary = _overview_clause(sections.get("summary"))
    highlights = _overview_clause(sections.get("market_highlights"))
    risk = _overview_clause(sections.get("risk"))
    if not summary or not highlights or not risk:
        return ""
    candidates = [
        f"總結｜{summary}。行情重點｜{highlights}。風險｜{risk}。",
        f"總結｜{summary}。行情重點｜{highlights}。風險｜待後續核對。",
        f"總結｜{summary}。行情重點｜{highlights}。風險｜留意市場變化。",
        f"總結｜{summary}。行情重點｜市場資料已整理。風險｜待後續核對。",
    ]
    return next((item for item in candidates if len(item) <= limit), "")


def project_public_message(label: str, assessment: dict[str, Any], limit: int = 60) -> str:
    raw_sections = assessment.get("summary_sections")
    sections: dict[str, Any] = raw_sections if isinstance(raw_sections, dict) else {}
    conclusion = _overview_clause(sections.get("summary"))
    driver = _overview_clause(assessment.get("dominant_driver"))
    prefix = f"📊 {label}｜"
    for body in (f"{conclusion}；{driver}。", f"{conclusion}。"):
        result = prefix + body
        if len(result) <= limit and "..." not in result and "…" not in result:
            return result
    return ""
