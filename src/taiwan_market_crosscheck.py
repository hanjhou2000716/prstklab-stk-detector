"""Official Taiwan market observations used to guard intraday TAIEX alerts.

This module deliberately treats the TWSE public MIS observation as the market
index price and the TAIFEX public TXF observation as a direction check.  A
futures price is not identical to the cash index, so it is never substituted
for TAIEX or compared point-for-point.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

from src.market_data import change_percent

TAIPEI = ZoneInfo("Asia/Taipei")
TWSE_MIS_TAIEX_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
TAIFEX_QUOTE_URL = "https://mis.taifex.com.tw/futures/api/getQuoteList"
HEADERS = {"User-Agent": "PRStK-Lab-public-research/1.0"}


def _number(value: Any) -> float | None:
    try:
        parsed = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _mis_time(row: dict[str, Any]) -> datetime | None:
    try:
        value = int(str(row.get("tlong") or ""))
        return datetime.fromtimestamp(value / 1000, tz=TAIPEI)
    except (TypeError, ValueError, OSError):
        return None


def parse_twse_taiex(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Parse one public TWSE MIS TAIEX observation without guessing fields."""
    rows = payload.get("msgArray") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return None
    row = next((item for item in rows if isinstance(item, dict) and str(item.get("c")) == "t00"), None)
    if row is None:
        return None
    price, previous = _number(row.get("z")), _number(row.get("y"))
    observed = _mis_time(row)
    if price is None or previous is None or observed is None:
        return None
    return {
        "ticker": "TAIEX",
        "price": round(price, 2),
        "previous_close": round(previous, 2),
        "change": round(price - previous, 2),
        "change_percent": change_percent(price, previous),
        "quote_date": observed.date().isoformat(),
        "quote_time": observed.isoformat(),
        "source": "TWSE MIS 公開市況",
    }


def parse_taifex_txf(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Parse the current-session TXF quote exposed by TAIFEX public MIS."""
    try:
        rows = payload["RtData"]["QuoteList"]
    except (KeyError, TypeError):
        return None
    row = next((item for item in rows if isinstance(item, dict) and item.get("SymbolID") == "TXF-S"), None)
    if row is None:
        return None
    price, previous = _number(row.get("CLastPrice")), _number(row.get("CRefPrice"))
    raw_date, raw_time = str(row.get("CDate") or ""), str(row.get("CTime") or "").zfill(6)
    try:
        observed = datetime.strptime(f"{raw_date}{raw_time}", "%Y%m%d%H%M%S").replace(tzinfo=TAIPEI)
    except ValueError:
        observed = None
    if price is None or previous is None or observed is None:
        return None
    return {
        "ticker": "TXF",
        "price": round(price, 2),
        "previous_close": round(previous, 2),
        "change": round(price - previous, 2),
        "change_percent": change_percent(price, previous),
        "quote_date": observed.date().isoformat(),
        "quote_time": observed.isoformat(),
        "source": "TAIFEX 公開市況",
    }


def fetch_twse_taiex(session: requests.Session | None = None) -> dict[str, Any] | None:
    client = session or requests.Session()
    response = client.get(
        TWSE_MIS_TAIEX_URL,
        params={"ex_ch": "tse_t00.tw", "json": "1", "delay": "0"},
        headers=HEADERS,
        timeout=15,
    )
    response.raise_for_status()
    return parse_twse_taiex(response.json())


def fetch_taifex_txf(session: requests.Session | None = None) -> dict[str, Any] | None:
    client = session or requests.Session()
    response = client.post(
        TAIFEX_QUOTE_URL,
        json={"cmd": "1", "ex": "1", "sid": "TXF", "lang": "zh_TW"},
        headers=HEADERS,
        timeout=15,
    )
    response.raise_for_status()
    return parse_taifex_txf(response.json())


def _same_direction(first: float | None, second: float | None) -> bool:
    if first is None or second is None:
        return False
    if abs(first) < 0.05 or abs(second) < 0.05:
        return True
    return (first > 0) == (second > 0)


def crosscheck_taiex_quote(
    quote: dict[str, Any], *,
    twse: dict[str, Any] | None,
    taifex: dict[str, Any] | None,
) -> dict[str, Any]:
    """Use TWSE as the TAIEX observation and require TXF direction agreement.

    The original aggregated quote remains in metadata so a source discrepancy
    can be inspected.  If either official observation is missing or their
    directions conflict, ``crosscheck_status`` blocks urgent price alerts.
    """
    source_observations = [
        {
            "provider": "TWSE",
            "label": "TWSE",
            "source_url": TWSE_MIS_TAIEX_URL,
            "url": TWSE_MIS_TAIEX_URL,
            "quote_time": (twse or {}).get("quote_time") or "",
            "quote_date": (twse or {}).get("quote_date"),
            "price": (twse or {}).get("price"),
            "change_percent": (twse or {}).get("change_percent"),
            "available": bool(twse),
        },
        {
            "provider": "TAIFEX",
            "label": "TAIFEX",
            "source_url": TAIFEX_QUOTE_URL,
            "url": TAIFEX_QUOTE_URL,
            "quote_time": (taifex or {}).get("quote_time") or "",
            "quote_date": (taifex or {}).get("quote_date"),
            "price": (taifex or {}).get("price"),
            "change_percent": (taifex or {}).get("change_percent"),
            "available": bool(taifex),
        },
    ]
    if not twse or not taifex:
        return {
            **quote,
            "crosscheck_status": "官方來源部分缺漏",
            "crosscheck_sources": source_observations,
            "quote_delayed": True,
        }

    confirmed = _same_direction(twse.get("change_percent"), taifex.get("change_percent"))
    aggregated_price = quote.get("price")
    price_gap_percent = None
    try:
        aggregate_value = float(str(aggregated_price))
        if aggregate_value > 0:
            price_gap_percent = round((float(twse["price"]) / aggregate_value - 1) * 100, 2)
    except (TypeError, ValueError, KeyError):
        pass
    status = "已交叉核對" if confirmed else "現貨期貨方向不一致"
    return {
        **quote,
        "price": twse["price"],
        # The official cash-index observation owns the comparison baseline.
        # Keeping the Yahoo baseline here can make the displayed price,
        # point change, and percentage change disagree after the cross-check.
        "previous_close": twse.get("previous_close", quote.get("previous_close")),
        "change": twse["change"],
        "change_percent": twse["change_percent"],
        "quote_date": twse["quote_date"],
        "quote_time": twse["quote_time"],
        "quote_source": "TWSE MIS cash index + TAIFEX public direction cross-check",
        "quote_basis": "TWSE 公開市況；TAIFEX 台指期方向核對",
        # The official cash/futures pair replaces the Yahoo observation. Do
        # not carry a stale marker from that replaced observation forward when
        # both official sources agree.
        "stale_used": not confirmed,
        "quote_delayed": not confirmed,
        "crosscheck_status": status,
        "crosscheck_sources": source_observations,
        "aggregated_price_gap_percent": price_gap_percent,
    }
