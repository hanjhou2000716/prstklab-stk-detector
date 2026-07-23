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
    {"symbol": "00685L.TW", "ticker": "00685L", "name": "國泰美國道瓊正2", "market": "taiwan"},
    {"symbol": "2330.TW", "ticker": "2330", "name": "台積電", "market": "taiwan"},
    {"symbol": "QQQM", "ticker": "QQQM", "name": "Invesco NASDAQ 100 ETF", "market": "us"},
    {"symbol": "QLD", "ticker": "QLD", "name": "ProShares Ultra QQQ", "market": "us"},
    {"symbol": "TSM", "ticker": "TSM", "name": "台積電 ADR", "market": "us"},
    {"symbol": "NVDA", "ticker": "NVDA", "name": "NVIDIA", "market": "us"},
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
        "currency": "TWD" if item["market"] == "taiwan" else "USD",
    }


def build_market_snapshot() -> dict[str, Any]:
    """Build a browser-friendly snapshot; one ticker failure never stops others."""
    from src.event_alerts import build_event_snapshot
    from src.momentum_research import build_momentum_snapshot
    from src.macro_summary import build_macro_summary
    from src.market_history import load_watchlist_history
    from src.research_scan import build_price_action_snapshot
    from src.resonance_scan import build_resonance_snapshot
    from src.value_quality import build_value_snapshot
    from src.risk_news import build_news_snapshot, build_risk_snapshot

    errors: list[dict[str, str]] = []
    quotes: list[dict[str, Any]] = []
    for item in WATCHLIST:
        try:
            quotes.append(get_quote(item))
        except Exception as exc:  # Individual source failures are disclosed in the UI.
            errors.append({"ticker": item["ticker"], "message": str(exc)})
    quote_data_status = "即時" if not errors else "部分缺漏"
    risk = build_risk_snapshot()
    news = build_news_snapshot()
    events = build_event_snapshot(news, quotes)
    macro = build_macro_summary(events, risk)
    histories, history_errors = load_watchlist_history(WATCHLIST)
    research = build_price_action_snapshot(WATCHLIST, histories=histories)
    momentum = build_momentum_snapshot(WATCHLIST, histories=histories)
    resonance = build_resonance_snapshot(WATCHLIST, histories=histories)
    value = build_value_snapshot(WATCHLIST)
    errors.extend({"ticker": "新聞", "message": message} for message in news["errors"])
    for market in ("taiwan", "us"):
        errors.extend({"ticker": risk[market]["label"], "message": message} for message in risk[market]["errors"])
    errors.extend({"ticker": "結構研究", "message": message} for message in research["errors"])
    errors.extend({"ticker": "動能研究", "message": message} for message in momentum["errors"])
    errors.extend({"ticker": "共振研究", "message": message} for message in resonance["errors"])
    errors.extend({"ticker": "價值研究", "message": message} for message in value["errors"])
    errors.extend({"ticker": "歷史資料", "message": message} for message in history_errors)
    return {
        "generated_at": datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
        "data_status": quote_data_status,
        "markets": {key: get_market_status(key) for key in MARKETS},
        "quotes": quotes,
        "risk": risk,
        "news": news,
        "events": events,
        "macro": macro,
        "research": research,
        "momentum": momentum,
        "resonance": resonance,
        "value": value,
        "errors": errors,
    }
