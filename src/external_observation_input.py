"""Privacy-safe ingress for already-normalized external intelligence.

Railway/Gmail may parse private mail, but the scheduled publisher must only
consume a reviewed, derived observation file.  This boundary deliberately
rejects transport identifiers and raw content before anything can reach a
market snapshot or the Pages tree.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

ALLOWED_SOURCES = {"financialjuice"}
BLOCKED_FIELDS = {
    "body", "raw_body", "attachments", "data", "local_path", "private_url",
    "gmail_message_id", "gmail_thread_id", "gmail_history_id", "message_id",
    "thread_id", "sender", "recipient", "email_address",
}
PARSE_FAILURES = {"parse_failed", "unsupported_template", "invalid_source", "duplicate"}
SAFE_FIELDS = {
    "observation_id", "source", "content_origin", "content_type", "event_type", "category",
    "title", "headline", "original_headline", "summary", "chinese_translation",
    "ai_commentary", "possible_impact", "vendor_analysis", "vendor_impact",
    "vendor_importance", "vendor_importance_present", "published_at", "source_published_at",
    "fetched_at", "source_url", "source_domain", "source_tier", "official_confirmed",
    "market_sync_confirmed", "cross_source_count", "market_evidence", "entities", "topics",
    "tickers", "parse_status", "parser_version", "event_cluster_key", "item_id", "content_hash",
    "candidate_event_type", "public_safe",
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
            "checked_at": checked_at.isoformat(), "issues": ["external_observations_unavailable"],
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
        "issues": ["rejected_records"] if rejected else [],
    }


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


__all__ = ["external_observations_path", "load_external_observations", "external_source_health", "merge_external_source_health"]
