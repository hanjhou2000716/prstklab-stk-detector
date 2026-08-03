"""Rule-based material-event and price-signal cards from public market data."""

from __future__ import annotations

import re
from datetime import UTC, datetime, time
from typing import Any
from urllib.parse import urlparse

from src.finance_intel_policy import threshold_rule
from src.event_classifier import classify_event_fields, notification_gate
from src.intel_contract import normalize_event_record


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
    """Return a material-event record using every story field, not only title."""
    title = _clean_title(story.get("title", ""))
    enriched = {**story, "title": title}
    classification = classify_event_fields(enriched)
    category = classification.get("category")
    all_text = " ".join(str(value or "") for value in enriched.values()).lower()
    # A company/sector mention alone is not a material event.  Keep the
    # existing earnings gate so routine semiconductor headlines stay out of
    # the risk card while body text can still trigger a real earnings story.
    if category == "semiconductor" and not any(term.lower() in all_text for term in EARNINGS_TERMS):
        category = None
    labels = {
        "fed": "Fed／貨幣政策",
        "macro": "重大經濟數據",
        "policy": "關稅／政策",
        "conflict": "地緣衝突",
        "black_swan": "黑天鵝／重大災害",
        "energy": "能源／原油",
        "semiconductor": "半導體／科技",
        "market": "市場波動",
        "material_positive": "重大正向事件",
    }
    if category == "semiconductor" and any(term.lower() in all_text for term in EARNINGS_TERMS):
        labels["semiconductor"] = "半導體財報"
    if category in labels:
        return {
            **enriched,
            "short_label": labels[category],
            "classification": category,
            "classification_reason": classification.get("reason"),
            "matched_terms": classification.get("matched_terms", []),
        }
    # Keep the historical rules as a compatibility fallback for deployments
    # with a temporarily incomplete alias database.
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


