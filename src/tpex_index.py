"""TPEx OpenAPI closing-index reader for the public market dashboard."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import requests


TPEX_INDEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_index"
HEADERS = {"User-Agent": "PRStK-Lab-public-research/1.0"}


def _number(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> str | None:
    try:
        return datetime.strptime(str(value), "%Y%m%d").date().isoformat()
    except (TypeError, ValueError):
        return None


def parse_tpex_index(payload: Any) -> dict[str, Any] | None:
    """Return the latest two official closes; never infer an intraday quote."""
    if not isinstance(payload, list):
        return None
    rows = sorted((item for item in payload if isinstance(item, dict)), key=lambda item: str(item.get("Date") or ""))
    if len(rows) < 2:
        return None
    latest, previous = rows[-1], rows[-2]
    close, prior_close, quote_date = _number(latest.get("Close")), _number(previous.get("Close")), _date(latest.get("Date"))
    if close is None or prior_close is None or quote_date is None or prior_close == 0:
        return None
    return {
        "symbol": "^TWOII",
        "ticker": "TPEx",
        "name": "臺灣上櫃指數",
        "market": "taiwan",
        "currency": "點",
        "price": round(close, 2),
        "previous_close": round(prior_close, 2),
        "change": round(close - prior_close, 2),
        "change_percent": round((close / prior_close - 1) * 100, 2),
        "quote_date": quote_date,
        "quote_time": None,
        "quote_source": "TPEx OpenAPI official close",
        "quote_basis": "TPEx 官方最近收盤",
        "quote_delayed": False,
    }


def fetch_tpex_index(session: requests.Session | None = None) -> dict[str, Any] | None:
    client = session or requests.Session()
    response = client.get(TPEX_INDEX_URL, headers=HEADERS, timeout=20)
    response.raise_for_status()
    return parse_tpex_index(response.json())
