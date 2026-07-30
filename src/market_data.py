"""Public-market quote collection and Taiwan/US session detection."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo


MARKETS = {
    "taiwan": {"calendar": "XTAI", "label": "台股", "timezone": "Asia/Taipei"},
    "us": {"calendar": "NYSE", "label": "美股", "timezone": "America/New_York"},
}

WATCHLIST = (
    {"symbol": "006208.TW", "ticker": "006208", "name": "富邦台50", "market": "taiwan"},
    {"symbol": "00685L.TW", "ticker": "00685L", "name": "群益臺灣加權正二", "market": "taiwan"},
    {"symbol": "2330.TW", "ticker": "2330", "name": "台積電", "market": "taiwan"},
    {"symbol": "QQQM", "ticker": "QQQM", "name": "Invesco NASDAQ 100 ETF", "market": "us"},
    {"symbol": "QLD", "ticker": "QLD", "name": "ProShares Ultra QQQ", "market": "us"},
    {"symbol": "TSM", "ticker": "TSM", "name": "台積電 ADR", "market": "us"},
    {"symbol": "NVDA", "ticker": "NVDA", "name": "NVIDIA", "market": "us"},
)

# Market indices are intentionally kept separate from representative
# securities. They describe the overall market and never enter research scans.
MARKET_INDICES = (
    {"symbol": "^TWII", "ticker": "TAIEX", "name": "臺灣加權指數", "market": "taiwan", "currency": "點"},
    {"symbol": "^TWOII", "ticker": "TPEx", "name": "櫃買指數", "market": "taiwan", "currency": "點"},
    {"symbol": "^GSPC", "ticker": "S&P 500", "name": "標普 500", "market": "us", "currency": "點"},
    {"symbol": "^IXIC", "ticker": "NASDAQ", "name": "那斯達克綜合指數", "market": "us", "currency": "點"},
    {"symbol": "^DJI", "ticker": "DJIA", "name": "道瓊工業指數", "market": "us", "currency": "點"},
    {"symbol": "^SOX", "ticker": "SOX", "name": "費城半導體指數", "market": "us", "currency": "點"},
    {"symbol": "^N225", "ticker": "NIKKEI", "name": "日經225", "market": "asia", "currency": "點"},
    {"symbol": "^KS11", "ticker": "KOSPI", "name": "韓國綜合", "market": "asia", "currency": "點"},
    {"symbol": "BZ=F", "ticker": "BRENT", "name": "Brent 原油", "market": "global", "currency": "USD"},
    {"symbol": "CL=F", "ticker": "WTI", "name": "WTI 原油", "market": "global", "currency": "USD"},
    {"symbol": "GC=F", "ticker": "GOLD", "name": "黃金期貨", "market": "global", "currency": "USD"},
    {"symbol": "BTC-USD", "ticker": "BTC", "name": "BTC", "market": "global", "currency": "USD"},
    {"symbol": "ETH-USD", "ticker": "ETH", "name": "ETH", "market": "global", "currency": "USD"},
)

# These references power the briefing's dedicated rates/FX card.  They remain
# separate from the main market-index list so the Mini App's market section
# stays focused on stock, commodity and crypto benchmarks.
MACRO_REFERENCES = (
    {"symbol": "DX-Y.NYB", "ticker": "DXY", "name": "美元指數", "market": "global", "currency": "點"},
    {"symbol": "^TNX", "ticker": "US10Y", "name": "美國10年債殖利率", "market": "global", "currency": "%"},
    {"symbol": "TWD=X", "ticker": "USD/TWD", "name": "美元兌台幣", "market": "global", "currency": "TWD"},
)


def change_percent(current: float, previous: float) -> float | None:
    """Return percent change, avoiding an invalid division by zero."""
    if previous == 0:
        return None
    return round((current / previous - 1) * 100, 2)


def get_market_status(market_key: str, today: date | None = None) -> dict[str, Any]:
    """Use an exchange calendar for holiday-aware trading-session status."""
    import pandas_market_calendars as mcal

    market = MARKETS[market_key]
    tz = ZoneInfo(market["timezone"])
    now = datetime.now(tz)
    target_day = today or now.date()
    calendar = mcal.get_calendar(market["calendar"])
    schedule = calendar.schedule(start_date=target_day, end_date=target_day)
    base = {
        "label": market["label"],
        "timezone": market["timezone"],
        "calendar": market["calendar"],
        "date": target_day.isoformat(),
    }
    if schedule.empty:
        return {**base, "is_trading_day": False, "session": "休市"}

    market_open = schedule.iloc[0]["market_open"].to_pydatetime().astimezone(tz)
    market_close = schedule.iloc[0]["market_close"].to_pydatetime().astimezone(tz)
    if now < market_open:
        session = "開盤前"
    elif now <= market_close:
        session = "交易中"
    else:
        session = "收盤後"
    return {
        **base,
        "is_trading_day": True,
        "session": session,
        "market_open": market_open.isoformat(),
        "market_close": market_close.isoformat(),
    }


def _close_series(history: Any) -> Any:
    """Handle both standard and multi-index yfinance response shapes."""
    close = history["Close"]
    if getattr(close, "ndim", 1) > 1:
        close = close.iloc[:, 0]
    return close.dropna()


def _daily_quote(item: dict[str, str], closes: Any) -> dict[str, Any]:
    """Build a clearly labelled quote from the latest completed daily bars."""
    if len(closes) < 2:
        raise ValueError("可用收盤資料不足。")
    latest, previous = float(closes.iloc[-1]), float(closes.iloc[-2])
    return {
        **item,
        "price": round(latest, 2),
        "change": round(latest - previous, 2),
        "change_percent": change_percent(latest, previous),
        "quote_date": closes.index[-1].date().isoformat(),
        "quote_time": None,
        "quote_basis": "日線收盤",
        "quote_source": "Yahoo Finance public daily quote",
        "currency": item.get("currency") or ("TWD" if item["market"] == "taiwan" else "USD"),
    }


def _intraday_quote(
    item: dict[str, str], daily_closes: Any, intraday_closes: Any, basis: str, *, delayed: bool = False
) -> dict[str, Any]:
    """Build a five-minute quote versus the preceding completed daily close."""
    if daily_closes.empty or intraday_closes.empty:
        raise ValueError("可用盤中資料不足。")
    latest = float(intraday_closes.iloc[-1])
    timestamp = intraday_closes.index[-1]
    # Yahoo may or may not include today's incomplete daily bar. When it
    # does, the preceding completed close is penultimate; otherwise the last
    # daily close is already the correct comparison base.
    latest_daily_date = daily_closes.index[-1].date()
    previous_close = float(
        daily_closes.iloc[-2]
        if latest_daily_date == timestamp.date() and len(daily_closes) >= 2
        else daily_closes.iloc[-1]
    )
    # Keep a real 15-minute move only when four consecutive five-minute bars
    # are available. Sparse session-boundary data must not be interpreted.
    change_15m_percent = None
    if len(intraday_closes) >= 4:
        earlier = intraday_closes.index[-4]
        elapsed_seconds = (timestamp - earlier).total_seconds()
        if 10 * 60 <= elapsed_seconds <= 25 * 60:
            change_15m_percent = change_percent(latest, float(intraday_closes.iloc[-4]))
    return {
        **item,
        "price": round(latest, 2),
        "change": round(latest - previous_close, 2),
        "change_percent": change_percent(latest, previous_close),
        "change_15m_percent": change_15m_percent,
        "quote_date": timestamp.date().isoformat(),
        "quote_time": timestamp.isoformat(),
        "quote_basis": basis,
        "quote_delayed": delayed,
        "quote_source": "Yahoo Finance public 5-minute quote",
        "currency": item.get("currency") or ("TWD" if item["market"] == "taiwan" else "USD"),
    }


def intraday_is_fresh(timestamp: Any, market: str, now: datetime | None = None) -> bool:
    """Treat a five-minute bar older than ten minutes as delayed, not live."""
    timezone = MARKETS[market]["timezone"]
    observed = timestamp
    if getattr(observed, "tzinfo", None) is None:
        observed = observed.tz_localize(timezone)
    else:
        observed = observed.tz_convert(timezone)
    reference = now or datetime.now(ZoneInfo(timezone))
    return reference - observed.to_pydatetime() <= timedelta(minutes=10)


def quote_freshness(quote: dict[str, Any], *, now: datetime | None = None) -> str:
    """Classify a quote by its published observation date, not scan time."""
    reference = now or datetime.now(ZoneInfo("Asia/Taipei"))
    try:
        observed = datetime.fromisoformat(str(quote.get("quote_time") or quote.get("quote_date"))).date()
    except ValueError:
        return "unknown"
    age_days = max(0, (reference.date() - observed).days)
    if age_days > 3:
        return "stale"
    if quote.get("quote_time") and not quote.get("quote_delayed"):
        return "live"
    return "recent_close"


def annotate_quote_freshness(quotes: list[dict[str, Any]], *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Expose stale data to the UI and health source instead of silently showing it."""
    return [{**quote, "freshness": quote_freshness(quote, now=now)} for quote in quotes]


