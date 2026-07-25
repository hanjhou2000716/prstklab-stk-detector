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


def _observation(event: dict[str, Any]) -> dict[str, str]:
    """Turn one verified event into the consistent four-line card format."""
    return {
        "title": event.get("brief_title") or event.get("short_label") or "公開市場事件",
        "event": event.get("summary") or event.get("title") or "公開資料已更新。",
        "importance": event.get("trigger") or "已核對公開資料，請持續觀察。",
        "market_impact": event.get("market_context") or "不預設事件與價格變動具有因果關係。",
        "watch": "搭配下一次公開報價與原始來源，確認趨勢是否延續。",
    }


def _move(item: dict[str, Any] | None) -> str:
    """Format a quote movement without treating a missing value as a signal."""
    if not item or item.get("change_percent") is None:
        return "資料暫時無法取得"
    return f"{float(item['change_percent']):+.2f}%"


def _market_observations(items: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    """Add fact-only regional context to each scheduled briefing."""
    taiwan = items.get("TAIEX")
    tsmc = items.get("2330")
    nikkei = items.get("NIKKEI")
    kospi = items.get("KOSPI")
    brent = items.get("BRENT")
    btc = items.get("BTC")
    eth = items.get("ETH")
    cards = []
    if taiwan or tsmc:
        cards.append({
            "title": "台股總經／權值觀察",
            "event": f"台指 {_move(taiwan)}；台積電 {_move(tsmc)}。",
            "importance": "台指與權值股可用於觀察台股整體與半導體權重的當日變化。",
            "market_impact": "不將單日報價解讀為因果；同步對照費半與 Nasdaq 公開收盤。",
            "watch": "下一次台股報價、費半與 Nasdaq 是否出現同向且延續的變動。",
        })
    if nikkei or kospi:
        cards.append({
            "title": "亞洲市場｜日韓股市",
            "event": f"日經225 {_move(nikkei)}；韓國綜合 {_move(kospi)}。",
            "importance": "日韓股市提供亞洲科技與出口型市場的公開觀察參考。",
            "market_impact": "跨市場價格可能不同步，僅觀察是否出現同向擴散。",
            "watch": "下一個交易時段的日韓指數與台股權值股是否同步。",
        })
    if brent or btc or eth:
        cards.append({
            "title": "能源／加密｜公開風險偏好",
            "event": f"Brent {_move(brent)}；BTC {_move(btc)}；ETH {_move(eth)}。",
            "importance": "能源與高波動資產可作為通膨、風險偏好與流動性變化的輔助公開觀察。",
            "market_impact": "不以單一資產變動推論股市方向，僅追蹤後續是否持續。",
            "watch": "油價是否延續、加密資產是否與主要科技指數呈現同步變動。",
        })
    return cards


def build_briefing_snapshot(snapshot: dict[str, Any], slot: str | None = None) -> dict[str, Any]:
    """Create one detailed card payload for the Mini App, without advice."""
    events = (snapshot.get("events") or {}).get("items", [])
    indices = snapshot.get("indices") or []
    quotes = snapshot.get("quotes") or []
    all_items = {item.get("ticker"): item for item in [*indices, *quotes]}
    cards = [all_items[ticker] for ticker in GLOBAL_TICKERS if all_items.get(ticker)]

    observations = [_observation(event) for event in events[:2]]
    observations.extend(_market_observations(all_items))
    if not observations:
        observations = [{
            "title": "市場公開資料觀察",
            "event": "本次沒有符合門檻的重大市場事件或價格訊號。",
            "importance": "持續以最新公開報價與官方資料更新為準。",
            "market_impact": "不預設短期價格變動具有因果關係。",
            "watch": "觀察主要市場是否出現同步且持續的變動。",
        }]

    lead = observations[0]
    return {
        "slot": slot or "live",
        "title": SLOT_TITLES.get(slot or "", "即時市場儀表板"),
        "overview": f"{lead['title']}：{lead['event']} {lead['market_impact']}",
        "markets": cards,
        "observations": observations,
        "reminder": "僅供公開資訊整理與教育性觀察，不構成投資建議。",
    }
