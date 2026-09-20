"""Build the small, release-bound payload used for the Mini App first paint.

The full market snapshot remains the audit and deferred-data source of truth.
This module only projects fields needed to render the notification/risk shell;
it never changes notification identity or delivery eligibility.
"""

from __future__ import annotations

from typing import Any

BOOTSTRAP_SCHEMA_VERSION = "1.0"
BOOTSTRAP_NAME = "bootstrap.json"
BOOTSTRAP_MAX_BYTES = 150 * 1024

_QUOTE_FIELDS = (
    "symbol", "ticker", "name", "market", "currency", "price",
    "previous_close", "change", "change_percent", "change_15m_percent",
    "quote_date", "quote_time", "quote_basis", "quote_source", "source_url",
    "source_label", "freshness", "data_status", "quote_delayed", "stale_used",
    "cross_checked", "snapshot_id", "observation_id",
)

_EVENT_FIELDS = (
    "notification_id", "alert_id", "event_cluster_key", "event_key", "item_id",
    "title", "brief_title", "public_short_message", "short_label", "event",
    "brief_summary", "summary", "traditional_chinese_summary", "source",
    "source_key", "source_url", "source_domain", "source_tier", "event_type",
    "importance", "risk_level", "classification", "classification_reason",
    "released_at", "published_at", "updated_at", "created_at", "snapshot_id",
    "observation_id", "market_scope", "market_direction", "market_move",
    "why_important", "possible_linkage", "market_assessment", "impact_confirmation",
    "source_trace", "evidence_state", "evidence_reason", "crosscheck_status",
)


def _copy_fields(value: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in fields if key in value}


def _quotes(value: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_copy_fields(item, _QUOTE_FIELDS) for item in value[:limit] if isinstance(item, dict)]


def _events(value: Any, limit: int = 6) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"items": []}
    result = {
        key: value[key]
        for key in ("is_major", "status", "message")
        if key in value
    }
    result["items"] = [_copy_fields(item, _EVENT_FIELDS) for item in (value.get("items") or [])[:limit] if isinstance(item, dict)]
    return result


def _briefing(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    fields = (
        "slot", "title", "overview", "assessment_summary", "public_short_message",
        "brief_title", "digest_status", "notification_eligible", "notification_status",
        "notification_reason", "snapshot_id", "observation_id", "trace_id",
        "reminder", "market_assessment", "displayed_event_keys",
    )
    result = _copy_fields(value, fields)
    observations = value.get("observations")
    if isinstance(observations, list):
        observation_fields = ("title", "event", "importance", "market_impact", "watch", "data_as_of", "source_note")
        result["observations"] = [_copy_fields(item, observation_fields) for item in observations[:6] if isinstance(item, dict)]
    primary = value.get("primary_theme")
    if isinstance(primary, dict):
        result["primary_theme"] = _copy_fields(
            primary,
            ("title", "what_happened", "why_important", "market_implication", "stock_observation", "source_evidence", "evidence"),
        )
    return result


def _risk(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key in ("notice", "summary"):
        if key in value:
            result[key] = value[key]
    for market in ("taiwan", "us"):
        section = value.get(market)
        if not isinstance(section, dict):
            continue
        compact = _copy_fields(section, ("label", "summary"))
        sentiment = section.get("sentiment")
        vix = section.get("vix")
        if isinstance(sentiment, dict):
            compact["sentiment"] = _copy_fields(sentiment, ("score", "label", "source_label", "date", "updated_at", "index_level"))
        if isinstance(vix, dict):
            compact["vix"] = _copy_fields(vix, ("value", "date", "change_percent", "stage", "source_label", "fetched_at", "freshness_state"))
        result[market] = compact
    return result


def _health(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    fields = (
        "checked_at", "status", "summary", "missing_source_count", "runtime_failure_count",
        "investor_status", "event_scan", "monitor_health", "observability", "slo",
    )
    result = _copy_fields(value, fields)
    # Source rows can be large; the first paint only needs the aggregate. The
    # complete source-health artifact is loaded after the shell is visible.
    result.pop("sources", None)
    return result


def build_bootstrap_snapshot(
    market: dict[str, Any],
    *,
    release_id: str,
    created_at: str,
    artifact_paths: dict[str, str] | None = None,
    artifact_hashes: dict[str, str] | None = None,
    alert_index_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a bounded first-paint projection bound to one release."""
    return {
        "schema_version": BOOTSTRAP_SCHEMA_VERSION,
        "release_id": release_id,
        "created_at": created_at,
        "snapshot_id": market.get("snapshot_id"),
        "market_snapshot_id": market.get("snapshot_id"),
        "generated_at": market.get("generated_at"),
        "data_status": market.get("data_status"),
        "snapshot_schema_version": market.get("snapshot_schema_version"),
        "markets": market.get("markets") if isinstance(market.get("markets"), dict) else {},
        "indices": _quotes(market.get("indices"), 20),
        "quotes": _quotes(market.get("quotes"), 12),
        "macro_quotes": _quotes(market.get("macro_quotes"), 12),
        "risk": _risk(market.get("risk")),
        "events": _events(market.get("events")),
        "briefing": _briefing(market.get("briefing")),
        "external_alert": _copy_fields(market.get("external_alert"), ("summary", "category", "expires_at", "source_url", "source_label")),
        "source_health": _health(market.get("source_health")),
        "alert_index": {
            "schema_version": "1.0",
            "alerts": [dict(row) for row in (alert_index_rows or []) if isinstance(row, dict)],
        },
        "deferred_artifacts": {
            "paths": dict(artifact_paths or {}),
            "hashes": dict(artifact_hashes or {}),
        },
    }