def get_quote(item: dict[str, str], session: str | None = None) -> dict[str, Any]:
    """Collect a five-minute live bar when eligible, otherwise a daily close."""
    import yfinance as yf

    history = yf.download(
        item["symbol"], period="10d", interval="1d", auto_adjust=False,
        progress=False, threads=False,
    )
    closes = _close_series(history)
    eligible = (item["market"] == "taiwan" and session == "交易中") or (
        item["market"] == "us" and session in {"交易中", "開盤前"}
    )
    if not eligible:
        return _daily_quote(item, closes)
    try:
        intraday = yf.download(
            item["symbol"], period="1d", interval="5m", auto_adjust=False,
            prepost=item["market"] == "us", progress=False, threads=False,
        )
        intraday_closes = _close_series(intraday)
        delayed = not intraday_is_fresh(intraday_closes.index[-1], item["market"])
        basis = "盤中延遲報價" if delayed and session == "交易中" else (
            "盤前延遲報價" if delayed else ("盤中 5 分鐘" if session == "交易中" else "盤前 5 分鐘")
        )
        return _intraday_quote(item, closes, intraday_closes, basis, delayed=delayed)
    except Exception:
        # Never fabricate a live price. The UI explicitly labels the daily fallback.
        return _daily_quote(item, closes)


