"""TPEx OpenAPI closing-index reader for the public market dashboard."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests


TPEX_INDEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_index"
HEADERS = {"User-Agent": "PRStK-Lab-public-research/1.0"}
TWSE_MIS_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
TAIPEI = ZoneInfo("Asia/Taipei")


def _number(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> str | None:
    text = str(value or "").strip().replace("-", "").replace("/", "")
    if not text:
        return None
    # TPEx has used both Gregorian and ROC-style dates across public feeds.
    if len(text) == 7 and text.isdigit():
        text = str(int(text[:3]) + 1911) + text[3:]
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def _payload_rows(payload: Any) -> list[dict[str, Any]]:
    """Normalise the list/container shapes returned by TPEx public feeds."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "Data", "result", "results", "records", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _field(row: dict[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def parse_tpex_index(payload: Any) -> dict[str, Any] | None:
    """Return the latest two official closes; never infer an intraday quote."""
    rows = []
    for item in _payload_rows(payload):
        quote_date = _date(_field(item, ("Date", "date", "TradingDate", "交易日期", "日期")))
        close = _number(_field(item, ("Close", "close", "Index", "index", "收盤指數", "收盤")))
        if quote_date and close is not None:
            rows.append((quote_date, close, item))
    if not rows:
        return None
    rows.sort(key=lambda item: item[0])
    quote_date, close, latest = rows[-1]
    prior_close = rows[-2][1] if len(rows) >= 2 else None
    change = round(close - prior_close, 2) if prior_close not in (None, 0) else None
    change_percent = round((close / prior_close - 1) * 100, 2) if prior_close not in (None, 0) else None
    return {
        "symbol": "^TWOII",
        "ticker": "TPEx",
        "name": "臺灣櫃買指數",
        "market": "taiwan",
        "currency": "點",
        "price": round(close, 2),
        "previous_close": round(prior_close, 2) if prior_close is not None else None,
        "change": change,
        "change_percent": change_percent,
        "quote_date": quote_date,
        "quote_time": None,
        "quote_source": "TPEx OpenAPI official close",
        "quote_basis": "TPEx 官方最近收盤",
        "quote_delayed": False,
    }


def fetch_tpex_index(session: requests.Session | None = None) -> dict[str, Any] | None:
    client = session or requests.Session()
    response = client.get(TPEX_INDEX_URL, headers=HEADERS, timeout=20)
    response.raise_for_status()
    return parse_tpex_index(response.json())


def parse_twse_mis_tpex(payload: Any) -> dict[str, Any] | None:
    """Parse the official TWSE MIS OTC index row used as a close fallback."""
    rows = payload.get("msgArray") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return None
    row = next((item for item in rows if isinstance(item, dict) and str(item.get("c")) == "o00"), None)
    if row is None:
        return None
    close, previous = _number(row.get("z")), _number(row.get("y"))
    try:
        observed = datetime.fromtimestamp(int(str(row.get("tlong"))) / 1000, tz=TAIPEI)
    except (TypeError, ValueError, OSError):
        return None
    if close is None:
        return None
    return {
        "symbol": "^TWOII",
        "ticker": "TPEx",
        "name": "臺灣櫃買指數",
        "market": "taiwan",
        "currency": "點",
        "price": round(close, 2),
        "previous_close": round(previous, 2) if previous is not None else None,
        "change": round(close - previous, 2) if previous not in (None, 0) else None,
        "change_percent": round((close / previous - 1) * 100, 2) if previous not in (None, 0) else None,
        "quote_date": observed.date().isoformat(),
        "quote_time": observed.isoformat(),
        "quote_source": "TWSE MIS official OTC index",
        "quote_basis": "最近收盤",
        "quote_delayed": True,
        "data_status": "recent_close",
        "fallback_reason": "TPEx OpenAPI 官方資料暫時無法取得",
    }


def fetch_twse_mis_tpex(session: requests.Session | None = None) -> dict[str, Any] | None:
    client = session or requests.Session()
    response = client.get(
        TWSE_MIS_URL,
        params={"ex_ch": "tse_t00.tw|otc_o00.tw", "json": "1", "delay": "0"},
        headers=HEADERS,
        timeout=15,
    )
    response.raise_for_status()
    return parse_twse_mis_tpex(response.json())


def fetch_tpex_yahoo_fallback() -> dict[str, Any] | None:
    """Return a clearly labelled recent close when TPEx OpenAPI is unavailable.

    This is intentionally a fallback only: the official TPEx endpoint remains
    the primary source and its failure is retained in source-health metadata.
    """
    import yfinance as yf

    history = yf.download(
        "^TWOII", period="10d", interval="1d", auto_adjust=False,
        progress=False, threads=False,
    )
    close = history["Close"]
    if getattr(close, "ndim", 1) > 1:
        close = close.iloc[:, 0]
    close = close.dropna()
    if close.empty:
        return None
    latest = float(close.iloc[-1])
    previous = float(close.iloc[-2]) if len(close) >= 2 else None
    return {
        "symbol": "^TWOII",
        "ticker": "TPEx",
        "name": "臺灣櫃買指數",
        "market": "taiwan",
        "currency": "點",
        "price": round(latest, 2),
        "previous_close": round(previous, 2) if previous is not None else None,
        "change": round(latest - previous, 2) if previous not in (None, 0) else None,
        "change_percent": round((latest / previous - 1) * 100, 2) if previous not in (None, 0) else None,
        "quote_date": close.index[-1].date().isoformat(),
        "quote_time": None,
        "quote_source": "Yahoo Finance public daily quote",
        "quote_basis": "最近收盤",
        "quote_delayed": True,
        "data_status": "recent_close",
        "fallback_reason": "TPEx 官方資料暫時無法取得",
    }


def fetch_tpex_recent_close_fallback() -> dict[str, Any] | None:
    """Prefer the official TWSE MIS OTC row, then use Yahoo as last resort."""
    try:
        official = fetch_twse_mis_tpex()
        if official:
            return official
    except Exception:
        pass
    try:
        return fetch_tpex_yahoo_fallback()
    except Exception:
        return None
