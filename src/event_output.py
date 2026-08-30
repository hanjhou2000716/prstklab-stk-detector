"""One output contract for major-event cards and watch-sized notifications."""

from __future__ import annotations

from typing import Any

from src.telegram_client import canonical_prstk_risk_level

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
    """Format one bounded watch message using only the canonical R0-R4 grade."""
    label = str(event.get("short_label") or event.get("event_type") or "市場事件").strip()
    direction = str(event.get("market_direction") or "市場待核對").strip()
    move = str(event.get("market_move") or "變動待核對").strip()
    risk = canonical_prstk_risk_level(event)
    text = f"{prefix}｜{label}｜{direction}｜{move}｜{risk}"
    return text[:30].rstrip("｜ ")
