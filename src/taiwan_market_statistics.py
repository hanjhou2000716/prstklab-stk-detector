"""Official Taiwan daily market breadth, turnover and institution evidence."""

from __future__ import annotations

import os
import re
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
    # Seven-digit ROC dates must be recognized before any Gregorian parser.
    # Otherwise a malformed value such as ``1150-09-07`` can look like a
    # valid year 1150 date and enter the public report.
    compact = raw.replace("/", "").replace("-", "")
    if len(compact) == 7 and compact.isdigit():
        try:
            return date(int(compact[:3]) + 1911, int(compact[3:5]), int(compact[5:7])).isoformat()
        except ValueError:
            return None
    parts = re.split(r"[/-]", raw)
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        year = int(parts[0])
        if len(parts[0]) == 3:
            try:
                return date(year + 1911, int(parts[1]), int(parts[2])).isoformat()
            except ValueError:
                return None
        # A Gregorian year before the ROC epoch is not a plausible TWSE
        # observation and is treated as malformed input.
        if len(parts[0]) != 4 or year < 1911:
            return None
    for fmt in ("%Y%m%d", "%Y/%m/%d", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(raw, fmt).date()
            return parsed.isoformat() if parsed.year >= 1911 else None
        except ValueError:
            continue
    return None


def _dated_row(rows: Any, date_fields: tuple[str, ...], target_date: str | None) -> dict[str, Any] | None:
    candidates: list[tuple[str, dict[str, Any]]] = []
    for item in rows if isinstance(rows, list) else []:
        if not isinstance(item, dict):
            continue
        observed = next((_date(item.get(field)) for field in date_fields if item.get(field)), None)
        if observed:
            candidates.append((observed, item))
    if target_date:
        target = _date(target_date)
        if not target:
            return None
        exact = [item for observed, item in candidates if observed == target]
        return exact[0] if exact else None
    return max(candidates, key=lambda pair: pair[0])[1] if candidates else None


def _breadth_scope(row: dict[str, Any]) -> tuple[str, bool]:
    raw = " ".join(
        str(row.get(key) or "").strip()
        for key in ("統計範圍", "統計口徑", "證券種類", "市場範圍", "類型", "Type")
    )
    if "股票" in raw and not any(term in raw for term in ("權證", "受益證券", "債券")):
        return raw, True
    # TWSE's ``整體市場`` row is the stock-market breadth row in this
    # endpoint.  Still retain the source label and a sanity bound so a
    # mixed-securities response cannot be presented as stock breadth.
    if raw in {"整體市場", "All"}:
        return raw, True
    return raw or "統計範圍未提供", False


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

    normalized_target = _date(target_date) if target_date else None
    rows = turnover_rows if isinstance(turnover_rows, list) else []
    row = _dated_row(rows, ("Date", "日期"), normalized_target)
    if row:
        observed = _date(row.get("Date") or row.get("日期"))
        trade_value = _number(row.get("TradeValue"))
        if observed and trade_value is not None:
            turnover = {
                "observed_date": observed,
                "trade_volume": _number(row.get("TradeVolume")),
                "trade_value": trade_value,
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
    breadth_candidates = [
        item for item in breadth_list
        if isinstance(item, dict) and str(item.get("類型") or item.get("Type") or "") in {"整體市場", "All"}
    ]
    breadth_row = _dated_row(breadth_candidates, ("出表日期", "Date"), normalized_target)
    if breadth_row:
        observed = _date(breadth_row.get("出表日期") or breadth_row.get("Date"))
        scope, scope_verified = _breadth_scope(breadth_row)
        values = {
            "advancing": _number(breadth_row.get("上漲") or breadth_row.get("Advancing")),
            "limit_up": _number(breadth_row.get("漲停") or breadth_row.get("LimitUp")),
            "declining": _number(breadth_row.get("下跌") or breadth_row.get("Declining")),
            "limit_down": _number(breadth_row.get("跌停") or breadth_row.get("LimitDown")),
            "unchanged": _number(breadth_row.get("持平") or breadth_row.get("Unchanged")),
            "untraded": _number(breadth_row.get("未成交") or breadth_row.get("Untraded")),
        }
        breadth_total = sum(value for value in values.values() if value is not None)
        reasonable = breadth_total <= 5_000 and values["advancing"] is not None and values["declining"] is not None
        if observed and reasonable:
            breadth = {
                "observed_date": observed,
                **values,
                "scope": scope,
                "scope_verified": scope_verified,
                "source": "TWSE official market breadth",
                "source_url": TWSE_BREADTH_URL,
                "is_proxy": False,
            }
        else:
            errors.append("breadth_invalid_values")
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

        institutional_date = _date(institution_payload.get("date"))
        if normalized_target and institutional_date != normalized_target:
            institutional_date = None
        if institutional_date and row_value("合計") is not None:
            institutional = {
                "observed_date": institutional_date,
                "foreign_net": row_value("外資及陸資(不含外資自營商)"),
                "investment_trust_net": row_value("投信"),
                "dealer_net": row_value("自營商(自行買賣)"),
                "total_net": row_value("合計"),
                "source": "TWSE BFI82U official institution trading statistics",
                "source_url": f"{TWSE_INSTITUTION_URL}?dayDate={institution_payload.get('date')}&response=json",
                "is_proxy": False,
            }
        else:
            errors.append("institutional_flow_invalid_date_or_value")
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
            target_date=target,
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
