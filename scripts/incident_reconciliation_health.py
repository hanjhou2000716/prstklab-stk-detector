"""Independently verify that central incident reconciliation remains observable."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from scripts.incident_reconciliation import (
    CENTRAL_HEALTH_MARKER,
    CENTRAL_WORKFLOW_PATH,
    SOURCE_WORKFLOWS,
    STATE_ARTIFACT_MEMBER,
    _download_artifact_json,
    _safe_int,
    finalize_alert_cadence,
)
from scripts.monitor_liveness import (
    MAX_AUDIT_SECONDS,
    LivenessAuditError,
    _open_incidents,
    _parse_time,
    _request_json,
)
from src.incident_cadence import can_emit_pending_alert, mark_pending_alert, preserve_pending_alert

ISSUE_TITLE_PREFIX = "Central incident reconciliation degraded"
CONTRACT = "central-incident-health-v1"
REMINDER_INTERVAL = timedelta(minutes=30)
STALE_AFTER = timedelta(minutes=10)
MAX_RUNS = 10


def _safe_root(value: object) -> str:
    raw = str(value or "").casefold()
    api_http = re.search(r"(?:monitor_liveness|incident)_api_http_(\d{3})", raw)
    if api_http:
        return f"central_reconciliation_api_http_{api_http.group(1)}"
    if "artifact" in raw or "terminal" in raw or "result" in raw:
        return "central_reconciliation_result_unavailable"
    if "cursor" in raw or "pagination" in raw or "coverage" in raw:
        return "central_reconciliation_coverage_incomplete"
    if "identity" in raw or "sha" in raw or "schema" in raw or "contract" in raw:
        return "central_reconciliation_evidence_invalid"
    return "central_reconciliation_diagnostic_incomplete"


def _marker(root: str) -> str:
    digest = hashlib.sha256(f"{CONTRACT}\n{root}".encode()).hexdigest()[:32]
    return f"{CENTRAL_HEALTH_MARKER}{digest}"


def _run_identity(run: object, *, workflow_id: int, repository: str) -> dict[str, Any]:
    if not isinstance(run, dict):
        raise LivenessAuditError("central_health_run_invalid")
    run_id = _safe_int(run.get("id"))
    attempt = _safe_int(run.get("run_attempt"))
    sha = str(run.get("head_sha") or "").lower()
    created_at = _parse_time(run.get("created_at"))
    head_repository = run.get("head_repository")
    if (
        not run_id or not attempt or _safe_int(run.get("workflow_id")) != workflow_id
        or str(run.get("path") or "") != CENTRAL_WORKFLOW_PATH
        or str(run.get("head_branch") or "") != "main"
        or not isinstance(head_repository, dict)
        or str(head_repository.get("full_name") or "") != repository
        or not re.fullmatch(r"[0-9a-f]{40}", sha)
        or created_at is None
    ):
        raise LivenessAuditError("central_health_run_identity_invalid")
    return run


def _read_runs(
    *, repository: str, api_url: str, token: str, deadline: float,
    triggered_run_id: str = "", triggered_run_attempt: str = "", triggered_run_sha: str = "",
) -> tuple[int, list[dict[str, Any]]]:
    workflow = _request_json(
        api_url, repository, token, "GET",
        f"actions/workflows/{Path(CENTRAL_WORKFLOW_PATH).name}",
        deadline_monotonic=deadline,
    )
    workflow_id = _safe_int(workflow.get("id")) if isinstance(workflow, dict) else None
    if not workflow_id or str(workflow.get("path") or "") != CENTRAL_WORKFLOW_PATH:
        raise LivenessAuditError("central_health_workflow_identity_invalid")
    query = urlencode({"branch": "main", "per_page": MAX_RUNS, "page": 1, "status": "all"})
    payload = _request_json(
        api_url, repository, token, "GET",
        f"actions/workflows/{workflow_id}/runs?{query}",
        deadline_monotonic=deadline,
    )
    runs = payload.get("workflow_runs") if isinstance(payload, dict) else None
    if not isinstance(runs, list) or len(runs) > MAX_RUNS:
        raise LivenessAuditError("central_health_runs_response_invalid")
    verified = [_run_identity(run, workflow_id=workflow_id, repository=repository) for run in runs]

    # The workflow_run event is emitted as soon as the source run completes, but
    # the workflow-runs listing can lag behind that event. Resolve the exact
    # event run by ID before turning an empty or stale listing into a
    # run-missing incident. The event identity is only a lookup hint; the API
    # response remains authoritative and must match the trusted workflow.
    expected_id = _safe_int(triggered_run_id)
    if triggered_run_id and not expected_id:
        raise LivenessAuditError("central_health_trigger_identity_invalid")
    if expected_id:
        expected_attempt = _safe_int(triggered_run_attempt)
        expected_sha = str(triggered_run_sha or "").lower()
        if not expected_attempt or not re.fullmatch(r"[0-9a-f]{40}", expected_sha):
            raise LivenessAuditError("central_health_trigger_identity_invalid")
        trigger_run = next((
            run for run in verified if _safe_int(run.get("id")) == expected_id
        ), None)
        if trigger_run is None:
            for attempt in range(3):
                try:
                    candidate = _request_json(
                        api_url, repository, token, "GET", f"actions/runs/{expected_id}",
                        deadline_monotonic=deadline,
                    )
                except LivenessAuditError as exc:
                    if "_http_404" not in str(exc) or attempt == 2:
                        if "_http_404" in str(exc):
                            raise LivenessAuditError("central_health_trigger_run_not_visible") from exc
                        raise
                    remaining = max(0.0, deadline - time.monotonic())
                    delay = min(2 ** attempt, 4, remaining)
                    if delay <= 0:
                        raise LivenessAuditError("central_health_trigger_run_not_visible") from exc
                    time.sleep(delay)
                    continue
                trigger_run = _run_identity(candidate, workflow_id=workflow_id, repository=repository)
                break
        if trigger_run is None:
            raise LivenessAuditError("central_health_trigger_run_not_visible")
        if (
            _safe_int(trigger_run.get("id")) != expected_id
            or str(trigger_run.get("head_sha") or "").lower() != expected_sha
            or (_safe_int(trigger_run.get("run_attempt")) or 0) < expected_attempt
        ):
            raise LivenessAuditError("central_health_trigger_run_identity_mismatch")
        if not any(_safe_int(run.get("id")) == expected_id for run in verified):
            verified.append(trigger_run)

    verified.sort(key=lambda row: (_parse_time(row.get("created_at")) or datetime.min.replace(tzinfo=UTC), _safe_int(row.get("id")) or 0), reverse=True)
    return workflow_id, verified


def _read_result(
    *, run: dict[str, Any], repository: str, api_url: str, token: str,
    deadline: float,
) -> dict[str, Any]:
    run_id = _safe_int(run.get("id"))
    attempt = _safe_int(run.get("run_attempt"))
    sha = str(run.get("head_sha") or "").lower()
    if not run_id or not attempt:
        raise LivenessAuditError("central_health_run_identity_invalid")
    member = _download_artifact_json(
        run=run,
        expected_artifact_name=f"incident-reconciliation-state-{run_id}-attempt-{attempt}",
        expected_member=STATE_ARTIFACT_MEMBER,
        repository=repository, api_url=api_url, token=token, deadline=deadline,
    )
    try:
        result = json.loads(member.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LivenessAuditError("central_health_result_json_invalid") from exc
    if (
        not isinstance(result, dict)
        or result.get("schema_version") != "incident-reconciliation-v1"
        or str(result.get("consumer_run_id") or "") != str(run_id)
        or _safe_int(result.get("consumer_attempt")) != attempt
        or str(result.get("consumer_sha") or "").lower() != sha
        or _parse_time(result.get("observed_at")) is None
    ):
        raise LivenessAuditError("central_health_result_identity_invalid")
    return result


def _cursor_fingerprint(result: dict[str, Any]) -> str:
    cursors = result.get("source_cursors")
    if not isinstance(cursors, dict):
        raise LivenessAuditError("central_health_cursor_state_missing")
    if not set(SOURCE_WORKFLOWS).issubset(cursors):
        raise LivenessAuditError("central_health_cursor_coverage_missing")
    for path in SOURCE_WORKFLOWS:
        row = cursors.get(path)
        run_id = row.get("run_id") if isinstance(row, dict) else None
        if (
            not isinstance(row, dict)
            or row.get("mode") not in {"live", "backfill"}
            or row.get("scan_complete") is not True
            or _parse_time(row.get("created_at")) is None
            or isinstance(run_id, bool)
            or not isinstance(run_id, int)
            or run_id < 0
        ):
            raise LivenessAuditError("central_health_cursor_state_invalid")
    encoded = json.dumps(cursors, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _result_is_complete(result: dict[str, Any]) -> tuple[bool, str, str]:
    # Preserve the original source failure when a bounded early exit could not
    # produce cursor state. Otherwise a missing cursor would mask the actionable
    # HTTP/contract cause with a generic coverage failure.
    if result.get("diagnostic_complete") is not True and result.get("failure_reason"):
        try:
            fingerprint = _cursor_fingerprint(result)
        except LivenessAuditError:
            fingerprint = ""
        return False, _safe_root(result.get("failure_reason")), fingerprint
    try:
        fingerprint = _cursor_fingerprint(result)
    except LivenessAuditError as exc:
        return False, _safe_root(exc), ""
    if result.get("coverage_status") != "complete":
        return False, "central_reconciliation_coverage_incomplete", fingerprint
    cursors = result.get("source_cursors")
    if not isinstance(cursors, dict) or any(
        not isinstance(cursors.get(path), dict)
        or cursors[path].get("scan_complete") is not True
        for path in SOURCE_WORKFLOWS
    ):
        return False, "central_reconciliation_coverage_incomplete", fingerprint
    if result.get("diagnostic_complete") is not True:
        return False, _safe_root(result.get("failure_reason") or "diagnostic_incomplete"), fingerprint
    if result.get("incident_handoff_status") != "accepted":
        return False, "central_reconciliation_handoff_incomplete", fingerprint
    alert_terminal = result.get("alert_terminal")
    cadence = result.get("cadence_finalization")
    if result.get("notification_due") is True:
        if (
            not isinstance(alert_terminal, dict)
            or alert_terminal.get("status") != "confirmed"
            or not isinstance(cadence, dict)
            or cadence.get("status") != "completed"
        ):
            return False, "central_reconciliation_alert_handoff_incomplete", fingerprint
    elif (
        not isinstance(alert_terminal, dict)
        or alert_terminal.get("status") != "not_due"
        or not isinstance(cadence, dict)
        or cadence.get("status") != "not_due"
    ):
        return False, "central_reconciliation_alert_state_invalid", fingerprint
    if result.get("business_status") not in {"healthy", "degraded"}:
        return False, "central_reconciliation_business_status_unknown", fingerprint
    return True, "", fingerprint


def _issue_body(
    *, repository: str, marker: str, root: str, now: datetime, first_failure: str,
    latest_run: dict[str, Any] | None, latest_progress: str, next_reminder: datetime,
    pending_consumer: str = "", prior_body: str = "",
) -> str:
    affected = [value for value in prior_body.splitlines() if value.startswith("Affected central runs:")]
    existing_ids: list[str] = []
    if affected:
        existing_ids = [item for item in affected[0].partition(":")[2].split(",") if item.strip().isdigit()]
    if latest_run:
        run_id = str(_safe_int(latest_run.get("id")) or "")
        if run_id:
            existing_ids = list(dict.fromkeys([*existing_ids, run_id]))[-20:]
    run_id = _safe_int(latest_run.get("id")) if latest_run else None
    attempt = _safe_int(latest_run.get("run_attempt")) if latest_run else None
    sha = str(latest_run.get("head_sha") or "")[:40] if latest_run else "unknown"
    run_url = f"https://github.com/{repository}/actions/runs/{run_id}" if run_id else "unavailable"
    lines = [
        marker,
        "Component: central_incident_reconciliation",
        f"Root cause: {root}",
        f"Contract: {CONTRACT}",
        f"First failure: {first_failure}",
        f"Latest run: {run_id or 'unavailable'} attempt {attempt or 'unknown'} ({sha})",
        f"Latest progress: {latest_progress or 'unknown'}",
        f"Affected central runs: {', '.join(existing_ids) if existing_ids else 'unknown'}",
        f"Observed at: {now.isoformat()}",
        f"Next reminder at: {next_reminder.isoformat()}",
        f"Run: {run_url}",
    ]
    if pending_consumer:
        lines.append(f"Alert pending consumer: {pending_consumer}")
    preserved = [
        line for line in prior_body.splitlines()
        if line.startswith(("Last reminder at:", "Alert pending consumer:", "Alert pending since:"))
    ]
    if preserved:
        lines = [line for line in lines if not line.startswith(("Alert pending consumer:", "Alert pending since:"))]
        lines.extend(preserved)
    return "\n".join(lines)


def _consolidate_duplicate_issues(
    *, issues: list[dict[str, Any]], repository: str, api_url: str, token: str,
    deadline: float,
) -> list[int]:
    groups: dict[str, list[dict[str, Any]]] = {}
    marker_pattern = re.compile(re.escape(CENTRAL_HEALTH_MARKER) + r"[0-9a-f]{32}")
    for issue in issues:
        lines = set(str(issue.get("body") or "").splitlines())
        markers = [line for line in lines if marker_pattern.fullmatch(line)]
        root = next((line.partition(":")[2].strip() for line in lines if line.startswith("Root cause:")), "")
        if (
            len(markers) == 1
            and root
            and _marker(root) in markers
            and "Component: central_incident_reconciliation" in lines
            and f"Contract: {CONTRACT}" in lines
        ):
            groups.setdefault(markers[0], []).append(issue)

    consolidated: list[int] = []
    for marker, duplicates in groups.items():
        if len(duplicates) < 2:
            continue
        numbered = [(_safe_int(issue.get("number")), issue) for issue in duplicates]
        numbers = [number for number, _issue in numbered]
        if any(not number for number in numbers) or len(set(numbers)) != len(numbers):
            raise LivenessAuditError("central_health_duplicate_issue_identity_invalid")
        numbered.sort(key=lambda pair: int(pair[0] or 0))
        primary_number = int(numbered[0][0] or 0)
        for duplicate_number_value, _duplicate in numbered[1:]:
            duplicate_number = int(duplicate_number_value or 0)
            _request_json(
                api_url, repository, token, "POST", f"issues/{duplicate_number}/comments",
                {"body": f"Duplicate central-health incident consolidated into #{primary_number}. The incident fingerprint {marker} matches exactly; this duplicate closure is not a recovery. The primary incident remains open until recovery is verified."},
                deadline_monotonic=deadline,
            )
            _request_json(
                api_url, repository, token, "PATCH", f"issues/{duplicate_number}",
                {"state": "closed", "state_reason": "duplicate"}, deadline_monotonic=deadline,
            )
            consolidated.append(duplicate_number)
    return consolidated


def _evaluate(
    *, runs: list[dict[str, Any]], workflow_id: int, repository: str,
    api_url: str, token: str, now: datetime, deadline: float,
) -> dict[str, Any]:
    if not runs:
        return {"healthy": False, "root": "central_reconciliation_run_missing", "latest_run": None, "progress": ""}
    latest = runs[0]
    if str(latest.get("status") or "").casefold() != "completed":
        started = _parse_time(latest.get("run_started_at")) or _parse_time(latest.get("created_at"))
        if started is not None and now - started < STALE_AFTER:
            return {"healthy": None, "root": "", "latest_run": latest, "progress": "pending"}
        return {"healthy": False, "root": "central_reconciliation_stalled", "latest_run": latest, "progress": "stale_active_run"}
    try:
        result = _read_result(
            run=latest, repository=repository, api_url=api_url, token=token, deadline=deadline,
        )
        complete, root, fingerprint = _result_is_complete(result)
        if not complete:
            return {"healthy": False, "root": root, "latest_run": latest, "progress": fingerprint, "result": result}
    except LivenessAuditError as exc:
        return {"healthy": False, "root": _safe_root(exc), "latest_run": latest, "progress": "", "evidence_error": str(exc)[:160]}
    healthy_runs = 1
    for run in runs[1:]:
        if healthy_runs >= 2 or str(run.get("status") or "").casefold() != "completed":
            continue
        try:
            prior = _read_result(
                run=run, repository=repository, api_url=api_url, token=token, deadline=deadline,
            )
            good, _root, _fingerprint = _result_is_complete(prior)
        except LivenessAuditError:
            good = False
        if good and _safe_int(run.get("id")) != _safe_int(latest.get("id")):
            healthy_runs += 1
    return {
        "healthy": True, "root": "", "latest_run": latest,
        "progress": fingerprint, "result": result, "healthy_run_count": healthy_runs,
    }


def reconcile_health(
    *, repository: str, api_url: str, token: str, now: datetime | None = None,
    consumer_run_id: str, consumer_attempt: int, consumer_sha: str,
    triggered_run_id: str = "", triggered_run_attempt: str = "", triggered_run_sha: str = "",
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not token:
        raise LivenessAuditError("central_health_configuration_invalid")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    deadline = time.monotonic() + MAX_AUDIT_SECONDS
    workflow_id, runs = _read_runs(
        repository=repository, api_url=api_url, token=token, deadline=deadline,
        triggered_run_id=triggered_run_id,
        triggered_run_attempt=triggered_run_attempt,
        triggered_run_sha=triggered_run_sha,
    )
    evaluation = _evaluate(
        runs=runs, workflow_id=workflow_id, repository=repository,
        api_url=api_url, token=token, now=current, deadline=deadline,
    )
    issues = [
        issue for issue in _open_incidents(api_url, repository, token, deadline_monotonic=deadline)
        if str(issue.get("title") or "").startswith(ISSUE_TITLE_PREFIX)
    ]
    consolidated = _consolidate_duplicate_issues(
        issues=issues, repository=repository, api_url=api_url, token=token, deadline=deadline,
    )
    consolidated_set = set(consolidated)
    issues = [issue for issue in issues if _safe_int(issue.get("number")) not in consolidated_set]
    result: dict[str, Any] = {
        "schema_version": "incident-reconciliation-v1",
        "consumer_run_id": str(consumer_run_id)[:32],
        "consumer_attempt": _safe_int(consumer_attempt),
        "consumer_sha": str(consumer_sha).lower()[:40],
        "business_status": "unknown" if evaluation["healthy"] is None else "healthy" if evaluation["healthy"] else "degraded",
        "diagnostic_complete": True,
        "incident_handoff_status": "accepted",
        "notification_due": False,
        "notification_reasons": [],
        "notification_cadence_confirmations": [],
        "consolidated_issue_numbers": consolidated,
        "results": [],
        "observed_at": current.isoformat(),
    }
    if evaluation["healthy"] is None:
        result["health_status"] = "pending"
        result["latest_central_run_id"] = _safe_int((evaluation.get("latest_run") or {}).get("id"))
        return result

    if evaluation["healthy"] is True:
        recovered: list[int] = []
        if int(evaluation.get("healthy_run_count") or 0) >= 2:
            for issue in issues:
                number = _safe_int(issue.get("number"))
                if not number:
                    raise LivenessAuditError("central_health_issue_identity_invalid")
                body = str(issue.get("body") or "")
                root = next((
                    line.partition(":")[2].strip()
                    for line in body.splitlines() if line.startswith("Root cause:")
                ), "")
                if (
                    not any(re.fullmatch(re.escape(CENTRAL_HEALTH_MARKER) + r"[0-9a-f]{32}", line) for line in body.splitlines())
                    or f"Contract: {CONTRACT}" not in body.splitlines()
                    or "Component: central_incident_reconciliation" not in body.splitlines()
                    or _marker(root) not in body.splitlines()
                ):
                    continue
                _request_json(
                    api_url, repository, token, "POST", f"issues/{number}/comments",
                    {"body": f"Central reconciliation recovery verified by two distinct complete runs at {current.isoformat()}. Historical missed reports remain unchanged."},
                    deadline_monotonic=deadline,
                )
                _request_json(
                    api_url, repository, token, "PATCH", f"issues/{number}",
                    {"state": "closed", "state_reason": "completed"}, deadline_monotonic=deadline,
                )
                recovered.append(number)
        result.update({
            "health_status": "healthy" if not issues else "recovery_pending" if not recovered else "recovered",
            "healthy_run_count": int(evaluation.get("healthy_run_count") or 0),
            "recovered_issue_numbers": recovered,
            "latest_central_run_id": _safe_int((evaluation.get("latest_run") or {}).get("id")),
            "latest_progress": evaluation.get("progress", ""),
        })
        return result

    root = str(evaluation.get("root") or "central_reconciliation_diagnostic_incomplete")
    marker = _marker(root)
    matching = [
        issue for issue in issues
        if marker in str(issue.get("body") or "").splitlines()
    ]
    if len(matching) > 1:
        raise LivenessAuditError("central_health_duplicate_issue")
    issue = matching[0] if matching else None
    latest = evaluation.get("latest_run")
    pending_consumer = f"{consumer_run_id}/{consumer_attempt}"
    next_due_value = next((
        line.partition(":")[2].strip()
        for line in str(issue.get("body") or "").splitlines()
        if line.startswith("Next reminder at:")
    ), "") if issue else ""
    next_due = _parse_time(next_due_value)
    due = issue is None or next_due is None or current >= next_due
    pending_current = bool(issue and any(
        line == f"Alert pending consumer: {pending_consumer}"
        for line in str(issue.get("body") or "").splitlines()
    ))
    notify_due = due and (
        issue is None or can_emit_pending_alert(str(issue.get("body") or ""), pending_consumer, current)
    )
    cadence: list[dict[str, str | int]] = []
    if issue is None:
        first_failure = current.isoformat()
        body = _issue_body(
            repository=repository, marker=marker, root=root, now=current, first_failure=first_failure,
            latest_run=latest, latest_progress=str(evaluation.get("progress") or ""),
            next_reminder=current, pending_consumer=pending_consumer,
        )
        body = mark_pending_alert(body, pending_consumer, current)
        created = _request_json(
            api_url, repository, token, "POST", "issues",
            {"title": f"{ISSUE_TITLE_PREFIX} / {root}", "body": body}, deadline_monotonic=deadline,
        )
        number = _safe_int(created.get("number")) if isinstance(created, dict) else None
        if not number:
            raise LivenessAuditError("central_health_issue_create_invalid")
        due = True
    else:
        number = _safe_int(issue.get("number"))
        if not number:
            raise LivenessAuditError("central_health_issue_identity_invalid")
        first_failure = next((
            line.partition(":")[2].strip()
            for line in str(issue.get("body") or "").splitlines()
            if line.startswith("First failure:")
        ), current.isoformat())
        body = _issue_body(
            repository=repository, marker=marker, root=root, now=current, first_failure=first_failure,
            latest_run=latest, latest_progress=str(evaluation.get("progress") or ""),
            next_reminder=next_due or current,
            pending_consumer=pending_consumer if notify_due else "",
            prior_body=str(issue.get("body") or ""),
        )
        if notify_due:
            body = mark_pending_alert(body, pending_consumer, current)
        else:
            body = preserve_pending_alert(body, issue.get("body"))
        _request_json(
            api_url, repository, token, "PATCH", f"issues/{number}",
            {"body": body}, deadline_monotonic=deadline,
        )
        if notify_due and not pending_current:
            _request_json(
                api_url, repository, token, "POST", f"issues/{number}/comments",
                {"body": f"Central reconciliation remains degraded ({root}); latest run {(_safe_int(latest.get('id')) if latest else 'unavailable')}. Checked at {current.isoformat()}."},
                deadline_monotonic=deadline,
            )
    if notify_due and not pending_current:
        cadence.append({
            "issue_number": number,
            "marker": marker,
            "next_reminder_at": (current + REMINDER_INTERVAL).isoformat(),
        })
        result["notification_due"] = True
        result["notification_reasons"] = ["central_health_incident_opened" if issue is None else "central_health_reminder_due"]
    result.update({
        "health_status": "degraded",
        "failure_reason": root,
        "consolidated_issue_numbers": consolidated,
        "latest_central_run_id": _safe_int(latest.get("id")) if latest else None,
        "latest_progress": evaluation.get("progress", ""),
        "evidence_error": evaluation.get("evidence_error", ""),
        "notification_cadence_confirmations": cadence,
    })
    return result


def main() -> int:
    result_path = Path(os.environ.get("INCIDENT_RECONCILIATION_RESULT_PATH", "incident-health.json"))
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    token = os.environ.get("GITHUB_TOKEN", "")
    consumer_run_id = os.environ.get("GITHUB_RUN_ID", "")
    consumer_attempt = _safe_int(os.environ.get("GITHUB_RUN_ATTEMPT", "")) or 0
    consumer_sha = os.environ.get("GITHUB_SHA", "")
    if sys.argv[1:] == ["--finalize-alert-cadence"]:
        try:
            finalize_alert_cadence(
                result_path=result_path, repository=repository, api_url=api_url, token=token,
                consumer_run_id=consumer_run_id, consumer_attempt=consumer_attempt,
                consumer_sha=consumer_sha,
                alert_emitted=os.environ.get("INCIDENT_ALERT_EMITTED", "").casefold() == "true",
                alert_step_outcome=os.environ.get("INCIDENT_ALERT_STEP_OUTCOME", ""),
            )
        except (LivenessAuditError, OSError) as exc:
            print(f"central_health_cadence_finalization_failed:{str(exc)[:160]}", file=sys.stderr)
            return 1
        return 0
    if sys.argv[1:]:
        print("central_health_arguments_invalid", file=sys.stderr)
        return 2
    try:
        result = reconcile_health(
            repository=repository, api_url=api_url, token=token,
            consumer_run_id=consumer_run_id, consumer_attempt=consumer_attempt,
            consumer_sha=consumer_sha,
            triggered_run_id=os.environ.get("TRIGGERED_CENTRAL_RUN_ID", ""),
            triggered_run_attempt=os.environ.get("TRIGGERED_CENTRAL_RUN_ATTEMPT", ""),
            triggered_run_sha=os.environ.get("TRIGGERED_CENTRAL_RUN_SHA", ""),
        )
    except (LivenessAuditError, OSError) as exc:
        result = {
            "schema_version": "incident-reconciliation-v1",
            "consumer_run_id": consumer_run_id[:32],
            "consumer_attempt": consumer_attempt,
            "consumer_sha": consumer_sha[:40],
            "business_status": "unknown",
            "diagnostic_complete": False,
            "incident_handoff_status": "failed",
            "notification_due": False,
            "failure_reason": str(exc)[:160],
            "observed_at": datetime.now(UTC).isoformat(),
        }
        try:
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass
        print(f"central_health_failed:{str(exc)[:160]}", file=sys.stderr)
        return 1
    try:
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        output = os.environ.get("GITHUB_OUTPUT", "")
        if output:
            with open(output, "a", encoding="utf-8") as handle:
                handle.write(f"notification_due={str(result['notification_due']).lower()}\n")
                handle.write(f"health_status={result.get('health_status', 'unknown')}\n")
    except OSError as exc:
        print(f"central_health_result_write_failed:{type(exc).__name__}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
