"""Market-specific source priority and cross-check policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.market_crosscheck import compare_quotes


@dataclass(frozen=True)
class SourcePolicy:
    ticker: str
    primary: str
    secondary: str
    max_age_minutes: int = 30
    max_gap_percent: float = 1.0
    require_confirmation_for_alert: bool = True


SOURCE_POLICIES = {
    "TAIEX": SourcePolicy("TAIEX", "TWSE", "TAIFEX", max_age_minutes=30, max_gap_percent=1.0),
    "TPEx": SourcePolicy("TPEx", "TPEx", "TWSE MIS", max_age_minutes=30, max_gap_percent=1.0),
    "S&P 500": SourcePolicy("S&P 500", "Yahoo", "public-market-secondary", max_age_minutes=60, max_gap_percent=1.5),
    "NASDAQ": SourcePolicy("NASDAQ", "Yahoo", "public-market-secondary", max_age_minutes=60, max_gap_percent=1.5),
    "DJIA": SourcePolicy("DJIA", "Yahoo", "public-market-secondary", max_age_minutes=60, max_gap_percent=1.5),
    "SOX": SourcePolicy("SOX", "Yahoo", "public-market-secondary", max_age_minutes=60, max_gap_percent=1.5),
    "BTC": SourcePolicy("BTC", "Binance", "CoinGecko", max_age_minutes=15, max_gap_percent=2.0),
    "ETH": SourcePolicy("ETH", "Binance", "CoinGecko", max_age_minutes=15, max_gap_percent=2.0),
    "WTI": SourcePolicy("WTI", "Yahoo", "EIA", max_age_minutes=24 * 60, max_gap_percent=5.0),
    "BRENT": SourcePolicy("BRENT", "Yahoo", "public-market-secondary", max_age_minutes=24 * 60, max_gap_percent=5.0),
    "GOLD": SourcePolicy("GOLD", "Yahoo", "public-market-secondary", max_age_minutes=24 * 60, max_gap_percent=5.0),
    "VIX": SourcePolicy("VIX", "Yahoo", "official-history", max_age_minutes=24 * 60, max_gap_percent=2.0),
}


def policy_for(ticker: str) -> SourcePolicy:
    return SOURCE_POLICIES.get(ticker, SourcePolicy(ticker, "primary", "secondary"))


def _time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC)


def _source_label(quote: dict[str, Any] | None, fallback: str) -> str:
    if not quote:
        return fallback
    return str(quote.get("source_label") or quote.get("quote_source") or quote.get("source") or fallback)


def cross_check_market(
    ticker: str,
    primary: dict[str, Any] | None,
    secondary: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a publishable quote evidence record; never infer confirmation."""
    policy = policy_for(ticker)
    comparison = compare_quotes(primary, secondary, max_age_minutes=policy.max_age_minutes, max_gap_percent=policy.max_gap_percent)
    primary_time = _time((primary or {}).get("quote_time") or (primary or {}).get("quote_date"))
    current = (now or datetime.now(UTC)).astimezone(UTC)
    age_minutes = (current - primary_time.astimezone(UTC)).total_seconds() / 60 if primary_time else None
    fresh = age_minutes is not None and age_minutes <= policy.max_age_minutes
    confirmed = bool(comparison.get("cross_checked")) and fresh
    status = "confirmed" if confirmed else "stale" if primary and not fresh else str(comparison.get("status") or "unavailable")
    return {
        "ticker": ticker,
        "primary_source": _source_label(primary, policy.primary),
        "secondary_source": _source_label(secondary, policy.secondary),
        "expected_sources": [policy.primary, policy.secondary],
        "primary_url": (primary or {}).get("source_url") or (primary or {}).get("url"),
        "secondary_url": (secondary or {}).get("source_url") or (secondary or {}).get("url"),
        "quote_time": (primary or {}).get("quote_time") or (primary or {}).get("quote_date"),
        "quote_basis": (primary or {}).get("quote_basis") or (primary or {}).get("freshness") or "unknown",
        "freshness": "recent" if fresh else "stale_or_unknown",
        "age_minutes": round(age_minutes, 1) if age_minutes is not None else None,
        "price_gap_percent": comparison.get("price_gap_percent"),
        "time_aligned": bool(comparison.get("time_aligned")),
        "cross_checked": confirmed,
        "status": status,
        "alert_allowed": confirmed if policy.require_confirmation_for_alert else fresh,
        "research_allowed": confirmed or (fresh and secondary is None),
    }


def source_health_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate source evidence without hiding unavailable second sources."""
    confirmed = sum(bool(item.get("cross_checked")) for item in records)
    return {
        "total": len(records),
        "confirmed": confirmed,
        "unconfirmed": len(records) - confirmed,
        "status": "healthy" if records and confirmed == len(records) else "partial" if records else "failed",
    }