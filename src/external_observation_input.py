"""Privacy-safe ingress for already-normalized external intelligence.

Railway/Gmail may parse private mail, but the scheduled publisher must only
consume a reviewed, derived observation file.  This boundary deliberately
rejects transport identifiers and raw content before anything can reach a
market snapshot or the Pages tree.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.creator_provider_registry import creator_ids

ALLOWED_SOURCES = {"financialjuice", *creator_ids()}
BLOCKED_FIELDS = {
    "body", "raw_body", "attachments", "data", "local_path", "private_url",
    "gmail_message_id", "gmail_thread_id", "gmail_history_id", "message_id",
    "thread_id", "sender", "recipient", "email_address",
}
PARSE_FAILURES = {"parse_failed", "unsupported_template", "invalid_source", "duplicate"}
CONTENT_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_FIELDS = {
    "observation_id", "source", "content_origin", "content_type", "event_type", "category",
    "title", "headline", "original_headline", "summary", "chinese_translation",
    "ai_commentary", "possible_impact", "vendor_analysis", "vendor_impact",
    "vendor_importance", "vendor_importance_present", "published_at", "source_published_at", "received_at",
    "fetched_at", "source_url", "source_domain", "source_tier", "official_confirmed",
    "market_sync_confirmed", "cross_source_count", "market_evidence", "entities", "topics",
    "tickers", "parse_status", "parser_version", "event_cluster_key", "item_id", "content_hash",
    "candidate_event_type", "public_safe",
    "creator_id", "creator_name", "episode_key", "episode_id", "episode_title",
    "key_takeaways", "creator_market_view", "creator_strategy_view", "creator_risk_view",
    "verification_state", "evidence_alignment", "prstk_correlation", "summary_image_available",
    "summary_image_hash", "source_adapter", "template_fingerprint", "provider_fields",
    "provider_fields_missing", "required_fields_present", "claims", "opinions",
}


def external_observations_path() -> Path | None:
    """Resolve the opt-in sanitized input and reject anything under ``site``."""
    configured = os.getenv("EXTERNAL_OBSERVATIONS_PATH", "").strip()
    if not configured:
        return None
    path = Path(configured).expanduser().resolve()
    site_root = (Path.cwd() / "site").resolve()
    if path == site_root or path.is_relative_to(site_root):
        return None
    return path


def _safe_record(record: dict[str, Any]) -> dict[str, Any] | None:
    if record.get("public_safe") is not True:
        return None
    if any(record.get(key) not in (None, "", [], {}) for key in BLOCKED_FIELDS):
        return None
    source = str(record.get("source") or record.get("content_origin") or "").strip().casefold()
    if source not in ALLOWED_SOURCES:
        return None
    observation_id = str(record.get("observation_id") or "").strip()
    if not observation_id:
        return None
    status = str(record.get("parse_status") or "normalized").strip().casefold()
    if status in PARSE_FAILURES:
        return None
    safe = {key: record[key] for key in SAFE_FIELDS if key in record}
    safe["source"] = source
    safe["content_origin"] = source
    safe["observation_id"] = observation_id
    safe["public_safe"] = True
    return safe


def _compound_records(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Flatten one parsed FinancialJuice envelope at the privacy boundary.

    The envelope's transport ``message_id`` is intentionally never copied to
    an observation.  Each public-safe item becomes an independent observation
    keyed by its stable ``item_id`` so the shared event pipeline can cluster,
    deduplicate, and trace it without retaining private mail identifiers.
    """
    if str(payload.get("content_origin") or "").strip().casefold() != "financialjuice":
        return [], 1
    if payload.get("public_safe") is not True:
        return [], 1
    if str(payload.get("parse_status") or "").strip().casefold() != "parsed":
        return [], 1
    items = payload.get("items")
    if not isinstance(items, list) or payload.get("item_count") != len(items):
        return [], 1
    accepted: list[dict[str, Any]] = []
    rejected = 0
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            rejected += 1
            continue
        item_id = str(item.get("item_id") or "").strip()
        cluster_key = str(item.get("event_cluster_key") or "").strip()
        candidate_type = str(item.get("candidate_event_type") or "").strip()
        headline = str(item.get("original_headline") or "").strip()
        content_hash = str(item.get("content_hash") or "").strip()
        if (
            not item_id or item_id in seen or not cluster_key or not candidate_type
            or not headline or not CONTENT_HASH_RE.fullmatch(content_hash)
            or item.get("public_safe") is False
            or item.get("observation_id") not in (None, "", item_id)
        ):
            rejected += 1
            continue
        # Preserve only fields admitted by _safe_record; envelope metadata and
        # any blocked/raw item fields are rejected before they can propagate.
        candidate = dict(item)
        candidate.update({
            "observation_id": item_id,
            "source": "financialjuice",
            "content_origin": "financialjuice",
            "public_safe": True,
        })
        safe = _safe_record(candidate)
        if safe is None:
            rejected += 1
            continue
        seen.add(item_id)
        accepted.append(safe)
    return accepted, rejected


