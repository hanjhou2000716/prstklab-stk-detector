"""One date-eligibility gate for current and retained market news."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

NEWS_MAX_TRADING_SESSIONS = 5
NEWS_MAX_CALENDAR_DAYS = 10
_MARKET_CALENDARS = {
    "taiwan": ("XTAI", "Asia/Taipei"),
    "us": ("NYSE", "America/New_York"),
}


@lru_cache(maxsize=32)
def _sessions_for_reference(calendar_name: str, reference_day: date) -> tuple[date, ...]:
    """Cache one month of exchange sessions for every scan/reference day."""
    import pandas_market_calendars as mcal

    exchange = mcal.get_calendar(calendar_name)
    schedule = exchange.schedule(
        start_date=reference_day - timedelta(days=30),
        end_date=reference_day,
    )
    return tuple(index.date() for index in schedule.index)


def _aware_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif value in (None, ""):
        return None
    else:
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def qualify_market_news_date(
    published_at: Any,
    market: str,
    reference_time: Any = None,
) -> dict[str, Any]:
    """Return a fail-closed, exchange-session-aware publication-date decision.

    The publication date is never inferred from fetch time.  ``current`` means
    the story was published on the scan's local calendar date; otherwise an
    eligible story is explicitly a recent reference, regardless of how it was
    retrieved (current scan or retained inventory).
    """
    market_key = str(market or "").casefold()
    calendar_spec = _MARKET_CALENDARS.get(market_key)
    if not calendar_spec:
        return {"eligible": False, "status": "excluded", "reason": "unsupported_market", "trading_sessions": None}

    published = _aware_datetime(published_at)
    if published is None:
        reason = "missing_published_at" if published_at in (None, "") else "invalid_published_at"
        return {"eligible": False, "status": "excluded", "reason": reason, "trading_sessions": None}
    reference = _aware_datetime(reference_time) if reference_time is not None else datetime.now(UTC)
    if reference is None:
        return {"eligible": False, "status": "excluded", "reason": "invalid_reference_time", "trading_sessions": None}
    if published > reference:
        return {"eligible": False, "status": "excluded", "reason": "future_published_at", "trading_sessions": None}

    calendar_name, zone_name = calendar_spec
    zone = ZoneInfo(zone_name)
    published_local = published.astimezone(zone)
    reference_local = reference.astimezone(zone)
    calendar_days = (reference_local.date() - published_local.date()).days
    if calendar_days < 0:
        return {"eligible": False, "status": "excluded", "reason": "future_published_at", "trading_sessions": None}
    if calendar_days > NEWS_MAX_CALENDAR_DAYS:
        return {"eligible": False, "status": "excluded", "reason": "outside_calendar_window", "trading_sessions": None}

    try:
        source_day = published_local.date()
        current_day = reference_local.date()
        sessions = _sessions_for_reference(calendar_name, current_day)
    except (ImportError, KeyError, TypeError, ValueError, IndexError):
        return {"eligible": False, "status": "excluded", "reason": "market_calendar_unavailable", "trading_sessions": None}

    anchors = [session for session in sessions if session <= source_day]
    if not anchors:
        return {"eligible": False, "status": "excluded", "reason": "market_session_unavailable", "trading_sessions": None}
    anchor = anchors[-1]
    age = sum(1 for session in sessions if anchor <= session <= current_day)
    if age < 1:
        return {"eligible": False, "status": "excluded", "reason": "market_session_unavailable", "trading_sessions": None}
    if age > NEWS_MAX_TRADING_SESSIONS:
        return {"eligible": False, "status": "excluded", "reason": "outside_trading_session_window", "trading_sessions": age}

    current_date = published_local.date() == reference_local.date()
    return {
        "eligible": True,
        "status": "current" if current_date else "recent_reference",
        "reason": None,
        "trading_sessions": age,
        "calendar_days": calendar_days,
        "published_local_date": published_local.date().isoformat(),
    }