def _impact_confirmation(
    index: dict[str, Any], related: list[dict[str, Any]], event_time: str | None = None
) -> dict[str, Any]:
    """Require a separate market observation before calling an alert high risk.

    A Taiwan intraday cash/futures cross-check is itself independent market
    confirmation.  For all other instruments, at least one related market
    must show a material public move.  This deliberately leaves a headline as
    an observation when the expected market transmission has not appeared.
    """
    if index.get("ticker") == "TAIEX" and index.get("crosscheck_status") in {None, "已核對同向"}:
        return {"confirmed": True, "method": "TWSE／TAIFEX 同向核對", "markets": ["TAIEX"]}
    confirmed = []
    source_time = str(event_time or index.get("quote_time") or "").strip()
    for item in related:
        if item.get("quote_delayed") or item.get("change_percent") is None:
            continue
        # An event must transmit to a related market within 30 minutes when
        # both timestamps are available; this prevents an old daily quote from
        # falsely confirming a breaking headline.
        item_time = str(item.get("quote_time") or item.get("quote_date") or "").strip()
        if source_time and item_time:
            try:
                left = datetime.fromisoformat(source_time.replace("Z", "+00:00"))
                right = datetime.fromisoformat(item_time.replace("Z", "+00:00"))
                # Public feeds mix ISO timestamps with and without offsets.
                # Compare them on one UTC timeline instead of raising when a
                # naive value meets an aware value.
                if left.tzinfo is None:
                    left = left.replace(tzinfo=UTC)
                if right.tzinfo is None:
                    right = right.replace(tzinfo=UTC)
                if abs((right - left).total_seconds()) > 30 * 60:
                    continue
            except ValueError:
                pass
        ticker = str(item.get("ticker") or "").upper()
        # Oil is a market-sync witness only after a move greater than 5%.
        # Require timestamps for oil so a stale daily close cannot confirm a
        # breaking geopolitical headline.
        threshold = 5.0 if ticker in {"WTI", "BRENT"} else 1.5 if ticker in {"GOLD", "DXY", "US10Y", "VIX"} else 1.0
        if ticker in {"WTI", "BRENT"} and (not source_time or not item_time):
            continue
        if abs(float(item["change_percent"])) >= threshold:
            confirmed.append(item)
    if confirmed:
        return {
            "confirmed": True,
            "method": "相關市場同步波動",
            "markets": [str(item.get("ticker")) for item in confirmed],
            "evidence": [
                {
                    "ticker": str(item.get("ticker") or ""),
                    "change_percent": item.get("change_percent"),
                    "quote_time": item.get("quote_time") or item.get("quote_date"),
                }
                for item in confirmed
            ],
        }
    return {"confirmed": False, "method": "尚無相關市場同步確認", "markets": [], "evidence": []}


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
    quote_time = str(index.get("quote_time") or "")
    taiwan_intraday = False
    if ticker == "TAIEX" and quote_time:
        try:
            observed = datetime.fromisoformat(quote_time.replace("Z", "+00:00"))
            taiwan_intraday = observed.weekday() < 5 and time(8, 45) <= observed.timetz().replace(tzinfo=None) <= time(13, 30)
        except ValueError:
            taiwan_intraday = False

    minimum_daily_move = {
        "TAIEX": 1.5,
        "SOX": 3.0,
        "NASDAQ": 2.0,
        "WTI": float(threshold_rule("oilDailyAbsoluteMovePercent")),
        "BRENT": float(threshold_rule("oilDailyAbsoluteMovePercent")),
        "GOLD": float(threshold_rule("goldDailyAbsoluteMovePercent")),
    }.get(ticker, 1.0)
    # During the Taiwan cash session, each new half-percent band is a useful
    # public market observation.  Offshore instruments retain their stricter
    # thresholds to avoid an alert stream dominated by routine volatility.
    if taiwan_intraday:
        minimum_daily_move = 0.5
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

    related = _related_indices(indices, ticker)
    impact_confirmation = _impact_confirmation(index, related, str(index.get("quote_time") or ""))
    if risk == "高風險" and not impact_confirmation["confirmed"]:
        risk = "警戒"
        stock_observation = (
            f"{stock_observation} 目前尚未看到相關市場同步確認，"
            "故維持警戒而非升級為高風險快報。"
        )

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
    source_url = str(index.get("source_url") or index.get("url") or "").strip()
    source_domain = str(index.get("source_domain") or "").strip()
    if not source_domain and source_url:
        source_domain = (urlparse(source_url).hostname or "").lower().removeprefix("www.")
    checked_at = str(index.get("fetched_at") or index.get("checked_at") or index.get("quote_time") or "").strip()
    verified_domains = [source_domain] if source_domain else []
    for value in (index.get("crosscheck_sources") or []):
        if isinstance(value, dict):
            domain = str(value.get("domain") or "").strip().lower().removeprefix("www.")
        else:
            domain = str(value).strip().lower().removeprefix("www.")
        if domain and domain not in verified_domains:
            verified_domains.append(domain)
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
        "event": trigger,
        "importance_detail": why_important,
        "market_impact": market_context,
        "watch": stock_observation,
        "market_direction": "上漲" if percent > 0 else "下跌" if percent < 0 else "持平",
        "market_move": move,
        "friendly_reminder": "僅供公開資訊整理與教育性觀察，不構成投資建議。",
        "source": "公開市場報價",
        "url": source_url,
        "source_trace": {
            "verification": str(index.get("crosscheck_status") or "公開市場報價"),
            "source_label": str(index.get("source_label") or index.get("quote_source") or "公開市場報價"),
            "source_url": source_url,
            "source_domain": source_domain,
            "event_time": str(index.get("quote_time") or index.get("quote_date") or ""),
            "checked_at": checked_at,
            "verified_domains": verified_domains,
        },
        "instrument": index,
        "related": related,
        "impact_confirmation": impact_confirmation,
        "change": change,
        # A Taiwan alert is keyed to its signed 0.5% band.  The monitor can
        # therefore notify only on a newly crossed band, not every five-minute
        # poll or a later scheduled briefing with the same percentage.
        "realert_interval_minutes": None,
        "signal_band": round(percent * 2) / 2 if taiwan_intraday else None,
        "signal_state": f"{pattern}:{risk}:{_signal_stage(percent, move_15m)}:{'up' if move_15m is not None and move_15m > 0 else 'down' if move_15m is not None and move_15m < 0 else 'daily'}:{round(percent * 2) / 2:+.1f}" if taiwan_intraday else f"{pattern}:{risk}:{_signal_stage(percent, move_15m)}:{'up' if move_15m is not None and move_15m > 0 else 'down' if move_15m is not None and move_15m < 0 else 'daily'}",
    }


