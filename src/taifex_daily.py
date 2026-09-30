"""Verified latest completed regular-session TX futures observations."""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from io import StringIO
from typing import Any
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from bs4 import BeautifulSoup

from src.market_data import change_percent
from src.taifex_calendar import get_taifex_index_futures_status

TAIPEI = ZoneInfo("Asia/Taipei")
TAIFEX_DAILY_API = "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"
TAIFEX_DAILY_TABLE = "https://www.taifex.com.tw/cht/3/futDailyMarketExcel"
TAIFEX_DAILY_TABLE_QUERY = f"{TAIFEX_DAILY_TABLE}?commodity_id=TX"
MAX_COMPLETED_SESSIONS_OLD = 3
_REGULAR_SESSIONS = {"一般", "一般交易時段", "regular", "regularsession", "day", "daysession", "r"}


def _key(value: Any) -> str:
    return re.sub(r"[\s_()（）%％]", "", str(value or "")).casefold()


def _value(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row:
            return row[name]
    normalized: dict[str, Any] = {}
    for name, value in row.items():
        normalized.setdefault(_key(name), value)
    for name in names:
        if _key(name) in normalized:
            return normalized[_key(name)]
    return None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    raw = str(value).strip()
    down_arrow = "▼" in raw
    text = raw.replace(",", "").replace("▲", "").replace("▼", "").replace("−", "-")
    text = text.replace("％", "%").rstrip("%")
    if text in {"", "-", "--", "N/A", "n/a"}:
        return None
    try:
        result = float(text)
    except ValueError:
        return None
    if down_arrow and result > 0:
        result = -result
    return result if result == result and abs(result) != float("inf") else None


def _date(value: Any) -> date | None:
    text = str(value or "").strip()
    for fmt in ("%Y%m%d", "%Y/%m/%d", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    roc = re.fullmatch(r"(\d{2,3})/(\d{1,2})/(\d{1,2})", text)
    if roc:
        try:
            return date(int(roc.group(1)) + 1911, int(roc.group(2)), int(roc.group(3)))
        except ValueError:
            return None
    return None


def _regular_session(value: Any) -> bool:
    return _key(value) in _REGULAR_SESSIONS


def _contract_month(value: Any) -> str:
    text = str(value or "").strip()
    match = re.fullmatch(r"(20\d{2})(0[1-9]|1[0-2])", text)
    return f"{match.group(1)}{match.group(2)}" if match else ""


@lru_cache(maxsize=72)
def _monthly_expiry(month: str) -> date | None:
    """TX expires on the third Wednesday, rolled to the next TAIFEX session."""
    parsed = _contract_month(month)
    if not parsed:
        return None
    year, month_number = int(parsed[:4]), int(parsed[4:])
    wednesdays = [
        day for day in range(1, calendar.monthrange(year, month_number)[1] + 1)
        if date(year, month_number, day).weekday() == 2
    ]
    if len(wednesdays) < 3:
        return None
    expiry = date(year, month_number, wednesdays[2])
    for _ in range(10):
        status = get_taifex_index_futures_status(
            today=expiry,
            now=datetime.combine(expiry, time(14, 0), TAIPEI),
        ).get("calendar_status")
        if status == "confirmed_open":
            return expiry
        if status != "confirmed_closed":
            return None
        expiry += timedelta(days=1)
    return None


def _contract_is_unexpired(month: str, now: datetime) -> bool:
    expiry = _monthly_expiry(month)
    if expiry is None:
        return False
    local_now = now.astimezone(TAIPEI)
    return local_now.date() < expiry or (local_now.date() == expiry and local_now.time() < time(13, 30))


def _calendar_open(day: date) -> bool:
    status = get_taifex_index_futures_status(today=day, now=datetime.combine(day, time(14, 0), TAIPEI))
    return status.get("calendar_status") == "confirmed_open"


def _session_gap(observed: date, reference: date) -> int:
    if observed > reference:
        return 10_000
    count = 0
    cursor = observed + timedelta(days=1)
    while cursor <= reference:
        status = get_taifex_index_futures_status(today=cursor, now=datetime.combine(cursor, time(14, 0), TAIPEI))
        if status.get("calendar_status") != "confirmed_open":
            if status.get("calendar_status") != "confirmed_closed":
                return 10_000
        else:
            count += 1
        cursor += timedelta(days=1)
    return count


def qualify_txf_quote_for_display(
    quote: dict[str, Any] | None, *, now: datetime | None = None,
) -> dict[str, Any]:
    """Classify a proven official TXF daily quote without promoting it to an alert."""
    unavailable = {"verified": False, "display_state": "unavailable", "alert_eligible": False}
    if not isinstance(quote, dict) or str(quote.get("ticker") or "").upper() != "TXF":
        return {**unavailable, "reason": "quote_missing_or_wrong_ticker"}
    reference_now = now or datetime.now(TAIPEI)
    if reference_now.tzinfo is None or reference_now.utcoffset() is None:
        return {**unavailable, "reason": "reference_time_unverified"}
    local_now = reference_now.astimezone(TAIPEI)
    observed = _date(quote.get("quote_date") or quote.get("quote_time"))
    observed_at: datetime | None
    try:
        observed_at = datetime.fromisoformat(str(quote.get("quote_time") or "").replace("Z", "+00:00"))
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            observed_at = None
        else:
            observed_at = observed_at.astimezone(TAIPEI)
    except ValueError:
        observed_at = None
    month = _contract_month(quote.get("contract_month"))
    source_url = str(quote.get("source_url") or "")
    try:
        parsed_url = urlparse(source_url)
    except ValueError:
        return {**unavailable, "reason": "official_source_unverified"}
    trusted_source = (
        parsed_url.scheme == "https"
        and parsed_url.hostname == "openapi.taifex.com.tw"
        and parsed_url.netloc == "openapi.taifex.com.tw"
        and parsed_url.path == "/v1/DailyMarketReportFut"
        and not parsed_url.query
        and not parsed_url.username and not parsed_url.password and not parsed_url.fragment
    ) or (
        parsed_url.scheme == "https"
        and parsed_url.hostname == "www.taifex.com.tw"
        and parsed_url.netloc == "www.taifex.com.tw"
        and parsed_url.path == "/cht/3/futDailyMarketExcel"
        and parsed_qs_is_tx(parsed_url.query)
        and parsed_url.netloc == "www.taifex.com.tw"
        and not parsed_url.username and not parsed_url.password and not parsed_url.fragment
    )
    price = _number(quote.get("price"))
    change = _number(quote.get("change"))
    percent = _number(quote.get("change_percent"))
    if not trusted_source:
        return {**unavailable, "reason": "official_source_unverified"}
    if (
        not observed or not observed_at or observed_at.date() != observed
        or observed > local_now.date()
    ):
        return {**unavailable, "reason": "observation_date_unverified"}
    if (
        str(quote.get("session") or "") != "regular"
        or str(quote.get("quote_basis") or "") != f"TAIFEX_TXF_DAY|contract={month}|session=regular"
        or str(quote.get("instrument_id") or "") != f"market:txf:taifex:{month}:regular"
        or not month or month < observed.strftime("%Y%m")
    ):
        return {**unavailable, "reason": "contract_or_session_unverified"}
    try:
        contract_unexpired = _contract_is_unexpired(month, local_now)
    except Exception:
        return {**unavailable, "reason": "taifex_calendar_unverified"}
    if not contract_unexpired:
        return {**unavailable, "reason": "contract_or_session_unverified"}
    if (
        price is None or price <= 0 or change is None or percent is None
        or str(quote.get("freshness") or quote.get("data_status") or "").casefold() not in {"recent_close", "stale"}
        or quote.get("stale_used") is True and quote.get("backup_used") is not True
    ):
        return {**unavailable, "reason": "quote_values_or_freshness_unverified"}

    latest_completed: date | None = None
    cursor = local_now.date()
    for _ in range(32):
        try:
            status = get_taifex_index_futures_status(
                today=cursor, now=datetime.combine(cursor, time(14, 0), TAIPEI),
            ).get("calendar_status")
        except Exception:
            return {**unavailable, "reason": "taifex_calendar_unverified"}
        if status not in {"confirmed_open", "confirmed_closed"}:
            return {**unavailable, "reason": "taifex_calendar_unverified"}
        if status == "confirmed_open" and (
            cursor < local_now.date() or local_now.time() >= time(13, 45)
        ):
            latest_completed = cursor
            break
        cursor -= timedelta(days=1)
    if latest_completed is None:
        return {**unavailable, "reason": "latest_completed_session_unavailable"}
    try:
        observed_session_open = _calendar_open(observed)
        age_sessions = _session_gap(observed, latest_completed)
    except Exception:
        return {**unavailable, "reason": "taifex_calendar_unverified"}
    if not observed_session_open:
        return {**unavailable, "reason": "observed_taifex_session_unverified"}
    if age_sessions > MAX_COMPLETED_SESSIONS_OLD:
        return {**unavailable, "reason": "backup_expired"}
    return {
        "verified": True,
        "display_state": "recent_close" if observed == latest_completed else "historical_reference",
        "date": observed.isoformat(),
        "is_today": observed == local_now.date(),
        "freshness": "recent_close" if observed == latest_completed else "historical_reference",
        "price": price,
        "change": change,
        "change_percent": percent,
        "contract_month": month,
        "age_completed_sessions": age_sessions,
        "alert_eligible": False,
        "reason": "verified_latest_completed_session" if observed == latest_completed else "verified_historical_reference",
    }


def parsed_qs_is_tx(query: str) -> bool:
    return parse_qs(query) == {"commodity_id": ["TX"]}


def _normalized_row(row: dict[str, Any]) -> dict[str, Any] | None:
    contract = str(_value(row, "Contract", "契約", "商品契約代號") or "").strip().upper()
    session = _value(row, "TradingSession", "交易時段", "Session")
    month = _contract_month(_value(row, "ContractMonth(Week)", "Contract Month(Week)", "ContractMonth", "到期月份(週別)", "到期月份"))
    day = _date(_value(row, "Date", "日期", "交易日期"))
    price = _number(_value(row, "Last", "LastPrice", "LastTradePrice", "最後成交價", "最後成交價(點)"))
    change = _number(_value(row, "Change", "ChangePrice", "漲跌價", "漲跌點"))
    percent = _number(_value(row, "ChangePercent", "Change%", "漲跌%", "漲跌幅"))
    # Both key identity and regular-session label must be explicit. Never infer
    # the session from the clock: TAIFEX night trades are date-attributed.
    if contract != "TX" or not _regular_session(session) or not month or not day or price is None:
        return None
    if change is None and percent is None:
        return None
    if change is None and percent is not None and abs(100 + percent) > 1e-9:
        change = round(price * percent / (100 + percent), 2)
    if percent is None and change is not None and price - change > 0:
        percent = change_percent(price, price - change)
    if change is None or percent is None or month < day.strftime("%Y%m"):
        return None
    return {"date": day, "contract_month": month, "price": price, "change": change, "change_percent": percent}


def parse_daily_api(payload: Any, *, now: datetime | None = None) -> dict[str, Any] | None:
    """Select the nearest monthly TX contract from explicit regular-session rows."""
    rows = payload if isinstance(payload, list) else payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return None
    local_now = (now or datetime.now(TAIPEI)).astimezone(TAIPEI)
    normalized = [item for raw in rows if isinstance(raw, dict) if (item := _normalized_row(raw))]
    normalized = [
        row for row in normalized
        if row["date"] <= local_now.date()
        and _calendar_open(row["date"])
        and (row["date"] < local_now.date() or local_now.time() >= time(13, 45))
        and _contract_is_unexpired(row["contract_month"], local_now)
    ]
    dates = sorted({row["date"] for row in normalized}, reverse=True)
    for observed in dates:
        if _session_gap(observed, local_now.date()) > MAX_COMPLETED_SESSIONS_OLD:
            continue
        candidates = sorted(
            (row for row in normalized if row["date"] == observed),
            key=lambda row: row["contract_month"],
        )
        if not candidates:
            continue
        return _to_quote(candidates[0], source="TAIFEX每日交易行情 OpenAPI", source_url=TAIFEX_DAILY_API, now=local_now)
    return None


def parse_daily_html(html: str, *, now: datetime | None = None) -> dict[str, Any] | None:
    """Parse the official TX daily table only when date, session and columns are explicit."""
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text(" ", strip=True)
    if "一般交易時段行情表" not in page_text or "到期月份" not in page_text or "最後" not in page_text:
        return None
    match = re.search(r"日期\s*[：:]\s*(20\d{2})/(\d{1,2})/(\d{1,2})", page_text)
    if not match:
        return None
    observed = _date("/".join(match.groups()))
    if observed is None:
        return None
    local_now = (now or datetime.now(TAIPEI)).astimezone(TAIPEI)
    if observed > local_now.date() or not _calendar_open(observed):
        return None
    if observed == local_now.date() and local_now.time() < time(13, 45):
        return None
    heading = next(
        (text for text in soup.find_all(string=True) if "一般交易時段行情表" in str(text)),
        None,
    )
    day_table = heading.find_next("table") if heading is not None else None
    if day_table is None:
        return None
    try:
        tables = pd.read_html(StringIO(str(day_table)))
    except (ValueError, ImportError):
        return None
    candidates: list[dict[str, Any]] = []
    for table in tables:
        labels = [" ".join(str(value) for value in label) if isinstance(label, tuple) else str(label) for label in table.columns]
        normalized_labels = [_key(label) for label in labels]
        contract_idx = next((i for i, label in enumerate(normalized_labels) if label in {"契約", "商品契約代號", "contract"}), None)
        month_idx = next((i for i, label in enumerate(normalized_labels) if "月份" in label or "contractmonth" in label), None)
        price_idx = next((i for i, label in enumerate(normalized_labels) if "最後" in label and "成交價" in label), None)
        change_idx = next((i for i, label in enumerate(normalized_labels) if "漲跌價" in label), None)
        percent_idx = next(
            (i for i, label in enumerate(labels) if "漲跌" in label and ("%" in label or "％" in label)),
            None,
        )
        if contract_idx is None or month_idx is None or price_idx is None:
            # The exchange's documented daily table has a stable initial
            # contract/month/open/high/low/last/change/change% column order.
            if len(labels) < 8:
                continue
            contract_idx, month_idx, price_idx, change_idx, percent_idx = 0, 1, 5, 6, 7
        for values in table.itertuples(index=False, name=None):
            if max(contract_idx, month_idx, price_idx) >= len(values):
                continue
            raw = {
                "Contract": values[contract_idx],
                "ContractMonth(Week)": values[month_idx],
                "Last": values[price_idx],
                "Change": values[change_idx] if change_idx is not None and change_idx < len(values) else None,
                "ChangePercent": values[percent_idx] if percent_idx is not None and percent_idx < len(values) else None,
                "Date": observed.isoformat(),
                "TradingSession": "一般交易時段",
            }
            parsed = _normalized_row(raw)
            if parsed:
                candidates.append(parsed)
    candidates = [row for row in candidates if _contract_is_unexpired(row["contract_month"], local_now)]
    if _session_gap(observed, local_now.date()) > MAX_COMPLETED_SESSIONS_OLD or not candidates:
        return None
    nearest = min(candidates, key=lambda row: row["contract_month"])
    return _to_quote(nearest, source="TAIFEX官方每日行情表", source_url=TAIFEX_DAILY_TABLE_QUERY, now=local_now)


def _to_quote(row: dict[str, Any], *, source: str, source_url: str, now: datetime) -> dict[str, Any]:
    observed = row["date"]
    return {
        "ticker": "TXF",
        "name": "臺股期貨近月",
        "market": "taiwan",
        "currency": "點",
        "price": round(float(row["price"]), 2),
        "previous_close": round(float(row["price"] - row["change"]), 2),
        "change": round(float(row["change"]), 2),
        "change_percent": round(float(row["change_percent"]), 2),
        "quote_date": observed.isoformat(),
        "quote_time": datetime.combine(observed, time(13, 45), TAIPEI).isoformat(),
        "source": source,
        "source_label": "TAIFEX日盤",
        "quote_source": source,
        "source_url": source_url,
        "source_tier": "official",
        "quote_basis": f"TAIFEX_TXF_DAY|contract={row['contract_month']}|session=regular",
        "instrument_id": f"market:txf:taifex:{row['contract_month']}:regular",
        "session": "regular",
        "freshness": "recent_close",
        "data_status": "recent_close",
        "contract_month": row["contract_month"],
        "contract_basis": "named_month_contract",
        "quote_delayed": observed < now.date(),
        "backup_used": False,
        "official_fallback_used": source.startswith("TAIFEX官方"),
        "fallback_reason": "current_session_closed_or_not_yet_published" if observed < now.date() else None,
    }


def _record_source_attempt(
    diagnostics: list[dict[str, str]] | None, source: str, outcome: str,
) -> None:
    if diagnostics is not None:
        diagnostics.append({"source": source, "outcome": outcome})


def fetch_latest_verified_txf(
    *, session: requests.Session | None = None, now: datetime | None = None,
    diagnostics: list[dict[str, str]] | None = None,
) -> dict[str, Any] | None:
    """Try official OpenAPI first, then the exchange table with safe diagnostics."""
    client = session or requests.Session()
    local_now = (now or datetime.now(TAIPEI)).astimezone(TAIPEI)
    try:
        response = client.get(TAIFEX_DAILY_API, headers={"User-Agent": "PRStK-Lab-public-research/1.0"}, timeout=15)
        response.raise_for_status()
        payload = response.json()
        quote = parse_daily_api(payload, now=local_now)
        if quote:
            _record_source_attempt(diagnostics, "taifex_openapi", "verified")
            return quote
        outcome = "not_published" if not payload else "parse_or_contract_mismatch"
        _record_source_attempt(diagnostics, "taifex_openapi", outcome)
    except (requests.RequestException, ValueError, TypeError) as exc:
        outcome = "connection_failed" if isinstance(exc, requests.RequestException) else "response_parse_failed"
        _record_source_attempt(diagnostics, "taifex_openapi", outcome)
    try:
        response = client.get(
            TAIFEX_DAILY_TABLE,
            params={"commodity_id": "TX"},
            headers={"User-Agent": "PRStK-Lab-public-research/1.0"},
            timeout=15,
        )
        response.raise_for_status()
        html = response.text
        quote = parse_daily_html(html, now=local_now)
        if quote:
            _record_source_attempt(diagnostics, "taifex_daily_table", "verified")
            return quote
        normalized_html = str(html or "").casefold()
        outcome = (
            "not_published" if not normalized_html.strip()
            or any(token in normalized_html for token in ("尚未公布", "尚無資料", "查無資料", "no data"))
            else "parse_or_contract_mismatch"
        )
        _record_source_attempt(diagnostics, "taifex_daily_table", outcome)
        return None
    except (requests.RequestException, ValueError, TypeError) as exc:
        outcome = "connection_failed" if isinstance(exc, requests.RequestException) else "response_parse_failed"
        _record_source_attempt(diagnostics, "taifex_daily_table", outcome)
        return None

def validated_txf_backup(
    store: Any, *, now: datetime | None = None,
    diagnostics: list[dict[str, str]] | None = None,
) -> dict[str, Any] | None:
    """Use only our own official-daily TXF rows with complete contract/session evidence."""
    if store is None:
        _record_source_attempt(diagnostics, "taifex_saved_backup", "backup_store_unavailable")
        return None
    local_now = (now or datetime.now(TAIPEI)).astimezone(TAIPEI)
    try:
        row = store.latest_quote(
            "TXF", before_or_on=local_now.date().isoformat(), provider="TAIFEX日盤",
        )
        if not isinstance(row, dict):
            _record_source_attempt(diagnostics, "taifex_saved_backup", "backup_not_found")
            return None
        contract_match = re.search(
            r"contract=(\d{6})",
            str(row.get("quote_basis") or ""),
        )
        month = _contract_month(contract_match.group(1) if contract_match else "")
        observed = _date(row.get("market_date"))
        observed_at_raw = str(row.get("observed_at") or "")
        observed_at: datetime | None
        try:
            observed_at = datetime.fromisoformat(observed_at_raw.replace("Z", "+00:00"))
            if observed_at.tzinfo is None or observed_at.utcoffset() is None:
                observed_at = None
            else:
                observed_at = observed_at.astimezone(TAIPEI)
        except ValueError:
            observed_at = None
        source_url = str(row.get("source_url") or "")
        try:
            parsed_url = urlparse(source_url)
        except ValueError:
            _record_source_attempt(diagnostics, "taifex_saved_backup", "backup_source_unverified")
            return None
        trusted_source = (
            parsed_url.scheme == "https"
            and parsed_url.netloc == "openapi.taifex.com.tw"
            and parsed_url.hostname == "openapi.taifex.com.tw"
            and parsed_url.path == "/v1/DailyMarketReportFut"
            and not parsed_url.query
            and not parsed_url.username and not parsed_url.password and not parsed_url.fragment
        ) or (
            parsed_url.scheme == "https"
            and parsed_url.netloc == "www.taifex.com.tw"
            and parsed_url.hostname == "www.taifex.com.tw"
            and parsed_url.path == "/cht/3/futDailyMarketExcel"
            and parse_qs(parsed_url.query) == {"commodity_id": ["TX"]}
            and not parsed_url.username and not parsed_url.password and not parsed_url.fragment
        )
        if not trusted_source:
            _record_source_attempt(diagnostics, "taifex_saved_backup", "backup_source_unverified")
            return None
        if (
            not month or not observed or observed > local_now.date()
            or month < observed.strftime("%Y%m")
            or not _contract_is_unexpired(month, local_now)
            or str(row.get("instrument_id") or "") != f"market:txf:taifex:{month}:regular"
            or str(row.get("quote_basis") or "") != f"TAIFEX_TXF_DAY|contract={month}|session=regular"
            or observed_at is None or observed_at.date() != observed
        ):
            _record_source_attempt(diagnostics, "taifex_saved_backup", "backup_identity_or_contract_mismatch")
            return None
        price = _number(row.get("price"))
        previous_close = _number(row.get("previous_close"))
        change = _number(row.get("change"))
        percent = _number(row.get("change_percent"))
        if price is None or price <= 0 or previous_close is None or change is None or percent is None:
            _record_source_attempt(diagnostics, "taifex_saved_backup", "backup_values_unverified")
            return None
        try:
            observed_session_open = _calendar_open(observed)
        except Exception:
            observed_session_open = False
        if not observed_session_open:
            _record_source_attempt(diagnostics, "taifex_saved_backup", "backup_taifex_calendar_unverified")
            return None
        if _session_gap(observed, local_now.date()) > MAX_COMPLETED_SESSIONS_OLD:
            _record_source_attempt(diagnostics, "taifex_saved_backup", "backup_expired")
            return None
        backup = {
            "ticker": "TXF", "name": "臺股期貨近月", "market": "taiwan", "currency": "點",
            "price": price, "previous_close": previous_close,
            "change": change, "change_percent": percent,
            "quote_date": observed.isoformat(), "quote_time": observed_at.isoformat(),
            "source": "Supabase verified TAIFEX daily observation", "source_label": "TAIFEX日盤備援",
            "quote_source": "Supabase verified TAIFEX daily observation", "source_url": source_url,
            "quote_basis": str(row.get("quote_basis")), "instrument_id": str(row.get("instrument_id")),
            "session": "regular", "freshness": "recent_close", "data_status": "recent_close",
            "contract_month": month, "contract_basis": "named_month_contract",
            "backup_used": True, "stale_used": True, "quote_delayed": True,
            "fallback_reason": "official_sources_temporarily_unavailable",
        }
        _record_source_attempt(diagnostics, "taifex_saved_backup", "verified")
        return backup
    except Exception:
        _record_source_attempt(diagnostics, "taifex_saved_backup", "backup_read_or_validation_failed")
        return None

__all__ = [
    "TAIFEX_DAILY_API", "TAIFEX_DAILY_TABLE_QUERY", "fetch_latest_verified_txf",
    "parse_daily_api", "parse_daily_html", "qualify_txf_quote_for_display", "validated_txf_backup",
]
