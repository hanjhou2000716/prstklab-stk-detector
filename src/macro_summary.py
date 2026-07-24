"""Create neutral macro summaries strictly from the current public snapshot."""
from __future__ import annotations
from typing import Any

def build_macro_summary(
    events: dict[str, Any], risk: dict[str, Any], program: dict[str, Any] | None = None
) -> dict[str, Any]:
    items = []
    if events.get("is_major"):
        for event in events.get("items", [])[:2]:
            items.append({"label": "事件", "text": f"{event['short_label']}：{event['title']}"})
    else:
        items.append({"label": "事件", "text": "今日無重大市場事件，持續觀察。"})
    for market in ("taiwan", "us"):
        item = risk.get(market, {})
        if market == "us" and item.get("sentiment"):
            text = f"美股情緒：{item['sentiment']['label']}"
        else:
            text = f"{item.get('label', '市場')}：{item.get('summary', '資料暫時無法取得')}"
        items.append({"label": "風險", "text": text})
    if program:
        items.append({
            "label": "節目更新",
            "text": program["title"],
            "url": program["url"],
            "source": program["source"],
            "published_at": program.get("published_at"),
        })
    else:
        items.append({"label": "節目更新", "text": "最新公開節目暫時無法取得。"})
    return {
        "notice": "僅整理本次公開資料的已知事實與風險觀察；節目僅提供公開標題與原始連結，不替代完整內容。",
        "items": items[:5],
    }
