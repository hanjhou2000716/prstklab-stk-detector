"""Privacy-safe diagnostics for Railway state-store persistence.

The monitor can create a SQLite file on any writable filesystem.  That is not
enough for delivery receipts: a process restart must preserve the outbox and
receipt ledger.  This module distinguishes a writable directory from a
detected mounted volume so health consumers cannot mistake an ephemeral local
file for durable state.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _safe_writable(path: Path) -> bool:
    """Return whether *path* is writable without exposing an exception."""

    try:
        return os.access(path, os.W_OK)
    except (OSError, ValueError):
        return False


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
        "fail_closed_for_high_risk": status != "ready",
    }


__all__ = ["storage_diagnostics"]
