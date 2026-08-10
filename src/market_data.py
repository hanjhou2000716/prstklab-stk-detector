"""Public-market quote collection and Taiwan/US session detection."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.intel_contract import normalize_quote_record

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
    {"symbol": "^TWOII", "ticker": "TPEx", "name": "臺灣櫃買指數", "market": "taiwan", "currency": "點"},
    {"symbol": "^GSPC", "ticker": "S&P 500", "name": "標普 500", "market": "us", "currency": "點"},
    {"symbol": "^IXIC", "ticker": "NASDAQ", "name": "那斯達克綜合指數", "market": "us", "currency": "點"},
    {"symbol": "^DJI", "ticker": "DJIA", "name": "道瓊工業指數", "market": "us", "currency": "點"},
    {"symbol": "^SOX", "ticker": "SOX", "name": "費城半導體指數", "market": "us", "currency": "點"},
    {"symbol": "^N225", "ticker": "NIKKEI", "name": "日經225", "market": "asia", "currency": "點"},
    {"symbol": "^KS11", "ticker": "KOSPI", "name": "韓國綜合", "market": "asia", "currency": "點"},
    {"symbol": "BZ=F", "ticker": "BRENT", "name": "Brent 原油", "market": "global", "currency": "USD"},
    {"symbol": "CL=F", "ticker": "WTI", "name": "WTI 原油", "market": "global", "currency": "USD"},
    {"symbol": "GC=F", "ticker": "GOLD", "name": "黃金期貨", "market": "global", "currency": "USD"},
    {"symbol": "BTC-USD", "ticker": "BTC", "name": "比特幣", "market": "global", "currency": "USD"},
    {"symbol": "ETH-USD", "ticker": "ETH", "name": "以太坊", "market": "global", "currency": "USD"},
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


def _technical_context(closes: Any, *, window: int = 20, long_window: int = 60) -> dict[str, Any]:
    """Summarise a quote's recent price location without issuing a signal.

    The noon report needs the same kind of context a human reader gets from a
    chart: a recent range, the current location in that range, and whether the
    quote is near the range boundary.  This is deliberately descriptive (not a
    buy/sell rule) and is kept on the quote record so every report can cite the
    same calculation.
    """
    try:
        series = closes.dropna()
        recent = series.tail(window)
        long = series.tail(long_window)
        if len(recent) < 5:
            return {"window_days": int(len(recent)), "long_window_days": int(len(long)), "status": "insufficient"}
        low = float(recent.min())
        high = float(recent.max())
        long_low = float(long.min())
        long_high = float(long.max())
        latest = float(recent.iloc[-1])
        span = high - low
        position = 50.0 if span <= 0 else (latest - low) / span * 100
        if position <= 25:
            zone = "接近20日支撐區"
        elif position >= 75:
            zone = "接近20日壓力區"
        else:
            zone = "位於20日區間中段"
        return {
            "window_days": int(len(recent)),
            "long_window_days": int(len(long)),
            "low": round(low, 2),
            "high": round(high, 2),
            "long_low": round(long_low, 2),
            "long_high": round(long_high, 2),
            "position_pct": round(position, 1),
            "zone": zone,
            "as_of": str(series.index[-1].date()),
            "status": "ok",
        }
    except Exception:
        return {"window_days": 0, "status": "unavailable"}


def _daily_quote(item: dict[str, str], closes: Any) -> dict[str, Any]:
    """Build a clearly labelled quote from the latest completed daily bars."""
    if len(closes) < 2:
        raise ValueError("可用收盤資料不足。")
    latest, previous = float(closes.iloc[-1]), float(closes.iloc[-2])
    return normalize_quote_record({
        **item,
        "price": round(latest, 2),
        "previous_close": round(previous, 2),
        "change": round(latest - previous, 2),
        "change_percent": change_percent(latest, previous),
        "quote_date": closes.index[-1].date().isoformat(),
        "quote_time": None,
        "quote_basis": "日線收盤",
        "quote_source": "Yahoo Finance public daily quote",
        "source_url": f"https://finance.yahoo.com/quote/{item['symbol']}",
        "currency": item.get("currency") or ("TWD" if item["market"] == "taiwan" else "USD"),
        "technical_context": _technical_context(closes),
    })


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
    return normalize_quote_record({
        **item,
        "price": round(latest, 2),
        "previous_close": round(previous_close, 2),
        "change": round(latest - previous_close, 2),
        "change_percent": change_percent(latest, previous_close),
        "change_15m_percent": change_15m_percent,
        "quote_date": timestamp.date().isoformat(),
        "quote_time": timestamp.isoformat(),
        "quote_basis": basis,
        "quote_delayed": delayed,
        "quote_source": "Yahoo Finance public 5-minute quote",
        "source_url": f"https://finance.yahoo.com/quote/{item['symbol']}",
        "currency": item.get("currency") or ("TWD" if item["market"] == "taiwan" else "USD"),
        "technical_context": _technical_context(daily_closes),
    })


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


def _latest_completed_session_date(quote: dict[str, Any], reference: datetime) -> date:
    """Return the most recent completed trading date for a public quote.

    A daily bar during a live session is normally yesterday's close, so it is
    still useful but must never be labelled as a delayed live quote.  Once the
    next market close has passed, the same bar becomes stale.  Crypto is the
    exception because it trades every calendar day.
    """
    ticker = str(quote.get("ticker") or "")
    market = str(quote.get("market") or "global")
    if ticker in {"BTC", "ETH"}:
        # Binance/CoinGecko and Yahoo crypto daily bars are keyed to UTC.
        # Comparing them with the Taipei calendar turns a valid quote into a
        # false stale state during 00:00–08:00 Asia/Taipei, which can suppress
        # otherwise valid cross-asset observations and distort the aggregate
        # market health label.
        return reference.astimezone(ZoneInfo("UTC")).date()

    market_config = MARKETS.get(market)
    if market_config:
        import pandas_market_calendars as mcal

        timezone = ZoneInfo(market_config["timezone"])
        local_now = reference.astimezone(timezone)
        calendar = mcal.get_calendar(market_config["calendar"])
        schedule = calendar.schedule(
            start_date=local_now.date() - timedelta(days=10),
            end_date=local_now.date(),
        )
        if not schedule.empty:
            latest = schedule.index[-1].date()
            market_close = schedule.iloc[-1]["market_close"].to_pydatetime().astimezone(timezone)
            if latest == local_now.date() and local_now < market_close and len(schedule) >= 2:
                return schedule.index[-2].date()
            return latest

    # Japan, Korea, futures and cash references use the most recent weekday
    # when an official exchange calendar is not available in this project.
    local_day = reference.astimezone(ZoneInfo("Asia/Taipei")).date()
    while local_day.weekday() >= 5:
        local_day -= timedelta(days=1)
    return local_day


def quote_freshness(quote: dict[str, Any], *, now: datetime | None = None) -> str:
    """Classify a quote by its latest expected market observation date."""
    # Keep an unavailable official quote distinct from an old close or an
    # unparseable timestamp.  The UI and source-health card can then disclose
    # the gap instead of treating an empty row as a current quote.
    if quote.get("price") is None and not (quote.get("quote_time") or quote.get("quote_date")):
        return "unavailable"
    reference = now or datetime.now(ZoneInfo("Asia/Taipei"))
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=ZoneInfo("Asia/Taipei"))
    try:
        observed = datetime.fromisoformat(str(quote.get("quote_time") or quote.get("quote_date"))).date()
    except ValueError:
        return "unknown"
    expected = _latest_completed_session_date(quote, reference)
    if observed < expected:
        return "stale"
    if quote.get("quote_time") and not quote.get("quote_delayed"):
        try:
            timestamp = datetime.fromisoformat(str(quote["quote_time"]))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=reference.tzinfo)
            if reference.astimezone(ZoneInfo("UTC")) - timestamp.astimezone(ZoneInfo("UTC")) <= timedelta(minutes=15):
                return "live"
        except ValueError:
            return "unknown"
    return "recent_close"


def annotate_quote_freshness(quotes: list[dict[str, Any]], *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Expose stale data to the UI and health source instead of silently showing it."""
    annotated: list[dict[str, Any]] = []
    for quote in quotes:
        item = dict(quote)
        freshness = quote_freshness(item, now=now)
        # A fallback/cache marker is authoritative for alert safety. Some
        # official cross-checks preserve a current timestamp from the source
        # they replaced; that timestamp must not upgrade stale data to live.
        if item.get("stale_used") is True and freshness == "live":
            freshness = quote_freshness({**item, "quote_delayed": True}, now=now)
        item["freshness"] = freshness
        item["data_status"] = {
            "live": "盤中",
            "recent_close": "最近收盤",
            "stale": "資料過期",
            "unavailable": "暫無資料",
        }.get(freshness, "時間待核對")
        # A delayed or close-only quote can remain visible, but cannot create a
        # high-risk alert.  This is the hard freshness gate from the TXT.
        if freshness != "live" or item.get("stale_used") is True or item.get("quote_delayed") is True:
            item["alert_eligible"] = False
        annotated.append(item)
    return annotated


