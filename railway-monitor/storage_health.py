"""Privacy-safe diagnostics for Railway state-store persistence.

The monitor can create a SQLite file on any writable filesystem.  That is not
enough for delivery receipts: a process restart must preserve the outbox and
receipt ledger.  This module distinguishes a writable directory from a
detected mounted volume so health consumers cannot mistake an ephemeral local
file for durable state.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_PROBE_FILE = ".prstk-storage-probe.json"


def _safe_writable(path: Path) -> bool:
    """Return whether *path* is writable without exposing an exception."""

    try:
        return os.access(path, os.W_OK)
    except (OSError, ValueError):
        return False


def _probe_path(state_path: str | Path) -> Path:
    """Return the redacted startup marker path beside the state database."""

    return Path(state_path).parent / _PROBE_FILE


def _read_probe(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    started_at = payload.get("started_at")
    if not isinstance(started_at, str) or not started_at.strip():
        return None
    # ``restart_verified`` is written by the *next* startup.  A marker that
    # merely exists proves that this process can write the directory, not
    # that a restart has occurred, so old markers (schema v1) remain
    # explicitly unverified for backward compatibility.
    return {
        "started_at": started_at.strip(),
        "restart_verified": payload.get("restart_verified") is True,
    }


def record_storage_startup(state_path: str | Path, *, now: datetime | None = None) -> dict[str, Any]:
    """Persist a tiny privacy-safe process-start marker.

    A second process start that can read the previous marker proves that the
    state directory survived that restart.  It does *not* override the mount
    check or the fail-closed high-risk gate; it only supplies stronger
    observability than a writable directory alone.
    """

    marker = _probe_path(state_path)
    timestamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
    previous = _read_probe(marker) if marker.exists() else None
    payload = {
        "schema_version": 2,
        "started_at": timestamp,
        # The previous marker is evidence that a prior process started and
        # persisted state.  Persist the result so later health projections do
        # not mistake the current process's first write for a restart.
        "restart_verified": previous is not None,
    }
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        # Avoid ``tempfile.NamedTemporaryFile`` here.  On Windows-mounted
        # OneDrive volumes its randomized-name probing can block behind the
        # sync/filter driver, which stalls Gmail ingress startup indefinitely.
        # A deterministic per-process sibling keeps the same atomic replace
        # semantics without the unbounded candidate-name loop.
        temporary = marker.with_name(f"{marker.name}.{os.getpid()}.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, marker)
    except (OSError, ValueError) as error:
        try:
            temporary.unlink(missing_ok=True)
        except (UnboundLocalError, OSError):
            pass
        return {
            "status": "failed",
            "previous_started_at": previous.get("started_at") if previous else None,
            "error": type(error).__name__,
        }
    return {
        "status": "verified" if previous else "not_verified",
        "previous_started_at": previous.get("started_at") if previous else None,
        "error": None,
    }


def storage_probe_diagnostics(state_path: str | Path) -> dict[str, Any]:
    """Read startup continuity without exposing the marker path or contents."""

    marker = _probe_path(state_path)
    if not marker.exists():
        return {"status": "not_verified", "previous_started_at": None, "error": None}
    payload = _read_probe(marker)
    if payload is None:
        return {"status": "failed", "previous_started_at": None, "error": "invalid_marker"}
    return {
        "status": "verified" if payload.get("restart_verified") else "not_verified",
        "previous_started_at": payload["started_at"] if payload.get("restart_verified") else None,
        "error": None,
    }


def storage_diagnostics(state_path: str | Path) -> dict[str, Any]:
    """Describe persistence readiness without returning secrets or file data.

    Railway's durable volume is expected at ``/data``.  ``ismount`` is used
    instead of assuming that a directory named ``/data`` is persistent; the
    latter can be created inside an ephemeral container and was the source of
    misleading healthy-after-restart diagnostics.
    """

    path = Path(state_path)
    parent = path.parent
    try:
        parent_exists = parent.exists()
        writable = parent_exists and _safe_writable(parent)
        mount_detected = parent_exists and os.path.ismount(parent)
    except (OSError, ValueError):
        parent_exists = False
        writable = False
        mount_detected = False
    if not writable:
        status = "unavailable"
    elif mount_detected:
        status = "ready"
    else:
        status = "unknown"
    return {
        "status": status,
        "durable_volume_detected": bool(mount_detected),
        "state_parent_writable": bool(writable),
        "state_parent_exists": bool(parent_exists),
        "expected_volume_path": "/data",
        "restart_continuity": storage_probe_diagnostics(path),
        "fail_closed_for_high_risk": status != "ready",
    }


__all__ = ["record_storage_startup", "storage_diagnostics", "storage_probe_diagnostics"]
