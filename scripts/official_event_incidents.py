"""Deduplicate per-event delivery incidents into first/reminder/recovery updates."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from scripts.monitor_liveness import (
    EVENT_INCIDENT_MARKER,
    EVENT_ISSUE_TITLE_PREFIX,
    MAX_AUDIT_SECONDS,
    LivenessAuditError,
    _open_incidents,
    _parse_time,
    _request_json,
)

REMINDER_INTERVAL = timedelta(minutes=30)
SUMMARY_ESCALATION = timedelta(minutes=10)


def _marker(body: object) -> str:
    for line in str(body or "").splitlines():
        if line.startswith(EVENT_INCIDENT_MARKER):
            return line[len(EVENT_INCIDENT_MARKER):].strip()
    return ""


def _timestamp(body: object, label: str) -> datetime | None:
    prefix = f"{label}:"
    for line in str(body or "").splitlines():
        if line.startswith(prefix):
            return _parse_time(line[len(prefix):].strip())
    return None


def _issue_event_refs(body: object) -> tuple[list[str], bool]:
    lines = str(body or "").splitlines()
    refs_line = next((line for line in lines if line.startswith("Event refs:")), "")
    refs = [item.strip()[:64] for item in refs_line.partition(":")[2].split(",") if item.strip()]
    expected_count = next((line.partition(":")[2].strip() for line in lines if line.startswith("Affected event count:")), "")
    try:
        count = int(expected_count)
    except (TypeError, ValueError):
        count = -1
    complete_line = next((line for line in lines if line.startswith("Event refs complete:")), "")
    complete = complete_line.partition(":")[2].strip().casefold() == "true" if complete_line else (
        count >= 0 and len(refs) >= count
    )
    return list(dict.fromkeys(refs)), complete


def _resolved_event_refs(trace: dict[str, Any]) -> set[str]:
    resolved: set[str] = set()
    for row in trace.get("events", []):
        if not isinstance(row, dict):
            continue
        event_ref = str(row.get("event_ref") or "").strip()[:64]
        if not event_ref:
            continue
        status = str(row.get("status") or "").casefold()
        reason = str(row.get("reason") or "").casefold()
        expected = bool(row.get("expected"))
        if status in {"delivered", "already_delivered", "expired"}:
            resolved.add(event_ref)
        elif not expected and status in {"suppressed", "policy_suppressed", "no_event"}:
            resolved.add(event_ref)
        elif status == "suppressed" and reason in {
            "already_delivered", "policy_suppressed", "notification_not_required",
        }:
            resolved.add(event_ref)
    return resolved


def _incident_group(reason: str, contract: str) -> tuple[str, str]:
    component = "financialjuice_summary" if "summary" in reason or "content" in reason else "official_event_delivery"
    source = f"{component}\n{reason[:120]}\n{contract[:40]}"
    return component, hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]


def _read_trace(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LivenessAuditError(f"official_event_trace_unavailable:{type(exc).__name__}") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "official-event-trace-v1"
        or not isinstance(value.get("events"), list)
        or not isinstance(value.get("stages"), dict)
        or not value.get("workflow_run_id")
        or not value.get("workflow_sha")
    ):
        raise LivenessAuditError("official_event_trace_identity_invalid")
    return value


def _active_incidents(trace: dict[str, Any], now: datetime) -> dict[str, dict[str, Any]]:
    active: dict[str, dict[str, Any]] = {}
    stages = trace.get("stages", {}) if isinstance(trace.get("stages"), dict) else {}
    for row in trace["events"]:
        if not isinstance(row, dict) or not row.get("expected"):
            continue
        status = str(row.get("status") or "unknown").casefold()
        if status in {"delivered", "already_delivered"}:
            continue
        reason = str(row.get("reason") or status)[:120]
        if status in {"suppressed", "no_event"}:
            reason = reason or "expected_event_not_processed"
        detected = _parse_time(row.get("first_detected_at") or row.get("candidate_recorded_at"))
        if status == "ready":
            if str(stages.get("queue") or "").casefold() not in {"acquired", "completed", "not_required"}:
                reason = "writer_queue_blocked"
            elif str(stages.get("prepare") or "").casefold() not in {"prepared_release_current", "not_required"}:
                reason = "release_preparation_failed"
            elif str(stages.get("public_gate") or "").casefold() != "true":
                reason = "public_release_gate_blocked"
            elif str(stages.get("sender") or "").casefold() in {"failure", "skipped", "cancelled"}:
                reason = "sender_not_completed"
            elif str(stages.get("durable_receipt") or "").casefold() != "true":
                reason = "durable_receipt_unverified"
            else:
                continue
        if status in {"summary_pending", "summary_timeout", "content_incomplete"}:
            if detected is None or now - detected < SUMMARY_ESCALATION:
                continue
            reason = "priority_summary_timeout"
        elif status == "unknown" and reason in {"candidate_ready", "notification_policy_not_eligible"}:
            continue
        contract = str(row.get("summary_contract_version") or "unknown")[:40]
        component, incident_key = _incident_group(reason, contract)
        incident = active.setdefault(incident_key, {
            "component": component,
            "reason": reason,
            "contract_version": contract,
            "first_failure_at": detected.isoformat() if detected else now.isoformat(),
            "event_refs": [],
            "latest_progress_at": str(row.get("last_progress_at") or row.get("candidate_recorded_at") or "")[:80],
            "workflow_run_id": str(trace["workflow_run_id"])[:32],
            "workflow_sha": str(trace["workflow_sha"])[:40],
        })
        event_ref = str(row.get("event_ref") or "")[:64]
        if event_ref and event_ref not in incident["event_refs"]:
            incident["event_refs"].append(event_ref)
        progress = str(row.get("last_progress_at") or row.get("candidate_recorded_at") or "")[:80]
        if progress > incident["latest_progress_at"]:
            incident["latest_progress_at"] = progress
        if detected:
            current_first = _parse_time(incident["first_failure_at"])
            if current_first is None or detected < current_first:
                incident["first_failure_at"] = detected.isoformat()
    return active


def _body(
    key: str, incident: dict[str, Any], now: datetime, *,
    preserve_first: datetime | None = None,
    next_reminder_at: datetime | None = None,
) -> str:
    first = preserve_first or _parse_time(incident.get("first_failure_at")) or now
    all_refs = list(dict.fromkeys(str(ref)[:64] for ref in incident.get("event_refs", []) if str(ref)))
    refs = ", ".join(all_refs[:100]) or "not available"
    next_reminder = next_reminder_at or (now + REMINDER_INTERVAL)
    return "\n".join((
        f"{EVENT_INCIDENT_MARKER}{key}",
        f"Component: {incident['component']}",
        f"Root cause: {incident['reason']}",
        f"Summary contract: {incident['contract_version']}",
        f"Affected event count: {len(all_refs)}",
        f"Event refs: {refs}",
        f"Event refs complete: {'true' if len(all_refs) <= 100 else 'false'}",
        f"First failure: {first.isoformat()}",
        f"Latest progress: {incident['latest_progress_at'] or 'unknown'}",
        f"Latest run: {incident['workflow_run_id']} ({incident['workflow_sha']})",
        f"Observed at: {now.isoformat()}",
        f"Next reminder at: {next_reminder.isoformat()}",
    ))


def reconcile_incidents(
    *, api_url: str, repository: str, token: str, trace_path: str | Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    trace = _read_trace(trace_path)
    stages = trace["stages"]
    # A failed or incomplete scan is not evidence that an earlier incident recovered.
    scan_complete = str(stages.get("scan") or "").casefold() in {"success", "completed"}
    active = _active_incidents(trace, current)
    deadline = __import__("time").monotonic() + MAX_AUDIT_SECONDS
    issues = _open_incidents(api_url, repository, token, deadline_monotonic=deadline)
    event_issues = [
        issue for issue in issues
        if str(issue.get("title") or "").startswith(EVENT_ISSUE_TITLE_PREFIX)
    ]
    indexed: dict[str, list[dict[str, Any]]] = {}
    for issue in event_issues:
        key = _marker(issue.get("body"))
        if key:
            indexed.setdefault(key, []).append(issue)
    if any(len(rows) > 1 for rows in indexed.values()):
        raise LivenessAuditError("official_event_incident_duplicate_issue")
    opened: list[int] = []
    reminded: list[int] = []
    recovered: list[int] = []
    for key, incident in active.items():
        matches = indexed.get(key, [])
        if not matches:
            body = _body(key, incident, current)
            created = _request_json(
                api_url, repository, token, "POST", "issues",
                {"title": f"{EVENT_ISSUE_TITLE_PREFIX} / {incident['component']}", "body": body},
                deadline_monotonic=deadline,
            )
            if not isinstance(created, dict) or not isinstance(created.get("number"), int):
                raise LivenessAuditError("official_event_incident_create_invalid")
            opened.append(created["number"])
            continue
        issue = matches[0]
        number = issue.get("number")
        if not isinstance(number, int):
            raise LivenessAuditError("official_event_incident_identity_invalid")
        first = _timestamp(issue.get("body"), "First failure")
        next_due = _timestamp(issue.get("body"), "Next reminder at")
        due = next_due is None or current >= next_due
        prior_refs, prior_refs_complete = _issue_event_refs(issue.get("body"))
        merged_incident = dict(incident)
        merged_incident["event_refs"] = list(dict.fromkeys([*prior_refs, *incident["event_refs"]]))
        body = _body(
            key, merged_incident, current, preserve_first=first,
            next_reminder_at=current + REMINDER_INTERVAL if due else next_due,
        )
        if not prior_refs_complete:
            body = body.replace("Event refs complete: true", "Event refs complete: false")
        _request_json(
            api_url, repository, token, "PATCH", f"issues/{number}", {"body": body},
            deadline_monotonic=deadline,
        )
        if due:
            _request_json(
                api_url, repository, token, "POST", f"issues/{number}/comments",
                {"body": (
                    f"Still degraded: {incident['reason']}; {len(incident['event_refs'])} affected event(s). "
                    f"Latest run {incident['workflow_run_id']} at {current.isoformat()}."
                )}, deadline_monotonic=deadline,
            )
            reminded.append(number)
    if scan_complete:
        resolved_refs = _resolved_event_refs(trace)
        for key, rows in indexed.items():
            if key in active:
                continue
            issue = rows[0]
            number = issue.get("number")
            if not isinstance(number, int):
                raise LivenessAuditError("official_event_incident_identity_invalid")
            issue_refs, refs_complete = _issue_event_refs(issue.get("body"))
            # A clean scan with no candidates is not evidence of recovery. Close
            # only when every event recorded on the issue has a terminal outcome.
            if not refs_complete or not issue_refs or not set(issue_refs).issubset(resolved_refs):
                continue
            _request_json(
                api_url, repository, token, "POST", f"issues/{number}/comments",
                {"body": (
                    "Recovery verified by a complete official-event scan at "
                    f"{current.isoformat()}; terminal event evidence: {', '.join(issue_refs[:20])}."
                )},
                deadline_monotonic=deadline,
            )
            _request_json(
                api_url, repository, token, "PATCH", f"issues/{number}",
                {"state": "closed", "state_reason": "completed"}, deadline_monotonic=deadline,
            )
            recovered.append(number)
    return {
        "schema_version": "official-event-incident-reconcile-v1",
        "diagnostic_complete": scan_complete,
        "incident_active": bool(active),
        "opened_issue_numbers": opened,
        "reminded_issue_numbers": reminded,
        "recovered_issue_numbers": recovered,
    }


def main() -> int:
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    trace_path = os.environ.get("OFFICIAL_EVENT_TRACE_PATH", "official-event-trace.json")
    if not token or "/" not in repository:
        print("official_event_incident_configuration_invalid", file=sys.stderr)
        return 1
    try:
        result = reconcile_incidents(
            api_url=api_url, repository=repository, token=token, trace_path=trace_path,
        )
    except LivenessAuditError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
