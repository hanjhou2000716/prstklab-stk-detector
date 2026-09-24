"""Evidence-first narrative projections for the four scheduled briefings.

This module deliberately consumes only release-bound themes, quotes and
statistics.  It adds editorial structure without changing notification
eligibility, event identity, or the underlying market assessment.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Any

NARRATIVE_VERSION = "four-report-narrative-v2"

SLOT_FOCUS = {
    "morning": "隔夜美股與全球變化、主要事件及今日日程",
    "pre_open": "最近台股收盤、法人與隔夜科技及匯率",
    "post_close": "當日價格結構、成交廣度、法人與收盤事件",
    "us_premarket": "台亞收盤、已發布總經資料、美國日程與科技事件",
    "intraday": "盤中價格門檻、量價與跨市場同步",
    "midday": "午盤價格結構、跨市場分歧與後續確認",
    "afternoon": "收盤前價格結構、事件與下一項確認",
    "us_open": "美股開盤價格、科技股分歧與即時確認",
}

_TOPIC_GROUPS = {
    "risk": frozenset({
        "taiwan_market", "semiconductor_ai", "global_market", "rates_fx",
        "energy_geopolitics", "company_industry",
    }),
    "taiwan": frozenset({"taiwan_market"}),
    "semiconductor": frozenset({"semiconductor_ai", "company_industry"}),
    "external": frozenset({"rates_fx", "energy_geopolitics"}),
    "us_market": frozenset({
        "global_market", "semiconductor_ai", "rates_fx", "energy_geopolitics",
    }),
}

_GENERIC = frozenset({
    "此公開事件可能影響市場預期",
    "可能連動主要股市、利率或商品市場",
    "觀察主要市場是否出現持續、同步且可核對的價格變化",
    "持續核對公開資料",
    "等待相關市場價格與後續公開資料核對",
})


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _specific(value: Any) -> str:
    text = _text(value)
    if not text or text in _GENERIC or text.lower() in {"null", "none", "nan", "undefined"}:
        return ""
    return text.rstrip("。")


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _topic(theme: dict[str, Any]) -> str:
    return _text(theme.get("market_topic"))


def _themes_for_section(themes: Iterable[dict[str, Any]], section: str) -> list[dict[str, Any]]:
    allowed = _TOPIC_GROUPS.get(section, _TOPIC_GROUPS["risk"])
    result: list[dict[str, Any]] = []
    for theme in themes:
        if not isinstance(theme, dict) or _topic(theme) not in allowed:
            continue
        fact = _specific(theme.get("what_happened"))
        # "市場價格" is useful evidence but is not an event narrative.
        if fact and _text(theme.get("title")) != "市場價格":
            result.append(theme)
        if len(result) == 2:
            break
    return result


def _quote_text(facts: Iterable[str]) -> str:
    values = [_text(item) for item in facts if _text(item)]
    return "；".join(values[:4]).rstrip("；")


def _stats_text(statistics: dict[str, Any]) -> list[str]:
    result: list[str] = []
    turnover = statistics.get("turnover")
    if isinstance(turnover, dict):
        value = _number(turnover.get("trade_value"))
        if value is not None:
            unit = _text(turnover.get("unit") or turnover.get("currency"))
            result.append(f"成交值 {value:,.2f}{unit}")
    breadth = statistics.get("breadth")
    if isinstance(breadth, dict) and breadth.get("scope_verified") is True:
        advancing = _number(breadth.get("advancing"))
        declining = _number(breadth.get("declining"))
        if advancing is not None and declining is not None:
            flat = _number(breadth.get("unchanged"))
            text = f"上漲 {advancing:.0f} 家、下跌 {declining:.0f} 家"
            if flat is not None:
                text += f"、平盤 {flat:.0f} 家"
            result.append(text)
    flows = statistics.get("institutional_flows")
    if isinstance(flows, dict):
        total = _number(flows.get("total_net"))
        if total is not None:
            unit = _text(flows.get("unit") or flows.get("currency"))
            result.append(f"三大法人合計淨額 {total:+,.2f}{unit}")
    return result


def _evidence_refs(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project provenance without exposing transport or private identifiers."""
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        projected = {
            key: item[key]
            for key in (
                "source", "source_label", "quote_source", "source_domain", "source_url",
                "ticker", "name", "quote_date", "quote_time", "published_at", "freshness",
                "data_status", "kind",
            )
            if item.get(key) not in (None, "")
        }
        identity = "|".join(str(projected.get(key, "")) for key in ("source", "ticker", "name", "quote_date", "published_at"))
        if not projected or identity in seen:
            continue
        seen.add(identity)
        result.append(projected)
        if len(result) >= 8:
            break
    return result


