"""Capture a redacted, read-only external acceptance snapshot.

The snapshot is deliberately diagnostic: it never sends Telegram messages,
changes Railway configuration, or promotes a failed source to healthy.  It
keeps the distinction between a reachable service, a configured source, an
empty scan and a failed scan so offline evidence cannot be mistaken for
production acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
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


def _fetch_bytes(url: str, *, timeout: float, session: requests.Session) -> tuple[int | None, bytes | None, str | None]:
    """Fetch one public artifact without retaining its payload in evidence.

    Artifact verification is intentionally separate from ``_fetch_json``: a
    release may contain JSON, images, or another public-safe binary.  Only the
    status, byte hash and bounded error label leave this function.
    """
    try:
        response = session.get(
            url,
            timeout=timeout,
            headers={"Accept": "*/*", "Cache-Control": "no-cache", "User-Agent": "PRStK-external-acceptance"},
        )
        status = response.status_code
        response.raise_for_status()
        content = getattr(response, "content", None)
        if not isinstance(content, (bytes, bytearray)):
            return status, None, "missing_bytes"
        return status, bytes(content), None
    except requests.RequestException as exc:
        return locals().get("status"), None, type(exc).__name__
    except (TypeError, ValueError, OSError):
        return locals().get("status"), None, "invalid_payload"


_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _artifact_hash_audit(
    manifest: dict[str, Any],
    *,
    public_root: str,
    timeout: float,
    session: requests.Session,
) -> tuple[dict[str, Any], list[str]]:
    """Verify every manifest-declared public artifact, fail-closed.

    The report contains names and hashes only; it never stores artifact bytes
    or response bodies.  Paths are constrained to relative public paths so a
    malformed manifest cannot make the acceptance probe fetch an arbitrary
    external URL.
    """
    hashes = manifest.get("artifact_hashes")
    paths = manifest.get("artifact_paths")
    audit: dict[str, Any] = {
        "declared_count": len(hashes) if isinstance(hashes, dict) else 0,
        "verified_count": 0,
        "missing_count": 0,
        "mismatch_count": 0,
        "error_count": 0,
        "snapshot_mismatch_count": 0,
        "mismatches": [],
        "errors": [],
        "snapshot_errors": [],
    }
    reasons: list[str] = []
    if not isinstance(hashes, dict) or not hashes:
        return audit, ["pages_artifact_hashes_missing"]
    if not isinstance(paths, dict):
        return audit, ["pages_artifact_paths_missing"]
    for name, expected in hashes.items():
        artifact_name = str(name)
        expected_hash = str(expected or "").lower()
        relative = paths.get(name)
        if not _SHA256.fullmatch(expected_hash):
            audit["error_count"] += 1
            audit["errors"].append(artifact_name)
            reasons.append(f"pages_artifact_hash_invalid:{artifact_name}")
            continue
        if not isinstance(relative, str) or not relative.strip() or relative.startswith(("/", "\\")):
            audit["missing_count"] += 1
            reasons.append(f"pages_artifact_path_missing:{artifact_name}")
            continue
        normalized = relative.replace("\\", "/")
        if any(part in {"", ".", ".."} for part in normalized.split("/")):
            audit["error_count"] += 1
            audit["errors"].append(artifact_name)
            reasons.append(f"pages_artifact_path_invalid:{artifact_name}")
            continue
        artifact_url = urljoin(public_root, normalized)
        status, content, error = _fetch_bytes(artifact_url, timeout=timeout, session=session)
        if content is None:
            audit["error_count"] += 1
            audit["errors"].append(artifact_name)
            reasons.append(f"pages_artifact_unavailable:{artifact_name}:{error or status}")
            continue
        actual_hash = hashlib.sha256(content).hexdigest()
        if actual_hash != expected_hash:
            audit["mismatch_count"] += 1
            audit["mismatches"].append(artifact_name)
            reasons.append(f"pages_artifact_hash_mismatch:{artifact_name}")
            continue
        if artifact_name in {
            "market.json", "research-report.json", "event-ledger.json"
        }:
            try:
                decoded = json.loads(content.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                decoded = None
            expected_snapshot_key = {
                "market.json": "market_snapshot_id",
                "research-report.json": "research_snapshot_id",
                "event-ledger.json": "event_snapshot_id",
            }[artifact_name]
            expected_snapshot = str(manifest.get(expected_snapshot_key) or "").strip()
            actual_snapshot = (
                str(decoded.get("snapshot_id") or "").strip()
                if isinstance(decoded, dict)
                else ""
            )
            if not isinstance(decoded, dict):
                audit["error_count"] += 1
                audit["errors"].append(artifact_name)
                reasons.append(f"pages_artifact_json_invalid:{artifact_name}")
                continue
            if not expected_snapshot:
                audit["snapshot_mismatch_count"] += 1
                audit["snapshot_errors"].append(artifact_name)
                reasons.append(f"pages_manifest_snapshot_missing:{artifact_name}")
                continue
            if actual_snapshot != expected_snapshot:
                audit["snapshot_mismatch_count"] += 1
                audit["snapshot_errors"].append(artifact_name)
                reasons.append(f"pages_artifact_snapshot_mismatch:{artifact_name}")
                continue
        audit["verified_count"] += 1
    audit["mismatches"] = sorted(set(audit["mismatches"]))
    audit["errors"] = sorted(set(audit["errors"]))
    audit["snapshot_errors"] = sorted(set(audit["snapshot_errors"]))
    return audit, reasons


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
            if not isinstance(state, dict):
                continue
            status = str(state.get("status") or "")
            if section == "gmail":
                # ``status=ready`` only means the ingress is configured.  A
                # failed/stale users.watch lease is a separate operational
                # gate and must not be mistaken for a healthy mailbox.
                if status not in {"healthy", "no_new_content", "no_event", "not_checked", "ready"}:
                    reasons.append(f"railway_gmail:{status}")
                watch_status = str(state.get("watch_status") or "not_checked")
                if watch_status not in {"healthy", "active", "no_new_content", "no_event", "not_checked"}:
                    reasons.append(f"railway_gmail_watch:{watch_status}")
                storage = state.get("storage")
                if isinstance(storage, dict):
                    storage_status = str(storage.get("status") or "unknown")
                    if storage_status != "ready":
                        reasons.append(f"railway_gmail_persistence:{storage_status}")
                continue
            # Delivery health is a receipt state, not a provider availability
            # state.  A successful single-recipient acceptance therefore
            # reports ``delivered`` (and older Railway runtimes may report
            # ``sent``); treating those values as failures made a verified
            # receipt incorrectly downgrade the whole external acceptance.
            if section == "delivery":
                allowed_delivery = {
                    "healthy",
                    "delivered",
                    "sent",
                    "no_new_content",
                    "no_event",
                    "not_checked",
                }
                if status not in allowed_delivery:
                    reasons.append(f"railway_delivery:{status}")
                storage = state.get("storage")
                if isinstance(storage, dict):
                    storage_status = str(storage.get("status") or "unknown")
                    if storage_status != "ready":
                        # A writable SQLite file on an ephemeral filesystem can
                        # look healthy until Railway restarts.  Keep the
                        # receipt itself visible, but do not call the external
                        # acceptance durable until a mounted volume is proven.
                        reasons.append(f"railway_delivery_persistence:{storage_status}")
                continue
            if status not in {"healthy", "no_new_content", "no_event", "not_checked"}:
                reasons.append(f"railway_{section}:{status}")
        runtime_config = health.get("runtime_config")
        if isinstance(runtime_config, dict) and runtime_config.get("migration_required") is True:
            # A legacy delivery secret may keep the callback reachable, but it
            # is not the canonical production contract.  Keep acceptance
            # fail-closed until the operator migrates the variable; never
            # persist or expose its value here.
            reasons.append("railway_runtime_config:secret_migration_required")
    artifact_audit: dict[str, Any] = {
        "declared_count": 0,
        "verified_count": 0,
        "missing_count": 0,
        "mismatch_count": 0,
        "error_count": 0,
        "snapshot_mismatch_count": 0,
        "mismatches": [],
        "errors": [],
        "snapshot_errors": [],
    }
    if manifest_status != 200 or manifest is None:
        reasons.append(f"pages_manifest_unavailable:{manifest_error or manifest_status}")
    elif manifest.get("status") != "ready":
        reasons.append(f"pages_manifest_status:{manifest.get('status')}")
    else:
        artifact_audit, artifact_reasons = _artifact_hash_audit(
            manifest,
            public_root=public,
            timeout=timeout,
            session=client,
        )
        reasons.extend(artifact_reasons)
    pages: dict[str, Any] = {"http_status": manifest_status, "error": manifest_error}
    if manifest is not None:
        pages.update({key: manifest.get(key) for key in ("status", "release_id", "market_snapshot_id", "research_snapshot_id", "event_snapshot_id", "artifact_hashes")})
        hashes = manifest.get("artifact_hashes")
        pages["artifact_hash_count"] = len(hashes) if isinstance(hashes, dict) else 0
        pages.pop("artifact_hashes", None)
    pages["artifact_hash_audit"] = artifact_audit
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
