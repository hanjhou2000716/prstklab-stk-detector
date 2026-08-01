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

GLOBAL_TICKERS = ("TAIEX", "2330", "NIKKEI", "KOSPI", "NASDAQ", "SOX", "BRENT", "WTI", "GOLD", "BTC", "ETH")


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


def _direction(item: dict[str, Any] | None) -> str:
    """Return a neutral direction description only when a fresh change exists."""
    change = (item or {}).get("change_percent")
    if change is None:
        return "資料未完整"
    if float(change) > 0:
        return "上漲"
    if float(change) < 0:
        return "下跌"
    return "持平"


def _pair_relation(
    left: dict[str, Any] | None, right: dict[str, Any] | None, *, left_name: str, right_name: str,
) -> str:
    """Describe confirmation or divergence without claiming causality."""
    left_direction, right_direction = _direction(left), _direction(right)
    if "資料未完整" in {left_direction, right_direction}:
        return f"{left_name}或{right_name}資料未完整，暫不判定是否同步。"
    if left_direction == right_direction:
        return f"{left_name}與{right_name}同為{left_direction}，可作為同向價格確認。"
    if "持平" in {left_direction, right_direction}:
        return f"{left_name}與{right_name}未呈現一致方向，暫不視為同步訊號。"
    return f"{left_name}{left_direction}、{right_name}{right_direction}，呈現分歧，暫不推論跨市場因果。"


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
            "加權指數代表大型權值股，櫃買指數較反映中小型股；兩者同步或分歧可用來判讀盤面廣度。",
            _pair_relation(taiwan, tpex, left_name="加權指數", right_name="櫃買指數"),
            "觀察台指期是否與現貨收斂、成交量是否放大，以及權值股是否主導盤勢。",
        ),
        _card(
            "台積電／半導體",
            f"台積電 {_move(tsmc)}；費半 {_move(sox)}；Nasdaq {_move(nasdaq)}。",
            "台積電、費半與 Nasdaq 可交叉辨識台美半導體與成長股是否同向，而非只看單一公司或指數。",
            _pair_relation(sox, tsmc, left_name="費半", right_name="台積電"),
            "觀察費半是否延續至美股收盤，以及台積電、AI 供應鏈與公開財報展望是否出現一致方向。",
        ),
        _card(
            "科技產業",
            f"Nasdaq {_move(nasdaq)}；費半 {_move(sox)}；日經225 {_move(nikkei)}；韓國綜合 {_move(kospi)}。",
            "美日韓科技市場的同向變化，較能反映區域風險偏好；若分歧，需保留各市場本地因素的解釋空間。",
            _pair_relation(nasdaq, kospi, left_name="Nasdaq", right_name="韓國綜合"),
            "觀察日韓下一交易時段是否延續，以及台股電子權值是否跟隨或出現明顯分歧。",
        ),
        _card(
            "利率匯率",
            f"美元指數 {_move(dxy)}；美國10年債殖利率 {_move(us10y)}；美元兌台幣 {_move(usd_twd)}。",
            "美元與長債殖利率影響成長股折現率；美元兌台幣則是觀察台股外資風險偏好的公開輔助指標。",
            _pair_relation(dxy, us10y, left_name="美元指數", right_name="美國10年債殖利率"),
            "觀察美元、殖利率與台幣是否連續兩個交易時段同向，並核對科技指數是否同步受壓或走穩。",
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
