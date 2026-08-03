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

# Legacy flat list retained for consumers that only need the principal
# benchmarks.  The Mini App uses ``market_topics`` below for the new grouped
# layout and can add event-related instruments separately.
GLOBAL_TICKERS = ("TAIEX", "2330", "NIKKEI", "KOSPI", "NASDAQ", "SOX", "BRENT", "WTI", "GOLD", "BTC", "ETH")


def _move(item: dict[str, Any] | None) -> str:
    """Format a quote movement without treating a missing value as a signal."""
    if not item or item.get("change_percent") is None:
        return "資料暫時無法取得"
    return f"{float(item['change_percent']):+.2f}%"


def _price_move(item: dict[str, Any] | None, name: str) -> str:
    """Format the observed price and daily move for an evidence line."""
    if not item or item.get("price") is None:
        return f"{name}資料暫時無法取得"
    currency = str(item.get("currency") or "").strip()
    suffix = f" {currency}" if currency and currency not in {"點", "TWD", "USD"} else (f" {currency}" if currency else "")
    return f"{name} {float(item['price']):,.2f}{suffix}（{_move(item)}）"


def _source_note(*items: dict[str, Any] | None) -> str:
    """Return a compact provenance line for a report card."""
    notes: list[str] = []
    for item in items:
        if not item:
            continue
        label = str(item.get("source_label") or item.get("quote_source") or item.get("source_domain") or "").strip()
        observed = str(item.get("quote_time") or item.get("quote_date") or "").strip()
        if label or observed:
            if "T" in observed:
                observed = observed.replace("T", " ")[:16]
            notes.append(" | ".join(part for part in (label, observed) if part))
    unique = list(dict.fromkeys(notes))
    return "資料來源：" + "；".join(unique[:2]) if unique else ""


def _technical_line(item: dict[str, Any] | None, name: str) -> str:
    """Describe recent range location; never turn it into trade advice."""
    context = (item or {}).get("technical_context") or {}
    if context.get("status") != "ok":
        return f"{name}近20日區間資料不足，暫不判定支撐／壓力位置。"
    days = int(context.get("window_days") or 20)
    low = float(context.get("low"))
    high = float(context.get("high"))
    long_low = context.get("long_low")
    long_high = context.get("long_high")
    position = float(context.get("position_pct"))
    zone = context.get("zone") or "位於20日區間中段"
    long_range = ""
    if long_low is not None and long_high is not None:
        long_days = int(context.get("long_window_days") or 60)
        long_range = f"；近{long_days}日 {float(long_low):,.2f}–{float(long_high):,.2f}"
    return f"{name}近{days}日區間 {low:,.2f}–{high:,.2f}{long_range}，目前{zone}（區間位置 {position:.0f}%）。"


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


