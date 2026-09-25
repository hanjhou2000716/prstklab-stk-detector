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


def fetch_latest_verified_txf(*, session: requests.Session | None = None, now: datetime | None = None) -> dict[str, Any] | None:
    """Try official OpenAPI first, then the exchange's regular-session table."""
    client = session or requests.Session()
    local_now = (now or datetime.now(TAIPEI)).astimezone(TAIPEI)
    try:
        response = client.get(TAIFEX_DAILY_API, headers={"User-Agent": "PRStK-Lab-public-research/1.0"}, timeout=15)
        response.raise_for_status()
        quote = parse_daily_api(response.json(), now=local_now)
        if quote:
            return quote
    except (requests.RequestException, ValueError, TypeError):
        pass
    try:
        response = client.get(
            TAIFEX_DAILY_TABLE,
            params={"commodity_id": "TX"},
            headers={"User-Agent": "PRStK-Lab-public-research/1.0"},
            timeout=15,
        )
        response.raise_for_status()
        return parse_daily_html(response.text, now=local_now)
    except (requests.RequestException, ValueError, TypeError):
        return None


def validated_txf_backup(store: Any, *, now: datetime | None = None) -> dict[str, Any] | None:
    """Use only our own official-daily TXF rows with complete contract/session evidence."""
    if store is None:
        return None
    local_now = (now or datetime.now(TAIPEI)).astimezone(TAIPEI)
    try:
        row = store.latest_quote("TXF", before_or_on=local_now.date().isoformat(), provider="TAIFEX日盤")
        if not isinstance(row, dict):
            return None
        contract_match = re.search(r"(?:^|\|)contract=(\d{6})(?:\||$)", str(row.get("quote_basis") or ""))
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
        parsed_url = urlparse(source_url)
        trusted_source = (
            parsed_url.scheme == "https"
            and parsed_url.netloc == "openapi.taifex.com.tw"
            and parsed_url.hostname == "openapi.taifex.com.tw"
            and parsed_url.path == "/v1/DailyMarketReportFut"
            and not parsed_url.username and not parsed_url.password and not parsed_url.fragment
        ) or (
            parsed_url.scheme == "https"
            and parsed_url.netloc == "www.taifex.com.tw"
            and parsed_url.hostname == "www.taifex.com.tw"
            and parsed_url.path == "/cht/3/futDailyMarketExcel"
            and parse_qs(parsed_url.query) == {"commodity_id": ["TX"]}
            and not parsed_url.username and not parsed_url.password and not parsed_url.fragment
        )
        price = _number(row.get("price"))
        previous_close = _number(row.get("previous_close"))
        change = _number(row.get("change"))
        percent = _number(row.get("change_percent"))
        if (
            not month or not observed or month < observed.strftime("%Y%m")
            or not _contract_is_unexpired(month, local_now)
            or price is None or price <= 0 or previous_close is None or change is None or percent is None
            or str(row.get("instrument_id") or "") != f"market:txf:taifex:{month}:regular"
            or str(row.get("quote_basis") or "") != f"TAIFEX_TXF_DAY|contract={month}|session=regular"
            or observed_at is None or observed_at.date() != observed
            or not trusted_source
            or _session_gap(observed, local_now.date()) > MAX_COMPLETED_SESSIONS_OLD
            or not _calendar_open(observed)
        ):
            return None
        return {
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
    except Exception:
        return None


__all__ = [
    "TAIFEX_DAILY_API", "TAIFEX_DAILY_TABLE_QUERY", "fetch_latest_verified_txf",
    "parse_daily_api", "parse_daily_html", "validated_txf_backup",
]
