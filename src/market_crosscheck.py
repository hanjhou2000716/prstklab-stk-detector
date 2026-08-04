"""Common cross-market quote verification helpers.

Providers are intentionally injected into these helpers so the production
fetchers can fail independently and tests can verify the decision without
network access.  A missing secondary quote is never presented as confirmed.
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


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            # Daily official closes carry a date but no clock time.  Treat
            # both same-day observations as aligned rather than silently
            # reporting them as uncheckable.
            parsed = datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC)


def compare_quotes(primary: dict[str, Any] | None, secondary: dict[str, Any] | None, *, max_age_minutes: int = 30, max_gap_percent: float = 1.0) -> dict[str, Any]:
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
    age_ok = left_time is not None and right_time is not None and abs((left_time - right_time).total_seconds()) <= max_age_minutes * 60
    checked = gap <= max_gap_percent and age_ok
    return {
        "cross_checked": checked,
        "status": "confirmed" if checked else "discrepancy",
        "price_gap_percent": round(gap, 3),
        "time_aligned": age_ok,
        "sources": [primary, secondary],
    }


def quote_provenance(quote: dict[str, Any]) -> dict[str, Any]:
    """Return the stable card fields required for every market quote."""
    ticker = str(quote.get("ticker") or "")
    source = str(quote.get("quote_source") or quote.get("source") or "公開來源")
    source_label = "TWSE" if "twse" in source.lower() else "TPEx" if "tpex" in source.lower() else "TAIFEX" if "taifex" in source.lower() else "Yahoo" if "yahoo" in source.lower() else "Binance" if "binance" in source.lower() else "CoinGecko" if "coingecko" in source.lower() else source.split(" ")[0]
    raw_sources = quote.get("crosscheck_sources")
    if isinstance(raw_sources, list):
        crosscheck_sources = raw_sources
    elif isinstance(raw_sources, dict):
        # Older TAIEX artifacts used {provider: observation}.  Normalize that
        # shape at the contract boundary so every new card exposes an array.
        crosscheck_sources = []
        for provider, observation in raw_sources.items():
            if isinstance(observation, dict):
                crosscheck_sources.append({
                    "label": str(provider).upper() if provider else source_label,
                    "url": observation.get("source_url") or observation.get("url") or "",
                    "quote_time": observation.get("quote_time") or observation.get("quote_date") or "",
                    "quote_date": observation.get("quote_date"),
                    "price": observation.get("price"),
                    "change_percent": observation.get("change_percent"),
                })
    else:
        crosscheck_sources = []
    return {
        "source_label": source_label,
        "quote_time": quote.get("quote_time") or quote.get("quote_date"),
        "quote_basis": "盤中" if quote.get("quote_time") and not quote.get("quote_delayed") else "最近收盤",
        "cross_checked": bool(quote.get("cross_checked") or quote.get("crosscheck_status") == "已交叉核對"),
        "crosscheck_status": quote.get("crosscheck_status") or "未交叉核對",
        "crosscheck_sources": crosscheck_sources,
        "expected_sources": list(MARKET_SOURCE_PAIRS.get(ticker, (source_label, ""))),
    }