def apply_taiwan_intraday_crosscheck(
    indices: list[dict[str, Any]], session: str, *,
    twse_fetcher: Any | None = None, taifex_fetcher: Any | None = None,
    tpex_fetcher: Any | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Replace an in-session TAIEX quote only after official source checks.

    TWSE public MIS supplies the cash-index observation.  TAIFEX's TXF public
    observation is deliberately a direction check, not a point-price proxy.
    A failed official call leaves the existing quote visible but marks it as
    non-actionable for an urgent TAIEX price alert.
    """
    from src.tpex_index import fetch_tpex_index
    tpex_fetcher = tpex_fetcher or fetch_tpex_index
    errors: list[dict[str, str]] = []
    tpex = None
    # Attempt the official close even when Yahoo failed before creating TPEx.
    try:
        tpex = tpex_fetcher()
    except Exception as exc:
        errors.append({"ticker": "TPEx", "message": f"TPEx 官方指數暫時無法取得：{type(exc).__name__}", "scope": "index"})
    if tpex and not any(item.get("ticker") == "TPEx" for item in indices):
        indices = [*indices, tpex]
    if session != "交易中":
        return [({**item, **tpex} if item.get("ticker") == "TPEx" and tpex else item) for item in indices], errors
    from src.taiwan_market_crosscheck import crosscheck_taiex_quote, fetch_taifex_txf, fetch_twse_taiex

    twse_fetcher = twse_fetcher or fetch_twse_taiex
    taifex_fetcher = taifex_fetcher or fetch_taifex_txf
    try:
        twse = twse_fetcher()
    except Exception as exc:
        twse = None
        errors.append({"ticker": "TAIEX", "message": f"TWSE 盤中交叉核對失敗：{type(exc).__name__}", "scope": "taiwan_crosscheck"})
    try:
        taifex = taifex_fetcher()
    except Exception as exc:
        taifex = None
        errors.append({"ticker": "TXF", "message": f"TAIFEX 盤中交叉核對失敗：{type(exc).__name__}", "scope": "taiwan_crosscheck"})

    checked: list[dict[str, Any]] = []
    for item in indices:
        if item.get("ticker") == "TAIEX":
            checked.append(crosscheck_taiex_quote(item, twse=twse, taifex=taifex))
        elif item.get("ticker") == "TPEx" and tpex:
            checked.append({**item, **tpex})
        else:
            checked.append(item)
    return checked, errors


def build_market_snapshot() -> dict[str, Any]:
    """Build a browser-friendly snapshot; one ticker failure never stops others."""
    from src.event_alerts import build_event_snapshot
    from src.briefing_cards import build_briefing_snapshot
    from src.official_events import fetch_official_events
    from src.macro_summary import build_macro_summary
    from src.macro_program_feed import fetch_yutinghao_latest_program
    from src.research_cards import load_research_cards
    from src.risk_news import build_news_snapshot, build_risk_snapshot
    from src.source_health import build_source_health

    scan_started_at = datetime.now(ZoneInfo("Asia/Taipei"))
    markets = {key: get_market_status(key) for key in MARKETS}
    errors: list[dict[str, str]] = []
    quotes: list[dict[str, Any]] = []
    for item in WATCHLIST:
        try:
            quotes.append(get_quote(item, markets.get(item["market"], {}).get("session")))
        except Exception as exc:  # Individual source failures are disclosed in the UI.
            errors.append({"ticker": item["ticker"], "message": str(exc)})
    indices: list[dict[str, Any]] = []
    for item in MARKET_INDICES:
        try:
            indices.append(get_quote(item, markets.get(item["market"], {}).get("session")))
        except Exception as exc:
            errors.append({"ticker": item["ticker"], "message": str(exc), "scope": "index"})
    indices, crosscheck_errors = apply_taiwan_intraday_crosscheck(
        indices, markets.get("taiwan", {}).get("session", "")
    )
    errors.extend(crosscheck_errors)
    quotes = annotate_quote_freshness(quotes)
    indices = annotate_quote_freshness(indices)
    for item in [*quotes, *indices]:
        if item.get("freshness") == "stale":
            errors.append({
                "ticker": item.get("ticker", "公開報價"),
                "message": f"{item.get('ticker', '公開報價')} 報價已逾三日，已標示為過期資料",
                "scope": "index" if item in indices else "",
            })
    macro_quotes: list[dict[str, Any]] = []
    for item in MACRO_REFERENCES:
        try:
            macro_quotes.append(get_quote(item, None))
        except Exception as exc:
            errors.append({"ticker": item["ticker"], "message": str(exc), "scope": "macro_quote"})
    quote_data_status = "即時" if not errors else "部分缺漏"
    risk = build_risk_snapshot()
    news = build_news_snapshot()
    official_events = fetch_official_events()
    events = build_event_snapshot(news, quotes, official_events, indices=indices)
    try:
        program = fetch_yutinghao_latest_program()
    except Exception:
        # The programme feed is optional. Its absence must not mark core
        # market data as unhealthy when YouTube changes a channel feed.
        program = None
    macro = build_macro_summary(events, risk, program)
    research_report = load_research_cards()
    errors.extend({"ticker": "新聞", "message": message} for message in news["errors"])
    errors.extend(
        {"ticker": "官方事件", "message": message, "scope": "official_event"}
        for message in official_events["errors"]
    )
    for market in ("taiwan", "us"):
        # A risk-provider outage does not mean that the whole market or its
        # representative quotes are unavailable. Keep the affected source in
        # the public health notice so the Mini App can explain it precisely.
        errors.extend(
            {
                "ticker": f"{risk[market]['label']}風險指標",
                "message": message,
                "scope": "risk",
            }
            for message in risk[market]["errors"]
        )
    scan_completed_at = datetime.now(ZoneInfo("Asia/Taipei"))
    source_health = build_source_health(
        errors=errors,
        events=events,
        research_report=research_report,
        checked_at=scan_completed_at,
    )
    live_quotes = sum(item.get("quote_time") is not None for item in [*quotes, *indices])
    close_quotes = len(quotes) + len(indices) - live_quotes
    return {
        "generated_at": scan_completed_at.isoformat(),
        "scan": {
            "started_at": scan_started_at.isoformat(),
            "completed_at": scan_completed_at.isoformat(),
            "scope": "公開市場定時掃描",
            "live_quote_count": live_quotes,
            "close_quote_count": close_quotes,
        },
        "data_status": quote_data_status,
        "markets": markets,
        "indices": indices,
        "quotes": quotes,
        "risk": risk,
        "news": news,
        "events": events,
        "official_events": official_events,
        "macro": macro,
        "macro_quotes": macro_quotes,
        "briefing": build_briefing_snapshot({
            "events": events, "indices": indices, "quotes": quotes,
            "macro_quotes": macro_quotes, "risk": risk,
        }),
        "research_report": research_report,
        "source_health": source_health,
        "errors": errors,
    }
