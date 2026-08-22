"""Capture a redacted, read-only external acceptance snapshot.

The snapshot is deliberately diagnostic: it never sends Telegram messages,
changes Railway configuration, or promotes a failed source to healthy.  It
keeps the distinction between a reachable service, a configured source, an
empty scan and a failed scan so offline evidence cannot be mistaken for
production acceptance.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import requests

SAFE_HEALTH_KEYS = {
    "status", "service", "started_at", "last_success_at", "last_failure_at",
    "item_count", "article_count", "alert_count", "pending_count",
    "pending_reasons", "error", "stale_cache_used", "health_dispatch_status",
    "health_dispatch_error", "health_dispatch_next_retry_at", "poll_seconds",
    "event_scan", "source_url", "fetched_at", "record_count", "last_cycle_started_at",
    "last_cycle_completed_at", "heartbeat_status", "heartbeat_timeout_seconds",
    "last_cycle_age_seconds", "current_cycle_age_seconds", "watch_status",
    "watch_expiration", "observations", "parser_error_count", "state",
    "missing",
    "queue_pending_count", "dead_letter_count", "history_cursor_present",
    "received_count", "parsed_count", "failed_count", "duplicate_count",
    "public_observation_count", "importance_gte_8_count", "pending_cluster_count",
    "decision", "coverage_status", "morning_batch_state", "consensus_status",
    "last_release_id", "last_snapshot_id", "last_observation_id",
    "last_telegram_delivery_status", "last_trace_id", "last_receipt_status",
    "receipt_matches_last_outbox", "retryable_count", "due_retry_count",
    "last_delivered_count", "last_failed_count", "last_recipient_count",
    "retention_days", "classifier_mode", "classifier_source_sha256",
    "keyword_bundle_sha256", "keyword_categories", "updated_at",
    "delivery_secret_configured", "canonical_name_present", "legacy_name_present",
    "active_name", "migration_required", "secret_values_exposed",
}


def _require_https(value: str, label: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{label} must use HTTPS")
    return value.strip().rstrip("/") + "/"


def _safe_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _safe_value(item) for key, item in value.items() if str(key) in SAFE_HEALTH_KEYS}
    if isinstance(value, list):
        return [_safe_value(item) for item in value[:20]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)[:120]


def _safe_health(payload: dict[str, Any]) -> dict[str, Any]:
    """Project only whitelisted operational fields; never persist raw payload."""
    projected: dict[str, Any] = {}
    for section in ("jin10", "gdelt", "market_sync", "monitor", "gmail", "creator", "financialjuice", "news", "runtime", "runtime_config", "delivery"):
        value = payload.get(section)
        if isinstance(value, dict):
            projected[section] = _safe_value(value)
    for key in ("status", "service", "started_at"):
        if key in payload:
            projected[key] = _safe_value(payload[key])
    return projected


def _fetch_json(url: str, *, timeout: float, session: requests.Session) -> tuple[int | None, dict[str, Any] | None, str | None]:
    try:
        response = session.get(
            url,
            timeout=timeout,
            headers={"Accept": "application/json", "Cache-Control": "no-cache", "User-Agent": "PRStK-external-acceptance"},
        )
        status = response.status_code
        response.raise_for_status()
        value = response.json()
    except requests.RequestException as exc:
        return locals().get("status"), None, type(exc).__name__
    except (ValueError, TypeError):
        return status, None, "invalid_json"
    if not isinstance(value, dict):
        return status, None, "json_not_object"
    return status, value, None


def capture(*, railway_url: str, public_url: str, timeout: float = 15.0, session: requests.Session | None = None) -> dict[str, Any]:
    """Fetch public health/manifest endpoints and return safe evidence."""
    railway = _require_https(railway_url, "Railway health URL")
    public = _require_https(public_url, "Pages URL")
    client = session or requests.Session()
    railway_status, health, railway_error = _fetch_json(urljoin(railway, "health"), timeout=timeout, session=client)
    manifest_status, manifest, manifest_error = _fetch_json(urljoin(public, "data/release-manifest.json"), timeout=timeout, session=client)
    reasons: list[str] = []
    if railway_status != 200 or health is None:
        reasons.append(f"railway_health_unavailable:{railway_error or railway_status}")
    else:
        for section in ("gmail", "gdelt", "delivery"):
            state = health.get(section)
            if isinstance(state, dict) and str(state.get("status") or "") not in {"healthy", "no_new_content", "no_event", "not_checked"}:
                reasons.append(f"railway_{section}:{state.get('status')}")
    if manifest_status != 200 or manifest is None:
        reasons.append(f"pages_manifest_unavailable:{manifest_error or manifest_status}")
    elif manifest.get("status") != "ready":
        reasons.append(f"pages_manifest_status:{manifest.get('status')}")
    pages: dict[str, Any] = {"http_status": manifest_status, "error": manifest_error}
    if manifest is not None:
        pages.update({key: manifest.get(key) for key in ("status", "release_id", "market_snapshot_id", "research_snapshot_id", "event_snapshot_id", "artifact_hashes")})
        hashes = manifest.get("artifact_hashes")
        pages["artifact_hash_count"] = len(hashes) if isinstance(hashes, dict) else 0
        pages.pop("artifact_hashes", None)
    return {
        "kind": "external-acceptance-readonly",
        "captured_at": datetime.now(UTC).isoformat(),
        "status": "PASS" if not reasons else "NEEDS_REVERIFY",
        "blocking_reasons": sorted(set(reasons)),
        "railway": {"url": railway, "http_status": railway_status, "error": railway_error, "health": _safe_health(health or {})},
        "pages": pages,
        "side_effects": {"telegram": False, "railway_write": False, "configuration_changed": False},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--railway-url", required=True)
    parser.add_argument("--public-url", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fail-on-needs-reverify", action="store_true")
    args = parser.parse_args(argv)
    report = capture(railway_url=args.railway_url, public_url=args.public_url)
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 1 if args.fail_on_needs_reverify and report["status"] != "PASS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
