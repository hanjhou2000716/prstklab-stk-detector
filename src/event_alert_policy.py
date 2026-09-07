"""Rate and materiality gates for the realtime event notification lane."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

EVENT_MIN_GAP_SECONDS = 90 * 60
EVENT_DAILY_MAX = 2
TAIPEI = ZoneInfo("Asia/Taipei")

# These are the fixed floors from the delivery contract.  A producer may also
# attach a rolling 20-session typical move; the effective floor is the larger
# of the two, so a calm market cannot accidentally lower the contract.
FIXED_MOVE_FLOORS = {
    "TAIEX": 0.5,
    "TPEX": 0.5,
    "2330": 0.8,
    "SOX": 0.8,
    "NASDAQ": 0.8,
    "S&P 500": 0.8,
    "DJIA": 0.8,
    "VIX": 1.2,
    "US10Y": 0.06,
    "USD/TWD": 0.2,
    "DXY": 0.2,
    "WTI": 1.2,
    "BRENT": 1.2,
}


def _instrument(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("instrument")
    return value if isinstance(value, dict) else event


def _time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)


def event_market_scope(event: dict[str, Any]) -> str:
    """Return the narrowest market bucket that can share a cooling window."""
    explicit = str(event.get("market_scope") or event.get("market") or "").strip().casefold()
    if explicit:
        if explicit in {"taiwan", "台股", "tw", "xtai"}:
            return "taiwan"
        if explicit in {"us", "美股", "nyse", "nasdaq"}:
            return "us"
        return explicit
    instrument = _instrument(event)
    ticker = str(instrument.get("ticker") or "").strip().upper()
    if ticker in {"TAIEX", "TPEX", "2330"}:
        return "taiwan"
    if ticker in {"SOX", "NASDAQ", "S&P 500", "DJIA", "VIX"}:
        return "us"
    category = str(event.get("market_topic") or event.get("classification") or event.get("event_type") or "").casefold()
    if category in {"taiwan_market", "taiwan", "twse", "mops"}:
        return "taiwan"
    if category in {"global_market", "us_market", "us", "sec"}:
        return "us"
    return "global"


def _risk_code(event: dict[str, Any]) -> str:
    nested = event.get("prstk_risk")
    if isinstance(nested, dict) and nested.get("prstk_risk_level"):
        return str(nested["prstk_risk_level"]).upper()
    return str(event.get("prstk_risk_level") or event.get("risk_level") or "").upper()


def _is_r4(event: dict[str, Any]) -> bool:
    return _risk_code(event) == "R4" or str(event.get("risk_level") or "") == "高風險" and bool(event.get("escalation"))


def _signal_threshold(event: dict[str, Any]) -> tuple[float | None, float | None, str]:
    instrument = _instrument(event)
    ticker = str(instrument.get("ticker") or "").strip().upper()
    fixed = FIXED_MOVE_FLOORS.get(ticker)
    if fixed is None:
        return None, None, ticker
    rolling: float | None = None
    for key in ("typical_move_percent", "volatility_20d_percent", "rolling_volatility_percent", "volatility_percent"):
        raw_value = instrument.get(key)
        if not isinstance(raw_value, (int, float, str)) or raw_value == "":
            continue
        try:
            candidate = float(raw_value)
        except (TypeError, ValueError):
            continue
        if candidate >= 0:
            rolling = candidate * 0.75
            break
    return max(fixed, rolling or 0.0), fixed, ticker


def _successful_event_rows(history: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in history:
        if not isinstance(row, dict):
            continue
        if str(row.get("alert_lane") or "").casefold() != "event":
            continue
        if str(row.get("delivery_status") or "delivered").casefold() not in {"delivered", "partial"}:
            continue
        if _time(row.get("sent_at")) is not None:
            rows.append(row)
    return rows


def decide_event_alert_policy(
    event: dict[str, Any],
    history: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fail closed on event volume while leaving the scheduled brief lane alone."""
    current = (now or datetime.now(UTC)).astimezone(UTC)
    # Minimal adapter doubles and old official snapshots do not carry enough
    # fields for the new event contract.  Keep their established budget path;
    # production-normalized events always have one of these fields.
    structured = event.get("kind") == "market_signal" or any(
        event.get(key) not in (None, "", [], {})
        for key in ("classification", "event_type", "market_topic", "market_scope", "canonical_fact_key", "source_published_at")
    )
    if not structured:
        return {"allowed": True, "reason": "legacy_event_shape", "market_scope": "global", "daily_count": 0}

    rows = _successful_event_rows(history)
    scope = event_market_scope(event)
    scoped = [row for row in rows if str(row.get("market_scope") or "global") == scope]
    today = current.astimezone(TAIPEI).date()
    today_rows = [row for row in rows if (_time(row.get("sent_at")) or current).astimezone(TAIPEI).date() == today]
    r4 = _is_r4(event)
    if len(today_rows) >= EVENT_DAILY_MAX:
        return {
            "allowed": False,
            "reason": "event_daily_budget_exhausted",
            "market_scope": scope,
            "daily_count": len(today_rows),
            "daily_max": EVENT_DAILY_MAX,
            "r4_override": False,
        }
    sent_times = [sent_at for row in scoped if (sent_at := _time(row.get("sent_at"))) is not None]
    latest = max(sent_times) if sent_times else None
    if latest is not None and current - latest < timedelta(seconds=EVENT_MIN_GAP_SECONDS) and not r4:
        return {
            "allowed": False,
            "reason": "event_market_cooldown",
            "market_scope": scope,
            "daily_count": len(today_rows),
            "min_gap_seconds": EVENT_MIN_GAP_SECONDS,
            "last_sent_at": latest.isoformat(),
            "r4_override": False,
        }

    threshold, fixed_floor, ticker = _signal_threshold(event)
    if threshold is not None:
        instrument = _instrument(event)
        raw_move = instrument.get("change_percent")
        try:
            move = abs(float(raw_move)) if isinstance(raw_move, (int, float, str)) and raw_move != "" else None
        except (TypeError, ValueError):
            move = None
        if move is None or move < threshold:
            return {
                "allowed": False,
                "reason": "sensitive_move_below_threshold",
                "market_scope": scope,
                "ticker": ticker,
                "change_percent": move,
                "effective_threshold": threshold,
                "fixed_floor": fixed_floor,
                "daily_count": len(today_rows),
            }
    return {
        "allowed": True,
        "reason": "event_materiality_available",
        "market_scope": scope,
        "daily_count": len(today_rows),
        "effective_threshold": threshold,
        "fixed_floor": fixed_floor,
        "r4_override": r4,
    }
