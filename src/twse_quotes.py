"""Official TWSE daily security observations used before Yahoo fallback."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

TWSE_STOCK_DAY_ALL_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TAIPEI = ZoneInfo("Asia/Taipei")
HEADERS = {"User-Agent": "PRStK-Lab-public-research/1.0"}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed and abs(parsed) != float("inf") else None


def _date(value: Any) -> str | None:
    raw = str(value or "").strip().replace("/", "").replace("-", "")
    if len(raw) == 7 and raw.isdigit():
        raw = f"{int(raw[:3]) + 1911}{raw[3:]}"
    if len(raw) != 8 or not raw.isdigit():
        return None
    try:
        return datetime.strptime(raw, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def _signed_change(row: dict[str, Any]) -> float | None:
    value = _number(row.get("漲跌價差") or row.get("Change") or row.get("change"))
    if value is None:
        return None
    sign = str(row.get("漲跌(+/-)") or row.get("漲跌") or row.get("Sign") or "").strip()
    if sign in {"-", "−", "負"}:
        return -abs(value)
    if sign in {"+", "正"}:
        return abs(value)
    return value


def _ticker(row: dict[str, Any]) -> str:
    return str(row.get("證券代號") or row.get("Code") or row.get("ticker") or "").strip()


def parse_twse_stock_day_all(payload: Any, *, observed_date: str | None = None) -> dict[str, dict[str, Any]]:
    """Parse the current TWSE all-stock feed without filling missing fields."""
    rows = payload if isinstance(payload, list) else []
    fallback_date = _date(observed_date) or datetime.now(TAIPEI).date().isoformat()
    parsed: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = _ticker(row)
        close = _number(row.get("收盤價") or row.get("ClosingPrice") or row.get("close"))
        if not ticker or close is None or close <= 0:
            continue
        change = _signed_change(row)
        previous = close - change if change is not None else None
        if change is not None and previous not in (None, 0):
            assert previous is not None
            percent = round(change / previous * 100, 2)
        else:
            percent = None
        date_value = _date(row.get("日期") or row.get("Date") or fallback_date) or fallback_date
        parsed[ticker] = {
            "symbol": f"{ticker}.TW",
            "ticker": ticker,
            "name": str(row.get("證券名稱") or row.get("Name") or ticker).strip(),
            "market": "taiwan",
            "currency": "TWD",
            "price": round(close, 2),
            "previous_close": round(previous, 2) if previous is not None else None,
            "change": round(change, 2) if change is not None else None,
            "change_percent": percent,
            "quote_date": date_value,
            "quote_time": None,
            "quote_source": "TWSE OpenAPI official daily quote",
            "source_label": "TWSE",
            "source_tier": "official",
            "source_url": TWSE_STOCK_DAY_ALL_URL,
            "quote_basis": "TWSE 官方日線收盤",
            "quote_delayed": False,
            "stale_used": False,
        }
    return parsed


def fetch_twse_stock_day_all(
    session: requests.Session | None = None, *, observed_date: str | None = None,
) -> dict[str, dict[str, Any]]:
    client = session or requests.Session()
    response = client.get(TWSE_STOCK_DAY_ALL_URL, headers=HEADERS, timeout=20)
    response.raise_for_status()
    return parse_twse_stock_day_all(response.json(), observed_date=observed_date)


__all__ = ["TWSE_STOCK_DAY_ALL_URL", "fetch_twse_stock_day_all", "parse_twse_stock_day_all"]
