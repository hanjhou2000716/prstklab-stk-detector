"""Official Taiwan daily market breadth, turnover and institution evidence."""

from __future__ import annotations

import os
import time
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

TWSE_FMTQIK_URL = "https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK"
TWSE_BREADTH_URL = "https://openapi.twse.com.tw/v1/opendata/twtazu_od"
TWSE_INSTITUTION_URL = "https://www.twse.com.tw/rwd/zh/fund/BFI82U"
HEADERS = {"User-Agent": "PRStK-Lab-public-research/1.0"}


def _number(value: Any) -> int | None:
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    # TWSE often publishes ROC dates with slashes (for example 115/09/07).
    # Convert that form before the Gregorian parser can interpret year 115.
    parts = raw.split("/")
    if len(parts) == 3 and len(parts[0]) == 3 and all(part.isdigit() for part in parts):
        try:
            return date(int(parts[0]) + 1911, int(parts[1]), int(parts[2])).isoformat()
        except ValueError:
            return None
    for fmt in ("%Y%m%d", "%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    # TWSE OpenAPI dates are often Republic of China years, e.g. 1150907.
    if len(raw) == 7 and raw.isdigit():
        try:
            year = int(raw[:3]) + 1911
            return date(year, int(raw[3:5]), int(raw[5:7])).isoformat()
        except ValueError:
            return None
    return None


def parse_twse_market_statistics(
    *,
    turnover_rows: Any = None,
    breadth_rows: Any = None,
    institution_payload: Any = None,
    target_date: str | None = None,
) -> dict[str, Any]:
    """Parse the three official payloads without filling missing fields."""
    errors: list[str] = []
    turnover: dict[str, Any] | None = None
    breadth: dict[str, Any] | None = None
    institutional: dict[str, Any] | None = None

    rows = turnover_rows if isinstance(turnover_rows, list) else []
    row = next((item for item in reversed(rows) if isinstance(item, dict)), None)
    if row:
        observed = _date(row.get("Date") or row.get("日期"))
        if target_date and observed and observed != target_date:
            row = None
        else:
            turnover = {
                "observed_date": observed,
                "trade_volume": _number(row.get("TradeVolume")),
                "trade_value": _number(row.get("TradeValue")),
                "transactions": _number(row.get("Transaction")),
                "taiex": row.get("TAIEX"),
                "change": row.get("Change"),
                "source": "TWSE FMTQIK official daily market statistics",
                "source_url": TWSE_FMTQIK_URL,
                "is_proxy": False,
            }
    if turnover is None:
        errors.append("turnover_unavailable")

    breadth_list = breadth_rows if isinstance(breadth_rows, list) else []
    breadth_row = next(
        (item for item in reversed(breadth_list) if isinstance(item, dict) and str(item.get("類型") or item.get("Type") or "") in {"整體市場", "All"}),
        None,
    )
    if breadth_row:
        observed = _date(breadth_row.get("出表日期") or breadth_row.get("Date"))
        breadth = {
            "observed_date": observed,
            "advancing": _number(breadth_row.get("上漲") or breadth_row.get("Advancing")),
            "limit_up": _number(breadth_row.get("漲停") or breadth_row.get("LimitUp")),
            "declining": _number(breadth_row.get("下跌") or breadth_row.get("Declining")),
            "limit_down": _number(breadth_row.get("跌停") or breadth_row.get("LimitDown")),
            "unchanged": _number(breadth_row.get("持平") or breadth_row.get("Unchanged")),
            "untraded": _number(breadth_row.get("未成交") or breadth_row.get("Untraded")),
            "source": "TWSE official market breadth",
            "source_url": TWSE_BREADTH_URL,
            "is_proxy": False,
        }
    else:
        errors.append("breadth_unavailable")

    if isinstance(institution_payload, dict) and str(institution_payload.get("stat") or "") == "OK":
        fields = institution_payload.get("fields") or []
        data = institution_payload.get("data") or []
        names = {str(name): index for index, name in enumerate(fields)}

        def row_value(label: str) -> int | None:
            record = next((item for item in data if isinstance(item, list) and item and str(item[0]) == label), None)
            if record is None:
                return None
            index = names.get("買賣差額")
            return _number(record[index]) if index is not None and index < len(record) else None

        institutional = {
            "observed_date": _date(institution_payload.get("date")),
            "foreign_net": row_value("外資及陸資(不含外資自營商)"),
            "investment_trust_net": row_value("投信"),
            "dealer_net": row_value("自營商(自行買賣)"),
            "total_net": row_value("合計"),
            "source": "TWSE BFI82U official institution trading statistics",
            "source_url": f"{TWSE_INSTITUTION_URL}?dayDate={institution_payload.get('date')}&response=json",
            "is_proxy": False,
        }
    else:
        errors.append("institutional_flow_unavailable")

    observed_dates: list[str] = []
    for value in (turnover, breadth, institutional):
        if not isinstance(value, dict):
            continue
        observed = value.get("observed_date")
        if isinstance(observed, str) and observed:
            observed_dates.append(observed)
    status = "complete" if turnover and breadth and institutional else "partial" if turnover or breadth or institutional else "unavailable"
    return {
        "status": status,
        "observed_date": max(observed_dates) if observed_dates else None,
        "turnover": turnover,
        "breadth": breadth,
        "institutional_flows": institutional,
        "source": "TWSE official daily market statistics",
        "source_url": TWSE_FMTQIK_URL,
        "errors": errors,
        "is_proxy": False,
    }


def fetch_twse_market_statistics(
    *, now: datetime | None = None, session: requests.Session | None = None,
) -> dict[str, Any]:
    """Fetch official statistics; optionally retry the post-close gap window.

    Production sets ``TWSE_STATS_RETRY_ATTEMPTS=3`` for the 14:20 post-close
    anchor.  The default remains one pass so library callers and tests never
    sleep unexpectedly.  Each retry is a new read of all three official
    endpoints and stops as soon as a complete payload is available.
    """
    client = session or requests.Session()
    target = (now or datetime.now(ZoneInfo("Asia/Taipei"))).date().strftime("%Y%m%d")
    requests_to_make: tuple[tuple[str, str, dict[str, str]], ...] = (
        ("turnover", TWSE_FMTQIK_URL, {}),
        ("breadth", TWSE_BREADTH_URL, {}),
        ("institution", TWSE_INSTITUTION_URL, {"dayDate": target, "response": "json"}),
    )
    def _nonnegative_int(name: str) -> int:
        try:
            return max(0, int(os.getenv(name, "0")))
        except (TypeError, ValueError):
            return 0

    retry_attempts = _nonnegative_int("TWSE_STATS_RETRY_ATTEMPTS")
    try:
        retry_wait_seconds = max(0.0, float(os.getenv("TWSE_STATS_RETRY_WAIT_SECONDS", "600")))
    except (TypeError, ValueError):
        retry_wait_seconds = 600.0
    last_result: dict[str, Any] = {}
    for attempt in range(retry_attempts + 1):
        payloads: dict[str, Any] = {}
        errors: list[str] = []
        for key, url, params in requests_to_make:
            try:
                response = client.get(url, params=params, headers=HEADERS, timeout=15)
                response.raise_for_status()
                payloads[key] = response.json()
            except (OSError, ValueError, requests.RequestException) as exc:
                errors.append(f"{key}:{type(exc).__name__}")
        parsed = parse_twse_market_statistics(
            turnover_rows=payloads.get("turnover"),
            breadth_rows=payloads.get("breadth"),
            institution_payload=payloads.get("institution"),
            target_date=None,
        )
        parsed["errors"] = list(dict.fromkeys([*parsed.get("errors", []), *errors]))
        parsed["retry_attempt"] = attempt
        parsed["retry_attempts_configured"] = retry_attempts
        parsed["retry_wait_seconds"] = retry_wait_seconds
        last_result = parsed
        if parsed.get("status") == "complete" or attempt >= retry_attempts:
            return parsed
        time.sleep(retry_wait_seconds)
    return last_result


__all__ = ["fetch_twse_market_statistics", "parse_twse_market_statistics"]