def _detail_event(event: dict[str, Any], indices: list[dict[str, Any]]) -> dict[str, Any]:
    """Give official or news events the same card fields as price signals."""
    # Preserve the provider's original labels before normalization.  The
    # normalizer intentionally maps provider-specific event types to broad
    # categories (for example ``macro``), so checking only the normalized
    # record would lose explicit disaster/black-swan wording and weaken the
    # strict high-risk gate.
    raw_event = dict(event)
    event = normalize_event_record(event)
    label = str(event.get("short_label") or "市場事件")
    title = str(event.get("title") or "公開事件更新")
    why_important, market_context, stock_observation = _event_market_context(label)
    prior_trace = event.get("source_trace") if isinstance(event.get("source_trace"), dict) else {}
    url = str(event.get("source_url") or event.get("url") or prior_trace.get("source_url") or "").strip()
    parsed = urlparse(url)
    domain = (parsed.hostname or "").lower().removeprefix("www.")
    released_at = str(event.get("released_at") or event.get("published_at") or "").strip()
    source = str(event.get("source") or "公開來源").strip()
    trace = {
        "verification": "一手官方來源" if event.get("relevance") == "official" or event.get("source_tier") == "official" else "公開來源待後續核對",
        "source_label": str(prior_trace.get("source_label") or source),
        "source_url": url if parsed.scheme == "https" else "",
        "source_domain": domain,
        "event_time": released_at or str(prior_trace.get("event_time") or ""),
        "checked_at": str(event.get("checked_at") or prior_trace.get("checked_at") or event.get("fetched_at") or ""),
        "verified_domains": list(dict.fromkeys(([domain] if domain else []) + [
            str(item.get("domain") or "").lower().removeprefix("www.")
            for item in (event.get("verified_sources") or [])
            if isinstance(item, dict) and item.get("domain")
        ])),
    }
    preclassification = classify_event_fields({**raw_event, **event})
    pre_category = str(event.get("classification") or preclassification.get("category") or "")
    related = event.get("related") or _related_indices(indices, "")
    # Energy/geopolitical stories must include the commodity witness in the
    # same event record; otherwise a >5% WTI move could never be evaluated.
    pre_text = str(preclassification.get("text") or "")
    if pre_category in {"conflict", "black_swan", "energy"} and any(
        token in pre_text for token in ("wti", "brent", "crude oil", "原油", "油價", "石油", "航運", "shipping")
    ):
        for ticker in ("WTI", "BRENT", "GOLD"):
            item = next((value for value in indices if value.get("ticker") == ticker), None)
            if item and item not in related:
                related.append(item)
    impact_confirmation = _impact_confirmation(
        {"ticker": event.get("ticker", "")}, related, released_at
    )
    classification = classify_event_fields({**raw_event, **event, "related_quotes": related})
    category = str(event.get("classification") or classification.get("category") or "") or None
    classification_reason = str(event.get("classification_reason") or classification.get("reason") or "")
    risk_level = event.get("risk_level") or "持續觀察"
    brief_title = event.get("brief_title") or f"{label}｜重要事件｜觀察"
    event_text = " ".join(
        str(record.get(key) or "")
        for record in (raw_event, event)
        for key in ("event_type", "category", "short_label", "brief_title", "title", "brief_summary")
    ).lower()
    is_black_swan = event.get("kind") != "market_signal" and (
        category in {"black_swan", "conflict"}
        or any(
        term in event_text for term in ("黑天鵝", "重大災害", "black swan", "disaster", "earthquake", "tsunami", "戰爭", "戰事", "war", "invasion", "conflict", "攻擊", "供應中斷")
        )
    )
    official_verified = event.get("relevance") == "official" or event.get("source_tier") == "official"
    strict_confirmation = official_verified and impact_confirmation["confirmed"]
    notification = notification_gate(
        category,
        official_confirmed=official_verified,
        market_sync_confirmed=bool(impact_confirmation.get("confirmed")),
    )
    verification_plan = ["ECB 官方 RSS", "Reuters／GDELT"] if category in {"conflict", "energy", "policy", "macro", "black_swan"} else []
    if verification_plan:
        trace["verification_plan"] = verification_plan
    if risk_level == "高風險" and not impact_confirmation["confirmed"]:
        risk_level = "警戒"
        brief_title = f"{label}｜重要事件｜警戒"
        stock_observation = f"{stock_observation} 尚未核對到相關市場同步波動，維持警戒觀察。"
    # Black-swan and major-disaster notices are never allowed to become a
    # high-risk push from a headline alone: a first-party confirmation and at
    # least one related market move are both required.
    if is_black_swan and not strict_confirmation:
        risk_level = "警戒" if risk_level in {"高風險", "高波動"} else risk_level
        brief_title = f"{label}｜重要事件｜警戒"
        stock_observation = f"{stock_observation} 僅在官方來源與相關市場同步確認後升級高風險。"
    if is_black_swan:
        related_names = "、".join(str(item.get("ticker") or "市場") for item in related[:3]) or "相關市場"
        confirmation = "已出現相關公開價格確認" if impact_confirmation["confirmed"] else "尚未出現足夠的相關公開價格確認"
        why_important = "重大災害可能改變區域供應、航運、能源或避險需求；實際影響須由官方資訊與公開市場資料共同確認。"
        market_context = f"市場傳導：{confirmation}；本輪連動觀察為 {related_names}。"
        stock_observation = "後續觀察：官方災情與基建／航運資訊、能源與避險資產，以及主要股市是否持續同步波動。"
    related_moves = [item.get("change_percent") for item in related if isinstance(item, dict) and item.get("change_percent") is not None]
    representative_move = max(related_moves, key=lambda value: abs(float(value))) if related_moves else None
    market_direction = "上漲" if representative_move is not None and float(representative_move) > 0 else "下跌" if representative_move is not None and float(representative_move) < 0 else "市場待核對"
    market_move = f"{float(representative_move):+.1f}%" if representative_move is not None else "變動待核對"
    return normalize_event_record({
        **event,
        "kind": event.get("kind") or "major_event",
        "pattern": event.get("pattern") or "重要事件",
        "risk_level": risk_level,
        "brief_title": brief_title,
        "summary": event.get("summary") or event.get("brief_summary") or title,
        "trigger": event.get("trigger") or (f"事件：{event.get('brief_summary') or title}。核對來源：{source}。" if is_black_swan else "已核對公開來源；請查看完整內容與市場後續反應。"),
        "why_important": event.get("why_important") or why_important,
        "market_context": event.get("market_context") or market_context,
        "stock_observation": event.get("stock_observation") or stock_observation,
        "friendly_reminder": event.get("friendly_reminder") or "僅供公開資訊整理與教育性觀察，不構成投資建議。",
        "event": event.get("event") or event.get("trigger") or event.get("summary") or title,
        "importance_detail": event.get("importance_detail") or event.get("why_important") or why_important,
        "market_impact": event.get("market_impact") or event.get("market_context") or market_context,
        "watch": event.get("watch") or event.get("stock_observation") or stock_observation,
        "market_direction": market_direction,
        "market_move": market_move,
        "related": related,
        "impact_confirmation": impact_confirmation,
        "source_trace": trace,
        "official_confirmed": official_verified,
        "high_risk_eligible": bool(strict_confirmation) if is_black_swan else True,
        "classification": category,
        "classification_reason": classification_reason,
        "matched_terms": classification.get("matched_terms", []),
        "notification_status": notification["status"],
        "notification_reasons": notification["reasons"],
        "notification_reason": "、".join(notification["reasons"]),
        "verification_plan": verification_plan,
    })


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

    events = events[:4]
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
