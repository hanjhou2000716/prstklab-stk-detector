"""Rule-based material-event and price-signal cards from public market data."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from src.finance_intel_policy import threshold_rule


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
    """Return two relevant, independently quoted cross-market references."""
    ticker = excluded_ticker.upper()
    preferred = {
        "TAIEX": ("SOX", "NASDAQ", "NIKKEI", "KOSPI"),
        "NASDAQ": ("SOX", "S&P 500", "TAIEX"),
        "SOX": ("NASDAQ", "TAIEX", "S&P 500"),
        "NIKKEI": ("KOSPI", "NASDAQ", "SOX"),
        "KOSPI": ("NIKKEI", "NASDAQ", "SOX"),
        "BRENT": ("GOLD", "WTI", "NASDAQ", "SOX"),
        "WTI": ("GOLD", "BRENT", "NASDAQ", "SOX"),
        "GOLD": ("WTI", "BRENT", "NASDAQ", "SOX"),
        "BTC": ("NASDAQ", "SOX", "TAIEX"),
        "ETH": ("NASDAQ", "SOX", "TAIEX"),
    }.get(ticker, ("NASDAQ", "SOX", "TAIEX", "S&P 500"))
    related: list[dict[str, Any]] = []
    for candidate in preferred:
        item = next((value for value in indices if value.get("ticker") == candidate), None)
        if item and item.get("ticker") != excluded_ticker and item.get("price") is not None:
            related.append(item)
    return related[:2]


def _signal_market_context(ticker: str) -> tuple[str, str]:
    """Return neutral transmission and equity-observation language per market."""
    contexts = {
        "TAIEX": (
            "可能連動費半、Nasdaq 與台指期；以後續同步報價確認，而非預設因果。",
            "觀察台股權值與電子類股是否與台指期、費半維持同方向。",
        ),
        "NASDAQ": (
            "可能連動費半、S&P 500 與下一交易日台股科技開盤；以同步報價確認。",
            "觀察美國成長股、半導體權值及台股科技開盤是否出現同步或分歧。",
        ),
        "SOX": (
            "可能連動 Nasdaq、台股半導體權值與亞洲科技指數；以同步報價確認。",
            "觀察半導體上下游、台積電與台股電子權值是否跟隨或出現背離。",
        ),
        "NIKKEI": (
            "可能連動韓股、Nasdaq 與亞洲科技權值；以各市場開收盤報價確認。",
            "觀察日本與韓國科技權值是否與美國半導體指數同向。",
        ),
        "KOSPI": (
            "可能連動日經、Nasdaq 與亞洲半導體供應鏈；以各市場報價確認。",
            "觀察韓國科技權值、日經與台股電子類股是否出現同步波動。",
        ),
        "BRENT": (
            "可能連動能源、航運、通膨預期與利率敏感類股；以油價與市場報價確認。",
            "觀察能源成本、通膨預期及全球股市風險偏好是否同時變化。",
        ),
        "WTI": (
            "可能連動能源、航運、通膨預期與利率敏感類股；以油價與市場報價確認。",
            "觀察能源成本、通膨預期及全球股市風險偏好是否同時變化。",
        ),
        "GOLD": (
            "可能連動避險需求、美元、利率預期與地緣風險；以後續公開報價確認。",
            "觀察黃金、油價、美元與主要股市是否同時出現可核對的風險偏好變化。",
        ),
        "BTC": (
            "可能反映高波動資產的風險偏好，並與 Nasdaq 等市場一併觀察；不預設因果。",
            "觀察 BTC、ETH 與科技股是否同向波動，留意流動性與波動是否擴大。",
        ),
        "ETH": (
            "可能反映高波動資產的風險偏好，並與 Nasdaq 等市場一併觀察；不預設因果。",
            "觀察 BTC、ETH 與科技股是否同向波動，留意流動性與波動是否擴大。",
        ),
    }
    return contexts.get(ticker, (
        "可能與其他主要市場同時波動；須以各自的公開報價確認，不能直接推論因果。",
        "觀察主要股市、利率與商品市場是否出現持續且同步的變化。",
    ))


def _signal_stage(percent: float, move_15m: float | None) -> str:
    """Classify a move for de-duplication without changing the public risk label."""
    magnitude = max(abs(percent), abs(move_15m or 0.0))
    if magnitude >= 4.0:
        return "極端"
    if magnitude >= 3.0:
        return "擴大"
    return "初始"


def _event_market_context(label: str) -> tuple[str, str, str]:
    """Translate a verified macro category into neutral market transmission context."""
    contexts = {
        "Fed／貨幣政策": (
            "利率預期可能影響美元、美債殖利率與成長股評價，因此需核對後續價格反應。",
            "可能連動 Nasdaq、費半、美元與美債；台股科技開盤反應應以實際報價確認。",
            "觀察利率預期變化後，科技與半導體權值是否同步或出現分歧。",
        ),
        "重大經濟數據": (
            "通膨與就業數據會影響市場對利率與景氣的預期，實際影響仍須由價格驗證。",
            "可能連動美元、美債、Nasdaq、費半與亞洲科技市場。",
            "觀察利率敏感的科技股與半導體指數是否持續反映相同方向。",
        ),
        "關稅／政策": (
            "政策訊號可能改變供應鏈、成本與需求預期，需區分公告內容與實際執行範圍。",
            "可能連動出口導向、半導體、Nasdaq、費半及台股科技權值。",
            "觀察費半、Nasdaq 與台股電子權值是否出現同步反應或明顯分歧。",
        ),
        "地緣衝突": (
            "地緣事件可能推升避險與能源風險溢酬，影響範圍及持續性應由後續公開資料確認。",
            "可能連動油價、黃金、美元、航運與全球股市風險偏好。",
            "觀察能源價格、科技指數與亞洲股市是否同時擴大波動。",
        ),
        "半導體財報": (
            "財報與展望可能改變 AI／半導體需求預期，但單一公司消息不代表整體產業。",
            "可能連動費半、Nasdaq、台積電與台股半導體權值。",
            "觀察費半與台美半導體權值是否以成交與價格同步確認趨勢。",
        ),
    }
    return contexts.get(label, (
        "此公開事件可能影響市場預期；應以後續可核對的價格與官方資訊確認。",
        "可能連動主要股市、利率或商品市場，實際傳導範圍仍待公開資料驗證。",
        "觀察主要市場是否出現持續、同步且可核對的價格變化。",
    ))


def _price_signal(index: dict[str, Any], indices: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Create an educational alert card for a material index move, never advice."""
    # A delayed intraday bar remains useful as an explicitly labelled quote,
    # but must not create an urgent notification from an out-of-date move.
    if index.get("quote_delayed"):
        return None
    # Taiwan intraday alerts have a higher evidence bar than a daily card:
    # TWSE's cash-index observation and TAIFEX TXF must be available and have
    # the same direction.  The Mini App may still display a partial quote, but
    # it must not become an urgent Telegram alert.
    if (
        index.get("ticker") == "TAIEX"
        and index.get("quote_time")
        and index.get("crosscheck_status")
        and index.get("crosscheck_status") != "已交叉核對"
    ):
        return None
    percent = index.get("change_percent")
    if percent is None:
        return None
    percent = float(percent)
    ticker = str(index.get("ticker", "市場"))
    minimum_daily_move = {
        "TAIEX": 1.5,
        "SOX": 3.0,
        "NASDAQ": 2.0,
        "WTI": float(threshold_rule("oilDailyAbsoluteMovePercent")),
        "BRENT": float(threshold_rule("oilDailyAbsoluteMovePercent")),
        "GOLD": float(threshold_rule("goldDailyAbsoluteMovePercent")),
    }.get(ticker, 1.0)
    minimum_15m_move = {
        "TAIEX": 1.0,
        "SOX": 1.0,
        "NASDAQ": 1.0,
        "WTI": 2.0,
        "BRENT": 2.0,
        "GOLD": 2.0,
    }.get(ticker, 1.0)
    move_15m = index.get("change_15m_percent")
    move_15m = float(move_15m) if move_15m is not None else None
    has_daily_move = abs(percent) >= minimum_daily_move
    has_15m_acceleration = move_15m is not None and abs(move_15m) >= minimum_15m_move
    if not has_daily_move and not has_15m_acceleration:
        return None

    market_context, stock_observation = _signal_market_context(ticker)
    if ticker == "TAIEX":
        label = "台指價格訊號觸發"
    elif ticker == "NASDAQ":
        label = "Nasdaq價格訊號觸發"
    elif ticker == "SOX":
        label = "費半價格訊號觸發"
    else:
        label = f"{ticker}價格訊號觸發"

    if move_15m is not None and move_15m >= minimum_15m_move and percent < 0:
        pattern, risk = "突然大漲", "警戒"
        stock_observation = "觀察反彈能否延續並與 Nasdaq、費半或台指同步；單一訊號僅供公開市場觀察。"
    elif move_15m is not None and move_15m <= -minimum_15m_move:
        pattern = "急跌"
        risk = "高風險" if abs(percent) >= 3.5 or abs(move_15m) >= 1.5 else "警戒"
    elif percent <= -2:
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
    intraday_text = f"｜15分鐘 {move_15m:+.2f}%" if move_15m is not None else ""
    change_text = f"{float(change):+,.2f}" if isinstance(change, (int, float)) else "資料暫缺"
    trigger = f"日內 {move}{intraday_text}｜點數 {change_text}｜最新 {price:,.2f}" if isinstance(price, (int, float)) else f"日內 {move}{intraday_text}"
    if pattern == "突然大漲":
        why_important = f"{trigger}。跌深後快速反彈代表短線風險偏好回升，仍需以後續連續報價確認。"
    elif has_15m_acceleration:
        why_important = f"{trigger}。15 分鐘內波動擴大，需留意是否持續並擴散至相關市場。"
    else:
        why_important = f"{trigger}。日內變動達固定觀察門檻，需以後續公開報價確認。"
    return {
        "kind": "market_signal",
        "short_label": label,
        "pattern": pattern,
        "risk_level": risk,
        "brief_title": f"{label}｜{pattern}｜{risk}",
        "title": f"{index.get('name', ticker)}日內變動 {move}",
        "summary": f"{index.get('name', ticker)} {price:,.2f}" if isinstance(price, (int, float)) else f"{index.get('name', ticker)} 公開報價更新",
        "trigger": trigger,
        "why_important": why_important,
        "market_context": market_context,
        "stock_observation": stock_observation,
        "friendly_reminder": "僅供公開資訊整理與教育性觀察，不構成投資建議。",
        "source": "公開市場報價",
        "url": "",
        "source_trace": {
            "verification": "公開市場報價",
            "source_label": "公開市場報價",
            "source_url": "",
            "source_domain": "",
            "event_time": str(index.get("quote_time") or index.get("quote_date") or ""),
            "checked_at": "",
            "verified_domains": [],
        },
        "instrument": index,
        "related": _related_indices(indices, ticker),
        "change": change,
        # Taiwan's broad-market alert is intentionally eligible for one
        # hourly update while a high-risk move persists.  A worsening stage
        # remains a separate signal and can be delivered immediately.
        "realert_interval_minutes": 60 if ticker == "TAIEX" and risk in {"高風險", "高波動"} else None,
        "signal_state": f"{pattern}:{risk}:{_signal_stage(percent, move_15m)}:{'up' if move_15m is not None and move_15m > 0 else 'down' if move_15m is not None and move_15m < 0 else 'daily'}",
    }


