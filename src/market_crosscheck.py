"""Common cross-market quote verification helpers.

Providers are intentionally injected into these helpers so production
fetchers can fail independently and tests can verify decisions without
network access. A missing secondary quote is never presented as confirmed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

MARKET_SOURCE_PAIRS = {
    "TAIEX": ("TWSE", "TAIFEX"),
    "TPEx": ("TPEx", "TWSE MIS"),
    "NASDAQ": ("Yahoo", "public-market-secondary"),
    "SOX": ("Yahoo", "public-market-secondary"),
    "S&P 500": ("Yahoo", "public-market-secondary"),
    "DJIA": ("Yahoo", "public-market-secondary"),
    "NIKKEI": ("Yahoo", "public-market-secondary"),
    "KOSPI": ("Yahoo", "public-market-secondary"),
    "BTC": ("Binance", "CoinGecko"),
    "ETH": ("Binance", "CoinGecko"),
    "WTI": ("Yahoo", "EIA"),
    "BRENT": ("Yahoo", "public-market-secondary"),
    "GOLD": ("Yahoo", "public-market-secondary"),
    "VIX": ("Yahoo", "official-history"),
}

CONFIRMED_STATUS_VALUES = frozenset({
    "confirmed",
    "verified",
    "cross_checked",
    "cross-checked",
    "已交叉核對",
    "已核對",
    "交叉核對",
})


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC)


def compare_quotes(
    primary: dict[str, Any] | None,
    secondary: dict[str, Any] | None,
    *,
    max_age_minutes: int = 30,
    max_gap_percent: float = 1.0,
) -> dict[str, Any]:
    """Compare two same-asset observations without comparing unlike contracts."""
    if not primary or not secondary:
        return {"cross_checked": False, "status": "secondary_unavailable", "sources": [primary, secondary]}
    primary_price = primary.get("price")
    secondary_price = secondary.get("price")
    if primary_price is None or secondary_price is None:
        return {"cross_checked": False, "status": "price_unavailable", "sources": [primary, secondary]}
    try:
        gap = abs(float(primary_price) / float(secondary_price) - 1) * 100
    except (TypeError, ValueError, ZeroDivisionError):
        return {"cross_checked": False, "status": "invalid_price", "sources": [primary, secondary]}
    left_time = _timestamp(primary.get("quote_time") or primary.get("quote_date"))
    right_time = _timestamp(secondary.get("quote_time") or secondary.get("quote_date"))
    age_ok = (
        left_time is not None
        and right_time is not None
        and abs((left_time - right_time).total_seconds()) <= max_age_minutes * 60
    )
    checked = gap <= max_gap_percent and age_ok
    return {
        "cross_checked": checked,
        "status": "confirmed" if checked else "discrepancy",
        "price_gap_percent": round(gap, 3),
        "time_aligned": age_ok,
        "sources": [primary, secondary],
    }


def quote_provenance(quote: dict[str, Any]) -> dict[str, Any]:
    """Return stable card fields required for every market quote."""
    ticker = str(quote.get("ticker") or "")
    # Keep source priority and comparison semantics in the published
    # provenance.  The policy is imported lazily because source_policy uses
    # this module's generic quote comparator; doing so avoids an import cycle
    # while ensuring every producer and consumer sees the same contract.
    from src.source_policy import source_policy_for

    policy = source_policy_for(ticker)
    source = str(quote.get("quote_source") or quote.get("source") or "unknown")
    source_lower = source.lower()
    if "twse" in source_lower:
        source_label = "TWSE"
    elif "tpex" in source_lower:
        source_label = "TPEx"
    elif "taifex" in source_lower:
        source_label = "TAIFEX"
    elif "yahoo" in source_lower:
        source_label = "Yahoo"
    elif "binance" in source_lower:
        source_label = "Binance"
    elif "coingecko" in source_lower:
        source_label = "CoinGecko"
    else:
        source_label = source.split(" ")[0]
    raw_sources = quote.get("crosscheck_sources")
    if isinstance(raw_sources, list):
        crosscheck_sources = raw_sources
    elif isinstance(raw_sources, dict):
        crosscheck_sources = []
        for provider, observation in raw_sources.items():
            if isinstance(observation, dict):
                crosscheck_sources.append({
                    "provider": str(provider).upper() if provider else source_label,
                    "label": str(provider).upper() if provider else source_label,
                    "source_url": observation.get("source_url") or observation.get("url") or "",
                    "url": observation.get("source_url") or observation.get("url") or "",
                    "quote_time": observation.get("quote_time") or observation.get("quote_date") or "",
                    "quote_date": observation.get("quote_date"),
                    "price": observation.get("price"),
                    "change_percent": observation.get("change_percent"),
                })
    else:
        crosscheck_sources = []
    status = str(quote.get("crosscheck_status") or "").strip().lower()
    cross_checked = bool(quote.get("cross_checked")) or status in CONFIRMED_STATUS_VALUES
    return {
        "source_label": source_label,
        "quote_time": quote.get("quote_time") or quote.get("quote_date"),
        "quote_basis": "盤中" if quote.get("quote_time") and not quote.get("quote_delayed") else "最近收盤",
        "cross_checked": cross_checked,
        "crosscheck_status": quote.get("crosscheck_status") or "未交叉核對",
        "crosscheck_sources": crosscheck_sources,
        "expected_sources": list(
            policy.primary + policy.secondary
            if policy.primary and policy.secondary
            else MARKET_SOURCE_PAIRS.get(ticker, (source_label, ""))
        ),
        "crosscheck_policy": policy.to_dict(),
        "comparison_basis": (
            "direction_only" if ticker.strip().upper() == "TAIEX"
            else "price_and_time" if policy.primary and policy.secondary
            else "not_defined"
        ),
    }
