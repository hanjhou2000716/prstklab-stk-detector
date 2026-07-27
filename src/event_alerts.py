"""Rule-based material-event and price-signal cards from public market data."""

from __future__ import annotations

import re
from typing import Any


EVENT_RULES = (
    ("Fed／貨幣政策", ("fomc", "fed", "聯準會", "升息", "降息")),
    ("重大經濟數據", ("cpi", "pce", "非農", "失業率", "就業報告")),
    ("關稅／政策", ("關稅", "出口管制", "制裁", "禁令", "政策")),
    ("地緣衝突", ("戰爭", "攻擊", "軍事", "入侵", "停火")),
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


def _related_indices(indices: list[dict[str, Any]], excluded_ticker: str) -> list[dict[str, Any]]:
    """Return a compact cross-market reference set for the alert card."""
    related: list[dict[str, Any]] = []
    for ticker in ("NASDAQ", "SOX", "S&P 500"):
        item = next((value for value in indices if value.get("ticker") == ticker), None)
        if item and item.get("ticker") != excluded_ticker and item.get("price") is not None:
            related.append(item)
    return related[:2]


def _price_signal(index: dict[str, Any], indices: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Create an educational alert card for a material index move, never advice."""
    # A delayed intraday bar remains useful as an explicitly labelled quote,
    # but must not create an urgent notification from an out-of-date move.
    if index.get("quote_delayed"):
        return None
    percent = index.get("change_percent")
    if percent is None:
        return None
    percent = float(percent)
    if abs(percent) < 1:
        return None

    ticker = str(index.get("ticker", "市場"))
    if ticker == "TAIEX":
        label = "台指價格訊號觸發"
        context = "台股科技／半導體權值走勢；同步觀察費半與 Nasdaq。"
    elif ticker == "NASDAQ":
        label = "Nasdaq價格訊號觸發"
        context = "美國成長股與半導體相關走勢；同步觀察費半與台股開盤反應。"
    elif ticker == "SOX":
        label = "費半價格訊號觸發"
        context = "半導體族群波動擴大；同步觀察 Nasdaq 與台股權值股。"
    else:
        label = f"{ticker}價格訊號觸發"
        context = "市場波動擴大，請搭配其他公開市場資料持續觀察。"

    if percent <= -2:
        pattern, risk = "急跌", "高風險"
    elif percent <= -1:
        pattern, risk = "急跌", "警戒"
    elif percent >= 2:
        pattern, risk = "急升", "高波動"
    else:
        pattern, risk = "上漲", "波動擴大"

    price = index.get("price")
    change = index.get("change")
    move = f"{percent:+.2f}%"
    trigger = f"日內變動 {move}，"
    trigger += "達 -2.0% 高風險門檻。" if percent <= -2 else (
        "達 -1.0% 警戒門檻。" if percent <= -1 else "波動達 1.0% 以上。"
    )
    return {
        "kind": "market_signal",
        "short_label": label,
        "pattern": pattern,
        "risk_level": risk,
        "brief_title": f"{label}｜{pattern}｜{risk}",
        "title": f"{index.get('name', ticker)}日內變動 {move}",
        "summary": f"{index.get('name', ticker)} {price:,.2f}" if isinstance(price, (int, float)) else f"{index.get('name', ticker)} 公開報價更新",
        "trigger": trigger,
        "market_context": context,
        "friendly_reminder": "僅供公開資訊整理與教育性觀察，不構成投資建議。",
        "source": "公開市場報價",
        "url": "",
        "instrument": index,
        "related": _related_indices(indices, ticker),
        "change": change,
    }


def _detail_event(event: dict[str, Any]) -> dict[str, Any]:
    """Give official or news events the same card fields as price signals."""
    label = str(event.get("short_label") or "市場事件")
    title = str(event.get("title") or "公開事件更新")
    return {
        **event,
        "kind": event.get("kind") or "major_event",
        "pattern": event.get("pattern") or "重要事件",
        "risk_level": event.get("risk_level") or "持續觀察",
        "brief_title": event.get("brief_title") or f"{label}｜重要事件｜觀察",
        "summary": event.get("summary") or title,
        "trigger": event.get("trigger") or "已核對公開來源；請查看完整內容與市場後續反應。",
        "market_context": event.get("market_context") or "不預設事件與市場走勢具有因果關係，持續觀察公開資訊。",
        "friendly_reminder": event.get("friendly_reminder") or "僅供公開資訊整理與教育性觀察，不構成投資建議。",
        "related": event.get("related") or [],
    }


def build_event_snapshot(
    news: dict[str, Any],
    quotes: list[dict[str, Any]],
    official: dict[str, Any] | None = None,
    indices: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Identify up to three material public events and make alert-card data."""
    indices = indices or []
    events: list[dict[str, Any]] = []
    seen: set[str] = set()

    def append(event: dict[str, Any], key: str) -> None:
        if key not in seen:
            events.append(_detail_event(event))
            seen.add(key)

    for event in (official or {}).get("items", []):
        append(event, event.get("url") or f"official:{event.get('title', '')}")

    # Some public index endpoints occasionally lag one market by several days.
    # A stale close must not create an urgent alert beside a current close.
    latest_dates = {
        market: max(
            (str(item.get("quote_date")) for item in indices if item.get("market") == market and item.get("quote_date")),
            default=None,
        )
        for market in {item.get("market") for item in indices}
    }
    fresh_indices = [
        item for item in indices
        if not item.get("quote_date") or item.get("quote_date") == latest_dates.get(item.get("market"))
    ]
    signals = [signal for item in fresh_indices if (signal := _price_signal(item, fresh_indices))]
    priority = {"TAIEX": 0, "SOX": 1, "NASDAQ": 2}
    signals.sort(key=lambda item: (
        priority.get(str(item["instrument"].get("ticker")), 9),
        -abs(float(item["instrument"].get("change_percent", 0))),
    ))
    for signal in signals:
        append(signal, f"signal:{signal['instrument'].get('ticker')}")

    for market in ("taiwan", "us"):
        for story in news.get(market, []):
            event = detect_major_event(story)
            if event:
                append(event, event.get("url") or f"news:{event.get('title', '')}")

    # A representative security is a fallback only; broad index moves take priority.
    for quote in quotes:
        if quote.get("change_percent") is not None and abs(float(quote["change_percent"])) >= 3:
            fallback = _price_signal({**quote, "name": quote.get("name", quote.get("ticker"))}, [])
            if fallback:
                append(fallback, f"signal:{quote.get('ticker')}")

    events = events[:3]
    if events:
        return {
            "is_major": True,
            "status": "市場訊號已更新",
            "message": "已核對的重要市場事件與價格訊號；請查看完整脈絡。",
            "items": events,
        }
    return {
        "is_major": False,
        "status": "持續觀察",
        "message": "今日無重大市場事件，持續觀察。",
        "items": [],
    }
