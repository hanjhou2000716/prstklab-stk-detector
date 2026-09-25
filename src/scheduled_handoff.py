"""Bounded same-slot handoff for a scheduled US premarket run superseded by main."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.schedule_contract import (
    EXPLICIT_TIMESTAMP_SCHEDULE_CONTRACT_VERSION,
    NEW_YORK,
    parse_scheduled_for,
    us_premarket_anchor,
)

HANDOFF_EVENT = "scheduled-brief-handoff"
HANDOFF_WORKFLOW_PATH = ".github/workflows/scheduled-brief.yml"
_UTC = UTC


class HandoffError(RuntimeError):
    """Raised when a same-slot handoff cannot be established safely."""


def _utc_now() -> datetime:
    return datetime.now(_UTC)


def _http_json(url: str, *, method: str, token: str, body: Mapping[str, object] | None = None) -> tuple[int, object]:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "prstk-scheduled-brief-handoff",
    }
    data = json.dumps(body, separators=(",", ":")).encode("utf-8") if body is not None else None
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=15) as response:
            raw = response.read()
            return int(response.status), json.loads(raw.decode("utf-8")) if raw else None
    except HTTPError as exc:
        # A 4xx is a definitive rejection.  A 5xx may follow server-side
        # acceptance, so callers must reconcile and must never POST again.
        if 400 <= exc.code < 500:
            raise HandoffError(f"handoff_request_rejected_http_{exc.code}") from exc
        raise HandoffError(f"handoff_request_outcome_unknown_http_{exc.code}") from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise HandoffError(f"handoff_request_outcome_unknown_{type(exc).__name__}") from exc


def handoff_deadline(slot_context: Mapping[str, object]) -> datetime:
    slot = str(slot_context.get("scheduled_slot") or slot_context.get("effective_slot") or "")
    scheduled = parse_scheduled_for(slot_context.get("scheduled_for_at"))
    if slot != "us_premarket" or scheduled is None:
        raise HandoffError("handoff_context_not_us_premarket")
    anchor = us_premarket_anchor(scheduled.astimezone(NEW_YORK).date())
    if abs((scheduled - anchor).total_seconds()) > 300:
        raise HandoffError("handoff_context_slot_anchor_mismatch")
    return anchor.astimezone(_UTC) + timedelta(minutes=30)


def build_handoff_payload(
    slot_context: Mapping[str, object], *, parent_run_id: int, parent_sha: str,
    target_sha: str, now: datetime | None = None,
) -> dict[str, object]:
    """Build a single-use v2 explicit-anchor dispatch while the original slot is open."""
    current = (now or _utc_now()).astimezone(_UTC)
    deadline = handoff_deadline(slot_context)
    if current >= deadline:
        raise HandoffError("handoff_window_expired")
    if str(slot_context.get("delivery_intent") or "") != "notify_candidate":
        raise HandoffError("handoff_delivery_not_required")
    if str(slot_context.get("contract_status") or "") != "valid":
        raise HandoffError("handoff_original_schedule_unverified")
    slot = str(slot_context.get("scheduled_slot") or slot_context.get("effective_slot") or "")
    scheduled = parse_scheduled_for(slot_context.get("scheduled_for_at"))
    if slot != "us_premarket" or scheduled is None or parent_run_id <= 0:
        raise HandoffError("handoff_identity_incomplete")
    trace_id = str(slot_context.get("dispatch_trace_id") or f"parent-run-{parent_run_id}")
    handoff_id = f"{slot}-{scheduled.astimezone(NEW_YORK).date().isoformat()}-{parent_run_id}"
    scheduled_new_york = scheduled.astimezone(NEW_YORK)
    payload: dict[str, object] = {
        "event_type": HANDOFF_EVENT,
        "client_payload": {
            "slot": slot,
            "scheduled_slot": slot,
            "scheduled_for_at": scheduled_new_york.isoformat(),
            "time_zone": "America/New_York",
            "schedule_contract_version": EXPLICIT_TIMESTAMP_SCHEDULE_CONTRACT_VERSION,
            "notify": True,
            "force": False,
            "trigger_kind": "scheduled-handoff",
            "handoff_parent_run_id": parent_run_id,
            "handoff_parent_sha": str(parent_sha).lower(),
            "handoff_target_sha": str(target_sha).lower(),
            "handoff_id": handoff_id,
            "handoff_attempt": 1,
            "handoff_deadline_at": deadline.isoformat(),
            "trace_id": trace_id,
        },
    }
    return payload


def _fetch_run_list(*, api_url: str, repository: str, token: str) -> list[dict[str, object]]:
    url = f"{api_url.rstrip('/')}/repos/{repository}/actions/runs?event=repository_dispatch&per_page=100"
    _status, payload = _http_json(url, method="GET", token=token)
    values = payload.get("workflow_runs") if isinstance(payload, Mapping) else None
    return [row for row in values if isinstance(row, dict)] if isinstance(values, list) else []


def _find_child(rows: list[dict[str, object]], handoff_id: str) -> dict[str, object] | None:
    for row in rows:
        if (
            row.get("name") != "Scheduled market brief"
            or row.get("path") != HANDOFF_WORKFLOW_PATH
            or row.get("event") != "repository_dispatch"
        ):
            continue
        title = str(row.get("display_title") or row.get("run_name") or "")
        if handoff_id and handoff_id in title:
            return row
    return None


def dispatch_and_wait(
    payload: Mapping[str, object], *, repository: str, token: str,
    api_url: str = "https://api.github.com", deadline: datetime,
    now_fn: Callable[[], datetime] = _utc_now, sleep_fn: Callable[[float], None] = time.sleep,
    poll_seconds: float = 5,
) -> dict[str, object]:
    """POST exactly once; reconcile by unique run name until child finishes or slot expires."""
    client_payload = payload.get("client_payload")
    if not isinstance(client_payload, Mapping):
        raise HandoffError("handoff_payload_invalid")
    handoff_id = str(client_payload.get("handoff_id") or "")
    if not handoff_id:
        raise HandoffError("handoff_id_missing")
    url = f"{api_url.rstrip('/')}/repos/{repository}/dispatches"
    request_outcome = "unknown"
    try:
        response_status, _ = _http_json(url, method="POST", token=token, body=payload)
        if response_status != 204:
            raise HandoffError(f"handoff_unexpected_http_{response_status}")
        request_outcome = "accepted"
    except HandoffError as exc:
        message = str(exc)
        if "rejected" in message:
            return {"status": "rejected", "reason": message, "request_outcome": "rejected", "handoff_id": handoff_id}
        request_outcome = "unknown"

    while now_fn().astimezone(_UTC) < deadline.astimezone(_UTC):
        rows = _fetch_run_list(api_url=api_url, repository=repository, token=token)
        child = _find_child(rows, handoff_id)
        if child is not None:
            child_status = str(child.get("status") or "")
            if child_status == "completed":
                conclusion = str(child.get("conclusion") or "unknown")
                target_sha = str(client_payload.get("handoff_target_sha") or "").lower()
                child_sha = str(child.get("head_sha") or "").lower()
                if child_sha != target_sha or child.get("head_branch") != "main":
                    return {
                        "status": "child_failed",
                        "reason": "handoff_child_revision_mismatch" if child_sha != target_sha else "handoff_child_branch_mismatch",
                        "request_outcome": request_outcome,
                        "handoff_id": handoff_id,
                        "child_run_id": child.get("id"),
                        "child_sha": child_sha,
                        "child_conclusion": conclusion,
                    }
                return {
                    "status": "delivered" if conclusion == "success" else "child_failed",
                    "reason": "handoff_child_completed" if conclusion == "success" else f"handoff_child_{conclusion}",
                    "request_outcome": request_outcome,
                    "handoff_id": handoff_id,
                    "child_run_id": child.get("id"),
                    "child_sha": child.get("head_sha"),
                    "child_conclusion": conclusion,
                }
            if child_status in {"queued", "in_progress", "waiting", "pending"}:
                sleep_fn(min(poll_seconds, max(0.0, (deadline - now_fn().astimezone(_UTC)).total_seconds())))
                continue
        sleep_fn(min(poll_seconds, max(0.0, (deadline - now_fn().astimezone(_UTC)).total_seconds())))
    return {
        "status": "unconfirmed",
        "reason": "handoff_child_not_confirmed_before_deadline",
        "request_outcome": request_outcome,
        "handoff_id": handoff_id,
    }


def validate_handoff_parent(
    client_payload: Mapping[str, object], *, repository: str, token: str,
    api_url: str = "https://api.github.com", now: datetime | None = None,
    current_sha: str = "",
) -> dict[str, object]:
    """Check the dispatch parent belongs to this repo's scheduled brief and the same open slot."""
    try:
        parent_id = int(str(client_payload.get("handoff_parent_run_id") or ""))
    except (TypeError, ValueError):
        return {"valid": False, "reason": "handoff_parent_id_invalid"}
    slot = str(client_payload.get("scheduled_slot") or client_payload.get("slot") or "")
    scheduled = parse_scheduled_for(client_payload.get("scheduled_for_at"))
    if (
        slot != "us_premarket" or scheduled is None
        or str(client_payload.get("handoff_attempt") or "") != "1"
        or str(client_payload.get("event_type") or HANDOFF_EVENT) != HANDOFF_EVENT
        or client_payload.get("notify") is not True
        or client_payload.get("force") is not False
        or str(client_payload.get("time_zone") or "") != "America/New_York"
        or str(client_payload.get("schedule_contract_version") or "") != EXPLICIT_TIMESTAMP_SCHEDULE_CONTRACT_VERSION
    ):
        return {"valid": False, "reason": "handoff_contract_invalid"}
    try:
        deadline = handoff_deadline({"scheduled_slot": slot, "scheduled_for_at": scheduled.isoformat()})
    except HandoffError as exc:
        return {"valid": False, "reason": str(exc)}
    current = (now or _utc_now()).astimezone(_UTC)
    if current >= deadline:
        return {"valid": False, "reason": "handoff_window_expired"}
    target_sha = str(client_payload.get("handoff_target_sha") or "").strip().lower()
    if not target_sha or (current_sha and target_sha != str(current_sha).strip().lower()):
        return {"valid": False, "reason": "handoff_target_revision_mismatch"}
    payload_deadline = parse_scheduled_for(client_payload.get("handoff_deadline_at"))
    if payload_deadline is None or payload_deadline.astimezone(_UTC) != deadline.astimezone(_UTC):
        return {"valid": False, "reason": "handoff_deadline_mismatch"}
    url = f"{api_url.rstrip('/')}/repos/{repository}/actions/runs/{parent_id}"
    try:
        _status, run = _http_json(url, method="GET", token=token)
    except HandoffError as exc:
        return {"valid": False, "reason": str(exc)}
    if not isinstance(run, Mapping):
        return {"valid": False, "reason": "handoff_parent_unavailable"}
    try:
        if int(str(run.get("id") or "")) != parent_id:
            return {"valid": False, "reason": "handoff_parent_identity_mismatch"}
    except (TypeError, ValueError):
        return {"valid": False, "reason": "handoff_parent_identity_mismatch"}
    parent_repo = run.get("repository")
    parent_repo_name = str(parent_repo.get("full_name") or "") if isinstance(parent_repo, Mapping) else ""
    if parent_repo_name.casefold() != repository.casefold():
        return {"valid": False, "reason": "handoff_parent_repository_mismatch"}
    if run.get("path") != HANDOFF_WORKFLOW_PATH or run.get("name") != "Scheduled market brief":
        return {"valid": False, "reason": "handoff_parent_workflow_mismatch"}
    if run.get("status") != "in_progress":
        return {"valid": False, "reason": "handoff_parent_not_active"}
    if run.get("head_branch") != "main" or run.get("event") not in {"schedule", "repository_dispatch"}:
        return {"valid": False, "reason": "handoff_parent_trigger_mismatch"}
    parent_sha = str(run.get("head_sha") or "").lower()
    if parent_sha != str(client_payload.get("handoff_parent_sha") or "").lower():
        return {"valid": False, "reason": "handoff_parent_revision_mismatch"}
    created = parse_scheduled_for(run.get("created_at"))
    anchor = us_premarket_anchor(scheduled.astimezone(NEW_YORK).date()).astimezone(_UTC)
    if created is None or created < anchor - timedelta(minutes=5) or created >= deadline:
        return {"valid": False, "reason": "handoff_parent_outside_slot"}
    expected_id = f"us_premarket-{scheduled.astimezone(NEW_YORK).date().isoformat()}-{parent_id}"
    if str(client_payload.get("handoff_id") or "") != expected_id:
        return {"valid": False, "reason": "handoff_identity_mismatch"}
    return {
        "valid": True,
        "reason": "handoff_parent_verified",
        "parent_run_id": parent_id,
        "parent_sha": parent_sha,
        "target_sha": target_sha,
        "scheduled_for_at": scheduled.isoformat(),
        "deadline_at": deadline.isoformat(),
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Validate a scheduled premarket handoff parent")
    parser.add_argument("validate", choices={"validate"})
    args = parser.parse_args()
    del args
    repository = os.getenv("GITHUB_REPOSITORY", "")
    token = os.getenv("GITHUB_TOKEN", "")
    payload_raw = os.getenv("HANDOFF_CLIENT_PAYLOAD", "{}")
    try:
        payload = json.loads(payload_raw)
    except ValueError:
        payload = {}
    result = validate_handoff_parent(
        payload if isinstance(payload, Mapping) else {}, repository=repository, token=token,
        current_sha=os.getenv("GITHUB_SHA", ""),
    )
    output_path = os.getenv("GITHUB_OUTPUT", "")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            for key, value in result.items():
                handle.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")
    print(json.dumps(result, sort_keys=True))
    if not result.get("valid"):
        print(f"::error::{result.get('reason', 'handoff_invalid')}")
        return 1
    return 0


__all__ = [
    "HANDOFF_EVENT", "HandoffError", "build_handoff_payload", "dispatch_and_wait",
    "handoff_deadline", "validate_handoff_parent",
]


if __name__ == "__main__":
    raise SystemExit(main())
