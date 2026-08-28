"""Shared, source-backed contracts for events and public market quotes.

The dashboard and Telegram layers consume data from several providers.  These
small normalisers keep provenance, freshness and classification fields
consistent without changing provider-specific payloads.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

SOURCE_TIERS = {"official", "public-market", "discovery"}
EVENT_TYPES = {
    "macro", "central-bank", "policy", "conflict", "energy", "semiconductor",
    "cyber", "health", "disaster", "crypto", "market",
}
IMPORTANCE_LEVELS = {"normal", "warning", "high-risk"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _normalize_quote_change(item: dict[str, Any]) -> None:
    """Make direction, point change and percent change agree before display."""
    price = _number(item.get("price"))
    previous = _number(item.get("previous_close"))
    raw_change = _number(item.get("change"))
    raw_percent = _number(item.get("change_percent"))
    calculated_change = None
    calculated_percent = None
    if price is not None and previous not in (None, 0):
        assert previous is not None
        calculated_change = round(price - previous, 2)
        calculated_percent = round((price / previous - 1) * 100, 2)

    if calculated_change is not None and calculated_percent is not None:
        mismatch = (
            raw_change is not None and abs(raw_change - calculated_change) > 0.01
        ) or (
            raw_percent is not None and abs(raw_percent - calculated_percent) > 0.05
        )
        if mismatch:
            if raw_change is not None:
                item["raw_change"] = raw_change
            if raw_percent is not None:
                item["raw_change_percent"] = raw_percent
            item["change_consistency"] = "reconciled"
        else:
            item["change_consistency"] = "consistent"
        item["change"] = calculated_change
        item["change_percent"] = calculated_percent
    elif raw_percent is not None:
        if raw_change is not None and raw_percent != 0 and raw_change * raw_percent < 0:
            item["raw_change"] = raw_change
            item["change"] = round(abs(raw_change) * (1 if raw_percent > 0 else -1), 2)
            item["change_consistency"] = "reconciled"
        else:
            item["change_consistency"] = "consistent"
        item["change_percent"] = round(raw_percent, 2)
    else:
        item["change_consistency"] = "insufficient_data"

    canonical_percent = _number(item.get("change_percent"))
    if canonical_percent is None or canonical_percent == 0:
        item["direction_sign"] = 0
        item["market_direction"] = "持平"
    elif canonical_percent > 0:
        item["direction_sign"] = 1
        item["market_direction"] = "上漲"
    else:
        item["direction_sign"] = -1
        item["market_direction"] = "下跌"


def source_domain(url: Any) -> str:
    """Return a stable lower-case hostname, excluding the common www prefix."""
    raw = str(url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    return (parsed.hostname or "").lower().removeprefix("www.")


def _source_tier(record: dict[str, Any]) -> str:
    value = str(record.get("source_tier") or "").strip().lower()
    if value in SOURCE_TIERS:
        return value
    if record.get("relevance") == "official" or record.get("kind") == "official_event":
        return "official"
    if record.get("kind") == "market_signal" or record.get("quote_source"):
        return "public-market"
    return "discovery"


def _event_type(record: dict[str, Any]) -> str:
    value = str(record.get("event_type") or "").strip().lower()
    if value in EVENT_TYPES:
        return value
    kind = str(record.get("kind") or "").lower()
    label = f"{record.get('short_label', '')} {record.get('title', '')}".lower()
    if kind == "market_signal":
        return "market"
    if any(term in label for term in ("fed", "fomc", "利率", "央行")):
        return "central-bank"
    if any(term in label for term in ("半導體", "nvidia", "台積電", "tsm")):
        return "semiconductor"
    if any(term in label for term in ("戰爭", "停火", "攻擊", "制裁")):
        return "conflict"
    if any(term in label for term in ("地震", "海嘯", "災害")):
        return "disaster"
    if any(term in label for term in ("btc", "eth", "加密")):
        return "crypto"
    return "macro"


def normalize_event_record(
    record: dict[str, Any], *, fetched_at: str | None = None
) -> dict[str, Any]:
    """Add the common event contract while preserving provider fields."""
    item = dict(record)
    instrument = item.get("instrument") if isinstance(item.get("instrument"), dict) else None
    if instrument and str(item.get("kind") or "") == "market_signal":
        instrument_percent = _number(instrument.get("change_percent"))
        if instrument_percent is not None:
            item["market_direction"] = "上漲" if instrument_percent > 0 else "下跌" if instrument_percent < 0 else "持平"
            item["market_move"] = f"{instrument_percent:+.2f}%"
    url = str(item.get("source_url") or item.get("url") or "").strip()
    trace_value = item.get("source_trace")
    trace: dict[str, Any] = trace_value if isinstance(trace_value, dict) else {}
    if not url:
        url = str(trace.get("source_url") or "").strip()
    published = item.get("published_at") or item.get("released_at") or item.get("event_time")
    impact_value = item.get("impact_confirmation")
    impact: dict[str, Any] = impact_value if isinstance(impact_value, dict) else {}
    importance = str(item.get("importance") or "").strip().lower()
    if importance not in IMPORTANCE_LEVELS:
        risk = str(item.get("risk_level") or "").lower()
        importance = "high-risk" if "高風險" in risk else "warning" if "警戒" in risk else "normal"
    transmission = item.get("market_transmission")
    if not isinstance(transmission, list):
        transmission = [str(value.get("ticker")) for value in item.get("related", [])
                        if isinstance(value, dict) and value.get("ticker")]
    item.update({
        "source_tier": _source_tier(item),
        "fetched_at": item.get("fetched_at") or fetched_at or _now(),
        "published_at": published,
        "traditional_chinese_summary": item.get("traditional_chinese_summary")
        or item.get("brief_summary") or item.get("summary") or item.get("title", ""),
        "event_type": _event_type(item),
        "importance": importance,
        "market_transmission": transmission,
        "source_url": url,
        "source_domain": source_domain(url),
        "cross_checked": bool(item.get("cross_checked") or impact.get("confirmed")),
        "data_gap": item.get("data_gap"),
        "stale_used": bool(item.get("stale_used") or item.get("quote_delayed")),
    })
    return item


def normalize_quote_record(record: dict[str, Any], *, fetched_at: str | None = None) -> dict[str, Any]:
    """Add provenance and canonical direction fields to a quote."""
    item = dict(record)
    _normalize_quote_change(item)
    source = str(item.get("quote_source") or item.get("source") or "")
    official = any(token in source.lower() for token in ("twse", "taifex", "tpex", "official", "mis"))
    url = str(item.get("source_url") or item.get("url") or "")
    # Keep one compact provenance contract for every card, regardless of
    # whether the secondary source was available this round.
    from src.market_crosscheck import quote_provenance
    provenance = quote_provenance(item)
    # Source policy fields are producer-owned. Do not carry forward a stale
    # policy/basis from an older release: the artifact contract validates these
    # fields against the ticker's canonical policy and would otherwise reject
    # an otherwise safe observation. Unknown instruments have no policy, so
    # preserve their provider-supplied metadata for backwards compatibility.
    policy = provenance["crosscheck_policy"]
    has_canonical_policy = bool(policy.get("primary") or policy.get("secondary"))
    expected_sources = provenance["expected_sources"]
    comparison_basis = provenance["comparison_basis"]
    canonical_policy = policy if has_canonical_policy else item.get("crosscheck_policy") or policy
    canonical_expected = expected_sources if has_canonical_policy else item.get("expected_sources") or expected_sources
    canonical_basis = comparison_basis if comparison_basis != "not_defined" else item.get("comparison_basis") or comparison_basis
    item.update({
        "source_tier": item.get("source_tier") or ("official" if official else "public-market"),
        "fetched_at": item.get("fetched_at") or fetched_at or _now(),
        "published_at": item.get("published_at") or item.get("quote_time") or item.get("quote_date"),
        "source_url": url,
        "source_domain": source_domain(url),
        "stale_used": bool(item.get("stale_used") or item.get("quote_delayed") or item.get("quote_basis") == "最近收盤"),
        "source_label": item.get("source_label") or provenance["source_label"],
        "quote_basis_label": item.get("quote_basis_label") or provenance["quote_basis"],
        "cross_checked": bool(item.get("cross_checked") or provenance["cross_checked"]),
        "crosscheck_status": item.get("crosscheck_status") or provenance["crosscheck_status"],
        "crosscheck_sources": item.get("crosscheck_sources") or provenance["crosscheck_sources"],
        "expected_sources": canonical_expected,
        "crosscheck_policy": canonical_policy,
        "comparison_basis": canonical_basis,
    })
    return item