def _timestamp(record: dict[str, Any], *fields: str) -> tuple[datetime, str] | None:
    """Return a validated timestamp without exposing transport metadata."""
    for field in fields:
        value = record.get(field)
        if value in (None, ""):
            continue
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        parsed = parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)
        return parsed, parsed.isoformat()
    return None


def _importance(record: dict[str, Any]) -> float | None:
    value = record.get("vendor_importance")
    if value in (None, ""):
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _observability(accepted: list[dict[str, Any]], rejected: int) -> dict[str, Any]:
    """Summarize FJ operational state without raw content or private IDs."""
    received = [item for item in (_timestamp(row, "fetched_at", "published_at", "source_published_at") for row in accepted) if item]
    parsed = [item for item in (_timestamp(row, "fetched_at") for row in accepted) if item]
    qualifying = [row for row in accepted if (_importance(row) or 0) >= 8]
    qualifying_times = [item for item in (_timestamp(row, "fetched_at", "published_at") for row in qualifying) if item]
    pending_clusters = {
        str(row.get("event_cluster_key") or row.get("observation_id") or "").strip()
        for row in qualifying
        if not (row.get("official_confirmed") is True and row.get("market_sync_confirmed") is True)
    }
    pending_clusters.discard("")
    eligible = any(row.get("official_confirmed") is True and row.get("market_sync_confirmed") is True for row in qualifying)
    decision = "eligible" if eligible else "pending_confirmation" if qualifying else "no_event"
    return {
        "last_received_at": max(received, default=(None, None))[1],
        "last_parsed_at": max(parsed, default=(None, None))[1],
        "parser_error_count": rejected,
        "last_importance_ge8_at": max(qualifying_times, default=(None, None))[1],
        "qualifying_item_count": len(qualifying),
        "pending_cluster_count": len(pending_clusters),
        "last_notification_decision": decision,
        "last_delivery_at": None,
    }


def load_external_observations(path: Path | None = None) -> tuple[list[dict[str, Any]], int]:
    """Load derived records and return ``(accepted, rejected_count)``.

    A malformed or private record is rejected rather than partially copied.
    The raw input is never returned, logged, or published.
    """
    resolved = path if path is not None else external_observations_path()
    if resolved is None or not resolved.is_file():
        return [], 0
    site_root = (Path.cwd() / "site").resolve()
    if resolved.resolve() == site_root or resolved.resolve().is_relative_to(site_root):
        return [], 1
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return [], 1
    if isinstance(payload, dict) and "items" in payload:
        return _compound_records(payload)
    records = payload.get("observations") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        return [], 1
    accepted: list[dict[str, Any]] = []
    rejected = 0
    seen: set[str] = set()
    for record in records:
        safe = _safe_record(record) if isinstance(record, dict) else None
        if safe is None or safe["observation_id"] in seen:
            rejected += 1
            continue
        seen.add(safe["observation_id"])
        accepted.append(safe)
    return accepted, rejected


def external_source_health(*, path: Path | None, accepted: list[dict[str, Any]], rejected: int, checked_at: datetime) -> dict[str, Any] | None:
    """Return one optional-source health row; unset configuration stays hidden."""
    if path is None:
        return None
    if not path.is_file():
        return {
            "key": "external_financialjuice", "label": "FinancialJuice sanitized ingress",
            "provider": "financialjuice", "role": "optional", "status": "failed",
            "state": "failed", "semantic_state": "failed", "provider_status": "unavailable",
            "source_tier": "discovery", "source_url": "https://financialjuice.com/",
            "checked_at": checked_at.isoformat(), "observability": _observability([], 1),
            "issues": ["external_observations_unavailable"],
        }
    status = "partial" if rejected else "healthy" if accepted else "no_event"
    state = "partial" if rejected else "healthy" if accepted else "no_event"
    return {
        "key": "external_financialjuice", "label": "FinancialJuice sanitized ingress",
        "provider": "financialjuice", "role": "optional", "status": status,
        "state": state, "semantic_state": state, "provider_status": "scan_complete",
        "source_tier": "discovery", "source_url": "https://financialjuice.com/",
        "checked_at": checked_at.isoformat(), "accepted_count": len(accepted),
        "rejected_count": rejected, "last_success_at": checked_at.isoformat(),
        "observability": _observability(accepted, rejected),
        "issues": ["rejected_records"] if rejected else [],
    }


