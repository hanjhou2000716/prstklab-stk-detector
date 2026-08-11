"""Shared scan-state classification for public research workers."""

from __future__ import annotations


def classify_scan_state(*, expected: int, completed: int, failed: int) -> str:
    """Return a fail-closed state for one scan invocation.

    A partial run is ``building`` so the UI distinguishes it from an empty,
    successfully completed scan. A run with no completed records is failed.
    """
    expected = max(0, int(expected))
    completed = max(0, int(completed))
    failed = max(0, int(failed))
    if failed:
        return "building" if completed else "failed"
    if expected > 0 and completed < expected:
        return "building" if completed else "failed"
    return "complete"

