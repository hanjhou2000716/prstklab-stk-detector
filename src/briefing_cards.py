"""Build slot-aware, educational briefing cards from the public snapshot."""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.briefing_narrative import NARRATIVE_VERSION, build_narrative
from src.market_scope import market_scope_for_slot, scope_snapshot

SLOT_TITLES = {
    "morning": "投資晨報儀表板",
    "pre_open": "台股盤前儀表板",
    "intraday": "台股盤中儀表板",
    "midday": "台股午盤儀表板",
    "afternoon": "台股收盤前儀表板",
    "post_close": "台股盤後儀表板",
    "us_premarket": "美股盤前儀表板",
    "us_open": "美股開盤儀表板",
}

# Legacy flat list retained for consumers that only need the principal
# benchmarks.  The Mini App uses ``market_topics`` below for the grouped
# layout and can add event-related instruments separately.
GLOBAL_TICKERS = ("TAIEX", "2330", "NIKKEI", "KOSPI", "NASDAQ", "SOX", "DJIA", "BRENT", "WTI", "GOLD", "BTC", "ETH")
SCOPED_TICKER_ORDER = {
    "taiwan": ("TAIEX", "TXF"),
    "us": ("S&P 500", "NASDAQ", "DJIA", "ES", "NQ", "YM", "SOX"),
}
_UNUSABLE_FRESHNESS = frozenset({"stale", "delayed", "unavailable", "unknown", "failed"})
_GENERIC_EVENT_CONTEXT = frozenset({
    "此公開事件可能影響市場預期",
    "可能連動主要股市、利率或商品市場",
    "觀察主要市場是否出現持續、同步且可核對的價格變化",
})
_MEDIA_CONTEXT_TAIL_RE = re.compile(
    r"\s*[-–—]\s*(?:Storm\.mg|Reuters|Bloomberg|Yahoo Finance|Yahoo股市|Yahoo新聞|Google News|CNBC|Financial Times|UDN|聯合新聞網|news\.cnyes\.com|鉅亨網|CMoney投資網誌|CMoney|財經焦點情報站)+\s*[。.!?]?\s*$",
    re.IGNORECASE,
)


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _usable_change(item: dict[str, Any] | None) -> float | None:
    """Return a change only when its quote is usable for regime evidence."""
    if not item or item.get("change_percent") in (None, ""):
        return None
    freshness = str(item.get("freshness") or item.get("data_status") or "live").lower()
    if freshness in _UNUSABLE_FRESHNESS or item.get("quote_delayed") is True:
        return None
    try:
        value = float(item["change_percent"])
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _regime_factors(items: dict[str, dict[str, Any]], risk: dict[str, Any]) -> dict[str, float | int | None]:
    """Build conservative factor evidence from timestamped public quotes.

    Missing factors are intentionally omitted; ``classify_regime`` exposes the
    resulting gaps instead of treating a single index move as a full regime.
    """
    factors: dict[str, float | int | None] = {}
    equity_tickers = ("TAIEX", "NASDAQ", "SOX", "DJIA", "NIKKEI", "KOSPI")
    equity_moves = [move for ticker in equity_tickers if (move := _usable_change(items.get(ticker))) is not None]
    if equity_moves:
        factors["trend"] = round(max(-2.0, min(2.0, sum(equity_moves) / len(equity_moves) / 2)), 3)
    if len(equity_moves) >= 3:
        breadth = sum(1 if move > 0 else -1 if move < 0 else 0 for move in equity_moves)
        factors["breadth"] = round(max(-2.0, min(2.0, breadth / len(equity_moves) * 2)), 3)
    vix_changes: list[float] = []
    for value in risk.values() if isinstance(risk, dict) else ():
        vix = value.get("vix") if isinstance(value, dict) else None
        move = _usable_change(vix if isinstance(vix, dict) else None)
        if move is not None:
            vix_changes.append(move)
    if vix_changes:
        factors["volatility"] = round(max(-2.0, min(2.0, -sum(vix_changes) / len(vix_changes) / 5)), 3)
    for factor, ticker, sign, divisor in (
        ("rates", "US10Y", -1, 1), ("usd", "DXY", -1, 1),
        ("gold", "GOLD", -1, 2), ("oil", "WTI", -1, 2),
    ):
        move = _usable_change(items.get(ticker))
        if move is not None:
            factors[factor] = round(max(-2.0, min(2.0, sign * move / divisor)), 3)
    crypto = [move for ticker in ("BTC", "ETH") if (move := _usable_change(items.get(ticker))) is not None]
    if crypto:
        factors["crypto"] = round(max(-2.0, min(2.0, sum(crypto) / len(crypto) / 2)), 3)
    return factors


