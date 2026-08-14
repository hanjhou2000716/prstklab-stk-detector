"""Privacy-safe boundary for reviewed external observations.

Only normalized, public-safe records may cross from Railway/Gmail into a
published market snapshot.  Raw mail and transport identifiers are rejected.
"""

from __future__ import annotations

import json
import os
import re
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
CONTENT_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
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
    configured = os.getenv("EXTERNAL_OBSERVATIONS_PATH", "").strip()
    if not configured:
        return None
    path = Path(configured).expanduser().resolve()
    site = (Path.cwd() / "site").resolve()
    return None if path == site or path.is_relative_to(site) else path


def _safe(record: dict[str, Any]) -> dict[str, Any] | None:
    if record.get("public_safe") is not True or any(record.get(k) not in (None, "", [], {}) for k in BLOCKED_FIELDS):
        return None
    source = str(record.get("source") or record.get("content_origin") or "").strip().casefold()
    observation_id = str(record.get("observation_id") or "").strip()
    if source not in ALLOWED_SOURCES or not observation_id:
        return None
    if str(record.get("parse_status") or "normalized").casefold() in PARSE_FAILURES:
        return None
    result = {k: record[k] for k in SAFE_FIELDS if k in record}
    result.update({"source": source, "content_origin": source, "observation_id": observation_id, "public_safe": True})
    return result


def _compound(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    if payload.get("content_origin", "").casefold() != "financialjuice" or payload.get("public_safe") is not True:
        return [], 1
    items = payload.get("items")
    if payload.get("parse_status") != "parsed" or not isinstance(items, list) or payload.get("item_count") != len(items):
        return [], 1
    accepted: list[dict[str, Any]] = []
    rejected = 0
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            rejected += 1
            continue
        item_id = str(item.get("item_id") or "").strip()
        if (not item_id or item_id in seen or not item.get("event_cluster_key")
                or not item.get("candidate_event_type") or not item.get("original_headline")
                or not CONTENT_HASH_RE.fullmatch(str(item.get("content_hash") or ""))):
            rejected += 1
            continue
        candidate = {**item, "observation_id": item_id, "source": "financialjuice", "content_origin": "financialjuice", "public_safe": True}
        safe = _safe(candidate)
        if safe is None:
            rejected += 1
            continue
        seen.add(item_id)
        accepted.append(safe)
    return accepted, rejected


def load_external_observations(path: Path | None = None) -> tuple[list[dict[str, Any]], int]:
    resolved = path if path is not None else external_observations_path()
    if resolved is None or not resolved.is_file():
        return [], 0
    site = (Path.cwd() / "site").resolve()
    if resolved.resolve() == site or resolved.resolve().is_relative_to(site):
        return [], 1
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return [], 1
    if isinstance(payload, dict) and "items" in payload:
        return _compound(payload)
    records = payload.get("observations") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        return [], 1
    accepted: list[dict[str, Any]] = []
    rejected = 0
    seen: set[str] = set()
    for record in records:
        safe = _safe(record) if isinstance(record, dict) else None
        if safe is None or safe["observation_id"] in seen:
            rejected += 1
            continue
        seen.add(safe["observation_id"])
        accepted.append(safe)
    return accepted, rejected


def _observability(rows: list[dict[str, Any]], rejected: int) -> dict[str, Any]:
    qualifying = [r for r in rows if float(r.get("vendor_importance") or 0) >= 8]
    pending = {str(r.get("event_cluster_key") or r.get("observation_id")) for r in qualifying if not (r.get("official_confirmed") and r.get("market_sync_confirmed"))}
    return {"qualifying_item_count": len(qualifying), "pending_cluster_count": len(pending), "parser_error_count": rejected, "last_notification_decision": "eligible" if any(r.get("official_confirmed") and r.get("market_sync_confirmed") for r in qualifying) else "pending_confirmation" if qualifying else "no_event", "last_delivery_at": None}


def external_source_health(*, path: Path | None, accepted: list[dict[str, Any]], rejected: int, checked_at: datetime) -> dict[str, Any] | None:
    if path is None:
        return None
    if not path.is_file():
        status = "failed"
        issues = ["external_observations_unavailable"]
    else:
        status = "partial" if rejected else "healthy" if accepted else "no_event"
        issues = ["rejected_records"] if rejected else []
    return {"key": "external_financialjuice", "label": "FinancialJuice sanitized ingress", "provider": "financialjuice", "role": "optional", "status": status, "state": status, "semantic_state": status, "provider_status": "scan_complete" if status != "failed" else "unavailable", "source_tier": "discovery", "source_url": "https://financialjuice.com/", "checked_at": checked_at.isoformat(), "accepted_count": len(accepted), "rejected_count": rejected, "observability": _observability(accepted, rejected), "issues": issues}


def merge_external_source_health(health: dict[str, Any], row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return health
    merged = dict(health)
    sources = [dict(x) for x in health.get("sources", []) if isinstance(x, dict)]
    by_key = {str(x.get("key")): x for x in sources}
    by_key[str(row["key"])] = dict(row)
    sources = list(by_key.values())
    gap_states = {"fallback_active", "configuration_missing", "stale", "partial", "failed", "critical"}
    gaps = [x for x in sources if str(x.get("semantic_state") or x.get("status")) in gap_states]
    runtime = [x for x in gaps if x.get("semantic_state") != "configuration_missing"]
    merged.update({"sources": sources, "data_gaps": [{"source": x.get("label", x.get("key", "")), "key": x.get("key", ""), "issues": x.get("issues", [])} for x in gaps], "missing_source_count": len(gaps), "runtime_failure_count": len(runtime), "configuration_missing_count": len(gaps) - len(runtime), "gap_source_keys": [str(x.get("key")) for x in gaps]})
    merged["status"] = "partial" if runtime and merged.get("status") != "critical" else merged.get("status", "healthy")
    return merged


__all__ = ["external_observations_path", "load_external_observations", "external_source_health", "merge_external_source_health"]
