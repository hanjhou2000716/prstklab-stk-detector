"""Serialize incident reconciliation for report, monitor, and research runs."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import tempfile
import time
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request

from scripts.monitor_liveness import (
    AUDIT_INCIDENT_MARKER,
    EVENT_INCIDENT_MARKER,
    INCIDENT_MARKER,
    MAX_AUDIT_SECONDS,
    LivenessAuditError,
    _next_link,
    _open_incidents,
    _parse_time,
    _request_json,
    audit_liveness,
    reconcile_audit_failure_incident,
)
from scripts.official_event_incidents import reconcile_incidents as reconcile_official_events
from scripts.scheduled_brief_incidents import ISSUE_MARKER as SCHEDULED_INCIDENT_MARKER
from scripts.scheduled_brief_incidents import reconcile as reconcile_scheduled_brief
from src.scheduled_slot_audit import _open_artifact_url

RESEARCH_TITLE_PREFIX = "Unified research report degraded"
RESEARCH_MARKER = "unified-research-incident="
REMINDER_INTERVAL = timedelta(minutes=30)
SOURCE_WORKFLOWS = {
    ".github/workflows/scheduled-brief.yml": "Scheduled market brief",
    ".github/workflows/scheduled-brief-slot-audit.yml": "Scheduled brief slot receipt audit",
    ".github/workflows/official-event-monitor.yml": "Official event monitor",
    ".github/workflows/unified-research-report.yml": "Unified Taiwan-US research report",
}
SOURCE_ARTIFACTS = {
    "Scheduled market brief": ("scheduled-terminal-{run_id}-attempt-{attempt}", "scheduled-terminal-*.json"),
    "Scheduled brief slot receipt audit": ("scheduled-slot-audit-{run_id}-attempt-{attempt}", "scheduled-slot-audit-*.json"),
    "Official event monitor": ("official-event-trace-{run_id}-attempt-{attempt}", "official-event-trace.json"),
    "Unified Taiwan-US research report": (
        "unified-research-terminal-{run_id}-attempt-{attempt}",
        "unified-research-terminal.json",
    ),
}
CENTRAL_WORKFLOW_PATH = ".github/workflows/incident-reconciliation.yml"
STATE_ARTIFACT_MEMBER = "incident-reconciliation-state.json"
STATE_SCHEMA = "incident-reconciliation-cursor-v1"
SOURCE_PAGE_SIZE = 100
SOURCE_MAX_PAGES = 10
STATE_ARTIFACT_LIMIT = 20 * 1024 * 1024
CADENCE_MARKER_PREFIXES = (
    AUDIT_INCIDENT_MARKER,
    EVENT_INCIDENT_MARKER,
    INCIDENT_MARKER,
    SCHEDULED_INCIDENT_MARKER,
    RESEARCH_MARKER,
)


def _safe_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _field(body: object, name: str) -> str:
    prefix = f"{name}:"
    for line in str(body or "").splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _notification_reasons(results: list[dict[str, Any]]) -> list[str]:
    """Only incidents that require a native failure alert make the job fail.

    Recovery is recorded on the Issue and in the reconciliation artifact; it
    is not a "still degraded" native alert.
    """
    reasons: list[str] = []
    for item in results:
        for key in ("opened_issue_numbers", "reminded_issue_numbers"):
            if item.get(key):
                reasons.append(key)
        if item.get("incident_opened"):
            reasons.append("incident_opened")
        if item.get("reminder_sent"):
            reasons.append("reminder_sent")
    return sorted(set(reasons))


def _cadence_marker_valid(marker: object) -> bool:
    value = str(marker or "")
    if not value or len(value) > 200 or "\n" in value or "\r" in value:
        return False
    if value.startswith((EVENT_INCIDENT_MARKER, SCHEDULED_INCIDENT_MARKER, RESEARCH_MARKER)):
        return re.fullmatch(r"[^=]+=([0-9a-f]{32})", value) is not None
    if value.startswith(INCIDENT_MARKER):
        return value == f"{INCIDENT_MARKER}official-monitor-stalled:main"
    if value.startswith(AUDIT_INCIDENT_MARKER):
        return re.fullmatch(
            re.escape(AUDIT_INCIDENT_MARKER) + r"official-monitor-audit:[A-Za-z0-9_.:-]{1,100}",
            value,
        ) is not None
    return False


def finalize_alert_cadence(
    *, result_path: Path, repository: str, api_url: str, token: str,
    consumer_run_id: str, consumer_attempt: int, consumer_sha: str,
    alert_emitted: bool, alert_step_outcome: str, now: datetime | None = None,
) -> dict[str, Any]:
    """Advance issue reminders only after the expected alert step failed."""
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LivenessAuditError("incident_cadence_result_unavailable") from exc
    if not isinstance(result, dict) or result.get("schema_version") != "incident-reconciliation-v1":
        raise LivenessAuditError("incident_cadence_result_schema_invalid")
    if (
        str(result.get("consumer_run_id") or "") != str(consumer_run_id)
        or _safe_int(result.get("consumer_attempt")) != _safe_int(consumer_attempt)
        or str(result.get("consumer_sha") or "").lower() != str(consumer_sha).lower()
        or not re.fullmatch(r"[0-9a-f]{40}", str(consumer_sha).lower())
    ):
        raise LivenessAuditError("incident_cadence_consumer_identity_mismatch")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    updated: list[int] = []
    superseded: list[int] = []
    alert_confirmed = False
    try:
        if result.get("notification_due") is not True or alert_emitted is not True or alert_step_outcome != "failure":
            raise LivenessAuditError("incident_cadence_alert_terminal_unconfirmed")
        if not isinstance(repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not token:
            raise LivenessAuditError("incident_cadence_configuration_invalid")
        confirmations = result.get("notification_cadence_confirmations")
        if not isinstance(confirmations, list):
            raise LivenessAuditError("incident_cadence_confirmations_invalid")
        normalized: list[tuple[int, str, datetime]] = []
        seen: set[int] = set()
        for row in confirmations:
            if not isinstance(row, dict) or set(row) != {"issue_number", "marker", "next_reminder_at"}:
                raise LivenessAuditError("incident_cadence_confirmation_invalid")
            number = _safe_int(row.get("issue_number"))
            marker = str(row.get("marker") or "")
            next_due = _parse_time(row.get("next_reminder_at"))
            if number is None or number in seen or not _cadence_marker_valid(marker) or next_due is None:
                raise LivenessAuditError("incident_cadence_confirmation_invalid")
            if not current < next_due <= current + timedelta(minutes=31):
                raise LivenessAuditError("incident_cadence_timestamp_out_of_bounds")
            seen.add(number)
            normalized.append((number, marker, next_due))

        deadline = time.monotonic() + MAX_AUDIT_SECONDS
        verified: list[tuple[int, str, datetime, dict[str, Any]]] = []
        for number, marker, next_due in normalized:
            issue = _request_json(
                api_url, repository, token, "GET", f"issues/{number}",
                deadline_monotonic=deadline,
            )
            if not isinstance(issue, dict) or _safe_int(issue.get("number")) != number:
                raise LivenessAuditError("incident_cadence_issue_identity_mismatch")
            body = str(issue.get("body") or "")
            if body.splitlines().count(marker) != 1:
                raise LivenessAuditError("incident_cadence_issue_marker_mismatch")
            state = str(issue.get("state") or "").casefold()
            if state == "closed":
                superseded.append(number)
                continue
            if state != "open":
                raise LivenessAuditError("incident_cadence_issue_state_unknown")
            verified.append((number, marker, next_due, issue))

        result["alert_terminal"] = {
            "status": "confirmed",
            "alert_emitted_marker": True,
            "step_outcome": "failure",
            "observed_at": current.isoformat(),
        }
        alert_confirmed = True
        for number, _marker, next_due, issue in verified:
            lines = str(issue.get("body") or "").splitlines()
            lines = [line for line in lines if not line.startswith("Alert pending consumer:")]
            next_rows = [index for index, line in enumerate(lines) if line.startswith("Next reminder at:")]
            if len(next_rows) > 1:
                raise LivenessAuditError("incident_cadence_issue_timestamp_ambiguous")
            value = f"Next reminder at: {next_due.isoformat()}"
            if next_rows:
                lines[next_rows[0]] = value
            else:
                lines.append(value)
            last_rows = [index for index, line in enumerate(lines) if line.startswith("Last reminder at:")]
            if len(last_rows) > 1:
                raise LivenessAuditError("incident_cadence_issue_timestamp_ambiguous")
            if last_rows:
                lines[last_rows[0]] = f"Last reminder at: {current.isoformat()}"
            else:
                lines.append(f"Last reminder at: {current.isoformat()}")
            _request_json(
                api_url, repository, token, "PATCH", f"issues/{number}",
                {"body": "\n".join(lines)[:12000]}, deadline_monotonic=deadline,
            )
            updated.append(number)
        result["cadence_finalization"] = {
            "status": "completed",
            "updated_issue_numbers": updated,
            "superseded_by_recovery_issue_numbers": superseded,
            "observed_at": current.isoformat(),
        }
        _write_json_atomic(result_path, result)
        return result
    except (LivenessAuditError, OSError) as exc:
        if not alert_confirmed:
            result["alert_terminal"] = {
                "status": "confirmed" if alert_emitted and alert_step_outcome == "failure" else "unconfirmed",
                "alert_emitted_marker": bool(alert_emitted),
                "step_outcome": str(alert_step_outcome)[:32],
                "observed_at": current.isoformat(),
            }
        result["cadence_finalization"] = {
            "status": "failed",
            "updated_issue_numbers": updated,
            "superseded_by_recovery_issue_numbers": superseded,
            "failure_reason": str(exc)[:160],
            "observed_at": current.isoformat(),
        }
        _write_json_atomic(result_path, result)
        raise


def _research_incident(
    *, event: dict[str, Any], repository: str, api_url: str, token: str,
    now: datetime, terminal: dict[str, Any] | None = None,
    defer_notification_cadence: bool = False,
) -> dict[str, Any]:
    run_id = _safe_int(event.get("run_id"))
    attempt = _safe_int(event.get("attempt"))
    sha = str(event.get("head_sha") or "").lower()
    conclusion = str(event.get("conclusion") or "unknown").casefold()
    workflow_id = _safe_int(event.get("workflow_id"))
    if not run_id or not attempt or len(sha) != 40 or workflow_id != 319283753:
        raise LivenessAuditError("incident_research_trigger_identity_invalid")
    if terminal is not None and (
        terminal.get("schema_version") != "unified-research-terminal-v1"
        or _safe_int(terminal.get("run_id")) != run_id
        or _safe_int(terminal.get("attempt")) != attempt
        or str(terminal.get("sha") or "").lower() != sha
        or not isinstance(terminal.get("production_run"), bool)
        or terminal.get("business_status") not in {"healthy", "degraded", "not_applicable"}
        or not isinstance(terminal.get("reason"), str)
        or len(str(terminal.get("reason"))) > 120
        or re.fullmatch(r"[A-Za-z0-9_.:-]*", str(terminal.get("reason"))) is None
    ):
        raise LivenessAuditError("incident_research_terminal_identity_invalid")
    if terminal is not None and terminal.get("production_run") is False:
        return {
            "component": "unified_research_report",
            "status": "not_applicable",
            "notification_cadence_confirmations": [],
        }
    key = hashlib.sha256(b"unified-research-report\nworkflow-failure-v1").hexdigest()[:32]
    deadline = time.monotonic() + MAX_AUDIT_SECONDS
    issues = [
        item for item in _open_incidents(api_url, repository, token, deadline_monotonic=deadline)
        if str(item.get("title") or "").startswith(RESEARCH_TITLE_PREFIX)
    ]
    matches = [
        item for item in issues
        if any(line == f"{RESEARCH_MARKER}{key}" for line in str(item.get("body") or "").splitlines())
    ]
    if len(matches) > 1:
        raise LivenessAuditError("incident_research_duplicate_issue")
    terminal_degraded = terminal is not None and terminal.get("business_status") == "degraded"
    if terminal is None and conclusion in {"success", "neutral", "skipped"}:
        return {
            "component": "unified_research_report",
            "status": "evidence_unavailable",
            "diagnostic_complete": True,
            "recovered_issue_numbers": [],
            "notification_cadence_confirmations": [],
        }
    failure = conclusion not in {"success", "neutral", "skipped"} or terminal_degraded
    latest_reason = (
        str(terminal.get("reason") or "") if terminal is not None else ""
    ) or ("research_workflow_failed" if conclusion not in {"success", "neutral", "skipped"} else "")
    if not failure:
        recovered: list[int] = []
        for issue in matches:
            number = _safe_int(issue.get("number"))
            if not number:
                raise LivenessAuditError("incident_research_issue_identity_invalid")
            _request_json(
                api_url, repository, token, "POST", f"issues/{number}/comments",
                {"body": f"Recovery verified by workflow run {run_id} attempt {attempt} ({sha}) at {now.isoformat()}."},
                deadline_monotonic=deadline,
            )
            _request_json(
                api_url, repository, token, "PATCH", f"issues/{number}",
                {"state": "closed", "state_reason": "completed"}, deadline_monotonic=deadline,
            )
            recovered.append(number)
        return {
            "component": "unified_research_report",
            "status": "recovered" if recovered else "healthy",
            "recovered_issue_numbers": recovered,
            "notification_cadence_confirmations": [],
        }

    consumer_run_id = str(os.environ.get("GITHUB_RUN_ID") or "").strip()
    consumer_attempt = str(os.environ.get("GITHUB_RUN_ATTEMPT") or "").strip()
    pending_consumer = f"{consumer_run_id}/{consumer_attempt}" if consumer_run_id and consumer_attempt else "local"
    run_url = f"https://github.com/{repository}/actions/runs/{run_id}"
    if not matches:
        body = "\n".join((
            f"{RESEARCH_MARKER}{key}",
            "Component: unified_research_report",
            f"Root cause: {latest_reason or 'research_workflow_failed'}",
            "Contract: unified-research-incident-v1",
            f"First failure: {now.isoformat()}",
            f"Latest run: {run_id} attempt {attempt} ({sha})",
            f"Latest evidence: conclusion={conclusion}; business_status={terminal.get('business_status') if terminal else 'unavailable'}",
            f"Next reminder at: {(now if defer_notification_cadence else now + REMINDER_INTERVAL).isoformat()}",
            f"Run: {run_url}",
            *([f"Alert pending consumer: {pending_consumer}"] if defer_notification_cadence else []),
        ))
        created = _request_json(
            api_url, repository, token, "POST", "issues",
            {"title": f"{RESEARCH_TITLE_PREFIX} / main", "body": body}, deadline_monotonic=deadline,
        )
        number = _safe_int(created.get("number")) if isinstance(created, dict) else None
        if not number:
            raise LivenessAuditError("incident_research_issue_create_invalid")
        confirmations = [{
            "issue_number": number,
            "marker": f"{RESEARCH_MARKER}{key}",
            "next_reminder_at": (now + REMINDER_INTERVAL).isoformat(),
        }] if defer_notification_cadence else []
        return {
            "component": "unified_research_report", "status": "degraded",
            "opened_issue_numbers": [number],
            "notification_cadence_confirmations": confirmations,
        }

    issue = matches[0]
    number = _safe_int(issue.get("number"))
    if not number:
        raise LivenessAuditError("incident_research_issue_identity_invalid")
    next_due = _parse_time(_field(issue.get("body"), "Next reminder at"))
    due = next_due is None or now >= next_due
    pending_current = (
        defer_notification_cadence
        and _field(issue.get("body"), "Alert pending consumer") == pending_consumer
    )
    if due and not pending_current:
        scheduled_next = (
            (next_due or now) if defer_notification_cadence else now + REMINDER_INTERVAL
        )
        body = "\n".join((
            f"{RESEARCH_MARKER}{key}",
            "Component: unified_research_report",
            f"Root cause: {latest_reason or 'research_workflow_failed'}",
            "Contract: unified-research-incident-v1",
            f"First failure: {_field(issue.get('body'), 'First failure') or now.isoformat()}",
            f"Latest run: {run_id} attempt {attempt} ({sha})",
            f"Latest evidence: conclusion={conclusion}; business_status={terminal.get('business_status') if terminal else 'unavailable'}",
            f"Next reminder at: {scheduled_next.isoformat()}",
            f"Run: {run_url}",
            *([f"Alert pending consumer: {pending_consumer}"] if defer_notification_cadence else []),
        ))
        _request_json(api_url, repository, token, "PATCH", f"issues/{number}", {"body": body}, deadline_monotonic=deadline)
        _request_json(
            api_url, repository, token, "POST", f"issues/{number}/comments",
            {"body": f"Still degraded: research workflow concluded {conclusion}; business_status={terminal.get('business_status') if terminal else 'unavailable'}, reason={latest_reason or 'unknown'}. Latest run {run_id} attempt {attempt} ({sha})."},
            deadline_monotonic=deadline,
        )
    confirmations = [{
        "issue_number": number,
        "marker": f"{RESEARCH_MARKER}{key}",
        "next_reminder_at": (now + REMINDER_INTERVAL).isoformat(),
    }] if defer_notification_cadence and due else []
    return {
        "component": "unified_research_report", "status": "degraded",
        "reminded_issue_numbers": [number] if due else [],
        "notification_cadence_confirmations": confirmations,
    }


def _source_workflow_id(
    *, path: str, repository: str, api_url: str, token: str,
    deadline: float,
) -> int:
    payload = _request_json(
        api_url, repository, token, "GET", f"actions/workflows/{path.rsplit('/', 1)[-1]}",
        deadline_monotonic=deadline,
    )
    workflow_id = _safe_int(payload.get("id")) if isinstance(payload, dict) else None
    if (
        not workflow_id
        or str(payload.get("path") or "") != path
        or str(payload.get("state") or "") != "active"
    ):
        raise LivenessAuditError("incident_source_workflow_identity_unavailable")
    return workflow_id


def _workflow_runs_since(
    *, path: str, workflow_id: int, repository: str, api_url: str, token: str,
    cursor: dict[str, Any], now: datetime, deadline: float, repository_id: int,
) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
    cursor_time = _parse_time(cursor.get("created_at")) or (now - timedelta(minutes=20))
    cursor_id = _safe_int(cursor.get("run_id")) or 0
    created_filter = f">={cursor_time.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    filters = {"branch": "main", "created": created_filter}
    query = urlencode({"branch": "main", "created": created_filter, "per_page": SOURCE_PAGE_SIZE, "page": 1})
    endpoint_path = f"/repos/{repository}/actions/workflows/{workflow_id}/runs"
    numeric_path = f"/repositories/{repository_id}/actions/workflows/{workflow_id}/runs"
    request_path = f"actions/workflows/{workflow_id}/runs?{query}"
    collected: dict[int, dict[str, Any]] = {}
    observed_run_ids: set[int] = set()
    active_times: list[tuple[datetime, int]] = []
    expected_total: int | None = None
    fetched_total = 0
    next_cursor = {"created_at": cursor_time.isoformat(), "run_id": cursor_id}
    page = 1
    while page <= SOURCE_MAX_PAGES:
        headers: dict[str, str] = {}
        payload = _request_json(
            api_url, repository, token, "GET", request_path,
            response_headers=headers, deadline_monotonic=deadline,
        )
        rows = payload.get("workflow_runs") if isinstance(payload, dict) else None
        total_count = payload.get("total_count") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not isinstance(total_count, int) or any(not isinstance(row, dict) for row in rows):
            raise LivenessAuditError("incident_source_runs_response_invalid")
        if expected_total is None:
            expected_total = total_count
        elif expected_total != total_count:
            raise LivenessAuditError("incident_source_runs_total_changed_during_read")
        fetched_total += len(rows)
        for row in rows:
            run_id = _safe_int(row.get("id"))
            created_at = _parse_time(row.get("created_at"))
            if run_id is None or created_at is None or _safe_int(row.get("workflow_id")) != workflow_id:
                raise LivenessAuditError("incident_source_run_identity_invalid")
            if run_id in observed_run_ids:
                raise LivenessAuditError("incident_source_run_duplicated_across_pages")
            observed_run_ids.add(run_id)
            if str(row.get("head_branch") or "") != "main":
                continue
            if (
                created_at < cursor_time
                or (created_at == cursor_time and run_id <= cursor_id)
            ):
                continue
            if str(row.get("status") or "").casefold() != "completed":
                active_times.append((created_at, run_id))
                continue
            previous = collected.get(run_id)
            if previous is not None and previous != row:
                raise LivenessAuditError("incident_source_run_changed_during_read")
            collected[run_id] = row
        next_url = _next_link(
            headers.get("link", ""), api_url=api_url,
            expected_path=(endpoint_path, numeric_path), expected_page=page + 1,
            per_page=SOURCE_PAGE_SIZE, expected_query=filters,
        )
        if next_url:
            if page == SOURCE_MAX_PAGES:
                raise LivenessAuditError("incident_source_runs_pagination_incomplete")
            request_path = next_url
            page += 1
            continue
        if len(rows) == SOURCE_PAGE_SIZE:
            if page == SOURCE_MAX_PAGES:
                raise LivenessAuditError("incident_source_runs_pagination_incomplete")
            page += 1
            request_path = f"actions/workflows/{workflow_id}/runs?" + urlencode({
                "branch": "main", "created": created_filter,
                "per_page": SOURCE_PAGE_SIZE, "page": page,
            })
            continue
        if fetched_total < (expected_total or 0):
            raise LivenessAuditError("incident_source_runs_pagination_incomplete")
        break
    runs = sorted(collected.values(), key=lambda row: (
        _parse_time(row.get("created_at")) or datetime.min.replace(tzinfo=UTC),
        _safe_int(row.get("id")) or 0,
    ))
    hold = False
    if active_times:
        oldest_active = min(active_times)
        next_cursor = {"created_at": oldest_active[0].isoformat(), "run_id": 0}
        hold = True
    elif runs:
        latest = max(runs, key=lambda row: (
            _parse_time(row.get("created_at")) or datetime.min.replace(tzinfo=UTC),
            _safe_int(row.get("id")) or 0,
        ))
        next_cursor = {"created_at": _parse_time(latest.get("created_at")).isoformat(), "run_id": _safe_int(latest.get("id")) or 0}
    return runs, next_cursor, hold


def _download_artifact_json(
    *, run: dict[str, Any], expected_artifact_name: str, expected_member: str,
    repository: str, api_url: str, token: str, deadline: float,
) -> bytes:
    run_id = _safe_int(run.get("id"))
    attempt = _safe_int(run.get("run_attempt"))
    sha = str(run.get("head_sha") or "").lower()
    if not run_id or not attempt or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise LivenessAuditError("incident_artifact_run_identity_invalid")
    payload = _request_json(
        api_url, repository, token, "GET",
        f"actions/runs/{run_id}/artifacts?per_page=100&page=1",
        deadline_monotonic=deadline,
    )
    artifacts = payload.get("artifacts") if isinstance(payload, dict) else None
    total = payload.get("total_count") if isinstance(payload, dict) else None
    if not isinstance(artifacts, list) or not isinstance(total, int) or total != len(artifacts) or total > 100:
        raise LivenessAuditError("incident_artifact_list_incomplete")
    matches = [item for item in artifacts if isinstance(item, dict) and item.get("name") == expected_artifact_name]
    if not matches:
        raise LivenessAuditError("incident_artifact_missing")
    if len(matches) != 1:
        raise LivenessAuditError("incident_artifact_ambiguous")
    artifact = matches[0]
    artifact_id = _safe_int(artifact.get("id"))
    workflow_run = artifact.get("workflow_run")
    if (
        not artifact_id or artifact.get("expired") is True
        or not isinstance(workflow_run, dict)
        or _safe_int(workflow_run.get("id")) != run_id
        or str(workflow_run.get("head_sha") or "").lower() != sha
    ):
        raise LivenessAuditError("incident_artifact_identity_invalid")
    endpoint = f"{api_url.rstrip('/')}/repos/{repository}/actions/artifacts/{artifact_id}/zip"
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise LivenessAuditError("incident_artifact_download_deadline_exceeded")
    request = Request(endpoint, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "PRStK-incident-reconciliation",
    })
    try:
        with _open_artifact_url(request, timeout=max(1, int(min(15, remaining)))) as response:
            archive_bytes = response.read(STATE_ARTIFACT_LIMIT + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise LivenessAuditError(f"incident_artifact_download_{type(exc).__name__}") from exc
    if len(archive_bytes) > STATE_ARTIFACT_LIMIT:
        raise LivenessAuditError("incident_artifact_archive_too_large")
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            files = [name for name in archive.namelist() if not name.endswith("/")]
            if len(files) != 1 or files[0] != expected_member:
                raise LivenessAuditError("incident_artifact_archive_contract_invalid")
            info = archive.getinfo(files[0])
            if info.file_size > 1_000_000:
                raise LivenessAuditError("incident_artifact_member_too_large")
            return archive.read(info)
    except (zipfile.BadZipFile, KeyError) as exc:
        raise LivenessAuditError("incident_artifact_archive_invalid") from exc


def _load_cursor_state(
    *, repository: str, api_url: str, token: str, current_run_id: int, deadline: float,
) -> dict[str, Any]:
    workflow = _request_json(
        api_url, repository, token, "GET", f"actions/workflows/{CENTRAL_WORKFLOW_PATH.rsplit('/', 1)[-1]}",
        deadline_monotonic=deadline,
    )
    workflow_id = _safe_int(workflow.get("id")) if isinstance(workflow, dict) else None
    if not workflow_id or str(workflow.get("path") or "") != CENTRAL_WORKFLOW_PATH:
        raise LivenessAuditError("incident_cursor_workflow_identity_invalid")
    runs_payload = _request_json(
        api_url, repository, token, "GET",
        f"actions/workflows/{workflow_id}/runs?per_page=20&page=1&branch=main&status=completed",
        deadline_monotonic=deadline,
    )
    runs = runs_payload.get("workflow_runs") if isinstance(runs_payload, dict) else None
    if not isinstance(runs, list):
        raise LivenessAuditError("incident_cursor_runs_response_invalid")
    for run in runs:
        if not isinstance(run, dict) or _safe_int(run.get("id")) in (None, current_run_id):
            continue
        run_id = _safe_int(run.get("id"))
        attempt = _safe_int(run.get("run_attempt"))
        sha = str(run.get("head_sha") or "").lower()
        head_repository = run.get("head_repository")
        head_full_name = head_repository.get("full_name") if isinstance(head_repository, dict) else ""
        if (
            not run_id or not attempt or not re.fullmatch(r"[0-9a-f]{40}", sha)
            or _safe_int(run.get("workflow_id")) != workflow_id
            or str(run.get("path") or "") != CENTRAL_WORKFLOW_PATH
            or str(run.get("head_branch") or "") != "main"
            or str(head_full_name or "") != repository
        ):
            continue
        name = f"incident-reconciliation-state-{run_id}-attempt-{attempt}"
        try:
            data = _download_artifact_json(
                run=run, expected_artifact_name=name, expected_member=STATE_ARTIFACT_MEMBER,
                repository=repository, api_url=api_url, token=token, deadline=deadline,
            )
            state = json.loads(data.decode("utf-8"))
        except (LivenessAuditError, UnicodeError, json.JSONDecodeError):
            continue
        if (
            isinstance(state, dict) and state.get("schema_version") == "incident-reconciliation-v1"
            and isinstance(state.get("source_cursors"), dict)
            and str(state.get("consumer_run_id") or "") == str(run_id)
            and _safe_int(state.get("consumer_attempt")) == attempt
            and str(state.get("consumer_sha") or "").lower() == sha
        ):
            return state["source_cursors"]
    return {}


def _source_event_from_run(
    run: dict[str, Any], *, workflow_name: str, repository: str,
) -> dict[str, Any]:
    head_repository = run.get("head_repository")
    repo = head_repository.get("full_name") if isinstance(head_repository, dict) else ""
    event = {
        "repository": repository,
        "workflow_name": workflow_name,
        "workflow_id": run.get("workflow_id"),
        "head_branch": str(run.get("head_branch") or ""),
        "head_repository": str(repo or ""),
        "run_id": str(run.get("id") or ""),
        "attempt": str(run.get("run_attempt") or ""),
        "head_sha": str(run.get("head_sha") or ""),
        "conclusion": str(run.get("conclusion") or "unknown"),
    }
    if (
        event["head_branch"] != "main" or event["head_repository"] != repository
        or not _safe_int(event["run_id"]) or not _safe_int(event["attempt"])
        or not re.fullmatch(r"[0-9a-f]{40}", event["head_sha"].lower())
    ):
        raise LivenessAuditError("incident_source_run_identity_invalid")
    return event


def _reconcile_source_run(
    *, run: dict[str, Any], workflow_name: str, repository: str, api_url: str,
    token: str, now: datetime, deadline: float,
) -> dict[str, Any]:
    event = _source_event_from_run(run, workflow_name=workflow_name, repository=repository)
    run_id = _safe_int(event.get("run_id"))
    attempt = _safe_int(event.get("attempt"))
    if not run_id or not attempt:
        raise LivenessAuditError("incident_source_run_identity_invalid")
    artifact_name_template, _member_pattern = SOURCE_ARTIFACTS[workflow_name]
    artifact_name = artifact_name_template.format(run_id=run_id, attempt=attempt)
    if workflow_name == "Unified Taiwan-US research report":
        try:
            content = _download_artifact_json(
                run=run, expected_artifact_name=artifact_name,
                expected_member="unified-research-terminal.json",
                repository=repository, api_url=api_url, token=token, deadline=deadline,
            )
        except LivenessAuditError as exc:
            if str(exc) != "incident_artifact_missing":
                raise
            return _research_incident(
                event=event, repository=repository, api_url=api_url, token=token, now=now,
                defer_notification_cadence=True,
            )
        try:
            terminal = json.loads(content.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise LivenessAuditError("incident_research_terminal_json_invalid") from exc
        if not isinstance(terminal, dict):
            raise LivenessAuditError("incident_research_terminal_json_invalid")
        return _research_incident(
            event=event, repository=repository, api_url=api_url, token=token, now=now,
            terminal=terminal, defer_notification_cadence=True,
        )
    if workflow_name == "Official event monitor":
        expected_member = "official-event-trace.json"
    elif workflow_name == "Scheduled market brief":
        expected_member = f"scheduled-terminal-{run_id}-attempt-{attempt}.json"
    else:
        expected_member = f"scheduled-slot-audit-{run_id}-attempt-{attempt}.json"
    content = _download_artifact_json(
        run=run, expected_artifact_name=artifact_name, expected_member=expected_member,
        repository=repository, api_url=api_url, token=token, deadline=deadline,
    )
    with tempfile.TemporaryDirectory(prefix="prstk-incident-") as temp:
        directory = Path(temp)
        evidence_path = directory / expected_member
        evidence_path.write_bytes(content)
        if workflow_name in {"Scheduled market brief", "Scheduled brief slot receipt audit"}:
            return reconcile_scheduled_brief(
                event=event, evidence_directory=directory,
                repository=repository, api_url=api_url, token=token, now=now,
                defer_notification_cadence=True,
            )
        return reconcile_official_events(
            api_url=api_url, repository=repository, token=token,
            trace_path=evidence_path, now=now, defer_notification_cadence=True,
        )


def reconcile(*, result_path: Path, evidence_directory: Path) -> dict[str, Any]:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    token = os.environ.get("GITHUB_TOKEN", "")
    if "/" not in repository or not token:
        raise LivenessAuditError("incident_reconciliation_configuration_invalid")
    try:
        payload = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    except (KeyError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LivenessAuditError("incident_reconciliation_event_unavailable") from exc
    now = datetime.now(UTC)
    deadline = time.monotonic() + MAX_AUDIT_SECONDS
    cursors = _load_cursor_state(
        repository=repository, api_url=api_url, token=token,
        current_run_id=_safe_int(os.environ.get("GITHUB_RUN_ID")) or 0,
        deadline=deadline,
    )
    repository_info = _request_json(
        api_url, repository, token, "GET", f"repos/{repository}", deadline_monotonic=deadline,
    )
    repository_id = _safe_int(repository_info.get("id")) if isinstance(repository_info, dict) else None
    if repository_id is None:
        raise LivenessAuditError("incident_repository_identity_unavailable")
    source_definitions: dict[str, tuple[int, str]] = {}
    cursor_updates: dict[str, dict[str, Any]] = {}
    source_rows: list[tuple[datetime, int, str, dict[str, Any]]] = []
    for path, workflow_name in SOURCE_WORKFLOWS.items():
        workflow_id = _source_workflow_id(
            path=path, repository=repository, api_url=api_url, token=token,
            deadline=deadline,
        )
        source_definitions[path] = (workflow_id, workflow_name)
        old_cursor = cursors.get(path) if isinstance(cursors.get(path), dict) else {
            "created_at": (now - timedelta(minutes=20)).isoformat(), "run_id": 0,
        }
        cursors[path] = old_cursor
        runs, next_cursor, _held = _workflow_runs_since(
            path=path, workflow_id=workflow_id, repository=repository,
            api_url=api_url, token=token, cursor=old_cursor, now=now,
            deadline=deadline, repository_id=repository_id,
        )
        cursor_updates[path] = next_cursor
        for run in runs:
            created = _parse_time(run.get("created_at"))
            run_id = _safe_int(run.get("id"))
            if created is None or run_id is None:
                raise LivenessAuditError("incident_source_run_identity_invalid")
            source_rows.append((created, run_id, workflow_name, run))

    # A webhook is authoritative for its completed run, including a long-running
    # source whose creation time predates the saved cursor window.
    incoming = payload.get("workflow_run") if isinstance(payload, dict) else None
    if isinstance(incoming, dict):
        incoming_id = _safe_int(incoming.get("workflow_id"))
        for workflow_id, workflow_name in source_definitions.values():
            if workflow_id == incoming_id:
                incoming_run = dict(incoming)
                incoming_run["workflow_id"] = workflow_id
                incoming_run["status"] = "completed"
                incoming_run.setdefault("run_attempt", incoming.get("run_attempt"))
                if _safe_int(incoming_run.get("id")) is not None:
                    created = _parse_time(incoming_run.get("created_at")) or now
                    key = (_safe_int(incoming_run.get("id")) or 0, _safe_int(incoming_run.get("run_attempt")) or 1)
                    existing = {
                        (_safe_int(row.get("id")) or 0, _safe_int(row.get("run_attempt")) or 1)
                        for _created, _run_id, _name, row in source_rows
                    }
                    if key not in existing:
                        source_rows.append((created, key[0], workflow_name, incoming_run))
                break
    source_rows.sort(key=lambda item: (item[0], item[1], item[2]))
    if len(source_rows) > 100:
        raise LivenessAuditError("incident_source_backlog_limit_exceeded")
    results: list[dict[str, Any]] = []
    for _created, run_id, workflow_name, run in source_rows:
        source_result = _reconcile_source_run(
            run=run, workflow_name=workflow_name, repository=repository,
            api_url=api_url, token=token, now=now, deadline=deadline,
        )
        results.append({
            "source_workflow": workflow_name,
            "source_run_id": run_id,
            "source_attempt": _safe_int(run.get("run_attempt")) or 1,
            **source_result,
        })
        if source_result.get("diagnostic_complete") is False:
            path = next((p for p, (_wid, name) in source_definitions.items() if name == workflow_name), "")
            if path:
                cursor_updates[path] = {
                    "created_at": (_parse_time(run.get("created_at")) or now).isoformat(),
                    "run_id": 0,
                }
    if os.environ.get("GITHUB_EVENT_NAME") in {"schedule", "workflow_dispatch"}:
        try:
            result = audit_liveness(
                api_url=api_url, repository=repository, token=token, now=now,
                defer_notification_cadence=True,
            )
        except LivenessAuditError as exc:
            result = reconcile_audit_failure_incident(
                api_url=api_url, repository=repository, token=token,
                reason=str(exc), now=now, defer_notification_cadence=True,
            )
            result["audit_failure_reason"] = str(exc)[:160]
        results.append({"source_workflow": "Official monitor liveness audit", **result})
    cadence_confirmations: list[dict[str, str | int]] = []
    for item in results:
        confirmations = item.get("notification_cadence_confirmations")
        if isinstance(confirmations, list):
            cadence_confirmations.extend(
                row for row in confirmations if isinstance(row, dict)
            )
    notification_reasons = _notification_reasons(results)
    confirmations_by_issue: dict[int, dict[str, str | int]] = {}
    for row in cadence_confirmations:
        number = _safe_int(row.get("issue_number"))
        if number is None:
            raise LivenessAuditError("incident_notification_cadence_issue_invalid")
        existing = confirmations_by_issue.get(number)
        if existing is not None and existing != row:
            raise LivenessAuditError("incident_notification_cadence_conflict")
        confirmations_by_issue[number] = row
    diagnostic_complete = all(item.get("diagnostic_complete") is not False for item in results)
    final_cursors = {
        path: cursor
        for path, cursor in cursor_updates.items()
    }
    result = {
        "schema_version": "incident-reconciliation-v1",
        "consumer_run_id": os.environ.get("GITHUB_RUN_ID", "")[:32],
        "consumer_attempt": _safe_int(os.environ.get("GITHUB_RUN_ATTEMPT", "")),
        "consumer_sha": os.environ.get("GITHUB_SHA", "")[:40],
        "source_run_ids": sorted({str(item.get("source_run_id")) for item in results if item.get("source_run_id")}),
        "business_status": "degraded" if any(item.get("status") in {"stalled", "degraded"} or item.get("incident_active") for item in results) else "healthy",
        "diagnostic_complete": diagnostic_complete,
        "incident_handoff_status": "accepted" if diagnostic_complete or all(
            item.get("diagnostic_complete") is not False or item.get("incident_active") is True
            for item in results
        ) else "incomplete",
        "notification_due": bool(notification_reasons),
        "notification_reasons": sorted(set(notification_reasons)),
        "notification_cadence_confirmations": list(confirmations_by_issue.values()),
        "alert_terminal": {"status": "pending" if notification_reasons else "not_due"},
        "cadence_finalization": {"status": "pending" if notification_reasons else "not_due"},
        "results": results,
        "source_cursors": final_cursors,
        "observed_at": now.isoformat(),
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = result_path.with_suffix(result_path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, result_path)
    output_path = os.environ.get("GITHUB_OUTPUT", "")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"notification_due={str(result['notification_due']).lower()}\n")
            handle.write(f"business_status={result['business_status']}\n")
    return result


def main() -> int:
    path = Path(os.environ.get("INCIDENT_RECONCILIATION_RESULT_PATH", "incident-reconciliation.json"))
    if sys.argv[1:] == ["--finalize-alert-cadence"]:
        try:
            result = finalize_alert_cadence(
                result_path=path,
                repository=os.environ.get("GITHUB_REPOSITORY", ""),
                api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
                token=os.environ.get("GITHUB_TOKEN", ""),
                consumer_run_id=os.environ.get("GITHUB_RUN_ID", ""),
                consumer_attempt=_safe_int(os.environ.get("GITHUB_RUN_ATTEMPT")) or 0,
                consumer_sha=os.environ.get("GITHUB_SHA", ""),
                alert_emitted=os.environ.get("INCIDENT_ALERT_EMITTED", "").casefold() == "true",
                alert_step_outcome=os.environ.get("INCIDENT_ALERT_STEP_OUTCOME", ""),
            )
        except (LivenessAuditError, OSError) as exc:
            print(f"incident_cadence_finalization_failed:{str(exc)[:200]}", file=sys.stderr)
            return 1
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    if sys.argv[1:]:
        print("incident_reconciliation_arguments_invalid", file=sys.stderr)
        return 2
    directory = Path(os.environ.get("INCIDENT_EVIDENCE_DIR", "incident-evidence"))
    try:
        result = reconcile(result_path=path, evidence_directory=directory)
    except (LivenessAuditError, OSError) as exc:
        result = {
            "schema_version": "incident-reconciliation-v1",
            "consumer_run_id": os.environ.get("GITHUB_RUN_ID", "")[:32],
            "consumer_attempt": _safe_int(os.environ.get("GITHUB_RUN_ATTEMPT", "")),
            "consumer_sha": os.environ.get("GITHUB_SHA", "")[:40],
            "business_status": "unknown",
            "diagnostic_complete": False,
            "incident_handoff_status": "failed",
            "notification_due": False,
            "failure_reason": str(exc)[:200],
            "observed_at": datetime.now(UTC).isoformat(),
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, path)
        except OSError:
            pass
        print(f"incident_reconciliation_failed:{str(exc)[:200]}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    summary = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("\n## Central incident reconciliation\n")
            handle.write(f"- business_status: {result['business_status']}\n")
            handle.write(f"- incident_handoff_status: {result['incident_handoff_status']}\n")
            handle.write(f"- notification_due: {str(result['notification_due']).lower()}\n")
    return 0 if result.get("incident_handoff_status") == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