def _theme_evidence(themes: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for theme in themes:
        for key in ("source_evidence", "evidence", "quote_evidence"):
            values = theme.get(key)
            if isinstance(values, list):
                items.extend(item for item in values if isinstance(item, dict))
    return items


def _fallback_why(section: str) -> str:
    return {
        "risk": "市場結論由同次台美價格、情緒與波動資料共同核對；新聞只用來界定關注主因。",
        "taiwan": "加權與櫃買的相對方向，搭配成交值、廣度與法人資料，可分辨權值股與中小型股是否同向。",
        "semiconductor": "台積電、費半與 Nasdaq 的同向或分歧，是科技供應鏈與成長股風險偏好的交叉確認。",
        "external": "利率、美元、能源與黃金提供估值、通膨及避險背景，必須以同次資料時間核對。",
        "us_market": "美股現貨與指數期貨各自代表不同交易工具，需分開核對來源、日期與合約口徑。",
    }.get(section, "本輪判讀只採用可追溯的價格、事件與官方資料。")


def _fallback_confirmation(slot: str, section: str) -> str:
    focus = SLOT_FOCUS.get(slot, "下一個有效資料時點")
    if section == "risk":
        return f"後續核對{focus}是否出現同向且可追溯的新證據。"
    return f"下一步核對{focus}的同口徑資料是否延續或出現分歧。"


def _catalyst(themes: list[dict[str, Any]], slot: str, section: str) -> str:
    for theme in themes:
        for key in ("next_catalyst", "catalyst", "follow_up_observation", "stock_observation"):
            value = _specific(theme.get(key))
            if value:
                return value
    return _fallback_confirmation(slot, section)


def build_narrative(
    *,
    slot: str,
    section: str,
    as_of: Any,
    facts: list[str],
    quote_evidence: list[dict[str, Any]],
    themes: list[dict[str, Any]],
    assessment: dict[str, Any] | None = None,
    statistics: dict[str, Any] | None = None,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    """Build a compact preview plus expandable evidence narrative."""
    assessment = assessment if isinstance(assessment, dict) else {}
    statistics = statistics if isinstance(statistics, dict) else {}
    relevant = _themes_for_section(themes, section)
    theme_evidence = _theme_evidence(relevant)
    evidence_refs = _evidence_refs([*quote_evidence, *theme_evidence])
    quote_text = _quote_text(facts)
    statistic_text = _stats_text(statistics) if section == "taiwan" else []
    reaction_parts = [part for part in (quote_text, "；".join(statistic_text)) if part]
    reaction = "；".join(reaction_parts)
    market_highlights = _specific((assessment.get("summary_sections") or {}).get("market_highlights"))
    event_facts = [_specific(theme.get("what_happened")) for theme in relevant]
    event_facts = [value for value in event_facts if value]
    event_text = "；".join(event_facts[:2])
    if not event_text:
        event_text = "本輪沒有合格事件，以可核對行情與統計資料整理。" if reaction else "本輪沒有可核對事件或行情，暫不形成方向結論。"
    if section == "risk" and market_highlights and market_highlights not in event_text:
        reaction = "；".join(part for part in (market_highlights, reaction) if part)
    theme_why = next((_specific(theme.get("why_important")) for theme in relevant if _specific(theme.get("why_important"))), "")
    theme_impact = next((_specific(theme.get("market_implication")) for theme in relevant if _specific(theme.get("market_implication"))), "")
    theme_watch = next((_specific(theme.get("stock_observation")) for theme in relevant if _specific(theme.get("stock_observation"))), "")
    why = theme_why or _fallback_why(section)
    impact = theme_impact or (
        "本輪價格與事件若同向，只能描述同步；若方向不同，保留分歧，不推論因果。"
        if section == "risk" else
        "美股現貨、指數期貨與費半各自依自身資料時間判讀，不混用點位或推論因果。"
        if section == "us_market" else
        "行情與事件未同步時維持待確認，單一指標不取代交叉核對。"
    )
    confirmation = theme_watch or _catalyst(relevant, slot, section)
    # The report focus is retained as structured metadata.  It is not copied
    # into the public card text, where it would compete with the actual next
    # confirmation condition.
    slot_confirmation = confirmation
    limit_values = [value for value in (_text(item) for item in (limitations or [])) if value]
    if not evidence_refs:
        limit_values.append("本輪沒有可供展開的來源引用。")
    limit_values = list(dict.fromkeys(limit_values))
    details = [
        {"label": "發生什麼", "text": event_text, "evidence_refs": evidence_refs[:4]},
        {"label": "為何重要", "text": why, "evidence_refs": evidence_refs[:4]},
        {"label": "可能傳導", "text": impact, "evidence_refs": evidence_refs[:4]},
        {"label": "下一項催化劑", "text": slot_confirmation, "evidence_refs": evidence_refs[:4]},
    ]
    highlights = [
        event_text,
        reaction or "本輪沒有可用的價格或統計反映。",
        slot_confirmation,
    ]
    return {
        "version": NARRATIVE_VERSION,
        "slot": slot,
        "section": section,
        "as_of": as_of,
        "focus": SLOT_FOCUS.get(slot, "本輪可核對市場資料"),
        "highlights": list(dict.fromkeys(highlights))[:3],
        "details": details,
        "evidence_refs": evidence_refs,
        "limitations": limit_values,
    }