def summarize_market_freshness(quotes: list[dict[str, Any]]) -> dict[str, Any]:
    """Return one honest aggregate state without hiding per-card freshness.

    ``quote_time`` alone is not sufficient: a provider can return an old
    daily bar with a new fetch timestamp.  Aggregate state is therefore based
    on the already-classified ``freshness`` field.
    """
    counts = {"live": 0, "recent_close": 0, "stale": 0, "unavailable": 0}
    for quote in quotes:
        state = str(quote.get("freshness") or "unavailable")
        counts[state if state in counts else "unavailable"] += 1
    total = sum(counts.values())
    if not total or counts["unavailable"] == total:
        overall = "unavailable"
    elif counts["stale"] or counts["unavailable"]:
        overall = "degraded"
    elif counts["live"] and counts["recent_close"]:
        overall = "mixed"
    elif counts["live"]:
        overall = "live"
    else:
        overall = "close_only"
    return {
        "overall_state": overall,
        "live_count": counts["live"],
        "recent_close_count": counts["recent_close"],
        "stale_count": counts["stale"],
        "unavailable_count": counts["unavailable"],
    }


def market_data_status(summary: dict[str, Any]) -> str:
    """Render an honest aggregate label from the classified freshness state."""
    return {
        "live": "即時",
        "mixed": "混合資料",
        "close_only": "最近收盤",
        "degraded": "部分缺漏",
        "unavailable": "無法取得",
    }.get(str(summary.get("overall_state") or ""), "無法取得")