def _card(title: str, event: str, importance: str, market_impact: str, watch: str, *, source_note: str = "") -> dict[str, str]:
    card = {
        "title": title,
        "event": event,
        "importance": importance,
        "market_impact": market_impact,
        "watch": watch,
    }
    if source_note:
        card["source_note"] = source_note
    return card


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
    """Build the six fixed, detailed public-observation cards for every slot."""
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
    wti = items.get("WTI") or items.get("BRENT")
    gold = items.get("GOLD")
    btc = items.get("BTC")
    eth = items.get("ETH")
    primary_event = events[0] if events else {}
    event_title = primary_event.get("brief_title") or "今日無重大市場事件，持續觀察"
    event_text = primary_event.get("summary") or "本次未出現符合重大門檻的公開事件。"
    event_market_context = str(primary_event.get("market_context") or "").strip()

    return [
        _card(
            "台股總經",
            f"{_price_move(taiwan, '台指')}；{_price_move(tpex, '櫃買指數')}。台股風險：{_risk_line(risk, 'taiwan')}",
            "加權指數代表大型權值股，櫃買指數較反映中小型股；同步代表盤面廣度較一致，分歧則要保留產業結構差異。",
            _pair_relation(taiwan, tpex, left_name="加權指數", right_name="櫃買指數"),
            f"技術觀察：{_technical_line(taiwan, '加權指數')} {_technical_line(tpex, '櫃買指數')} 後續核對台指期是否與現貨收斂、成交量是否放大。",
            source_note=_source_note(taiwan, tpex),
        ),
        _card(
            "台積電／半導體",
            f"{_price_move(tsmc, '台積電')}；{_price_move(sox, '費半')}；{_price_move(nasdaq, 'Nasdaq')}。",
            "台積電、費半與 Nasdaq 同向時，較支持半導體／成長股風險偏好的共同變化；若只有單一市場變動，不足以推論產業趨勢。",
            f"{_pair_relation(sox, tsmc, left_name='費半', right_name='台積電')} {event_market_context}".strip(),
            f"技術觀察：{_technical_line(tsmc, '台積電')} {_technical_line(sox, '費半')} 後續核對台積電、AI 供應鏈財報展望與費半是否延續。",
            source_note=_source_note(tsmc, sox, nasdaq),
        ),
        _card(
            "科技產業",
            f"{_price_move(nasdaq, 'Nasdaq')}；{_price_move(sox, '費半')}；{_price_move(nikkei, '日經225')}；{_price_move(kospi, '韓國綜合')}。",
            "美日韓科技市場同向時，較能反映區域風險偏好；若分歧，可能由匯率、產業權重或本地政策造成，不直接視為全球趨勢。",
            _pair_relation(nasdaq, kospi, left_name="Nasdaq", right_name="韓國綜合"),
            f"技術觀察：{_technical_line(nasdaq, 'Nasdaq')} { _technical_line(kospi, '韓國綜合')} 後續觀察日韓下一交易時段與台股電子權值是否延續或分歧。",
            source_note=_source_note(nasdaq, nikkei, kospi),
        ),
        _card(
            "利率／匯率／黃金能源",
            f"{_price_move(dxy, '美元指數')}；{_price_move(us10y, '美國10年債殖利率')}；{_price_move(usd_twd, '美元兌台幣')}；{_price_move(gold, '黃金')}；{_price_move(wti, '油價')}。",
            "利率、美元、黃金與能源共同反映通膨及避險需求；只有同時觀察方向與資料時間，才能分辨利率重估或單一商品波動。",
            _pair_relation(dxy, gold, left_name="美元指數", right_name="黃金"),
            "技術觀察：核對美元與黃金是否同向、油價是否突破近20日區間，並觀察科技指數與台股權值是否同步或分歧。",
            source_note=_source_note(dxy, us10y, usd_twd, gold, wti),
        ),
        _card(
            "加密市場",
            f"{_price_move(btc, 'BTC')}；{_price_move(eth, 'ETH')}。",
            "BTC／ETH 是高波動風險偏好的補充觀察；需搭配 Nasdaq、美元與流動性資料，不把單一幣價變動當成股市方向。",
            _pair_relation(btc, eth, left_name="BTC", right_name="ETH"),
            f"技術觀察：{_technical_line(btc, 'BTC')} {_technical_line(eth, 'ETH')} 後續核對兩者是否同步、波動是否放大，以及科技股是否同向。",
            source_note=_source_note(btc, eth),
        ),
        _card(
            "風險提醒",
            f"本次焦點：{event_title}。{event_text} 美股風險：{_risk_line(risk, 'us')}",
            primary_event.get("why_important") or primary_event.get("trigger") or "目前以最新公開報價、官方資料與重大事件門檻持續核對。",
            primary_event.get("market_context") or "沒有重大事件時，不將短期價格變動視為明確因果。",
            primary_event.get("stock_observation") or "觀察主要市場、能源與利率是否出現同步且持續的價格變化。",
            source_note=_source_note(primary_event),
        ),
    ]