def external_source_health_from_remote(
    remote_health: dict[str, Any],
    *,
    accepted: list[dict[str, Any]],
    rejected: int,
    checked_at: datetime,
) -> dict[str, Any]:
    """Translate Railway ingress status into the shared source-health contract.

    The Railway endpoint is intentionally not exposed as a public source URL;
    this row reports the public provider and the sanitized export's operational
    state while retaining local fallback observations when available.
    """
    raw_status = str(remote_health.get("status") or "failed").strip().casefold()
    provider_status = raw_status or "failed"
    if raw_status in {"ready", "healthy"}:
        state = "healthy" if accepted else "no_event"
    elif raw_status == "no_event":
        state = "no_event"
    elif accepted:
        state = "partial"
    elif raw_status == "configuration_missing":
        state = "configuration_missing"
    else:
        state = "failed"
    issues: list[str] = []
    reason = str(remote_health.get("reason") or "").strip()
    if reason:
        issues.append(reason)
    if rejected:
        issues.append("rejected_records")
    row: dict[str, Any] = {
        "key": "external_financialjuice",
        "label": "FinancialJuice sanitized Railway ingress",
        "provider": "financialjuice",
        "role": "optional",
        "status": state,
        "state": state,
        "semantic_state": state,
        "provider_status": provider_status,
        "source_tier": "discovery",
        "source_url": "https://financialjuice.com/",
        "checked_at": checked_at.isoformat(),
        "accepted_count": len(accepted),
        "rejected_count": rejected,
        "observability": _observability(accepted, rejected),
        "issues": list(dict.fromkeys(issues)),
    }
    if state in {"healthy", "no_event"} and raw_status in {"ready", "healthy", "no_event"}:
        row["last_success_at"] = checked_at.isoformat()
    return row


def merge_external_source_health(health: dict[str, Any], row: dict[str, Any] | None) -> dict[str, Any]:
    """Merge the optional row while preserving source-health count invariants."""
    if not row:
        return health
    merged = dict(health)
    sources = [dict(item) for item in (health.get("sources") or []) if isinstance(item, dict)]
    by_key = {str(item.get("key")): item for item in sources}
    by_key[str(row["key"])] = dict(row)
    sources = list(by_key.values())
    gap_states = {"fallback_active", "configuration_missing", "stale", "partial", "failed", "critical"}
    gaps = [item for item in sources if str(item.get("semantic_state") or item.get("status") or "") in gap_states]
    runtime = [item for item in gaps if str(item.get("semantic_state")) != "configuration_missing"]
    config = [item for item in gaps if str(item.get("semantic_state")) == "configuration_missing"]
    merged["sources"] = sources
    merged["data_gaps"] = [{"source": item.get("label", item.get("key", "")), "key": item.get("key", ""), "issues": item.get("issues", [])} for item in gaps]
    merged["missing_source_count"] = len(gaps)
    merged["runtime_failure_count"] = len(runtime)
    merged["configuration_missing_count"] = len(config)
    merged["gap_source_keys"] = [str(item.get("key") or "") for item in gaps]
    merged["status"] = "partial" if runtime and merged.get("status") != "critical" else merged.get("status", "healthy")
    state_counts = {state: sum(str(item.get("state") or item.get("semantic_state") or "") == state for item in sources) for state in ("healthy", "no_event", "partial", "failed", "configuration_missing")}
    merged["state_counts"] = {**dict(health.get("state_counts") or {}), **state_counts}
    observability = dict(health.get("observability") or {})
    observability["runtime_failure_count"] = len(runtime)
    observability["configuration_missing_count"] = len(config)
    observability["no_event_count"] = sum(str(item.get("status")) == "no_event" for item in sources)
    merged["observability"] = observability
    return merged


__all__ = [
    "external_observations_path", "load_external_observations", "external_source_health",
    "external_source_health_from_remote", "merge_external_source_health",
]
