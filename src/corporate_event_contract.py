"""Corporate-event provenance and eligibility contract.

Corporate notices are useful evidence, but they are not interchangeable with
market-wide events.  This normalizer keeps issuer identity and publication
provenance explicit, and fails closed when a required field is absent.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from src.intel_contract import normalize_event_record


CORPORATE_SOURCE_KEYS = {"mops", "twse", "twse_market", "sec"}
ISSUER_CODE_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def _published_at(record: dict[str, Any]) -> str | None:
    value = record.get("published_at") or record.get("released_at") or record.get("event_time")
    return str(value).strip() or None if value is not None else None


def _ticker(record: dict[str, Any]) -> str | None:
    for key in ("issuer_ticker", "ticker", "symbol", "code"):
        value = str(record.get(key) or "").strip()
        if value:
            return value.upper()
    match = ISSUER_CODE_RE.search(str(record.get("title") or ""))
    return match.group(1) if match else None


def normalize_corporate_event(
    record: dict[str, Any], *, fetched_at: str | None = None
) -> dict[str, Any]:
    """Normalize a corporate notice and expose fail-closed eligibility."""
    item = normalize_event_record(record, fetched_at=fetched_at)
    source_key = str(item.get("source_key") or "").lower()
    ticker = _ticker(item)
    gaps: list[str] = []
    if not ticker:
        gaps.append("missing_issuer")
    if not _published_at(item):
        gaps.append("missing_published_at")
    if not str(item.get("source_url") or "").strip():
        gaps.append("missing_source_url")
    item.update({
        "issuer_ticker": ticker,
        "corporate_event": True,
        "corporate_scope": "core_observation" if source_key in {"mops", "twse", "twse_market"} else "sec_watchlist",
        "corporate_candidate_eligible": not gaps,
        "corporate_data_gaps": gaps,
    })
    if gaps:
        item["data_gap"] = ";".join(gaps)
    return item

