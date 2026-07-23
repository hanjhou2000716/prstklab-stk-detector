"""Create neutral macro summaries strictly from the current public snapshot."""
from __future__ import annotations
from typing import Any

def build_macro_summary(events: dict[str, Any], risk: dict[str, Any]) -> dict[str, Any]:
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
    return {"notice": "僅整理本次公開資料的已知事實與風險觀察，不構成投資建議。", "items": items[:4]}
