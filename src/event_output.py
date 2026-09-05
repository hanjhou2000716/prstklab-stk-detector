"""One output contract for major-event cards and watch-sized notifications."""

from __future__ import annotations

from typing import Any

from src.telegram_client import canonical_prstk_risk_level, canonical_short_message

SECTION_KEYS = ("event", "importance", "market_impact", "watch")
SECTION_LABELS = ("事件", "為何重要", "可能連動", "股市觀察")


def four_section_event(event: dict[str, Any]) -> dict[str, str]:
    """Return the four required sections with concise, non-empty fallbacks."""
    values = (
        event.get("event") or event.get("trigger") or event.get("summary") or event.get("title") or "公開事件更新。",
        event.get("importance_detail") or event.get("why_important") or "需以官方資料與後續價格核對重要性。",
        event.get("market_impact") or event.get("market_context") or "可能連動主要市場，暫不預設因果。",
        event.get("watch") or event.get("stock_observation") or "觀察後續公開報價與官方更新。",
    )
    return dict(zip(SECTION_KEYS, (" ".join(str(value).split()) for value in values), strict=True))


def short_event_message(event: dict[str, Any], *, prefix: str = "快訊") -> str:
    """Format one bounded, evidence-grounded investor-facing message."""
    raw_instrument = event.get("instrument")
    instrument = raw_instrument if isinstance(raw_instrument, dict) else {}
    ticker = str(instrument.get("ticker") or event.get("ticker") or "").strip()
    raw_type = str(event.get("notification_topic") or event.get("short_label") or event.get("event_type") or "市場事件").strip()
    topic_map = {
        "fed": "Fed", "fomc": "Fed", "central-bank": "Fed",
        "tariff": "關稅", "trade-policy": "關稅", "conflict": "地緣",
        "geopolitical": "地緣", "macro": "總經", "energy": "能源",
        "market_signal": ticker or "市場", "price": ticker or "市場",
    }
    topic = topic_map.get(raw_type.casefold(), raw_type)
    if topic in {"市場事件", "官方事件", "重大事件", "重要事件"} and ticker:
        topic = ticker
    is_price = str(event.get("kind") or "").casefold() == "market_signal"
    if is_price:
        summary = "｜".join(
            part for part in (
                str(event.get("market_direction") or "").strip(),
                str(event.get("market_move") or "").strip(),
                str(event.get("pattern") or "").strip(),
            ) if part
        )
    else:
        summary = str(next(
            (event.get(key) for key in ("brief_summary", "summary", "title", "event", "verified_fact", "brief_title")
         if str(event.get(key) or "").strip()),
            "",
        ) or "")
    summary = " ".join(str(summary).split())
    generic = {"市場觀察", "市場風險", "重大風險", "市場待核對", "資料待核對", "價格訊號"}
    if summary in generic:
        summary = ""
    move = str(event.get("market_move") or "").strip()
    if not move and instrument.get("change_percent") is not None:
        try:
            move = f"{float(instrument['change_percent']):+.1f}%"
        except (TypeError, ValueError):
            move = ""
    if not summary:
        direction = str(event.get("market_direction") or "").strip()
        summary = "｜".join(part for part in (direction, move) if part)
        if is_price and not summary:
            # A ticker alone is not an event fact.  Do not turn missing price
            # evidence into a misleading public notification.
            return ""
        summary = summary or "資訊待核對"
    if topic in {"Fed／貨幣政策", "Fed/貨幣政策"}:
        topic = "Fed"
    risk = canonical_prstk_risk_level(event)
    # ``prefix`` is intentionally ignored when it is the generic scheduler
    # wrapper; the message should answer what happened, not which job ran.
    context = "｜".join(part for part in (topic, summary) if part)
    formatted = canonical_short_message(context, prstk_risk_level=risk)
    # A topic label by itself is not an event.  When the full fact cannot fit
    # at a sentence boundary, fail closed instead of publishing a bare
    # ``Fed``/``能源`` label that looks like a notification.
    if summary and formatted and formatted[0] in "🟢🟡🟠🔴" and formatted[2:].strip() == topic and summary != topic:
        return ""
    return formatted