def _detail_event(event: dict[str, Any], indices: list[dict[str, Any]]) -> dict[str, Any]:
    """Give official or news events the same card fields as price signals."""
    label = str(event.get("short_label") or "市場事件")
    title = str(event.get("title") or "公開事件更新")
    why_important, market_context, stock_observation = _event_market_context(label)
    url = str(event.get("url") or "").strip()
    parsed = urlparse(url)
    domain = (parsed.hostname or "").lower().removeprefix("www.")
    released_at = str(event.get("released_at") or event.get("published_at") or "").strip()
    source = str(event.get("source") or "公開來源").strip()
    trace = {
        "verification": "一手官方來源" if event.get("relevance") == "official" or event.get("source_tier") == "official" else "公開來源待後續核對",
        "source_label": source,
        "source_url": url if parsed.scheme == "https" else "",
        "source_domain": domain,
        "event_time": released_at,
        "checked_at": str(event.get("checked_at") or ""),
        "verified_domains": [domain] if domain else [],
    }
    return {
        **event,
        "kind": event.get("kind") or "major_event",
        "pattern": event.get("pattern") or "重要事件",
        "risk_level": event.get("risk_level") or "持續觀察",
        "brief_title": event.get("brief_title") or f"{label}｜重要事件｜觀察",
        "summary": event.get("summary") or title,
        "trigger": event.get("trigger") or "已核對公開來源；請查看完整內容與市場後續反應。",
        "why_important": event.get("why_important") or why_important,
        "market_context": event.get("market_context") or market_context,
        "stock_observation": event.get("stock_observation") or stock_observation,
        "friendly_reminder": event.get("friendly_reminder") or "僅供公開資訊整理與教育性觀察，不構成投資建議。",
        "related": event.get("related") or _related_indices(indices, ""),
        "source_trace": trace,
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
            events.append(_detail_event(event, indices))
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
