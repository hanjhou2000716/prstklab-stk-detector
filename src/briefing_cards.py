"""Build slot-aware, educational briefing cards from the public snapshot."""

from __future__ import annotations

from typing import Any


SLOT_TITLES = {
    "morning": "投資晨報儀表板",
    "pre_open": "台股盤前儀表板",
    "intraday": "台股盤中儀表板",
    "midday": "台股午報儀表板",
    "afternoon": "台股午盤儀表板",
    "post_close": "台股盤後儀表板",
    "us_premarket": "美股盤前儀表板",
    "us_open": "美股開盤儀表板",
}

GLOBAL_TICKERS = ("TAIEX", "2330", "NIKKEI", "KOSPI", "NASDAQ", "SOX", "BRENT", "BTC", "ETH")


def _move(item: dict[str, Any] | None) -> str:
    """Format a quote movement without treating a missing value as a signal."""
    if not item or item.get("change_percent") is None:
        return "資料暫時無法取得"
    return f"{float(item['change_percent']):+.2f}%"


def _risk_line(risk: dict[str, Any] | None, market: str) -> str:
    """Format a public sentiment/VIX state without implying an action."""
    item = (risk or {}).get(market, {})
    sentiment = item.get("sentiment") or {}
    vix = item.get("vix") or {}
    sentiment_text = sentiment.get("label") or "資料暫時無法取得"
    score = sentiment.get("score")
    if score is not None:
        sentiment_text = f"{sentiment_text} {float(score):.1f}"
    vix_text = "VIX 資料暫時無法取得" if vix.get("value") is None else (
        f"VIX {float(vix['value']):.2f}" + (f"（{float(vix['change_percent']):+.2f}%）" if vix.get("change_percent") is not None else "")
    )
    return f"{sentiment_text}；{vix_text}。"


def _card(title: str, event: str, importance: str, market_impact: str, watch: str) -> dict[str, str]:
    return {
        "title": title,
        "event": event,
        "importance": importance,
        "market_impact": market_impact,
        "watch": watch,
    }


def _market_observations(
    items: dict[str, dict[str, Any]], risk: dict[str, Any] | None, events: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Build the five fixed, detailed public-observation cards for every slot."""
    taiwan = items.get("TAIEX")
    tpex = items.get("TPEx")
    tsmc = items.get("2330")
    nasdaq = items.get("NASDAQ")
    sox = items.get("SOX")
    nikkei = items.get("NIKKEI")
    kospi = items.get("KOSPI")
    dxy = items.get("DXY")
    us10y = items.get("US10Y")
    usd_twd = items.get("USD/TWD")
    primary_event = events[0] if events else {}
    event_title = primary_event.get("brief_title") or "今日無重大市場事件，持續觀察"
    event_text = primary_event.get("summary") or "本次未出現符合重大門檻的公開事件。"

    return [
        _card(
            "台股總經",
            f"台指 {_move(taiwan)}；櫃買 {_move(tpex)}。台股風險：{_risk_line(risk, 'taiwan')}",
            "加權與櫃買可用來分辨權值與中小型股的當日表現是否出現差異。",
            "台股盤勢仍須搭配權值、半導體與海外市場報價確認，不以單日變動推論原因。",
            "觀察台指、櫃買與台指期是否延續同向，以及成交量是否同步變化。",
        ),
        _card(
            "台積電／半導體",
            f"台積電 {_move(tsmc)}；費半 {_move(sox)}；Nasdaq {_move(nasdaq)}。",
            "台積電與費半是台美半導體權值的公開參考，能協助辨識單一市場或跨市場的差異。",
            "半導體行情可能連動台股電子權值與美國科技指數，實際傳導需由後續報價驗證。",
            "觀察費半、台積電與 Nasdaq 是否同步，及公開財報／展望是否帶來持續影響。",
        ),
        _card(
            "科技產業",
            f"Nasdaq {_move(nasdaq)}；費半 {_move(sox)}；日經225 {_move(nikkei)}；韓國綜合 {_move(kospi)}。",
            "美日韓科技指數提供 AI、半導體與出口型市場的跨區域公開觀察。",
            "跨市場可能不同步；只觀察是否出現可核對的同向擴散或明顯分歧。",
            "觀察美國科技收盤、日韓開收盤與台股電子權值的方向是否一致。",
        ),
        _card(
            "利率匯率",
            f"美元指數 {_move(dxy)}；美國10年債殖利率 {_move(us10y)}；美元兌台幣 {_move(usd_twd)}。",
            "美元、長債殖利率與匯率可反映資金與折現率的公開環境，並非單獨決定股市方向。",
            "利率與匯率變化可能影響成長股評價、外資流向與台股風險偏好，須搭配實際市場資料。",
            "觀察美元、殖利率與美元兌台幣是否持續同向，以及科技指數是否同步反應。",
        ),
        _card(
            "風險提醒",
            f"本次焦點：{event_title}。{event_text} 美股風險：{_risk_line(risk, 'us')}",
            primary_event.get("why_important") or primary_event.get("trigger") or "目前以最新公開報價、官方資料與重大事件門檻持續核對。",
            primary_event.get("market_context") or "沒有重大事件時，不將短期價格變動視為明確因果。",
            primary_event.get("stock_observation") or "觀察主要市場、能源與利率是否出現同步且持續的價格變化。",
        ),
    ]


def build_briefing_snapshot(snapshot: dict[str, Any], slot: str | None = None) -> dict[str, Any]:
    """Create one detailed card payload for the Mini App, without advice."""
    events = (snapshot.get("events") or {}).get("items", [])
    indices = snapshot.get("indices") or []
    quotes = snapshot.get("quotes") or []
    macro_quotes = snapshot.get("macro_quotes") or []
    risk = snapshot.get("risk") or {}
    all_items = {item.get("ticker"): item for item in [*indices, *quotes, *macro_quotes]}
    cards = [all_items[ticker] for ticker in GLOBAL_TICKERS if all_items.get(ticker)]
    observations = _market_observations(all_items, risk, events)
    lead = events[0] if events else observations[0]
    return {
        "slot": slot or "live",
        "title": SLOT_TITLES.get(slot or "", "即時市場儀表板"),
        "overview": (
            f"{lead.get('brief_title') or lead['title']}｜"
            f"{lead.get('summary') or lead['event']} "
            f"{lead.get('market_context') or lead['market_impact']}"
        ),
        "markets": cards,
        "observations": observations,
        "reminder": "僅供公開資訊整理與教育性觀察，不構成投資建議。",
    }
