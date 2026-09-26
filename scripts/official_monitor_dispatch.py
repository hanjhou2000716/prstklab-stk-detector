"""Choose one safe Official monitor dispatch for a completed Gmail sync."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DispatchDecision:
    should_dispatch: bool
    reason: str
    payload_reason: str


def _is_true(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.strip().casefold() == "true")


def _positive_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _has_refs(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def candidate_ready(result: dict[str, Any]) -> bool:
    diagnostics = result.get("candidate_diagnostics")
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    counts = diagnostics.get("counts")
    if not isinstance(counts, dict):
        counts = {}

    if any(
        _positive_integer(result.get(key))
        for key in ("material_candidate_count", "priority_candidate_count", "priority_pending_count")
    ):
        return True
    if _positive_integer(counts.get("priority_candidate_detected")):
        return True

    return any(
        _has_refs(value)
        for value in (
            result.get("priority_pending_refs"),
            result.get("priority_event_refs"),
            diagnostics.get("priority_pending_refs"),
            diagnostics.get("priority_event_refs"),
        )
    )


def resolve_dispatch(
    *,
    event_name: str,
    notify: bool,
    latest_financialjuice: bool,
    manual_replay_count: int,
    has_candidate: bool,
) -> DispatchDecision:
    """Return at most one dispatch; manual replays never wake the delivery monitor."""
    if latest_financialjuice or manual_replay_count > 0:
        return DispatchDecision(False, "manual_replay_suppressed", "")
    if not notify:
        return DispatchDecision(False, "notify_disabled", "")
    if has_candidate:
        return DispatchDecision(
            True,
            "reviewed_candidate",
            "gmail-reviewed-observation-or-recovery",
        )
    if event_name == "schedule":
        return DispatchDecision(
            True,
            "scheduled_monitor_poll",
            "gmail-scheduled-monitor-poll",
        )
    if event_name == "repository_dispatch":
        return DispatchDecision(
            True,
            "repository_dispatch_monitor_poll",
            "gmail-repository-dispatch-monitor-poll",
        )
    return DispatchDecision(False, "manual_run_without_candidate", "")


def _event_latest_replay(event: dict[str, Any]) -> bool:
    inputs = event.get("inputs")
    payload = event.get("client_payload")
    return any(
        _is_true(container.get("latest_financialjuice"))
        for container in (inputs, payload)
        if isinstance(container, dict)
    )


def _manual_replay_count(result: dict[str, Any]) -> int:
    diagnostics = result.get("candidate_diagnostics")
    if not isinstance(diagnostics, dict):
        return 0
    counts = diagnostics.get("counts")
    if not isinstance(counts, dict):
        return 0
    value = counts.get("manual_replay")
    return value if _positive_integer(value) else 0


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: official_monitor_dispatch.py <gmail-sync-result.json>")

    result = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not event_path:
        raise SystemExit("GITHUB_EVENT_PATH is required")
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    if not isinstance(result, dict) or not isinstance(event, dict):
        raise SystemExit("Gmail result and GitHub event must be JSON objects")

    decision = resolve_dispatch(
        event_name=os.environ.get("GITHUB_EVENT_NAME", ""),
        notify=_is_true(os.environ.get("NOTIFY")),
        latest_financialjuice=_event_latest_replay(event),
        manual_replay_count=_manual_replay_count(result),
        has_candidate=candidate_ready(result),
    )
    print(json.dumps(asdict(decision), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