def get_quote(item: dict[str, str], session: str | None = None) -> dict[str, Any]:
    """Collect a five-minute live bar when eligible, otherwise a daily close."""
    import yfinance as yf

    history = yf.download(
        # Keep enough completed sessions for the report's 20-day support /
        # resistance context.  The payload remains small compared with the
        # research scans and avoids making a second provider request.
        item["symbol"], period="3mo", interval="1d", auto_adjust=False,
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
    tpex_fetcher: Any | None = None, tpex_fallback_fetcher: Any | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Replace an in-session TAIEX quote only after official source checks.

    TWSE public MIS supplies the cash-index observation.  TAIFEX's TXF public
    observation is deliberately a direction check, not a point-price proxy.
    A failed official call leaves the existing quote visible but marks it as
    non-actionable for an urgent TAIEX price alert.
    """
    from src.tpex_index import fetch_tpex_index
    if not session:
        # Callers that do not provide a market session are asking for a
        # structural merge, not a live official-source health verdict.
        return indices, []
    tpex_fetcher = tpex_fetcher or fetch_tpex_index
    tpex_metadata = next((item for item in MARKET_INDICES if item.get("ticker") == "TPEx"), {})
    errors: list[dict[str, str]] = []
    tpex = None
    tpex_fallback_used = False
    had_tpex_row = any(item.get("ticker") == "TPEx" for item in indices)
    # Attempt the official close even when Yahoo failed before creating TPEx.
    try:
        tpex = tpex_fetcher()
    except Exception as exc:
        # TPEx is auxiliary during a TAIEX intraday cross-check. A transient
        # outage must not block the primary TWSE/TAIFEX check.
        if had_tpex_row or session != "交易中":
            errors.append({"ticker": "TPEx", "message": f"TPEx 官方指數暫時無法取得：{type(exc).__name__}", "scope": "index"})
    if not tpex and tpex_fallback_fetcher is not None:
        try:
            tpex = tpex_fallback_fetcher()
            tpex_fallback_used = bool(tpex)
        except Exception as exc:
            if had_tpex_row or session != "交易中":
                errors.append({"ticker": "TPEx", "message": f"TPEx 最近收盤備援失敗：{type(exc).__name__}", "scope": "index"})
    if tpex_fallback_used:
        # A verified official MIS close (or a labelled public close as the
        # final fallback) keeps the card actionable; do not count the primary
        # endpoint outage as a market-data gap when a value was recovered.
        errors = [error for error in errors if error.get("ticker") != "TPEx"]
    if not tpex:
        # Keep the TPEx row visible when both public endpoints fail.  It is
        # deliberately non-actionable and is surfaced as a source gap rather
        # than silently disappearing from the market list.
        # During a TAIEX intraday cross-check, TPEx is an auxiliary index. Do
        # not turn its optional absence into a global quote failure unless the
        # caller explicitly requested a TPEx row or this is an off-session
        # dashboard refresh where the row itself is actionable.
        if (had_tpex_row or session != "交易中") and not errors:
            errors.append({"ticker": "TPEx", "message": "TPEx official endpoint returned no data", "scope": "index"})
        if not any(item.get("ticker") == "TPEx" for item in indices):
            tpex = {
                "ticker": "TPEx",
                "name": "臺灣櫃買指數",
                "market": "taiwan",
                "currency": "點",
                "price": None,
                "previous_close": None,
                "change": None,
                "change_percent": None,
                "quote_date": None,
                "quote_time": None,
                "quote_source": "TPEx OpenAPI official close",
                "quote_basis": "TPEx 官方資料暫時無法取得",
                "quote_delayed": True,
                "data_status": "unavailable",
            }
            indices = [*indices, tpex]
    elif not any(item.get("ticker") == "TPEx" for item in indices):
        # Official endpoints may return only price fields. Always retain the
        # canonical label so the Mini App never renders a bare TPEx row.
        indices = [*indices, {**tpex_metadata, **tpex}]
    if session != "交易中":
        merged_indices: list[dict[str, Any]] = []
        for item in indices:
            if item.get("ticker") != "TPEx" or not tpex:
                merged_indices.append(item)
                continue
            merged = {**tpex_metadata, **item, **tpex}
            source = str(merged.get("quote_source") or "").lower()
            merged["source_label"] = str(
                tpex.get("source_label")
                or ("TWSE" if "twse" in source or "mis" in source
                    else "Yahoo" if "yahoo" in source else "TPEx")
            )
            merged_indices.append(merged)
        return merged_indices, errors
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
            merged = {**tpex_metadata, **item, **tpex}
            source = str(merged.get("quote_source") or "").lower()
            merged["source_label"] = str(
                tpex.get("source_label")
                or ("TWSE" if "twse" in source or "mis" in source
                    else "Yahoo" if "yahoo" in source else "TPEx")
            )
            checked.append(merged)
        else:
            checked.append(item)
    return checked, errors


def apply_crypto_spot_crosscheck(
    indices: list[dict[str, Any]], spot_snapshot: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Use Binance spot as the primary BTC/ETH quote and CoinGecko as proof.

    The two providers are intentionally optional. If either is unavailable the
    existing card remains visible and is marked unverified rather than being
    replaced by a fabricated or stale value.
    """
    from src.market_crosscheck import compare_quotes

    snapshot = spot_snapshot or {}
    primary_quotes = snapshot.get("primary") or {}
    secondary_quotes = snapshot.get("secondary") or {}
    checked: list[dict[str, Any]] = []
    for item in indices:
        ticker = str(item.get("ticker") or "")
        if ticker not in {"BTC", "ETH"}:
            checked.append(item)
            continue
        primary = primary_quotes.get(ticker)
        secondary = secondary_quotes.get(ticker)
        if primary:
            result = compare_quotes(primary, secondary, max_age_minutes=60, max_gap_percent=2.0)
            merged = {**item, **primary}
            # The primary provider wins the displayed provenance.  Without
            # this assignment a Yahoo card can retain ``source_label=Yahoo``
            # while its URL/domain is Binance.US, making the release manifest
            # correctly reject an otherwise valid crypto observation.
            merged["source_label"] = "Binance"
            merged["quote_source"] = primary.get("quote_source") or "Binance public spot quote"
            merged["name"] = item.get("name") or primary.get("ticker")
            merged["market"] = item.get("market") or "global"
            merged["currency"] = item.get("currency") or "USD"
            merged["quote_date"] = str(primary.get("quote_time") or "")[:10] or item.get("quote_date")
            merged["cross_checked"] = bool(result.get("cross_checked"))
            merged["crosscheck_status"] = "已交叉核對" if result.get("cross_checked") else str(result.get("status") or "未交叉核對")
            merged["crosscheck_sources"] = [
                {"label": "Binance", "url": primary.get("source_url", ""), "quote_time": primary.get("quote_time", "")},
                {"label": "CoinGecko", "url": (secondary or {}).get("source_url", ""), "quote_time": (secondary or {}).get("quote_time", "")},
            ]
            checked.append(merged)
        else:
            checked.append({
                **item,
                "cross_checked": False,
                "crosscheck_status": "primary_unavailable",
                "crosscheck_sources": [
                    {"label": "Binance", "url": ""},
                    {"label": "CoinGecko", "url": (secondary or {}).get("source_url", "")},
                ],
            })
    return checked


def apply_public_market_secondary_crosscheck(
    indices: list[dict[str, Any]], secondary_snapshot: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Attach Stooq proof to Yahoo-based index and commodity cards.

    The primary Yahoo observation remains the displayed price.  Stooq is only
    a second observation used for the verification flag and provenance fields.
    """
    from src.market_crosscheck import MARKET_SOURCE_PAIRS, compare_quotes

    secondary_quotes = (secondary_snapshot or {}).get("quotes") or {}
    checked: list[dict[str, Any]] = []
    for item in indices:
        ticker = str(item.get("ticker") or "")
        expected = MARKET_SOURCE_PAIRS.get(ticker)
        secondary = secondary_quotes.get(ticker)
        if not secondary:
            # Dedicated official/crypto checks handle these instruments.
            # All other expected pairs expose the missing second source
            # explicitly instead of silently leaving a quote unverified.
            if expected and ticker not in {"TAIEX", "TPEx", "BTC", "ETH"}:
                merged = dict(item)
                merged["cross_checked"] = False
                merged["crosscheck_status"] = "secondary_unavailable"
                merged["crosscheck_reason"] = "secondary_source_unavailable"
                merged["expected_sources"] = list(expected)
                merged["crosscheck_sources"] = [
                    {
                        "label": expected[0],
                        "url": item.get("source_url", ""),
                        "quote_time": item.get("quote_time") or item.get("quote_date", ""),
                    },
                    {"label": expected[1], "url": "", "quote_time": ""},
                ]
                checked.append(merged)
            else:
                checked.append(item)
            continue
        result = compare_quotes(item, secondary, max_age_minutes=24 * 60, max_gap_percent=3.0)
        merged = dict(item)
        merged["cross_checked"] = bool(result.get("cross_checked"))
        merged["crosscheck_reason"] = "sources_aligned" if result.get("cross_checked") else "price_or_time_mismatch"
        if expected:
            merged["expected_sources"] = list(expected)
        merged["crosscheck_status"] = "已交叉核對" if result.get("cross_checked") else str(result.get("status") or "未交叉核對")
        merged["crosscheck_sources"] = [
            {
                "label": "Yahoo",
                "url": item.get("source_url", ""),
                "quote_time": item.get("quote_time") or item.get("quote_date", ""),
            },
            {
                "label": "Nasdaq" if secondary.get("source_domain") == "api.nasdaq.com" else "Stooq",
                "url": secondary.get("source_url", ""),
                "quote_time": secondary.get("quote_time") or secondary.get("quote_date", ""),
            },
        ]
        checked.append(merged)
    return checked


def build_market_snapshot() -> dict[str, Any]:
    from src.adapters.catalog import build_adapter_catalog

    """Build a browser-friendly snapshot; one ticker failure never stops others."""
    from src.briefing_cards import build_briefing_snapshot
    from src.event_alerts import build_event_snapshot
    from src.macro_program_feed import fetch_yutinghao_latest_program
    from src.macro_summary import build_macro_summary
    from src.official_events import fetch_official_events
    from src.phase_two_sources import build_phase_two_snapshot
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
    from src.tpex_index import fetch_tpex_recent_close_fallback
    indices, crosscheck_errors = apply_taiwan_intraday_crosscheck(
        indices,
        markets.get("taiwan", {}).get("session", ""),
        tpex_fallback_fetcher=fetch_tpex_recent_close_fallback,
    )
    errors.extend(crosscheck_errors)
    # A Yahoo failure is informational only when TPEx has been restored by
    # any validated fallback (TWSE MIS official close or a labelled public
    # recent close).  Do not retain the original provider error as a health
    # warning when the card is actually usable.
    if any(
        item.get("ticker") == "TPEx"
        and item.get("price") is not None
        for item in indices
    ):
        errors = [error for error in errors if error.get("ticker") != "TPEx"]
    quotes = annotate_quote_freshness(quotes)
    indices = annotate_quote_freshness(indices)
    from src.production_evidence import (
        bind_market_evidence,
        quality_summary,
        raw_observation_store_summary,
        record_market_snapshot_observation,
    )

    quotes = bind_market_evidence(quotes)
    indices = bind_market_evidence(indices)
    for item in [*quotes, *indices]:
        if item.get("freshness") in {"stale", "unavailable"}:
            errors.append({
                "ticker": item.get("ticker", "公開報價"),
                "message": (
                    f"{item.get('ticker', '公開報價')} 官方／公開報價暫時無法取得"
                    if item.get("freshness") == "unavailable"
                    else f"{item.get('ticker', '公開報價')} 報價已逾三日，已標示為過期資料"
                ),
                "scope": "index" if item in indices else "",
            })
    macro_quotes: list[dict[str, Any]] = []
    for item in MACRO_REFERENCES:
        try:
            macro_quotes.append(get_quote(item, None))
        except Exception as exc:
            errors.append({"ticker": item["ticker"], "message": str(exc), "scope": "macro_quote"})
    macro_quotes = [normalize_quote_record(item) for item in macro_quotes]
    risk = build_risk_snapshot()
    news = build_news_snapshot()
    official_events = fetch_official_events()
    phase_two = build_phase_two_snapshot()
    # Phase 5: crypto spot prices are independently checked after the regular
    # Yahoo/index pass. Re-annotate freshness because Binance is intraday.
    indices = apply_crypto_spot_crosscheck(indices, phase_two.get("crypto_spot"))
    indices = apply_public_market_secondary_crosscheck(
        indices, phase_two.get("public_market_secondary")
    )
    indices = bind_market_evidence(annotate_quote_freshness(indices))
    events = build_event_snapshot(news, quotes, official_events, indices=indices)
    try:
        program = fetch_yutinghao_latest_program()
    except Exception:
        # The programme feed is optional. Its absence must not mark core
        # market data as unhealthy when YouTube changes a channel feed.
        program = None
    macro = build_macro_summary(events, risk, program)
    research_report = load_research_cards()
    monitor_health: dict[str, Any] = {}
    monitor_health_path = Path("site/data/monitor-health.json")
    try:
        if monitor_health_path.exists():
            loaded_monitor_health = json.loads(monitor_health_path.read_text(encoding="utf-8"))
            if isinstance(loaded_monitor_health, dict):
                monitor_health = loaded_monitor_health
    except (OSError, ValueError, TypeError):
        # Optional diagnostics must never block the core market snapshot.
        monitor_health = {}
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
        official_sources=official_events.get("source_health", []),
        news_sources=news.get("source_health", []),
        additional_sources=phase_two.get("sources", []),
        monitor_health=monitor_health,
        quote_evidence={
            "quotes": quality_summary(quotes),
            "indices": quality_summary(indices),
        },
    )
    freshness_summary = summarize_market_freshness([*quotes, *indices])
    live_quotes = freshness_summary["live_count"]
    close_quotes = freshness_summary["recent_close_count"] + freshness_summary["stale_count"]
    # The aggregate label must follow classified quote freshness, not merely
    # whether an unrelated optional provider returned an error.  A close-only
    # snapshot must never be advertised as "即時".
    data_status = market_data_status(freshness_summary)
    snapshot = {
        "generated_at": scan_completed_at.isoformat(),
        "scan": {
            "started_at": scan_started_at.isoformat(),
            "completed_at": scan_completed_at.isoformat(),
            "scope": "公開市場定時掃描",
            "live_quote_count": live_quotes,
            "close_quote_count": close_quotes,
            **freshness_summary,
        },
        **freshness_summary,
        "data_status": data_status,
        "markets": markets,
        "indices": indices,
        "quotes": quotes,
        "risk": risk,
        "news": news,
        "events": events,
        "official_events": official_events,
        "phase_two": phase_two,
        "macro": macro,
        "macro_quotes": macro_quotes,
        "briefing": build_briefing_snapshot({
            "events": events, "indices": indices, "quotes": quotes,
            "macro_quotes": macro_quotes, "risk": risk,
        }),
        "research_report": research_report,
        "source_health": source_health,
        "source_catalog": build_adapter_catalog(),
        "evidence": {
            "quotes": quality_summary(quotes),
            "indices": quality_summary(indices),
        },
        "raw_observation_store": raw_observation_store_summary(),
        "errors": errors,
    }
    observation = record_market_snapshot_observation(snapshot)
    snapshot["raw_observation_store"] = {
        **snapshot.get("raw_observation_store", {}),
        **observation,
    }
    return snapshot
