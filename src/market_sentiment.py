"""Market-scoped, freshness-checked sentiment projections for public briefings."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

_TAIPEI = ZoneInfo("Asia/Taipei")
_NEW_YORK = ZoneInfo("America/New_York")
_MAX_SENTIMENT_AGE = timedelta(hours=36)


def _instant(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def project_market_sentiments(
    risk: Any,
    *,
    market_scope: str | None,
    as_of: Any,
) -> list[dict[str, Any]]:
    """Return only fresh, explicitly eligible sentiment from its own market."""
    root = risk if isinstance(risk, dict) else {}
    current = _instant(as_of)
    if current is None:
        return []
    scopes = [market_scope] if market_scope in {"taiwan", "us"} else ["taiwan", "us"]
    result: list[dict[str, Any]] = []
    for scope in scopes:
        market = root.get(scope)
        market = market if isinstance(market, dict) else {}
        sentiment = market.get("sentiment")
        sentiment = sentiment if isinstance(sentiment, dict) else {}
        if market.get("sentiment_signal_eligible") is not True:
            continue
        try:
            score = float(sentiment.get("score"))
        except (TypeError, ValueError):
            continue
        label = str(sentiment.get("label") or "").strip()
        source = str(sentiment.get("source_label") or "").strip()
        if not math.isfinite(score) or not 0 <= score <= 100 or not label or not source:
            continue

        if scope == "taiwan":
            if sentiment.get("calculation_state") != "fresh":
                continue
            if sentiment.get("data_quality") not in {"primary", "official"}:
                continue
            observed_at = _instant(sentiment.get("calculated_at"))
            observed_date = str(sentiment.get("date") or "").strip()
            if not observed_at or not observed_date:
                continue
            try:
                parsed_date = datetime.strptime(observed_date, "%Y-%m-%d").date()
            except ValueError:
                continue
            if observed_at.astimezone(_TAIPEI).date() != parsed_date:
                continue
            market_label = "台股情緒"
            source_url = str(sentiment.get("source_url") or "")
        else:
            observed_at = _instant(sentiment.get("updated_at"))
            if not observed_at:
                continue
            observed_date = observed_at.astimezone(_NEW_YORK).date().isoformat()
            market_label = "美股情緒"
            source_url = str(sentiment.get("source_url") or "")

        age = current - observed_at
        if age < timedelta(minutes=-5) or age > _MAX_SENTIMENT_AGE:
            continue
        result.append({
            "market": scope,
            "label": market_label,
            "score": round(score, 1),
            "sentiment": label,
            "observed_at": observed_at.isoformat(),
            "observed_date": observed_date,
            "source_label": source,
            "source_url": source_url,
            "freshness": "fresh",
            "text": f"{market_label}{score:.1f}／{label}",
        })
    return result
