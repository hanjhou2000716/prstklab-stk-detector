"""Public-market quote collection and Taiwan/US session detection."""

from __future__ import annotations

from datetime import date, datetime
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


def get_quote(item: dict[str, str]) -> dict[str, Any]:
    """Collect the latest two available closes for one public ticker."""
    import yfinance as yf

    history = yf.download(
        item["symbol"], period="10d", interval="1d", auto_adjust=False,
        progress=False, threads=False,
    )
    closes = _close_series(history)
    if len(closes) < 2:
        raise ValueError("可用收盤資料不足。")
    latest, previous = float(closes.iloc[-1]), float(closes.iloc[-2])
    delta = round(latest - previous, 2)
    return {
        **item,
        "price": round(latest, 2),
        "change": delta,
        "change_percent": change_percent(latest, previous),
        "quote_date": closes.index[-1].date().isoformat(),
        "currency": item.get("currency") or ("TWD" if item["market"] == "taiwan" else "USD"),
    }


def build_market_snapshot() -> dict[str, Any]:
    """Build a browser-friendly snapshot; one ticker failure never stops others."""
    from src.event_alerts import build_event_snapshot
    from src.official_events import fetch_official_events
    from src.macro_summary import build_macro_summary
    from src.macro_program_feed import fetch_yutinghao_latest_program
    from src.research_cards import load_research_cards
    from src.risk_news import build_news_snapshot, build_risk_snapshot

    errors: list[dict[str, str]] = []
    quotes: list[dict[str, Any]] = []
    for item in WATCHLIST:
        try:
            quotes.append(get_quote(item))
        except Exception as exc:  # Individual source failures are disclosed in the UI.
            errors.append({"ticker": item["ticker"], "message": str(exc)})
    indices: list[dict[str, Any]] = []
    for item in MARKET_INDICES:
        try:
            indices.append(get_quote(item))
        except Exception as exc:
            errors.append({"ticker": item["ticker"], "message": str(exc), "scope": "index"})
    quote_data_status = "即時" if not errors else "部分缺漏"
    risk = build_risk_snapshot()
    news = build_news_snapshot()
    official_events = fetch_official_events()
    events = build_event_snapshot(news, quotes, official_events, indices=indices)
    try:
        program = fetch_yutinghao_latest_program()
    except Exception:
        program = None
        errors.append({"ticker": "總經節目", "message": "最新公開節目暫時無法取得", "scope": "macro"})
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
    return {
        "generated_at": datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
        "data_status": quote_data_status,
        "markets": {key: get_market_status(key) for key in MARKETS},
        "indices": indices,
        "quotes": quotes,
        "risk": risk,
        "news": news,
        "events": events,
        "official_events": official_events,
        "macro": macro,
        "research_report": research_report,
        "errors": errors,
    }
