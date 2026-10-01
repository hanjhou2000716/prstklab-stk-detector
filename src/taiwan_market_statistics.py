"""Official Taiwan daily market breadth, turnover and institution evidence."""

from __future__ import annotations

import math
import re
import time
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

TWSE_FMTQIK_URL = "https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK"
TWSE_BREADTH_URL = "https://openapi.twse.com.tw/v1/opendata/twtazu_od"
TWSE_INSTITUTION_URL = "https://www.twse.com.tw/rwd/zh/fund/BFI82U"
TWSE_MI_INDEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TWSE_TAIEX_HISTORY_URL = "https://openapi.twse.com.tw/v1/indicesReport/MI_5MINS_HIST"
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
    ).strip()
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
        taiex = _finite_float(row.get("TAIEX"))
        change = _finite_float(row.get("Change"))
        if observed and (trade_value is not None or taiex is not None):
            turnover = {
                "observed_date": observed,
                "trade_volume": _number(row.get("TradeVolume")),
                "trade_value": trade_value,
                "unit": "元",
                "currency": "TWD",
                "transactions": _number(row.get("Transaction")),
                "taiex": taiex,
                "change": change,
                "source": "TWSE FMTQIK official daily market statistics",
                "source_url": TWSE_FMTQIK_URL,
                "is_proxy": False,
            }
    if turnover is None or turnover.get("trade_value") is None:
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
                "source": "TWSE MI_INDEX official stock breadth" if breadth_row.get("_source_url") == TWSE_MI_INDEX_URL else "TWSE official market breadth",
                "source_url": str(breadth_row.get("_source_url") or TWSE_BREADTH_URL),
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
                "unit": "元",
                "currency": "TWD",
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
    turnover_complete = bool(turnover and turnover.get("trade_value") is not None)
    status = "complete" if turnover_complete and breadth and institutional else "partial" if turnover or breadth or institutional else "unavailable"
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



def parse_twse_mi_index_breadth(payload: Any, *, target_date: str | None = None) -> list[dict[str, Any]]:
    """Extract stock breadth from the official TWSE MI_INDEX summary table."""
    if not isinstance(payload, dict):
        return []
    normalized_target = _date(target_date) if target_date else _date(payload.get("date"))
    for table in payload.get("tables") or []:
        if not isinstance(table, dict):
            continue
        title = str(table.get("title") or "")
        if "\u6f32\u8dcc\u8b49\u5238\u6578\u5408\u8a08" not in title:
            continue
        fields = [str(item) for item in (table.get("fields") or [])]
        rows = table.get("data") or []
        category_index = next((i for i, name in enumerate(fields) if name == "\u985e\u578b"), None)
        stock_index = next((i for i, name in enumerate(fields) if name in {"\u80a1\u7968", "Stock"}), None)
        if category_index is None or stock_index is None:
            continue

        def count(value: Any) -> int | None:
            match = re.search(r"\d[\d,]*", str(value or ""))
            return _number(match.group(0)) if match else None

        def limit_count(value: Any) -> int | None:
            match = re.search(r"\((\d[\d,]*)\)", str(value or ""))
            return _number(match.group(1)) if match else None

        values: dict[str, int | None] = {}
        for row in rows:
            if not isinstance(row, list) or category_index >= len(row) or stock_index >= len(row):
                continue
            label = str(row[category_index] or "").strip()
            if label.startswith("\u4e0a\u6f32"):
                values["advancing"] = count(row[stock_index])
                values["limit_up"] = limit_count(row[stock_index])
            elif label.startswith("\u4e0b\u8dcc"):
                values["declining"] = count(row[stock_index])
                values["limit_down"] = limit_count(row[stock_index])
            elif label.startswith("\u6301\u5e73"):
                values["unchanged"] = count(row[stock_index])
            elif label.startswith("\u672a\u6210\u4ea4"):
                values["untraded"] = count(row[stock_index])
        if values.get("advancing") is not None and values.get("declining") is not None:
            return [{
                "\u985e\u578b": "\u6574\u9ad4\u5e02\u5834",
                "\u51fa\u8868\u65e5\u671f": normalized_target,
                "\u4e0a\u6f32": values.get("advancing"),
                "\u6f32\u505c": values.get("limit_up"),
                "\u4e0b\u8dcc": values.get("declining"),
                "\u8dcc\u505c": values.get("limit_down"),
                "\u6301\u5e73": values.get("unchanged"),
                "\u672a\u6210\u4ea4": values.get("untraded"),
                "_source_url": TWSE_MI_INDEX_URL,
            }]
    return []