def _placeholder(ticker: str, name: str, currency: str = "") -> dict[str, Any]:
    """Keep a fixed topic card visible when a public quote is unavailable."""
    return {"ticker": ticker, "name": name, "currency": currency, "price": None, "change_percent": None,
            "quote_basis": "公開資料暫時無法取得", "data_status": "unavailable"}


def _topic_quote(items: dict[str, dict[str, Any]], ticker: str, name: str, currency: str = "點") -> dict[str, Any]:
    return items.get(ticker) or _placeholder(ticker, name, currency)


def _market_topics(items: dict[str, dict[str, Any]], events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build four fixed two-instrument themes plus event-driven extras."""
    taiwan = _topic_quote(items, "TAIEX", "台股加權", "點")
    txf = _topic_quote(items, "TXF", "台指期", "點")
    ai_second = items.get("NVDA") or _topic_quote(items, "SOX", "半導體（費半）", "點")
    topics = [
        {"title": "臺灣總經", "items": [taiwan, txf]},
        {"title": "AI科技業", "items": [_topic_quote(items, "2330", "台積電", "TWD"), ai_second]},
        {"title": "亞洲相關", "items": [_topic_quote(items, "NIKKEI", "日經225", "點"), _topic_quote(items, "KOSPI", "韓國綜合", "點")]},
        {"title": "美股相關", "items": [_topic_quote(items, "NASDAQ", "Nasdaq", "點"), _topic_quote(items, "SOX", "費半", "點")]},
    ]
    fixed = {str(item.get("ticker")) for topic in topics for item in topic["items"]}
    event_text = " ".join(str(event.get(key) or "") for event in events for key in ("event_type", "short_label", "brief_title", "title" )).lower()
    dynamic_tickers = ("BTC", "ETH") if any(term in event_text for term in ("crypto", "加密", "btc", "eth")) else ()
    if any(term in event_text for term in ("oil", "energy", "能源", "原油", "gold", "黃金", "地緣")):
        dynamic_tickers += ("WTI", "BRENT", "GOLD")
    if any(term in event_text for term in ("fed", "利率", "通膨", "貨幣", "policy", "重大經濟")):
        dynamic_tickers += ("DXY", "US10Y", "USD/TWD")
    dynamic = []
    for ticker in dict.fromkeys(dynamic_tickers):
        if ticker in fixed or ticker not in items:
            continue
        dynamic.append(items[ticker] | {"topic": "事件相關"})
    return topics, dynamic


def build_briefing_snapshot(snapshot: dict[str, Any], slot: str | None = None) -> dict[str, Any]:
    """Create one detailed card payload for the Mini App, without advice."""
    events = (snapshot.get("events") or {}).get("items", [])
    indices = snapshot.get("indices") or []
    quotes = snapshot.get("quotes") or []
    macro_quotes = snapshot.get("macro_quotes") or []
    risk = snapshot.get("risk") or {}
    all_items = {item.get("ticker"): item for item in [*indices, *quotes, *macro_quotes] if item.get("ticker")}
    taiex = all_items.get("TAIEX") or {}
    taifex = (taiex.get("crosscheck_sources") or {}).get("taifex") if isinstance(taiex.get("crosscheck_sources"), dict) else None
    if isinstance(taifex, dict) and taifex.get("price") is not None:
        all_items["TXF"] = {**taifex, "ticker": "TXF", "name": "台指期", "market": "taiwan", "currency": "點"}
    cards = [all_items[ticker] for ticker in GLOBAL_TICKERS if all_items.get(ticker)]
    observations = _market_observations(all_items, risk, events)
    market_topics, dynamic_markets = _market_topics(all_items, events)
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
        "market_topics": market_topics,
        "dynamic_markets": dynamic_markets,
        "observations": observations,
        "reminder": "僅供公開資訊整理與教育性觀察，不構成投資建議。",
    }
