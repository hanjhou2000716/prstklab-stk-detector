"""Rule-based detection of material market events from fresh public headlines."""

from __future__ import annotations

import re
from typing import Any


EVENT_RULES = (
    ("Fed／貨幣政策", ("fomc", "fed", "聯準會", "升息", "降息")),
    ("重大經濟數據", ("cpi", "pce", "非農", "失業率", "就業報告")),
    ("關稅／政策", ("關稅", "出口管制", "制裁", "禁令", "政策")),
    ("地緣衝突", ("戰爭", "攻擊", "軍事", "入侵", "停火", "關稅")),
)
SEMICONDUCTOR_TERMS = ("台積電", "2330", "tsm", "nvidia", "nvda", "輝達")
EARNINGS_TERMS = ("財報", "法說", "展望", "財測", "營收")


def _clean_title(title: str) -> str:
    """Remove a source-page rank prefix while retaining the original headline."""
    return re.sub(r"^\s*\d+\.\s*", "", title).strip()


def detect_major_event(story: dict[str, str]) -> dict[str, str] | None:
    """Return a material-event record when a headline meets a fixed threshold."""
    title = _clean_title(story.get("title", ""))
    normalized = title.lower()
    for short_label, terms in EVENT_RULES:
        if any(term in normalized for term in terms):
            return {**story, "title": title, "short_label": short_label}
    if any(term in normalized for term in SEMICONDUCTOR_TERMS) and any(
        term in normalized for term in EARNINGS_TERMS
    ):
        return {**story, "title": title, "short_label": "半導體財報"}
    return None


def build_event_snapshot(news: dict[str, Any], quotes: list[dict[str, Any]]) -> dict[str, Any]:
    """Identify up to three qualifying events and a visible no-event conclusion."""
    events: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for market in ("taiwan", "us"):
        for story in news.get(market, []):
            event = detect_major_event(story)
            if event and event["url"] not in seen_urls:
                events.append(event)
                seen_urls.add(event["url"])
    volatility_events = [
        quote for quote in quotes
        if quote.get("change_percent") is not None and abs(float(quote["change_percent"])) >= 3
    ]
    for quote in volatility_events:
        events.append({
            "title": f"{quote['ticker']} 單日波動 {quote['change_percent']:+.1f}%",
            "url": "",
            "source": "公開市場報價",
            "short_label": "波動顯著",
        })
    events = events[:3]
    if events:
        return {
            "is_major": True,
            "status": "重大市場事件",
            "message": "符合重大事件門檻，請查看來源與完整市場脈絡。",
            "items": events,
        }
    return {
        "is_major": False,
        "status": "持續觀察",
        "message": "今日無重大市場事件，持續觀察。",
        "items": [],
    }
