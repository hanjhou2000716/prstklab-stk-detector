"""Locally pinned, independently sourced TAIFEX Taiwan index-futures calendar.

The exchange publishes annual market-closure schedules and may issue ad-hoc
closure notices.  This adapter combines the reviewed official records checked
into ``taifex_calendar_data.json`` and fails closed outside verified coverage.
It intentionally does not infer TAIFEX sessions from the TWSE/XTAI calendar.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

TAIFEX_TIMEZONE = "Asia/Taipei"
TAIFEX_CALENDAR = "TAIFEX"
_TAIPEI = ZoneInfo(TAIFEX_TIMEZONE)
_DEFAULT_DATA_PATH = Path(__file__).with_name("taifex_calendar_data.json")
_SAFE_CALENDAR_ERRORS = {
    "unsupported_calendar_schema",
    "calendar_provider_mismatch",
    "calendar_years_missing",
    "calendar_year_not_published",
    "calendar_coverage_invalid",
    "calendar_date_outside_verified_coverage",
    "calendar_verification_date_invalid",
    "calendar_verification_date_in_future",
    "annual_source_missing",
    "additional_sources_invalid",
    "official_source_metadata_invalid",
    "closed_dates_missing",
    "closed_date_entry_invalid",
}


def _unverified_status(target_day: date, reason: str) -> dict[str, Any]:
    return {
        "label": "台指期日盤",
        "market_component": "TAIFEX Taiwan index futures day session",
        "timezone": TAIFEX_TIMEZONE,
        "calendar": TAIFEX_CALENDAR,
        "calendar_provider": TAIFEX_CALENDAR,
        "calendar_basis": "TAIFEX_official_calendar_unverified",
        "date": target_day.isoformat(),
        "is_trading_day": None,
        "calendar_status": "unverified",
        "session": "行事曆未驗證",
        "calendar_error": reason,
    }


def _load_calendar(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("unsupported_calendar_schema")
    if payload.get("provider") != TAIFEX_CALENDAR:
        raise ValueError("calendar_provider_mismatch")
    if not isinstance(payload.get("years"), dict):
        raise ValueError("calendar_years_missing")
    return payload


def _verified_year(payload: dict[str, Any], target_day: date) -> dict[str, Any]:
    years = payload.get("years")
    record = years.get(str(target_day.year)) if isinstance(years, dict) else None
    if not isinstance(record, dict):
        raise ValueError("calendar_year_not_published")
    try:
        start = date.fromisoformat(str(record.get("coverage_start") or ""))
        end = date.fromisoformat(str(record.get("coverage_end") or ""))
    except ValueError as exc:
        raise ValueError("calendar_coverage_invalid") from exc
    if start.year != target_day.year or end.year != target_day.year or start > end:
        raise ValueError("calendar_coverage_invalid")
    if not start <= target_day <= end:
        raise ValueError("calendar_date_outside_verified_coverage")
    try:
        verified_on = date.fromisoformat(str(record.get("verified_on") or ""))
    except ValueError as exc:
        raise ValueError("calendar_verification_date_invalid") from exc
    if verified_on > date.today():
        raise ValueError("calendar_verification_date_in_future")
    annual_source = record.get("annual_source")
    if not isinstance(annual_source, dict):
        raise ValueError("annual_source_missing")
    additional_sources = record.get("additional_sources", [])
    if not isinstance(additional_sources, list):
        raise ValueError("additional_sources_invalid")
    sources = [annual_source, *additional_sources]
    for source in sources:
        if (
            not isinstance(source, dict)
            or not str(source.get("title") or "").strip()
            or not str(source.get("url") or "").startswith("https://www.taifex.com.tw/")
        ):
            raise ValueError("official_source_metadata_invalid")
        try:
            date.fromisoformat(str(source.get("published_on") or ""))
        except ValueError as exc:
            raise ValueError("official_source_metadata_invalid") from exc
    if not str(annual_source.get("document") or "").strip():
        raise ValueError("official_source_metadata_invalid")
    closed_dates = record.get("closed_dates")
    if not isinstance(closed_dates, dict):
        raise ValueError("closed_dates_missing")
    for raw_date, reason in closed_dates.items():
        try:
            parsed = date.fromisoformat(str(raw_date))
        except ValueError as exc:
            raise ValueError("closed_date_entry_invalid") from exc
        if (
            parsed.year != target_day.year
            or parsed < start
            or parsed > end
            or not str(reason or "").strip()
        ):
            raise ValueError("closed_date_entry_invalid")
    return record


def get_taifex_index_futures_status(
    today: date | None = None,
    *,
    now: datetime | None = None,
    calendar_path: Path | None = None,
) -> dict[str, Any]:
    """Return the independently verified TAIFEX day-session status for a date.

    The reviewed calendar is deliberately bounded by the official schedule's
    coverage.  Missing, malformed, or out-of-range records produce an
    ``unverified`` status instead of falling back to XTAI or weekdays alone.
    """
    local_now = now or datetime.now(_TAIPEI)
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=_TAIPEI)
    local_now = local_now.astimezone(_TAIPEI)
    target_day = today or local_now.date()
    try:
        payload = _load_calendar(calendar_path or _DEFAULT_DATA_PATH)
        record = _verified_year(payload, target_day)
    except ValueError as exc:
        error_code = str(exc) if str(exc) in _SAFE_CALENDAR_ERRORS else "calendar_data_invalid"
        return _unverified_status(target_day, f"taifex_calendar_invalid:{error_code}")
    except (OSError, UnicodeError, TypeError) as exc:
        return _unverified_status(target_day, f"taifex_calendar_invalid:{type(exc).__name__}")

    closed_dates = record["closed_dates"]
    is_weekday = target_day.weekday() < 5
    closure_reason = str(closed_dates.get(target_day.isoformat()) or "")
    is_trading_day = is_weekday and not closure_reason
    coverage_start = str(record["coverage_start"])
    coverage_end = str(record["coverage_end"])
    annual_source = record["annual_source"]
    all_sources = [annual_source, *record.get("additional_sources", [])]
    source_urls = [str(source["url"]) for source in all_sources]
    basis = "TAIFEX_official_annual_schedule+official_closure_notices"

    result: dict[str, Any] = {
        "label": "台指期日盤",
        "market_component": "TAIFEX Taiwan index futures day session",
        "timezone": TAIFEX_TIMEZONE,
        "calendar": TAIFEX_CALENDAR,
        "calendar_provider": TAIFEX_CALENDAR,
        "calendar_basis": basis,
        "calendar_source_urls": source_urls,
        "calendar_source_published_on": [str(source["published_on"]) for source in all_sources],
        "calendar_coverage_start": coverage_start,
        "calendar_coverage_end": coverage_end,
        "calendar_verified_on": str(record.get("verified_on") or ""),
        "calendar_version": f"{TAIFEX_CALENDAR}-{target_day.year}",
        "calendar_source_document": str(annual_source["document"]),
        "date": target_day.isoformat(),
        "is_trading_day": is_trading_day,
        "calendar_status": "confirmed_open" if is_trading_day else "confirmed_closed",
        "session": "休市" if not is_trading_day else "交易日",
    }
    if not is_trading_day:
        result["closure_reason"] = closure_reason or "週末"
        next_trading_date: str | None = None
        for offset in range(1, 22):
            candidate = target_day + timedelta(days=offset)
            if candidate.isoformat() > coverage_end:
                break
            if candidate.weekday() < 5 and candidate.isoformat() not in closed_dates:
                next_trading_date = candidate.isoformat()
                break
        result["next_trading_date"] = next_trading_date
    else:
        market_open = datetime.combine(target_day, time(8, 45), _TAIPEI)
        market_close = datetime.combine(target_day, time(13, 45), _TAIPEI)
        result["market_open"] = market_open.isoformat()
        result["market_close"] = market_close.isoformat()
        if local_now.date() == target_day:
            if local_now < market_open:
                result["session"] = "開盤前"
            elif local_now <= market_close:
                result["session"] = "交易中"
            else:
                result["session"] = "收盤後"
    return result
