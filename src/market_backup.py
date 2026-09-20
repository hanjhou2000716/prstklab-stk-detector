"""Private Supabase last-known-good market observation store.

The store is deliberately optional for local runs.  A missing or unavailable
backup never becomes a fake healthy result: callers keep the source gap and
disable alert eligibility.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime, timedelta
from typing import Any

import requests

BACKUP_MAX_COMPLETED_SESSIONS = 3
BACKUP_SCHEMA_VERSION = "market-observations-v1"

_SESSION_POLICIES = {
    "taiwan": "XTAI",
    "us": "NYSE",
    "asia_japan": "JPX",
    "asia_korea": "XKRX",
    "us_close": "NYSE",
    "futures_energy": "CMEGlobex_Energy",
    "usd_twd": "XTAI",
}
_TICKER_POLICIES = {
    "NIKKEI": "asia_japan",
    "KOSPI": "asia_korea",
    "DXY": "us_close",
    "US10Y": "us_close",
    "BRENT": "futures_energy",
    "WTI": "futures_energy",
    "GOLD": "futures_energy",
    "USD/TWD": "usd_twd",
}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed and abs(parsed) != float("inf") else None


def _iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).isoformat()


def payload_hash(quote: dict[str, Any]) -> str:
    """Hash only normalized public fields, never the full provider payload."""
    fields = {
        key: quote.get(key)
        for key in (
            "ticker", "instrument_id", "market", "market_date", "quote_date",
            "price", "previous_close", "change", "change_percent", "volume", "currency",
            "quote_basis", "source_label", "quote_source",
        )
    }
    canonical = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class MarketBackupError(RuntimeError):
    """Raised when a configured backup operation cannot be trusted."""


class SupabaseMarketObservationStore:
    """Small service-role REST client for the private market backup tables."""

    def __init__(self, url: str, service_role_key: str, *, session: requests.Session | None = None) -> None:
        base = str(url or "").strip().rstrip("/")
        token = str(service_role_key or "").strip()
        if not base or not token:
            raise ValueError("Supabase market backup is not configured")
        self.base_url = f"{base}/rest/v1"
        self.session = session or requests.Session()
        self.headers = {
            "apikey": token,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, table: str, *, params: dict[str, Any] | None = None, payload: Any = None) -> Any:
        headers = dict(self.headers)
        if method.upper() in {"POST", "PATCH", "PUT"}:
            headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
        response = self.session.request(
            method,
            f"{self.base_url}/{table}",
            headers=headers,
            params=params,
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()

    def _quote_row(self, quote: dict[str, Any], *, fetched_at: datetime | None = None) -> dict[str, Any]:
        ticker = str(quote.get("ticker") or "").strip()
        market_date = str(quote.get("quote_date") or "").strip()
        instrument_id = str(quote.get("instrument_id") or f"market:{ticker.casefold()}").strip()
        provider = str(quote.get("source_label") or quote.get("quote_source") or "public-market").strip()
        if not ticker or not market_date or not instrument_id or _number(quote.get("price")) is None:
            raise MarketBackupError("invalid_normalized_quote")
        try:
            date.fromisoformat(market_date)
        except ValueError as exc:
            raise MarketBackupError("invalid_market_date") from exc
        captured = fetched_at or datetime.now(UTC)
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=UTC)
        return {
            "instrument_id": instrument_id,
            "ticker": ticker,
            "provider": provider[:120],
            "source_tier": "official" if str(quote.get("source_tier")) == "official" else "public-market",
            "market_date": market_date,
            "observed_at": _iso(quote.get("quote_time")),
            "price": _number(quote.get("price")),
            "previous_close": _number(quote.get("previous_close")),
            "change": _number(quote.get("change")),
            "change_percent": _number(quote.get("change_percent")),
            "volume": _number(quote.get("volume")),
            "quote_basis": str(quote.get("quote_basis") or "日線收盤")[:120],
            "currency": str(quote.get("currency") or "")[:16] or None,
            "quality_status": "verified" if quote.get("freshness") in {"live", "recent_close"} else "recent_close",
            "payload_hash": payload_hash(quote),
            "parser_version": BACKUP_SCHEMA_VERSION,
            "source_url": str(quote.get("source_url") or "")[:500] or None,
            "fetched_at": captured.isoformat(),
            "expires_at": (captured + timedelta(days=548)).isoformat(),
        }

    def upsert_quote(self, quote: dict[str, Any], *, fetched_at: datetime | None = None) -> dict[str, Any]:
        """Idempotently write one normalized observation."""
        result = self.upsert_quotes([quote], fetched_at=fetched_at)
        return result[0]

    def upsert_quotes(
        self,
        quotes: list[dict[str, Any]],
        *,
        fetched_at: datetime | None = None,
        batch_size: int = 100,
    ) -> list[dict[str, Any]]:
        """Idempotently write observations in bounded REST batches.

        Backfills can contain hundreds of daily rows.  Sending one request per
        row makes a GitHub runner appear hung and needlessly increases the
        chance of a transient failure.  Supabase/PostgREST upsert accepts an
        array, and the migration's unique key keeps reruns idempotent.
        """
        rows = [self._quote_row(quote, fetched_at=fetched_at) for quote in quotes]
        if not rows:
            return []
        results: list[dict[str, Any]] = []
        size = max(1, min(int(batch_size), 100))
        for start in range(0, len(rows), size):
            batch = rows[start:start + size]
            self._request(
                "POST",
                "market_observations",
                params={"on_conflict": "instrument_id,provider,market_date,quote_basis"},
                payload=batch,
            )
            results.extend({
                "stored": True,
                "ticker": str(row["ticker"]),
                "market_date": str(row["market_date"]),
                "provider": str(row["provider"]),
            } for row in batch)
        return results

    def latest_quote(self, ticker: str, *, before_or_on: str, provider: str | None = None) -> dict[str, Any] | None:
        params: dict[str, Any] = {
            "ticker": f"eq.{ticker}",
            "market_date": f"lte.{before_or_on}",
            "quality_status": "in.(verified,recent_close,degraded_with_fallback)",
            "order": "market_date.desc,fetched_at.desc",
            "limit": "1",
        }
        if provider:
            params["provider"] = f"eq.{provider}"
        rows = self._request("GET", "market_observations", params=params)
        if not isinstance(rows, list) or not rows:
            return None
        return rows[0] if isinstance(rows[0], dict) else None

    def history_quotes(self, ticker: str, *, limit: int = 500) -> list[dict[str, Any]]:
        rows = self._request(
            "GET",
            "market_observations",
            params={
                "ticker": f"eq.{ticker}",
                "quality_status": "in.(verified,recent_close,degraded_with_fallback)",
                "order": "market_date.asc,fetched_at.asc",
                "limit": str(max(1, min(int(limit), 1000))),
            },
        )
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

    def update_source_state(self, instrument_id: str, state: dict[str, Any]) -> None:
        row = {
            "instrument_id": instrument_id,
            "status": str(state.get("status") or "unavailable"),
            "active_provider": str(state.get("active_provider") or "")[:120] or None,
            "last_success_at": _iso(state.get("last_success_at")),
            "last_failure_at": _iso(state.get("last_failure_at")),
            "consecutive_failures": max(0, int(state.get("consecutive_failures") or 0)),
            "last_error_code": str(state.get("last_error_code") or "")[:120] or None,
            "fallback_used": bool(state.get("fallback_used")),
            "fallback_market_date": state.get("fallback_market_date"),
            "circuit_state": str(state.get("circuit_state") or "closed"),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        self._request("POST", "market_source_state", params={"on_conflict": "instrument_id"}, payload=row)


def from_environment(*, session: requests.Session | None = None) -> SupabaseMarketObservationStore | None:
    if os.getenv("MARKET_BACKUP_ENABLED", "").strip().lower() not in {"1", "true", "yes", "on"}:
        return None
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        return None
    try:
        return SupabaseMarketObservationStore(url, key, session=session)
    except ValueError:
        return None


def backup_quote_within_limit(
    quote: dict[str, Any], *, expected_market_date: date, max_completed_sessions: int = BACKUP_MAX_COMPLETED_SESSIONS,
) -> bool:
    """Accept only a bounded number of completed sessions of last-known-good data.

    The old implementation used calendar-day subtraction, which made a Friday
    close look four days old on a Monday and applied Taiwan weekends to global
    assets.  A quote with a known market policy is now measured against that
    exchange's completed sessions.  Unknown instruments retain a conservative
    weekday fallback for backwards compatibility.
    """
    try:
        observed = date.fromisoformat(str(quote.get("market_date") or quote.get("quote_date") or ""))
    except ValueError:
        return False
    if observed > expected_market_date or _number(quote.get("price")) is None:
        return False
    market = str(quote.get("market") or "").strip()
    ticker = str(quote.get("ticker") or "").strip()
    policy = _TICKER_POLICIES.get(ticker)
    calendar_name = _SESSION_POLICIES.get(market) or _SESSION_POLICIES.get(policy or "")
    if calendar_name:
        try:
            import pandas_market_calendars as mcal

            schedule = mcal.get_calendar(calendar_name).schedule(
                start_date=observed, end_date=expected_market_date,
            )
            age = sum(session.date() > observed for session in schedule.index)
        except Exception:
            # Falling back to calendar days is safer than silently accepting an
            # unknown age, and the caller still marks the result stale.
            age = (expected_market_date - observed).days
    else:
        age = (expected_market_date - observed).days
    return 0 <= age <= max(0, int(max_completed_sessions))


__all__ = [
    "BACKUP_MAX_COMPLETED_SESSIONS", "MarketBackupError", "SupabaseMarketObservationStore",
    "backup_quote_within_limit", "from_environment", "payload_hash",
]