def _finite_float(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _official_taiex_quote(
    *, observed_date: str, price: float, previous_close: float | None,
    change: float | None, change_percent: float | None, source_url: str,
    source_label: str, source_name: str,
) -> dict[str, Any]:
    return {
        "ticker": "TAIEX",
        "symbol": "^TWII",
        "name": "臺灣加權指數",
        "market": "taiwan",
        "currency": "點",
        "price": round(price, 2),
        "previous_close": round(previous_close, 2) if previous_close is not None else None,
        "change": round(change, 2) if change is not None else None,
        "change_percent": round(change_percent, 2) if change_percent is not None else None,
        "quote_date": observed_date,
        "quote_time": f"{observed_date}T13:30:00+08:00",
        "quote_basis": "TWSE_TAIEX_DAILY_CLOSE",
        "quote_source": source_name,
        "source": source_name,
        "source_url": source_url,
        "source_label": source_label,
        "source_tier": "official",
        "instrument_id": "twse:taiex",
        "freshness": "recent_close",
        "data_status": "最近收盤",
        "quote_delayed": True,
        "stale_used": False,
        "backup_used": False,
        "cross_checked": False,
        "crosscheck_status": "官方收盤資料",
        "alert_eligible": False,
        "routine_eligible": True,
    }


def taiex_quote_from_market_statistics(
    statistics: Any, *, expected_date: str,
) -> dict[str, Any] | None:
    """Reuse the TWSE FMTQIK close already fetched with the market statistics."""
    if not isinstance(statistics, dict):
        return None
    turnover = statistics.get("turnover")
    if not isinstance(turnover, dict) or turnover.get("is_proxy") is not False:
        return None
    observed = _date(turnover.get("observed_date"))
    target = _date(expected_date)
    if not observed or observed != target or turnover.get("source_url") != TWSE_FMTQIK_URL:
        return None
    price = _finite_float(turnover.get("taiex"))
    change = _finite_float(turnover.get("change"))
    if price is None or price <= 0:
        return None
    previous = price - change if change is not None else None
    if previous is not None and previous <= 0:
        return None
    percent = round(change / previous * 100, 2) if change is not None and previous is not None else None
    return _official_taiex_quote(
        observed_date=observed,
        price=price,
        previous_close=previous,
        change=change,
        change_percent=percent,
        source_url=TWSE_FMTQIK_URL,
        source_label="TWSE",
        source_name="TWSE FMTQIK official TAIEX close",
    )


def parse_twse_taiex_history(
    rows: Any, *, target_date: str,
) -> dict[str, Any] | None:
    """Parse TWSE monthly index history for one calendar-verified session."""
    target = _date(target_date)
    if not target or not isinstance(rows, list):
        return None
    dated: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        observed = _date(row.get("Date") or row.get("日期"))
        close = _finite_float(row.get("ClosingIndex") or row.get("收盤指數"))
        if observed and close is not None and close > 0:
            dated[observed] = close
    price = dated.get(target)
    if price is None:
        return None
    previous_dates = [observed for observed in dated if observed < target]
    previous_date = max(previous_dates) if previous_dates else None
    previous = dated.get(previous_date) if previous_date else None
    change = round(price - previous, 2) if previous is not None else None
    percent = round(change / previous * 100, 2) if change is not None and previous else None
    return _official_taiex_quote(
        observed_date=target,
        price=price,
        previous_close=previous,
        change=change,
        change_percent=percent,
        source_url=TWSE_TAIEX_HISTORY_URL,
        source_label="TWSE",
        source_name="TWSE official TAIEX index history",
    )


def fetch_twse_taiex_recent_close(
    *, target_date: str, session: requests.Session | None = None,
    diagnostics: list[dict[str, str]] | None = None,
) -> dict[str, Any] | None:
    """Fetch a TWSE close and, at a month boundary, its preceding close."""
    target = _date(target_date)
    if not target:
        if diagnostics is not None:
            diagnostics.append({"source": "twse_taiex_history", "outcome": "target_date_unverified"})
        return None
    client = session or requests.Session()
    year, month = map(int, target[:7].split("-"))
    current_month = date(year, month, 1)
    previous_month = date(year - 1, 12, 1) if month == 1 else date(year, month - 1, 1)
    attempts: list[dict[str, str]] = []

    def fetch_month(month_start: date, label: str) -> list[dict[str, Any]] | None:
        try:
            response = client.get(
                TWSE_TAIEX_HISTORY_URL,
                params={"date": month_start.strftime("%Y%m%d")},
                headers=HEADERS,
                timeout=5,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                attempts.append({"source": label, "outcome": "response_shape_invalid"})
                return None
            attempts.append({"source": label, "outcome": "received"})
            return [row for row in payload if isinstance(row, dict)]
        except (OSError, ValueError, TypeError, requests.RequestException) as exc:
            outcome = "connection_failed" if isinstance(exc, requests.RequestException) else "response_parse_failed"
            attempts.append({"source": label, "outcome": outcome})
            return None

    current_rows = fetch_month(current_month, "twse_taiex_history_current_month")
    quote = parse_twse_taiex_history(current_rows, target_date=target) if current_rows is not None else None
    if current_rows is not None and quote is not None and quote.get("change") is None:
        previous_rows = fetch_month(previous_month, "twse_taiex_history_previous_month")
        if previous_rows is not None:
            quote = parse_twse_taiex_history(
                [*current_rows, *previous_rows], target_date=target,
            )
    if quote is not None:
        attempts.append({"source": "twse_taiex_history", "outcome": "verified"})
    elif current_rows is not None:
        attempts.append({"source": "twse_taiex_history", "outcome": "date_or_values_unavailable"})
    if diagnostics is not None:
        diagnostics.extend(attempts)
    if quote:
        quote["source_attempts"] = attempts
    return quote

def fetch_twse_market_statistics(
    *, now: datetime | None = None, session: requests.Session | None = None,
) -> dict[str, Any]:
    """Fetch official daily statistics for the latest completed Taiwan session.

    The turnover feed is used to resolve the latest completed market date, so
    intraday runs do not ask breadth and institution endpoints for today's
    unfinished session.  MI_INDEX supplies current stock breadth when the
    legacy OpenAPI feed is stale.
    """
    client = session or requests.Session()
    anchor = now or datetime.now(ZoneInfo("Asia/Taipei"))
    requested_target = anchor.date().isoformat()

    # These statistics are supplementary and may not delay the fixed report
    # slot. Fetch once, preserve partial provenance, and let a later snapshot
    # refresh the data without creating another Telegram notification.
    retry_attempts = 0
    retry_wait_seconds = 0.0
    request_timeout_seconds = 5

    last_result: dict[str, Any] = {}
    for attempt in range(retry_attempts + 1):
        payloads: dict[str, Any] = {}
        errors: list[str] = []

        try:
            response = client.get(TWSE_FMTQIK_URL, params={}, headers=HEADERS, timeout=request_timeout_seconds)
            response.raise_for_status()
            payloads["turnover"] = response.json()
        except (OSError, ValueError, requests.RequestException) as exc:
            errors.append(f"turnover:{type(exc).__name__}")

        resolved_target = requested_target
        latest_turnover = _dated_row(payloads.get("turnover"), ("Date", "日期"), None)
        if latest_turnover:
            observed = _date(latest_turnover.get("Date") or latest_turnover.get("日期"))
            if observed and observed <= requested_target:
                resolved_target = observed

        try:
            response = client.get(TWSE_BREADTH_URL, params={}, headers=HEADERS, timeout=request_timeout_seconds)
            response.raise_for_status()
            payloads["breadth"] = response.json()
        except (OSError, ValueError, requests.RequestException) as exc:
            errors.append(f"breadth:{type(exc).__name__}")

        try:
            response = client.get(
                TWSE_INSTITUTION_URL,
                params={"dayDate": resolved_target.replace("-", ""), "response": "json"},
                headers=HEADERS,
                timeout=request_timeout_seconds,
            )
            response.raise_for_status()
            payloads["institution"] = response.json()
        except (OSError, ValueError, requests.RequestException) as exc:
            errors.append(f"institution:{type(exc).__name__}")

        parsed = parse_twse_market_statistics(
            turnover_rows=payloads.get("turnover"),
            breadth_rows=payloads.get("breadth"),
            institution_payload=payloads.get("institution"),
            target_date=resolved_target,
        )
        if parsed.get("breadth") is None:
            try:
                response = client.get(
                    TWSE_MI_INDEX_URL,
                    params={
                        "date": resolved_target.replace("-", ""),
                        "type": "MS",
                        "response": "json",
                    },
                    headers=HEADERS,
                    timeout=request_timeout_seconds,
                )
                response.raise_for_status()
                mi_rows = parse_twse_mi_index_breadth(response.json(), target_date=resolved_target)
            except (OSError, ValueError, requests.RequestException) as exc:
                mi_rows = []
                errors.append(f"breadth_mi_index:{type(exc).__name__}")
            if mi_rows:
                parsed = parse_twse_market_statistics(
                    turnover_rows=payloads.get("turnover"),
                    breadth_rows=[*mi_rows, *(payloads.get("breadth") or [])],
                    institution_payload=payloads.get("institution"),
                    target_date=resolved_target,
                )

        parsed["errors"] = list(dict.fromkeys([*parsed.get("errors", []), *errors]))
        parsed["retry_attempt"] = attempt
        parsed["retry_attempts_configured"] = retry_attempts
        parsed["retry_wait_seconds"] = retry_wait_seconds
        parsed["resolved_target_date"] = resolved_target
        last_result = parsed
        if parsed.get("status") == "complete" or attempt >= retry_attempts:
            return parsed
        time.sleep(retry_wait_seconds)
    return last_result


__all__ = ["fetch_twse_market_statistics", "parse_twse_market_statistics", "parse_twse_mi_index_breadth"]