def _contagion_inputs(items: dict[str, dict[str, Any]], risk: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map the public snapshot into the cross-asset monitor contract."""
    equities = items.get("TAIEX") or items.get("NASDAQ") or {}
    vix_items: list[dict[str, Any]] = [
        value["vix"] for value in risk.values()
        if isinstance(value, dict) and isinstance(value.get("vix"), dict)
    ]
    vix: dict[str, Any] = next(
        (item for item in vix_items if _usable_change(item) is not None),
        vix_items[0] if vix_items else {},
    )
    usd = items.get("DXY") or {}
    return {"equities": equities, "vix": vix, "usd": usd}


def _move(item: dict[str, Any] | None) -> str:
    """Format a quote movement without treating a missing value as a signal."""
    if not item or item.get("change_percent") is None:
        return "資料暫時無法取得"
    return f"{float(item['change_percent']):+.2f}%"


def _price_move(item: dict[str, Any] | None, name: str) -> str:
    """Format the observed price and daily move for an evidence line."""
    if not item:
        return f"{name}資料暫時無法取得"
    price = _finite_number(item.get("price"))
    change = _usable_change(item)
    if price is None or change is None:
        return f"{name}資料暫時無法取得"
    currency = str(item.get("currency") or "").strip()
    suffix = f" {currency}" if currency and currency not in {"點", "TWD", "USD"} else (f" {currency}" if currency else "")
    return f"{name} {price:,.2f}{suffix}（{change:+.2f}%）"


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


def _supporting_event_context(events: list[dict[str, Any]]) -> str:
    """Keep only specific context text for non-primary market cards."""
    for event in events:
        for key in ("market_context", "possible_linkage", "possible_impact"):
            value = str(event.get(key) or "").strip()
            if not value or any(marker in value for marker in _GENERIC_EVENT_CONTEXT):
                continue
            return _MEDIA_CONTEXT_TAIL_RE.sub("", value).strip()
    return ""


def _technical_line(item: dict[str, Any] | None, name: str) -> str:
    """Describe recent range location; never turn it into trade advice."""
    context = (item or {}).get("technical_context") or {}
    if context.get("status") != "ok":
        return f"{name}近20日區間資料不足，暫不判定支撐／壓力位置。"
    days = int(context.get("window_days") or 20)
    low = float(str(context.get("low")))
    high = float(str(context.get("high")))
    long_low = context.get("long_low")
    long_high = context.get("long_high")
    position = float(str(context.get("position_pct")))
    zone = context.get("zone") or "位於20日區間中段"
    as_of = str(context.get("as_of") or "").strip()
    long_range = ""
    if long_low is not None and long_high is not None:
        long_days = int(context.get("long_window_days") or 60)
        long_range = f"；近{long_days}日 {float(long_low):,.2f}–{float(long_high):,.2f}"
    as_of_text = f"，資料截至 {as_of}" if as_of else ""
    return f"{name}近{days}日區間 {low:,.2f}–{high:,.2f}{long_range}，目前{zone}（區間位置 {position:.0f}%）{as_of_text}。"


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
    change = _finite_number((item or {}).get("change_percent"))
    if change is None:
        return "資料未完整"
    if change > 0:
        return "上漲"
    if change < 0:
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


def _pair_observation(
    left: dict[str, Any] | None, right: dict[str, Any] | None, *, left_name: str, right_name: str,
) -> str:
    """Return a useful comparison only when at least one quote is valid."""
    left_valid = _usable_change(left) is not None
    right_valid = _usable_change(right) is not None
    if not left_valid and not right_valid:
        return ""
    if left_valid and not right_valid:
        return f"{left_name}方向可供核對。"
    if right_valid and not left_valid:
        return f"{right_name}方向可供核對。"
    return _pair_relation(left, right, left_name=left_name, right_name=right_name)


def _statistics_observation(statistics: dict[str, Any]) -> str:
    """Describe verified Taiwan statistics without repeating index quotes."""
    parts: list[str] = []
    turnover = statistics.get("turnover")
    if isinstance(turnover, dict) and not isinstance(turnover.get("trade_value"), bool):
        value = _finite_number(turnover.get("trade_value"))
        if value is not None:
            unit = str(turnover.get("unit") or turnover.get("currency") or "").strip()
            parts.append(f"成交值 {value:,.2f}{unit}")
    breadth = statistics.get("breadth")
    if isinstance(breadth, dict) and breadth.get("scope_verified") is True:
        values = [_finite_number(breadth.get(key)) for key in ("advancing", "declining")]
        if all(value is not None for value in values):
            text = f"上漲 {values[0]:.0f} 家、下跌 {values[1]:.0f} 家"
            unchanged = _finite_number(breadth.get("unchanged"))
            if unchanged is not None:
                text += f"、平盤 {unchanged:.0f} 家"
            parts.append(text)
    flows = statistics.get("institutional_flows")
    if isinstance(flows, dict) and not isinstance(flows.get("total_net"), bool):
        value = _finite_number(flows.get("total_net"))
        if value is not None:
            unit = str(flows.get("unit") or flows.get("currency") or "").strip()
            parts.append(f"三大法人合計淨額 {value:+,.2f}{unit}")
    return "；".join(parts)


def _narrative_detail(narrative: dict[str, Any], label: str) -> str:
    """Read a generated detail for legacy card fields without rendering it twice."""
    details = narrative.get("details")
    if not isinstance(details, list):
        return ""
    for detail in details:
        if isinstance(detail, dict) and str(detail.get("label") or "").strip() == label:
            return str(detail.get("text") or "").strip()
    return ""


def _market_observations(
    items: dict[str, dict[str, Any]], risk: dict[str, Any] | None, events: list[dict[str, Any]],
    *, primary_theme: dict[str, Any] | None = None,
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
    if primary_theme is not None:
        # The digest is the single public decision source.  Do not let this
        # legacy card reach back into ``events[0]``: that bypass used to
        # reintroduce unqualified publisher tails and unrelated news after
        # the first-screen summary had correctly become quote-led.
        theme_title = str(primary_theme.get("title") or "").strip()
        is_quote_led = theme_title == "市場價格"
        primary_event = {
            "brief_title": "行情主導" if is_quote_led else theme_title,
            "summary": primary_theme.get("what_happened") if not is_quote_led else "",
            "why_important": primary_theme.get("why_important"),
            "market_context": primary_theme.get("market_implication"),
            "stock_observation": primary_theme.get("stock_observation"),
            "source_evidence": primary_theme.get("source_evidence") or [],
        }
        event_title = str(primary_event.get("brief_title") or "行情主導")
        event_text = str(primary_event.get("summary") or "")
        if is_quote_led:
            event_text = str(primary_theme.get("what_happened") or "本輪行情證據已載入。")
        event_market_context = str(primary_event.get("market_context") or "").strip()
        if is_quote_led:
            # A quote-led report may still use a specific, non-primary event
            # explanation in the semiconductor card.  It must never replace
            # the quote-led risk card or carry a raw headline/publisher tail.
            event_market_context = _supporting_event_context(events) or event_market_context
    else:
        primary_event = events[0] if events else {}
        event_title = str(primary_event.get("brief_title") or "今日無重大市場事件，持續觀察")
        event_text = str(primary_event.get("summary") or "本次未出現符合重大門檻的公開事件。")
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
            str(primary_event.get("why_important") or primary_event.get("trigger") or "目前以最新公開報價、官方資料與重大事件門檻持續核對。"),
            str(primary_event.get("market_context") or "沒有重大事件時，不將短期價格變動視為明確因果。"),
            str(primary_event.get("stock_observation") or "觀察主要市場、能源與利率是否出現同步且持續的價格變化。"),
            source_note=_source_note(primary_event),
        ),
    ]


def _quote_gap(item: dict[str, Any] | None, ticker: str, name: str) -> dict[str, Any]:
    """Describe an omitted quote without exposing a public placeholder line."""
    if not item:
        reason = "quote_missing"
        data_status = "unavailable"
    else:
        price = _finite_number(item.get("price"))
        change_raw = item.get("change_percent")
        if price is None:
            reason = "invalid_or_missing_price"
        elif change_raw in (None, ""):
            reason = "missing_change_percent"
        elif item.get("quote_delayed") is True:
            reason = "quote_delayed"
        elif str(item.get("freshness") or item.get("data_status") or "live").lower() in _UNUSABLE_FRESHNESS:
            reason = "quote_unusable_freshness"
        else:
            change = _finite_number(change_raw)
            reason = "invalid_or_missing_change_percent" if change is None else "quote_unavailable"
        data_status = str(item.get("data_status") or item.get("freshness") or "unavailable")
    return {
        "kind": "quote",
        "ticker": ticker,
        "name": name,
        "reason": reason,
        "data_status": data_status,
        "observed_at": (item or {}).get("quote_time") or (item or {}).get("quote_date"),
    }


def _morning_quote_evidence(item: dict[str, Any] | None, ticker: str, name: str) -> tuple[str | None, dict[str, Any] | None]:
    """Return one factual quote line and a bounded evidence projection."""
    if not item or _finite_number(item.get("price")) is None or _usable_change(item) is None:
        return None, None
    line = _price_move(item, name)
    evidence = {
        "ticker": item.get("ticker"),
        "name": item.get("name") or name,
        "price": item.get("price"),
        "change": item.get("change"),
        "change_percent": item.get("change_percent"),
        "currency": item.get("currency"),
        "freshness": item.get("freshness") or item.get("data_status"),
        "quote_date": item.get("quote_date") or item.get("quote_time"),
        "source": item.get("source_label") or item.get("quote_source") or item.get("source_domain"),
        "source_url": item.get("source_url"),
        "is_proxy": item.get("is_proxy"),
    }
    return line, {key: value for key, value in evidence.items() if value not in (None, "")}


def _morning_confidence(evidence_count: int, missing: bool = False) -> str:
    if evidence_count >= 2 and not missing:
        return "high"
    if evidence_count >= 1:
        return "medium"
    return "low"


def _briefing_summary_facts(
    digest: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build the compact, structured facts shown above the briefing cards."""
    assessment_value = digest.get("market_assessment")
    assessment: dict[str, Any] = assessment_value if isinstance(assessment_value, dict) else {}
    sections_value = assessment.get("summary_sections")
    sections: dict[str, Any] = sections_value if isinstance(sections_value, dict) else {}
    quote_evidence = [item for item in (digest.get("quote_evidence") or []) if isinstance(item, dict)]
    joint_value = assessment.get("joint_market_signal")
    joint: dict[str, Any] = joint_value if isinstance(joint_value, dict) else {}
    joint_evidence_value = joint.get("evidence")
    joint_evidence_groups = joint_evidence_value if isinstance(joint_evidence_value, dict) else {}
    joint_evidence = [
        item for rows in joint_evidence_groups.values() if isinstance(rows, list)
        for item in rows if isinstance(item, dict)
    ]
    scope = str(assessment.get("market_scope_key") or "")
    if scope in {"taiwan", "us"}:
        label = "台股市場狀態" if scope == "taiwan" else "美股市場狀態"
        value = str(sections.get("summary") or "資料不足，暫不判讀").strip()
        status_evidence = quote_evidence[:4]
    else:
        label = "台美市場狀態"
        value = str(joint.get("label") or "資料不足，台美狀態待確認").strip()
        status_evidence = joint_evidence[:4] or quote_evidence[:4]
    facts: list[dict[str, Any]] = [
        {
            "key": "market_status",
            "label": label,
            "value": value,
            "evidence_refs": status_evidence,
        },
    ]
    highlights = str(sections.get("market_highlights") or "").strip() or "本輪未取得可核對行情比較。"
    facts.append({
        "key": "quote_comparison",
        "label": "行情比較",
        "value": highlights,
        "evidence_refs": quote_evidence[:3],
    })
    return facts


def _morning_analysis(
    items: dict[str, dict[str, Any]],
    risk: dict[str, Any],
    assessment: dict[str, Any],
    themes: list[dict[str, Any]],
    as_of: Any,
    slot: str,
    taiwan_market_statistics: dict[str, Any] | None = None,
    markets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the four evidence-driven morning sections.

    This is a projection of the existing quote, risk, event and digest data;
    unavailable quote factors are retained as structured system-analysis gaps,
    not public placeholder facts.
    """
    quote_specs = {
        "TAIEX": ("加權指數", "TAIEX"),
        "TPEx": ("櫃買指數", "TPEx"),
        "2330": ("台積電", "2330"),
        "SOX": ("費半", "SOX"),
        "NASDAQ": ("Nasdaq", "NASDAQ"),
        "NIKKEI": ("日經225", "NIKKEI"),
        "KOSPI": ("韓國綜合", "KOSPI"),
        "US10Y": ("美國10年債殖利率", "US10Y"),
        "DXY": ("美元指數", "DXY"),
        "USD/TWD": ("美元兌台幣", "USD/TWD"),
        "WTI": ("WTI油價", "WTI"),
        "BRENT": ("Brent油價", "BRENT"),
        "GOLD": ("黃金", "GOLD"),
    }

    def quote(ticker: str) -> tuple[str | None, dict[str, Any] | None]:
        name, _ = quote_specs[ticker]
        item = items.get(ticker)
        if ticker == "TPEx":
            item = item or items.get("TPEX")
        return _morning_quote_evidence(item, ticker, name)

    def structured_facts(
        facts: list[str], quote_facts: list[tuple[str, dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """Keep quote direction structured so the UI never guesses by regex."""
        by_text = {text: evidence for text, evidence in quote_facts}
        return [
            {"text": text, **({"quote": by_text[text]} if text in by_text else {})}
            for text in facts
        ]

    def section(
        title: str,
        facts: list[str],
        why: str,
        transmission: str,
        observation: str,
        next_catalyst: str,
        evidence: list[dict[str, Any]],
        *,
        missing: bool = False,
        freshness: str = "本輪資料",
        quote_facts: list[tuple[str, dict[str, Any]]] | None = None,
        narrative: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "title": title,
            "facts": facts,
            "facts_structured": structured_facts(facts, quote_facts or []),
            "why_it_matters": why,
            "transmission": transmission,
            "market_observation": observation,
            "next_catalyst": next_catalyst,
            "evidence": evidence,
            "freshness": freshness,
            "confidence": _morning_confidence(len(evidence), missing),
        }
        if narrative is not None:
            # Additive contract: legacy consumers continue to receive the
            # original fields while new renderers use one shared narrative.
            result["narrative"] = narrative
            result["highlights"] = narrative.get("highlights", [])
            result["details"] = narrative.get("details", [])
            result["limitations"] = narrative.get("limitations", [])
        return result

    quote_gaps: list[dict[str, Any]] = []
    taiwan_lines: list[str] = []
    taiwan_quote_facts: list[tuple[str, dict[str, Any]]] = []
    taiwan_evidence: list[dict[str, Any]] = []
    for ticker in ("TAIEX", "TPEx"):
        line, evidence = quote(ticker)
        if evidence:
            assert line is not None
            taiwan_lines.append(line)
            taiwan_quote_facts.append((line, evidence))
            taiwan_evidence.append(evidence)
        else:
            name, _ = quote_specs[ticker]
            item = items.get(ticker)
            if ticker == "TPEx":
                item = item or items.get("TPEX")
            gap = _quote_gap(item, ticker, name)
            gap["checked_at"] = as_of
            quote_gaps.append(gap)
    taipei = None
    try:
        taipei = datetime.fromisoformat(str(as_of).replace("Z", "+00:00")).astimezone(ZoneInfo("Asia/Taipei"))
    except (TypeError, ValueError, OverflowError):
        pass
    taiwan_slots = {"morning", "pre_open", "intraday", "midday", "afternoon", "post_close"}
    taiwan_status = markets.get("taiwan") if isinstance(markets, dict) else None
    us_status = markets.get("us") if isinstance(markets, dict) else None
    taiwan_closed = isinstance(taiwan_status, dict) and taiwan_status.get("is_trading_day") is False
    us_closed = isinstance(us_status, dict) and us_status.get("is_trading_day") is False
    market_session_state = "本輪市場時段"
    if taipei is not None:
        if slot in taiwan_slots and (taipei.weekday() >= 5 or taiwan_closed):
            market_session_state = "台股休市，使用最近收盤資料"
        elif slot in taiwan_slots:
            market_session_state = "台股交易時段／最近收盤資料"
        elif slot in {"us_premarket", "us_open"} and us_closed:
            market_session_state = "美股休市，使用最近收盤資料"
        elif slot in {"us_premarket", "us_open"}:
            market_session_state = "美股交易時段／最近收盤資料"
    taiwan_facts = list(taiwan_lines)
    statistics = taiwan_market_statistics if isinstance(taiwan_market_statistics, dict) else {}
    statistics_missing: list[str] = []
    turnover = statistics.get("turnover") if isinstance(statistics.get("turnover"), dict) else None
    breadth = statistics.get("breadth") if isinstance(statistics.get("breadth"), dict) else None
    institution = statistics.get("institutional_flows") if isinstance(statistics.get("institutional_flows"), dict) else None
    if turnover and turnover.get("trade_value") is not None:
        taiwan_evidence.append({"kind": "turnover", **turnover})
    else:
        statistics_missing.append("成交值")
    if (
        breadth and breadth.get("scope_verified") is True
        and breadth.get("advancing") is not None and breadth.get("declining") is not None
    ):
        taiwan_evidence.append({"kind": "breadth", **breadth})
    else:
        statistics_missing.append(
            "市場廣度（統計範圍未確認）" if breadth else "市場廣度"
        )
    if institution and institution.get("total_net") is not None:
        taiwan_evidence.append({"kind": "institutional_flows", **institution})
    else:
        statistics_missing.append("三大法人")
    semiconductor_lines: list[str] = []
    semiconductor_quote_facts: list[tuple[str, dict[str, Any]]] = []
    semiconductor_evidence: list[dict[str, Any]] = []
    for ticker in ("2330", "SOX", "NASDAQ"):
        line, evidence = quote(ticker)
        if evidence:
            assert line is not None
            semiconductor_lines.append(line)
            semiconductor_quote_facts.append((line, evidence))
            semiconductor_evidence.append(evidence)
        else:
            name, _ = quote_specs[ticker]
            gap = _quote_gap(items.get(ticker), ticker, name)
            gap["checked_at"] = as_of
            quote_gaps.append(gap)
    primary_theme = themes[0] if themes and isinstance(themes[0], dict) else {}
    macro_lines: list[str] = []
    macro_quote_facts: list[tuple[str, dict[str, Any]]] = []
    macro_evidence: list[dict[str, Any]] = []
    for ticker in ("US10Y", "DXY", "USD/TWD"):
        line, evidence = quote(ticker)
        if evidence:
            assert line is not None
            macro_lines.append(line)
            macro_quote_facts.append((line, evidence))
            macro_evidence.append(evidence)
        else:
            name, _ = quote_specs[ticker]
            gap = _quote_gap(items.get(ticker), ticker, name)
            gap["checked_at"] = as_of
            quote_gaps.append(gap)
    commodity_lines: list[str] = []
    commodity_quote_facts: list[tuple[str, dict[str, Any]]] = []
    commodity_evidence: list[dict[str, Any]] = []
    for ticker in ("WTI", "BRENT", "GOLD"):
        line, evidence = quote(ticker)
        if evidence:
            assert line is not None
            commodity_lines.append(line)
            commodity_quote_facts.append((line, evidence))
            commodity_evidence.append(evidence)
        else:
            name, _ = quote_specs[ticker]
            gap = _quote_gap(items.get(ticker), ticker, name)
            gap["checked_at"] = as_of
            quote_gaps.append(gap)
    external_lines = [*macro_lines, *commodity_lines]
    external_evidence = [*macro_evidence, *commodity_evidence]

    confidence = str(assessment.get("confidence") or "low")
    market_highlights = str((assessment.get("summary_sections") or {}).get("market_highlights") or "").strip()
    dominant_driver = str(assessment.get("dominant_driver") or "市場主因仍待價格確認")
    joint_value = assessment.get("joint_market_signal")
    joint: dict[str, Any] = joint_value if isinstance(joint_value, dict) else {}
    joint_label = str(joint.get("label") or "資料不足，台美狀態待確認").strip()
    event_evidence = [
        item for item in (primary_theme.get("source_evidence") or primary_theme.get("evidence") or [])
        if isinstance(item, dict)
    ][:3]
    risk_facts = [joint_label, market_highlights or "本輪未取得可核對行情比較。"]
    all_risk_evidence = [*event_evidence, *semiconductor_evidence[:1], *taiwan_evidence[:1]]
    gap_names = {
        str(gap.get("ticker")): str(gap.get("name") or gap.get("ticker") or "資料")
        for gap in quote_gaps
    }
    narratives = {
        "risk": build_narrative(
            slot=slot,
            section="risk",
            as_of=as_of,
            facts=risk_facts,
            quote_evidence=[*semiconductor_evidence[:1], *taiwan_evidence[:1], *macro_evidence[:1]],
            themes=themes,
            assessment=assessment,
            limitations=[gap_names[key] for key in gap_names],
        ),
        "taiwan": build_narrative(
            slot=slot,
            section="taiwan",
            as_of=as_of,
            facts=taiwan_lines,
            quote_evidence=taiwan_evidence,
            themes=themes,
            assessment=assessment,
            statistics=statistics,
            limitations=[*statistics_missing, *[gap_names[key] for key in ("TAIEX", "TPEx") if key in gap_names]],
        ),
        "semiconductor": build_narrative(
            slot=slot,
            section="semiconductor",
            as_of=as_of,
            facts=semiconductor_lines,
            quote_evidence=semiconductor_evidence,
            themes=themes,
            assessment=assessment,
            limitations=[gap_names[key] for key in ("2330", "SOX", "NASDAQ") if key in gap_names],
        ),
        "external": build_narrative(
            slot=slot,
            section="external",
            as_of=as_of,
            facts=external_lines,
            quote_evidence=external_evidence,
            themes=themes,
            assessment=assessment,
            limitations=[gap_names[key] for key in ("US10Y", "DXY", "USD/TWD", "WTI", "BRENT", "GOLD") if key in gap_names],
        ),
    }
    risk_observation = ""
    if all_risk_evidence:
        if "分歧" in joint_label or assessment.get("conflict_flags"):
            risk_observation = "台美價格方向分歧，暫不推論跨市場因果。"
        elif len(all_risk_evidence) >= 2:
            risk_observation = "台美價格方向可作為初步確認，等待事件與下一個同口徑收盤。"
        else:
            risk_observation = "目前只有部分價格證據，等待另一個獨立面向確認。"
    taiwan_observation = "；".join(
        value for value in (
            _pair_observation(
                items.get("TAIEX"),
                items.get("TPEx") or items.get("TPEX"),
                left_name="加權指數",
                right_name="櫃買指數",
            ),
            _statistics_observation(statistics),
        ) if value
    )
    semiconductor_observation = _pair_observation(
        items.get("SOX"), items.get("2330"), left_name="費半", right_name="台積電",
    ) or _pair_observation(
        items.get("NASDAQ"), items.get("SOX"), left_name="Nasdaq", right_name="費半",
    )
    external_observation = _pair_observation(
        items.get("DXY"), items.get("GOLD"), left_name="美元指數", right_name="黃金",
    ) or _pair_observation(
        items.get("US10Y"), items.get("USD/TWD"), left_name="美國10年債殖利率", right_name="美元兌台幣",
    )
    risk_why = _narrative_detail(narratives["risk"], "為何重要") or "新聞只用於說明關注主因；市場方向仍須由至少兩個獨立價格面向核對。"
    risk_transmission = _narrative_detail(narratives["risk"], "可能傳導") or f"{dominant_driver}；行情與事件若未同步，維持待確認，不推論因果。"
    risk_next = _narrative_detail(narratives["risk"], "下一項催化劑") or "等待下一個同口徑收盤或官方資料核對。"
    taiwan_why = _narrative_detail(narratives["taiwan"], "為何重要") or "加權與櫃買可分辨權值股與中小型股是否同向。"
    taiwan_transmission = _narrative_detail(narratives["taiwan"], "可能傳導") or "台股盤面需與美元兌台幣及外圍科技股交叉觀察。"
    taiwan_next = "等待下一次可核對的官方成交、廣度與法人資料。" if statistics_missing else (
        _narrative_detail(narratives["taiwan"], "下一項催化劑") or "等待下一次同口徑台股盤面資料核對。"
    )
    semiconductor_why = _narrative_detail(narratives["semiconductor"], "為何重要") or "台積電、費半與 Nasdaq 的相對方向可交叉確認科技風險偏好。"
    semiconductor_transmission = _narrative_detail(narratives["semiconductor"], "可能傳導") or "方向不一致時保留分歧，題材不能取代價格確認。"
    semiconductor_next = _narrative_detail(narratives["semiconductor"], "下一項催化劑") or "等待下一次科技股收盤或公司公告核對。"
    external_why = _narrative_detail(narratives["external"], "為何重要") or "利率、美元、能源與黃金提供估值、通膨及避險背景。"
    external_transmission = _narrative_detail(narratives["external"], "可能傳導") or "只有在價格與資料時間一致時，才形成外部風險傳導觀察。"
    external_next = _narrative_detail(narratives["external"], "下一項催化劑") or "等待下一次可核對的總經或政策資料。"
    sections = [
        section(
            "今日風險判讀",
            risk_facts,
            risk_why,
            risk_transmission,
            risk_observation,
            risk_next,
            all_risk_evidence,
            missing=len(all_risk_evidence) < 2,
            quote_facts=semiconductor_quote_facts[:1] + macro_quote_facts[:1],
            narrative=narratives["risk"],
        ),
        section(
            "台股總經與盤面",
            taiwan_facts,
            taiwan_why,
            taiwan_transmission,
            taiwan_observation,
            taiwan_next,
            taiwan_evidence,
            missing=bool(statistics_missing) or len(taiwan_evidence) < 2,
            quote_facts=taiwan_quote_facts,
            narrative=narratives["taiwan"],
        ),
        section(
            "台積電／半導體與 AI",
            semiconductor_lines,
            semiconductor_why,
            semiconductor_transmission,
            semiconductor_observation,
            semiconductor_next,
            semiconductor_evidence,
            missing=len(semiconductor_evidence) < 2,
            quote_facts=semiconductor_quote_facts,
            narrative=narratives["semiconductor"],
        ),
        section(
            "利率、匯率與外部風險",
            external_lines,
            external_why,
            external_transmission,
            external_observation,
            external_next,
            external_evidence,
            missing=len(external_evidence) < 2,
            quote_facts=macro_quote_facts + commodity_quote_facts,
            narrative=narratives["external"],
        ),
    ]
    return {
        "ruleset": "morning_analysis_evidence_v4",
        "narrative_version": NARRATIVE_VERSION,
        "evidence_as_of": as_of,
        # Kept as an additive field for old readers, but blank for current
        # releases so the UI cannot render a meaningless meta strip.  Real
        # closed-market information remains a fact in the Taiwan section.
        "market_session_state": "",
        "overall_stance": assessment.get("stance") or "divergent",
        "confidence": confidence,
        "sections": sections,
        "missing_evidence": [
            *dict.fromkeys(statistics_missing),
            *[gap["name"] for gap in quote_gaps],
            "下一項已知總經或政策催化劑",
        ],
        "system_analysis": {
            "data_gaps": [
                {"kind": "statistics", "name": name, "reason": "not_available_this_round", "checked_at": as_of}
                for name in dict.fromkeys(statistics_missing)
            ] + list({
                str(gap.get("ticker")): gap for gap in quote_gaps
            }.values()),
            "note": "公開卡片只呈現已核對事實；資料缺口保留於系統分析資料。",
            "market_session_state": market_session_state if "休市" in market_session_state else None,
            "joint_market_signal": {
                "status": joint.get("status"),
                "label": joint_label,
                "confidence": joint.get("confidence"),
                "valid_factor_count": joint.get("valid_factor_count"),
                "risk_adjustments": joint.get("risk_adjustments", []),
                "excluded_factors": joint.get("excluded_factors", []),
                "evidence": joint.get("evidence", {}),
            },
        },
        "source_health_notes": [
            "本分析只使用本輪已載入的公開行情、風險與合格事件。",
            "缺少的資料不以固定模板或推測補足。",
        ],
    }


def _placeholder(ticker: str, name: str, currency: str = "") -> dict[str, Any]:
    """Keep a fixed topic card visible when a public quote is unavailable."""
    return {"ticker": ticker, "name": name, "currency": currency, "price": None, "change_percent": None,
            "quote_basis": "公開資料暫時無法取得", "data_status": "unavailable"}


def _topic_quote(items: dict[str, dict[str, Any]], ticker: str, name: str, currency: str = "點") -> dict[str, Any]:
    return items.get(ticker) or _placeholder(ticker, name, currency)


def _market_topics(items: dict[str, dict[str, Any]], events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build fixed market themes plus event-driven extras."""
    events = events if isinstance(events, list) else []
    taiwan = _topic_quote(items, "TAIEX", "台股加權", "點")
    txf = _topic_quote(items, "TXF", "台指期", "點")
    ai_second = items.get("NVDA") or _topic_quote(items, "SOX", "半導體（費半）", "點")
    topics = [
        {"title": "臺灣總經", "items": [taiwan, txf]},
        {"title": "AI科技業", "items": [_topic_quote(items, "2330", "台積電", "TWD"), ai_second]},
        {"title": "亞洲相關", "items": [_topic_quote(items, "NIKKEI", "日經225", "點"), _topic_quote(items, "KOSPI", "韓國綜合", "點")]},
        {"title": "美股相關", "items": [_topic_quote(items, "NASDAQ", "Nasdaq", "點"), _topic_quote(items, "SOX", "費半", "點"), _topic_quote(items, "DJIA", "道瓊", "點")]},
    ]
    fixed = {
        str(item.get("ticker"))
        for topic in topics
        for item in topic["items"]
        if isinstance(item, dict)
    }
    event_text = " ".join(str(event.get(key) or "") for event in events for key in ("event_type", "short_label", "brief_title", "title" )).lower()
    dynamic_tickers: tuple[str, ...]
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


def _scoped_quote_detail(
    item: dict[str, Any] | None, ticker: str, name: str, *, scope: str,
) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    row = item if isinstance(item, dict) else {}
    price = _finite_number(row.get("price"))
    change = _finite_number(row.get("change_percent"))
    point_change = _finite_number(row.get("change"))
    observed = str(row.get("quote_time") or row.get("quote_date") or "").strip()
    freshness = str(row.get("freshness") or row.get("data_status") or "unknown")
    missing_reason = "quote_missing" if not row else "quote_unusable_or_time_unverified"
    if ticker == "TXF" and row and not str(row.get("contract_month") or "").strip():
        missing_reason = "official_contract_month_unverified"
    usable = (
        price is not None and change is not None and bool(observed)
        and freshness.casefold() not in _UNUSABLE_FRESHNESS
    )
    if scope == "taiwan" and ticker == "TXF" and missing_reason == "official_contract_month_unverified":
        usable = False
    if not usable:
        label = f"{name}資料未取得或口徑未核實"
        evidence = {
            "ticker": ticker,
            "name": name,
            "data_status": "unavailable",
            "quote_date": row.get("quote_date"),
            "quote_time": row.get("quote_time"),
            "source": row.get("source_label") or row.get("quote_source") or row.get("source"),
            "contract_month": row.get("contract_month"),
        }
        return label, evidence, {"ticker": ticker, "name": name, "reason": missing_reason}
    basis = str(row.get("quote_basis") or "").strip()
    contract_note = ""
    if ticker == "TXF":
        contract_note = f"，契約月份 {row['contract_month']}，日盤"
    elif ticker in {"ES", "NQ", "YM"}:
        contract_basis = str(row.get("contract_basis") or "continuous_contract")
        contract_note = "，連續合約，未標示特定到期月" if contract_basis == "continuous_contract" else f"，{contract_basis}"
    date_note = observed.replace("T", " ")[:19]
    point_note = f"漲跌 {point_change:+,.2f} 點；" if point_change is not None else "漲跌點數未提供；"
    quote_label = f"{name}{contract_note} 行情 {price:,.2f}；{point_note}{change:+.2f}%；觀測 {date_note}；{freshness}"
    if row.get("quote_delayed") is True:
        quote_label += "；來源延遲"
    if basis:
        quote_label += f"；{basis}"
    evidence = {
        key: row.get(key)
        for key in (
            "ticker", "name", "price", "change", "change_percent", "quote_date", "quote_time",
            "freshness", "data_status", "quote_basis", "quote_source", "source_label",
            "source_url", "session", "contract_month", "contract_basis", "quote_delayed",
            "backup_used", "official_fallback_used",
        )
        if row.get(key) not in (None, "")
    }
    return quote_label, evidence, None


def _scoped_morning_analysis(
    items: dict[str, dict[str, Any]], scope: str, as_of: Any, slot: str,
    taiwan_market_statistics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build only the market-specific explanations required for these slots."""
    specs = (
        [("TAIEX", "加權指數現貨"), ("TXF", "台指期近月日盤")]
        if scope == "taiwan" else
        [("S&P 500", "標普500現貨收盤"), ("NASDAQ", "Nasdaq Composite現貨收盤"),
         ("DJIA", "道瓊現貨收盤"), ("ES", "ES（S&P 500 E-mini 指數期貨）"),
         ("NQ", "NQ（Nasdaq-100 指數期貨，與 Nasdaq Composite 不同）"),
         ("YM", "YM（道瓊 E-mini 指數期貨）"), ("SOX", "費半最近收盤（輔助）")]
    )
    data_gaps: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    for ticker, name in specs:
        text, evidence, gap = _scoped_quote_detail(items.get(ticker), ticker, name, scope=scope)
        facts.append({"ticker": ticker, "name": name, "text": text, "quote": evidence})
        if gap:
            data_gaps.append({"kind": "quote", **gap, "checked_at": as_of})
    supplementary_section: dict[str, Any] | None = None
    supplementary_gaps: list[dict[str, Any]] = []
    market_card_projection: dict[str, Any] | None = None
    if scope == "taiwan":
        statistics = taiwan_market_statistics if isinstance(taiwan_market_statistics, dict) else {}
        turnover_value = statistics.get("turnover")
        breadth_value = statistics.get("breadth")
        institutions_value = statistics.get("institutional_flows")
        turnover: dict[str, Any] = turnover_value if isinstance(turnover_value, dict) else {}
        breadth: dict[str, Any] = breadth_value if isinstance(breadth_value, dict) else {}
        institutions: dict[str, Any] = institutions_value if isinstance(institutions_value, dict) else {}

        def amount_fact(
            label: str, record: dict[str, Any], value_key: str, *,
            source_default: str, source_url_default: str,
        ) -> tuple[str, dict[str, Any] | None]:
            value = _finite_number(record.get(value_key))
            if value is None:
                supplementary_gaps.append({"kind": "supplementary_statistic", "name": label, "reason": "not_published_or_not_obtained"})
                return f"{label}：尚未公布或本輪未取得；不延後簡報。", None
            # The TWSE endpoints report currency amounts in NT dollars. Show
            # the human-readable amount in hundred-million NT dollars while
            # retaining the raw source value and unit in structured evidence.
            amount = value / 100_000_000
            observed = str(record.get("observed_date") or "日期未提供")
            source = str(record.get("source") or source_default)
            source_url = str(record.get("source_url") or source_url_default)
            evidence = {
                **record,
                "raw_value": value,
                "raw_unit": str(record.get("unit") or "元"),
                "display_unit": "億元",
                "display_value": amount,
                "source": source,
                "source_url": source_url,
            }
            return f"{label} {amount:,.2f} 億元（{observed}）", evidence

        turnover_text, turnover_evidence = amount_fact(
            "上市市場成交金額", turnover, "trade_value",
            source_default="TWSE FMTQIK 官方每日市場成交資訊",
            source_url_default="https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK",
        )
        institution_text, institution_evidence = amount_fact(
            "三大法人合計買賣超", institutions, "total_net",
            source_default="TWSE BFI82U 官方三大法人買賣金額統計",
            source_url_default="https://www.twse.com.tw/rwd/zh/fund/BFI82U",
        )
        advancing = _finite_number(breadth.get("advancing"))
        declining = _finite_number(breadth.get("declining"))
        if breadth.get("scope_verified") is True and advancing is not None and declining is not None:
            unchanged = _finite_number(breadth.get("unchanged"))
            breadth_text = f"市場廣度：上漲 {advancing:.0f}／下跌 {declining:.0f}"
            if unchanged is not None:
                breadth_text += f"／平盤 {unchanged:.0f}"
            breadth_source = str(breadth.get("source") or "TWSE 官方上市市場漲跌家數統計")
            breadth_date = str(breadth.get("observed_date") or "日期未提供")
            breadth_text += f"（{breadth_date}）"
            breadth_evidence = {
                **breadth,
                "source": breadth_source,
                "source_url": str(breadth.get("source_url") or "https://openapi.twse.com.tw/v1/opendata/twtazu_od"),
            }
        else:
            breadth_text = "市場廣度：尚未公布或本輪未取得／統計範圍未核實；不延後簡報。"
            breadth_evidence = None
            supplementary_gaps.append({"kind": "supplementary_statistic", "name": "市場廣度", "reason": "not_published_not_obtained_or_scope_unverified"})
        stat_facts = [
            ("turnover", "成交金額", turnover_text, turnover_evidence),
            ("breadth", "市場廣度", breadth_text, breadth_evidence),
            ("institutions", "三大法人", institution_text, institution_evidence),
        ]
        supplementary_section = {
            "title": "台股輔助統計（官方）",
            "layout": "taiwan_stats_v2",
            "facts": [entry[2] for entry in stat_facts],
            "facts_structured": [
                {"ticker": f"TW_STATS_{key.upper()}", "name": name, "text": text, "quote": evidence or {}}
                for key, name, text, evidence in stat_facts
            ],
            "why_it_matters": "成交金額、漲跌家數與三大法人是盤面背景，不取代加權指數與台指期行情。",
            "transmission": "逐項標示資料日；缺漏就說明，不估算或延後簡報。",
            "market_observation": "；".join(entry[2] for entry in stat_facts),
            "next_catalyst": "後續資料更新只更新資訊卡，不因此對同一時段再次發送 Telegram。",
            "evidence": [entry[3] for entry in stat_facts if isinstance(entry[3], dict)],
            "freshness": "各統計欄逐項標示資料日與來源",
            "confidence": "low" if supplementary_gaps else "medium",
        }
        sections = [
            {
                "title": "台股加權指數（現貨）",
                "facts": [facts[0]["text"]], "facts_structured": [facts[0]],
                "why_it_matters": "加權指數描述台灣上市股票現貨市場，不等同於期貨契約。",
                "transmission": "現貨指數與期貨分列；不以期貨點位替代現貨，也不計算不同觀測時間的即時基差。",
                "market_observation": facts[0]["text"] if not any(g.get("ticker") == "TAIEX" for g in data_gaps) else "本輪加權指數資料缺漏。",
                "next_catalyst": "等待下一個可核對的台股現貨交易日收盤。",
                "evidence": [facts[0]["quote"]] if facts[0]["quote"].get("price") is not None else [],
                "freshness": facts[0]["quote"].get("freshness", "unavailable"),
                "confidence": "low" if any(g.get("ticker") == "TAIEX" for g in data_gaps) else "medium",
            },
            {
                "title": "台指期近月（日盤）",
                "facts": [facts[1]["text"]], "facts_structured": [facts[1]],
                "why_it_matters": "台指期是獨立的期貨契約；必須確認近月契約月份與日盤資料口徑。",
                "transmission": "僅說明期貨自身漲跌，不與不同收盤時間的加權指數計算即時基差。",
                "market_observation": facts[1]["text"] if not any(g.get("ticker") == "TXF" for g in data_gaps) else "近月契約月份或日盤行情未核實，故不列期貨方向。",
                "next_catalyst": "結算日後由官方契約月份切換規則確認近月；未核實月份時維持缺漏。",
                "evidence": [facts[1]["quote"]] if facts[1]["quote"].get("price") is not None else [],
                "freshness": facts[1]["quote"].get("freshness", "unavailable"),
                "confidence": "low" if any(g.get("ticker") == "TXF" for g in data_gaps) else "medium",
            },
            supplementary_section,
        ]
    else:
        sections = [
            {
                "title": "美股主要現貨最近收盤",
                "facts": [fact["text"] for fact in facts[:3]], "facts_structured": facts[:3],
                "why_it_matters": "標普500、Nasdaq Composite 與道瓊是三項分開標示的美股現貨基準。",
                "transmission": "現貨欄只採各指數最近已完成交易日；不以期貨替代現貨收盤。",
                "market_observation": "；".join(fact["text"] for fact in facts[:3]),
                "next_catalyst": "核對美股當日開盤後現貨走勢是否延續或背離盤前期貨。",
                "evidence": [fact["quote"] for fact in facts[:3] if fact["quote"].get("price") is not None],
                "freshness": "逐項標示觀測日期與資料狀態",
                "confidence": "low" if any(g.get("ticker") in {"S&P 500", "NASDAQ", "DJIA"} for g in data_gaps) else "medium",
            },
            {
                "title": "美股指數期貨盤前",
                "facts": [fact["text"] for fact in facts[3:6]], "facts_structured": facts[3:6],
                "why_it_matters": "ES、NQ、YM 分別對應標普500、Nasdaq-100、道瓊指數期貨；NQ 不是 Nasdaq Composite。",
                "transmission": "期貨按自身來源、觀測時間與連續／指定合約口徑呈現，不與現貨點位混算。",
                "market_observation": "；".join(fact["text"] for fact in facts[3:6]),
                "next_catalyst": "美股開盤時停止盤前通知；開盤後行情不回填為盤前即時資料。",
                "evidence": [fact["quote"] for fact in facts[3:6] if fact["quote"].get("price") is not None],
                "freshness": "逐項標示來源觀測時間、延遲與合約口徑",
                "confidence": "low" if any(g.get("ticker") in {"ES", "NQ", "YM"} for g in data_gaps) else "medium",
            },
            {
                "title": "費城半導體指數（輔助）",
                "facts": [facts[6]["text"]], "facts_structured": [facts[6]],
                "why_it_matters": "費半作為美國半導體產業背景，不替代三大現貨指數或指數期貨。",
                "transmission": "只作為獨立輔助觀察，不將台股／台積電行情塞入美股卡。",
                "market_observation": facts[6]["text"],
                "next_catalyst": "以最近完成交易日資料更新。",
                "evidence": [facts[6]["quote"]] if facts[6]["quote"].get("price") is not None else [],
                "freshness": facts[6]["quote"].get("freshness", "unavailable"),
                "confidence": "low" if any(g.get("ticker") == "SOX" for g in data_gaps) else "medium",
            },
        ]
    if scope == "taiwan" and supplementary_section is not None:
        source_pair = [sections[0]["facts_structured"][0], sections[1]["facts_structured"][0]]
        pair_facts: list[dict[str, Any]] = []
        for fact in source_pair:
            quote = fact.get("quote") if isinstance(fact.get("quote"), dict) else {}
            ticker = str(fact.get("ticker") or "")
            name = "加權現貨" if ticker == "TAIEX" else "台指期近月日盤"
            price = _finite_number(quote.get("price"))
            point_change = _finite_number(quote.get("change"))
            percent = _finite_number(quote.get("change_percent"))
            observed = str(quote.get("quote_date") or "")[:10]
            if price is None or percent is None:
                text = f"{name}：未取得可核對資料"
            else:
                point_change_text = f"{point_change:+,.2f} 點" if point_change is not None else "漲跌點數未提供"
                text = f"{name} {price:,.2f} 點｜{point_change_text}（{percent:+.2f}%）｜{observed or '資料日未確認'}"
                if ticker == "TXF":
                    month = str(quote.get("contract_month") or "")
                    text += f"｜契約 {month or '月份未核實'}"
                    if quote.get("quote_delayed") is True or (observed and observed != str(as_of or "")[:10]):
                        text += "｜最近已核實日盤，非今日／非即時"
            pair_facts.append({**fact, "text": text, "quote": quote})

        pair_dates = [str(item.get("quote", {}).get("quote_date") or "")[:10] for item in pair_facts]
        if pair_dates[0] and pair_dates[0] == pair_dates[1]:
            first_move = _finite_number(pair_facts[0]["quote"].get("change_percent"))
            second_move = _finite_number(pair_facts[1]["quote"].get("change_percent"))
            if first_move is None or second_move is None:
                pair_takeaway = "同日資料仍有缺項，現貨與期貨先分開看，不比較方向。"
            elif first_move * second_move < 0:
                pair_takeaway = "同日漲跌方向不同，分別解讀；不以兩者點位差當即時基差。"
            else:
                direction = "同漲" if first_move > 0 else "同跌" if first_move < 0 else "現貨持平"
                pair_takeaway = f"同日收盤方向{direction}；兩者仍是不同商品，不比較點位差。"
        elif pair_dates[0] or pair_dates[1]:
            pair_takeaway = "現貨與期貨資料日不同，不合併判讀；各自數值與日期分列。"
        else:
            pair_takeaway = "現貨或期貨資料未核實，暫不比較方向。"
        pair_section = {
            "title": "台股現貨與台指期",
            "layout": "taiwan_pair_v2",
            "facts": [item["text"] for item in pair_facts],
            "facts_structured": pair_facts,
            "takeaway": pair_takeaway,
            "why_it_matters": "加權指數是上市現貨；台指期是獨立近月契約。",
            "transmission": "分列各自漲跌與交易日；不同日期不合併判讀，也不計算不同收盤時間的即時基差。",
            "market_observation": "；".join(item["text"] for item in pair_facts),
            "next_catalyst": "下一個可核實的台股現貨與台指期日盤收盤。",
            "evidence": [item["quote"] for item in pair_facts if item["quote"].get("price") is not None],
            "freshness": "現貨與期貨分別標示資料日期與來源",
            "confidence": "low" if data_gaps else "medium",
        }
        stats_records: list[tuple[str, str, dict[str, Any] | None]] = [
            ("turnover", "上市成交金額", turnover_evidence),
            ("breadth", "上市漲跌家數", breadth_evidence),
            ("institutions", "三大法人合計", institution_evidence),
        ]
        compact_stats: list[dict[str, Any]] = []
        for key, name, compact_evidence in stats_records:
            if not isinstance(compact_evidence, dict):
                text = f"{name}：未公布或本輪未取得"
                quote = {}
            elif key == "turnover":
                text = f"{name} {float(compact_evidence['display_value']):,.2f} 億元（{compact_evidence.get('observed_date') or '日期未提供'}）"
                quote = compact_evidence
            elif key == "breadth":
                advancing = _finite_number(compact_evidence.get("advancing"))
                declining = _finite_number(compact_evidence.get("declining"))
                unchanged = _finite_number(compact_evidence.get("unchanged"))
                text = f"上漲 {advancing:.0f}／下跌 {declining:.0f}" if advancing is not None and declining is not None else "漲跌家數：未核實"
                if unchanged is not None:
                    text += f"／平盤 {unchanged:.0f}"
                text += f"（{compact_evidence.get('observed_date') or '日期未提供'}）"
                quote = compact_evidence
            else:
                display_value = compact_evidence.get("display_value")
                net = float(display_value if display_value is not None else float(compact_evidence["raw_value"]) / 100_000_000)
                text = f"{name} {'買超' if net > 0 else '賣超' if net < 0 else '相抵'} {abs(net):,.2f} 億元（{compact_evidence.get('observed_date') or '日期未提供'}）"
                quote = compact_evidence
            compact_stats.append({"ticker": f"TW_STATS_{key.upper()}", "name": name, "text": text, "quote": quote})
        stat_dates = {
            str(row.get("observed_date") or "")
            for _key, _name, row in stats_records
            if isinstance(row, dict) and row.get("observed_date")
        }
        if len(stat_dates) > 1:
            stats_takeaway = "統計資料日不同，請分項閱讀，不合併推論。"
        elif isinstance(breadth_evidence, dict):
            advancing = _finite_number(breadth_evidence.get("advancing"))
            declining = _finite_number(breadth_evidence.get("declining"))
            flow = _finite_number(institutions.get("total_net"))
            breadth_note = (
                "下跌家數較多" if advancing is not None and declining is not None and declining > advancing
                else "上漲家數較多" if advancing is not None and declining is not None and advancing > declining
                else "上漲與下跌家數相同" if advancing is not None and declining is not None
                else "盤面廣度未核實"
            )
            flow_note = (
                f"；三大法人合計{'買超' if flow > 0 else '賣超' if flow < 0 else '買賣相抵'} {abs(flow) / 100_000_000:,.2f} 億元"
                if flow is not None else ""
            )
            stats_takeaway = f"{breadth_note}{flow_note}；只作盤面背景，不單獨推論指數方向。"
        else:
            stats_takeaway = "官方統計只作輔助背景；缺項不估算，也不延後簡報。"
        stats_section = {
            **supplementary_section,
            "layout": "taiwan_stats_v2",
            "facts": [item["text"] for item in compact_stats],
            "facts_structured": compact_stats,
            "takeaway": stats_takeaway,
            "market_observation": "；".join(item["text"] for item in compact_stats),
            "evidence": [item["quote"] for item in compact_stats if item["quote"]],
        }
        sections = [pair_section, stats_section]
        market_card_projection = {
            "version": "taiwan-market-cards-v2",
            "market_scope": "taiwan",
            "slot": slot,
            "market_date": pair_dates[0] if pair_dates[0] and pair_dates[0] == pair_dates[1] else None,
            "instruments": pair_facts,
            "takeaway": pair_takeaway,
        }

    narrative_section = "taiwan" if scope == "taiwan" else "us_market"
    for section in sections:
        section_evidence = [
            row for row in section.get("evidence", []) if isinstance(row, dict)
        ]
        section_facts = [str(value) for value in section.get("facts", []) if value]
        section_rows = [
            item for item in section.get("facts_structured", [])
            if isinstance(item, dict)
        ]
        missing = [
            str(gap.get("name") or gap.get("ticker") or "行情資料")
            for gap in data_gaps
            if any(str(gap.get("ticker") or "") == str(item.get("ticker") or "") for item in section_rows)
        ]
        section["narrative"] = build_narrative(
            slot=slot,
            section=narrative_section,
            as_of=as_of,
            facts=section_facts,
            quote_evidence=section_evidence,
            themes=[],
            statistics=(taiwan_market_statistics or {}) if section is supplementary_section else None,
            limitations=missing,
        )
        section["highlights"] = section["narrative"].get("highlights", [])
        section["details"] = section["narrative"].get("details", [])
        section["limitations"] = section["narrative"].get("limitations", [])
    return {
        "ruleset": "market_scoped_card_v2" if scope == "taiwan" else "market_scoped_card_v1",
        "narrative_version": NARRATIVE_VERSION,
        "market_scope": scope,
        "market_card_projection": market_card_projection,
        "evidence_as_of": as_of,
        "overall_stance": "insufficient_evidence" if data_gaps else "market_specific_observation",
        "confidence": "low" if data_gaps else "medium",
        "sections": sections,
        "missing_evidence": [gap["name"] if "name" in gap else gap["ticker"] for gap in [*data_gaps, *supplementary_gaps]],
        "system_analysis": {
            "data_gaps": [*data_gaps, *supplementary_gaps],
            "note": "行情缺漏逐項揭露；不以舊值或其他市場替代。",
        },
    }


def _scoped_observations(analysis: dict[str, Any]) -> list[dict[str, str]]:
    sections = analysis.get("sections")
    if not isinstance(sections, list):
        return []
    cards: list[dict[str, str]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        facts = [str(item).strip() for item in section.get("facts", []) if str(item).strip()]
        source_parts = []
        for fact in section.get("facts_structured", []):
            quote = fact.get("quote") if isinstance(fact, dict) else None
            if isinstance(quote, dict):
                source = quote.get("source_url") or quote.get("source") or quote.get("quote_source")
                if source:
                    source_parts.append(str(source))
        cards.append(_card(
            str(section.get("title") or "市場觀察"),
            "；".join(facts) or "本輪未取得可核對資料。",
            str(section.get("why_it_matters") or "僅以目標市場可核對資料說明。"),
            str(section.get("transmission") or "不以其他市場行情替代。"),
            str(section.get("next_catalyst") or "等待下一筆目標市場可核對資料。"),
            source_note="；".join(source_parts),
        ))
    return cards


def build_briefing_snapshot(snapshot: dict[str, Any], slot: str | None = None) -> dict[str, Any]:
    """Create one detailed card payload for the Mini App, without advice."""
    slot = slot or "morning"
    market_scope = market_scope_for_slot(slot)
    snapshot = scope_snapshot(snapshot, slot)
    event_block = snapshot.get("events")
    event_rows = event_block.get("items") if isinstance(event_block, dict) else []
    events = [item for item in event_rows if isinstance(item, dict)] if isinstance(event_rows, list) else []
    indices = snapshot.get("indices") or []
    quotes = snapshot.get("quotes") or []
    macro_quotes = snapshot.get("macro_quotes") or []
    risk = snapshot.get("risk") or {}
    all_items = {item.get("ticker"): item for item in [*indices, *quotes, *macro_quotes] if item.get("ticker")}
    if market_scope:
        names = {
            "TAIEX": ("加權指數現貨", "點"), "TXF": ("台指期近月", "點"),
            "S&P 500": ("標普500現貨", "點"), "NASDAQ": ("Nasdaq Composite現貨", "點"),
            "DJIA": ("道瓊現貨", "點"), "ES": ("S&P 500 E-mini期貨", "點"),
            "NQ": ("Nasdaq-100指數期貨", "點"), "YM": ("道瓊E-mini期貨", "點"),
            "SOX": ("費半輔助指數", "點"),
        }
        cards = []
        for ticker in SCOPED_TICKER_ORDER[market_scope]:
            item = all_items.get(ticker)
            if item is None:
                name, currency = names[ticker]
                item = _placeholder(ticker, name, currency)
                item["market"] = market_scope
            cards.append(item)
    else:
        cards = [all_items[ticker] for ticker in GLOBAL_TICKERS if all_items.get(ticker)]
    observations = _market_observations(all_items, risk, events)
    briefing_data_as_of = snapshot.get("as_of") or snapshot.get("fetched_at") or snapshot.get("created_at")
    if briefing_data_as_of:
        for observation in observations:
            observation["data_as_of"] = briefing_data_as_of
    market_topics, dynamic_markets = _market_topics(all_items, events)
    if market_scope == "taiwan":
        market_topics = [{"title": "台股盤後", "items": cards}]
        dynamic_markets = []
    elif market_scope == "us":
        market_topics = [
            {"title": "美股現貨最近收盤", "items": cards[:3]},
            {"title": "美股指數期貨盤前", "items": cards[3:6]},
            {"title": "美股半導體輔助", "items": cards[6:]},
        ]
        dynamic_markets = []
    lead = events[0] if events else (observations[0] if observations else {"title": "市場資料狀態"})
    from src.intelligence_pipeline import build_intelligence_context

    observed_quotes = [*indices, *quotes, *macro_quotes]
    watchlist = (
        [ticker for ticker in SCOPED_TICKER_ORDER[market_scope] if ticker in all_items]
        if market_scope else
        [ticker for ticker in ("TAIEX", "NASDAQ", "SOX", "DJIA") if ticker in all_items]
    )
    public_watchlist = {ticker: round(1 / len(watchlist), 6) for ticker in watchlist} if watchlist else {}
    raw_macro = None if market_scope else snapshot.get("macro")
    macro_input = None
    if isinstance(raw_macro, dict):
        # Forward partial macro observations so the surprise engine can expose
        # `insufficient_evidence` instead of silently turning them into
        # `not_provided`.  Unknown producer fields are intentionally ignored.
        macro_input = {
            key: raw_macro[key]
            for key in (
                "expected", "actual", "previous", "historical_std",
                "revision", "release_time", "source_url",
            )
            if key in raw_macro
        }
    # The public release keeps every sanitized external row for lineage and
    # Creator display.  The shared market-event classifier consumes only the
    # FinancialJuice subset; editorial Creator observations use their own
    # attributed-content lane below.
    raw_external = snapshot.get("financialjuice_observations")
    if not isinstance(raw_external, list):
        raw_external = snapshot.get("external_observations")
    external_input = raw_external if isinstance(raw_external, list) else []
    intelligence = build_intelligence_context(
        lead if isinstance(lead, dict) else {"title": "briefing"},
        observed_quotes,
        external_observations=external_input,
        macro=macro_input,
        regime_factors=_regime_factors(all_items, risk),
        contagion_observations=_contagion_inputs(all_items, risk),
        stress_exposures=public_watchlist,
        advice_context={"general_research": True},
    )
    from src.production_integration import bind_intelligence

    intelligence = bind_intelligence(
        intelligence,
        snapshot=snapshot,
        observations=observed_quotes,
        policy_version=snapshot.get("policy_version"),
    )
    from src.creator_intelligence_pipeline import build_creator_intelligence_release
    from src.event_feedback import build_feedback_contract
    from src.paper_portfolio import build_paper_portfolio_snapshot, update_paper_observations

    research = {} if market_scope else (snapshot.get("research_report") or {})
    paper_portfolio = build_paper_portfolio_snapshot(
        research.get("candidates", []) if isinstance(research, dict) else [],
        observed_quotes,
        release_id=snapshot.get("release_id"),
    )
    # Historical closes are optional.  When a point-in-time archive is
    # available, update the same release-bound paper observations; otherwise
    # keep horizons explicitly pending instead of estimating returns.
    paper_history = snapshot.get("paper_portfolio_history")
    if isinstance(paper_history, dict) and paper_portfolio.get("records"):
        paper_portfolio["records"] = update_paper_observations(
            paper_portfolio["records"], paper_history
        )
        completed = sum(
            len(record.get("completed_horizons") or [])
            for record in paper_portfolio["records"]
        )
        paper_portfolio["tracking"] = {
            "status": "updated",
            "completed_horizon_count": completed,
            "history_source": "snapshot.paper_portfolio_history",
        }
    else:
        paper_portfolio["tracking"] = {
            "status": "pending",
            "completed_horizon_count": 0,
            "history_source": None,
        }
    feedback_events = [
        build_feedback_contract(event)
        for event in events[:10]
        if isinstance(event, dict)
    ]
    if not feedback_events:
        feedback_events = [build_feedback_contract({"event_type": "briefing"})]
    creator_release = None
    creator_records = None if market_scope else snapshot.get("creator_insights")
    if isinstance(creator_records, list):
        creator_result = build_creator_intelligence_release(
            [item for item in creator_records if isinstance(item, dict)],
            parent_manifest={
                "release_id": snapshot.get("release_id"),
                "market_snapshot_id": snapshot.get("market_snapshot_id"),
                "research_snapshot_id": snapshot.get("research_snapshot_id"),
                "event_snapshot_id": snapshot.get("event_snapshot_id"),
            },
            market_snapshot={
                "snapshot_id": snapshot.get("market_snapshot_id"),
                "as_of": snapshot.get("as_of") or snapshot.get("fetched_at") or snapshot.get("created_at"),
                "quotes": [*indices, *quotes, *macro_quotes],
            },
            research_snapshot=snapshot.get("research_report") if isinstance(snapshot.get("research_report"), dict) else None,
            event_snapshot={
                "snapshot_id": snapshot.get("event_snapshot_id"),
                "as_of": snapshot.get("as_of") or snapshot.get("fetched_at") or snapshot.get("created_at"),
                "events": [item for item in events if isinstance(item, dict)],
            },
            batch_as_of=(snapshot.get("fetched_at") or snapshot.get("created_at")) if (slot or "").casefold() == "morning" else None,
        )
        creator_release = creator_result["artifact"]
    from src.market_digest import build_market_digest

    digest = build_market_digest(snapshot, slot or "morning", intelligence=intelligence, risk=risk)
    # Re-project the fixed observation cards from the same digest used by
    # Telegram and the top summary.  Passing an empty theme intentionally
    # suppresses raw/unqualified events when the digest is unavailable.
    digest_theme = digest.get("primary_theme") if isinstance(digest.get("primary_theme"), dict) else {}
    observations = _market_observations(all_items, risk, events, primary_theme=digest_theme)
    digest_overview = digest.get("overview")
    if not digest_overview and digest.get("status") != "ready":
        digest_overview = "本輪公開市場證據不足，暫不形成判讀。"
    morning_analysis = _scoped_morning_analysis(
        all_items, market_scope, briefing_data_as_of, slot,
        snapshot.get("taiwan_market_statistics") if market_scope == "taiwan" else None,
    ) if market_scope else _morning_analysis(
        all_items,
        risk,
        digest.get("market_assessment") or {},
        [item for item in (digest.get("themes") or []) if isinstance(item, dict)],
        briefing_data_as_of,
        slot or "morning",
        snapshot.get("taiwan_market_statistics"),
        snapshot.get("markets") if isinstance(snapshot.get("markets"), dict) else None,
    )
    if market_scope:
        observations = _scoped_observations(morning_analysis)
        if briefing_data_as_of:
            for observation in observations:
                observation["data_as_of"] = str(briefing_data_as_of)
    return {
        "slot": slot,
        "title": SLOT_TITLES.get(slot or "", "即時市場儀表板"),
        "overview": digest_overview or (
            f"{lead.get('brief_title') or lead.get('title') or '市場資料狀態'}｜"
            f"{lead.get('summary') or lead.get('event') or '指定市場行情缺漏，不以其他市場替代'} "
            f"{lead.get('market_context') or lead.get('market_impact') or ''}"
        ),
        "assessment_summary": digest.get("assessment_summary", ""),
        "market_assessment": digest.get("market_assessment", {}),
        "morning_analysis": morning_analysis,
        "market_card_projection": (
            morning_analysis.get("market_card_projection")
            if isinstance(morning_analysis, dict) and market_scope == "taiwan" else None
        ),
        "summary_facts": _briefing_summary_facts(digest),
        "public_short_message": digest.get("public_short_message", ""),
        "public_summary_version": digest.get("public_summary_version", "public-summary-v2"),
        "public_summary_evidence_fields": digest.get("public_summary_evidence_fields", []),
        "public_summary_reason": digest.get("public_summary_reason", ""),
        "digest_status": digest.get("status", "suppressed"),
        "notification_eligible": digest.get("notification_eligible", False),
        "notification_reason": digest.get("notification_reason", "insufficient_evidence"),
        "briefing_id": digest.get("briefing_id", ""),
        "notification_key": digest.get("notification_key", ""),
        "canonical_content_hash": digest.get("canonical_content_hash", ""),
        "canonical_hash_version": digest.get("canonical_hash_version", 1),
        "decision_fingerprint": digest.get("decision_fingerprint", ""),
        "evidence_fingerprint": digest.get("evidence_fingerprint", ""),
        "evidence_material": digest.get("evidence_material", {}),
        "themes": digest.get("themes", []),
        "primary_theme": digest.get("primary_theme"),
        "secondary_signals": digest.get("secondary_signals", []),
        "displayed_event_keys": digest.get("displayed_event_keys", []),
        "evidence": digest.get("evidence", []),
        "source_evidence": digest.get("source_evidence", []),
        "quote_evidence": digest.get("quote_evidence", []),
        "lookback_hours": digest.get("lookback_hours", 24),
        "as_of": digest.get("as_of"),
        "market_scope": market_scope,
        "market_projection_version": snapshot.get("market_projection_version"),
        "quote_gaps": digest.get("quote_gaps", []),
        "data_gap_status": digest.get("data_gap_status", "unknown"),
        "scheduled_report": digest.get("scheduled_report") is True,
        "markets": cards,
        "market_topics": market_topics,
        "dynamic_markets": dynamic_markets,
        "observations": observations,
        "intelligence": intelligence,
        "creator_release": creator_release,
        "paper_portfolio": paper_portfolio,
        "event_feedback": {
            "enabled": True,
            "events": feedback_events,
            "policy_update_allowed": False,
            "pii_included": False,
        },
        "reminder": "僅供公開資訊整理與教育性觀察，不構成投資建議。",
    }
