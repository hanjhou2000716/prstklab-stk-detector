"""Independent public market observations for Phase 5 quote verification.

Stooq is used only as a secondary, read-only observation.  It is never used
to replace a missing primary quote, and an unavailable response is exposed as
a health gap instead of being interpreted as a confirmation.
"""

from __future__ import annotations

from datetime import UTC, datetime
import csv
import io
from typing import Any, Callable

import requests


STOOQ_URL = "https://stooq.com/q/l/"
SYMBOLS = {
    "S&P 500": "^spx",
    "NASDAQ": "^ndq",
    "DJIA": "^dji",
    "SOX": "^sox",
    "NIKKEI": "^nkx",
    "KOSPI": "^kospi",
    "WTI": "cl.f",
    "BRENT": "brn.f",
    "GOLD": "gc.f",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_row(text: str, ticker: str) -> dict[str, Any]:
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise ValueError("empty stooq response")
    row = rows[0]
    close = row.get("Close")
    if not close or close.upper() in {"N/D", "NA", "N/A"}:
        raise ValueError("missing stooq close")
    date = row.get("Date")
    time = row.get("Time")
    quote_time = f"{date}T{time}+00:00" if date and time and time != "N/D" else None
    return {
        "ticker": ticker,
        "price": float(close),
        "quote_date": date if date and date != "N/D" else None,
        "quote_time": quote_time,
        "quote_basis": "最近收盤",
        "quote_source": "Stooq public market quote",
        "source_url": f"{STOOQ_URL}?s={SYMBOLS[ticker]}&f=sd2t2ohlcv&h&e=csv",
        "source_domain": "stooq.com",
    }


def fetch_public_market_secondary(
    *, timeout: int = 15, requester: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Fetch independent public close observations with per-symbol isolation."""
    requester = requester or requests.get
    checked_at = _now()
    quotes: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for ticker, symbol in SYMBOLS.items():
        try:
            response = requester(
                STOOQ_URL,
                params={"s": symbol, "f": "sd2t2ohlcv", "h": "", "e": "csv"},
                timeout=timeout,
                headers={"Accept": "text/csv"},
            )
            response.raise_for_status()
            quotes[ticker] = _parse_row(response.text, ticker)
        except Exception as exc:
            errors.append(f"{ticker}:{type(exc).__name__}")
    status = "healthy" if quotes and not errors else "partial" if quotes else "failed"
    return {
        "status": status,
        "quotes": quotes,
        "errors": errors,
        "fetched_at": checked_at,
        "health": {
            "key": "public_market_secondary",
            "label": "Stooq 海外／商品第二行情來源",
            "source_tier": "public-market",
            "source_url": STOOQ_URL,
            "status": "healthy" if status == "healthy" else "partial",
            "provider_status": status,
            "checked_at": checked_at,
            "item_count": len(quotes),
            "data_gap": errors or None,
        },
    }
