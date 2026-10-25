"""Detect a stalled official-event monitor and keep one issue per incident."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

from src.github_issue_api import IssuePaginationError, read_open_issues
from src.incident_cadence import can_emit_pending_alert, mark_pending_alert

REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
INCIDENT_MARKER = "official-monitor-incident="
ISSUE_TITLE_PREFIX = "Official event monitor stalled"
INCIDENT_KEY = "official-monitor-stalled:main"
AUDIT_ISSUE_TITLE_PREFIX = "Official monitor liveness audit degraded"
AUDIT_INCIDENT_MARKER = "official-monitor-audit-incident="
EVENT_ISSUE_TITLE_PREFIX = "Official event delivery degraded"
EVENT_INCIDENT_MARKER = "official-event-incident="
STALE_AFTER = timedelta(minutes=10)
LOOKBACK = timedelta(minutes=20)
PAGE_SIZE = 10
MAX_PAGES = 10
MAX_AUDIT_SECONDS = 90
REMINDER_INTERVAL = timedelta(minutes=30)


class LivenessAuditError(RuntimeError):
    """A required GitHub API response could not be trusted."""


class GitHubAPIHttpError(LivenessAuditError):
    """A GitHub HTTP failure with safe request context for durable diagnostics."""

    def __init__(
        self, *, status_code: int, method: str, endpoint_class: str,
        request_id: str, retry_count: int,
    ) -> None:
        self.status_code = status_code
        self.method = method.upper()
        self.endpoint_class = endpoint_class
        self.request_id = request_id
        self.retry_count = retry_count
        super().__init__(f"monitor_liveness_api_http_{status_code}")

    @property
    def handoff_to_health(self) -> bool:
        # A bounded read-side 404 is an operational degradation. The immutable
        # result is handed to the independent health workflow, which owns the
        # first/30-minute/recovery notification cadence.
        return self.method == "GET" and self.status_code == 404

    def diagnostic(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "endpoint_class": self.endpoint_class,
            "http_status": self.status_code,
            "request_id": self.request_id or "unavailable",
            "retry_count": self.retry_count,
        }


def _safe_endpoint_class(url: str, *, api_url: str, repository: str) -> str:
    path = urlsplit(url).path
    api_path = urlsplit(api_url).path.rstrip("/")
    prefix = f"{api_path}/repos/{repository}/".lstrip("/")
    relative = path.lstrip("/")
    if prefix and relative.startswith(prefix):
        relative = relative[len(prefix):]
    elif relative.startswith("repos/"):
        return "repository"
    if re.fullmatch(r"actions/workflows/[^/]+(?:/runs)?", relative):
        return re.sub(r"actions/workflows/[^/]+", "actions/workflows/{workflow}", relative)
    if re.fullmatch(r"actions/runs/\d+(?:/(?:jobs|artifacts))?", relative):
        return re.sub(r"actions/runs/\d+", "actions/runs/{run_id}", relative)
    if re.fullmatch(r"actions/artifacts/\d+/zip", relative):
        return "actions/artifacts/{artifact_id}/zip"
    if re.fullmatch(r"issues(?:/\d+(?:/comments)?)?", relative):
        return re.sub(r"issues/\d+", "issues/{issue_number}", relative)
    return "unclassified"


def _parse_time(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _request_json(
    api_url: str,
    repository: str,
    token: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    response_headers: dict[str, str] | None = None,
    deadline_monotonic: float | None = None,
) -> Any:
    body = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else None
    request_url = (
        path if path.startswith("https://")
        else f"{api_url.rstrip('/')}/repos/{repository}/{path.lstrip('/')}"
    )
    endpoint_class = _safe_endpoint_class(request_url, api_url=api_url, repository=repository)
    for attempt in range(3):
        request = Request(
            request_url,
            data=body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "PRStK-monitor-liveness-audit",
            },
        )
        try:
            remaining = 15.0 if deadline_monotonic is None else deadline_monotonic - time.monotonic()
            if remaining <= 0:
                raise LivenessAuditError("monitor_liveness_audit_deadline_exceeded")
            with urlopen(request, timeout=min(15.0, remaining)) as response:
                if response_headers is not None:
                    response_headers["link"] = str(response.headers.get("Link") or "")
                raw = response.read(1_000_001)
                if len(raw) > 1_000_000:
                    raise LivenessAuditError("monitor_liveness_response_too_large")
                if not raw:
                    return None
                return json.loads(raw.decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 404 and method.upper() == "GET" and attempt < 2:
                remaining = 15.0 if deadline_monotonic is None else deadline_monotonic - time.monotonic()
                delay = min(float(2 ** attempt), max(0.0, remaining))
                exc.close()
                if delay > 0:
                    time.sleep(delay)
                    continue
            raw_request_id = str(exc.headers.get("X-GitHub-Request-Id") or "") if exc.headers else ""
            request_id = raw_request_id if re.fullmatch(r"[A-Za-z0-9:-]{1,100}", raw_request_id) else ""
            raise GitHubAPIHttpError(
                status_code=exc.code,
                method=method,
                endpoint_class=endpoint_class,
                request_id=request_id,
                retry_count=attempt + 1,
            ) from exc
        except (URLError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
            raise LivenessAuditError(f"monitor_liveness_api_{type(exc).__name__}") from exc
    raise LivenessAuditError("monitor_liveness_api_retry_exhausted")


def _next_link(
    link_header: str,
    *,
    api_url: str,
    expected_path: str | tuple[str, ...],
    expected_page: int,
    per_page: int = PAGE_SIZE,
    expected_query: Mapping[str, str | list[str]] | None = None,
) -> str | None:
    matches = re.findall(r"<([^>]+)>\s*;\s*rel=\"([^\"]+)\"", link_header)
    next_urls = [url for url, relation in matches if relation == "next"]
    if not next_urls:
        return None
    if len(next_urls) != 1:
        raise LivenessAuditError("monitor_liveness_pagination_ambiguous")
    url = next_urls[0]
    parsed = urlsplit(url)
    api = urlsplit(api_url)
    paths = (expected_path,) if isinstance(expected_path, str) else expected_path
    if (
        parsed.scheme.casefold() != "https"
        or parsed.netloc.casefold() != api.netloc.casefold()
        or parsed.path not in paths
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        safe_path = re.sub(r"[^A-Za-z0-9_./-]", "?", parsed.path)[:180]
        safe_host = re.sub(r"[^A-Za-z0-9.:-]", "?", parsed.netloc)[:100]
        raise LivenessAuditError(
            "monitor_liveness_pagination_identity_invalid:"
            f"host={safe_host};path={safe_path}"
        )
    query = parse_qs(parsed.query, keep_blank_values=True)
    expected = {
        key: [values] if isinstance(values, str) else list(values)
        for key, values in (expected_query or {}).items()
    }
    expected.update({"page": [str(expected_page)], "per_page": [str(per_page)]})
    if query != expected:
        raise LivenessAuditError(
            "monitor_liveness_pagination_query_invalid:"
            f"keys={','.join(sorted(query))[:160]}"
        )
    return url


def _get_runs(
    api_url: str, repository: str, token: str, *, deadline_monotonic: float,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    paths = (
        f"/repos/{repository}/actions/workflows/official-event-monitor.yml/runs",
        f"/repos/{repository}/actions/workflows/320209983/runs",
    )
    cutoff = (now or datetime.now(UTC)).astimezone(UTC) - LOOKBACK
    created_filter = f">={cutoff.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    filters = {"branch": "main", "created": created_filter}
    query = urlencode({"per_page": PAGE_SIZE, **filters, "page": 1})
    request_path = f"actions/workflows/official-event-monitor.yml/runs?{query}"
    result: list[dict[str, Any]] = []
    for page in range(1, MAX_PAGES + 1):
        headers: dict[str, str] = {}
        payload = _request_json(
            api_url, repository, token, "GET", request_path,
            response_headers=headers, deadline_monotonic=deadline_monotonic,
        )
        rows = payload.get("workflow_runs") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise LivenessAuditError("monitor_liveness_runs_response_invalid")
        for row in rows:
            run_id = row.get("id")
            if not isinstance(run_id, int) or run_id <= 0:
                raise LivenessAuditError("monitor_liveness_run_identity_invalid")
            created_at = _parse_time(row.get("created_at"))
            if created_at is None:
                raise LivenessAuditError("monitor_liveness_run_created_at_invalid")
            if (
                str(row.get("head_branch") or "") == "main"
                and created_at >= cutoff
            ):
                result.append(row)
        total = payload.get("total_count", len(rows))
        if not isinstance(total, int) or total < len(rows):
            raise LivenessAuditError("monitor_liveness_runs_total_count_invalid")
        next_url = _next_link(
            headers.get("link", ""), api_url=api_url, expected_path=paths,
            expected_page=page + 1,
            expected_query={key: [value] for key, value in filters.items()},
        )
        if next_url is None:
            if page * PAGE_SIZE < total:
                raise LivenessAuditError("monitor_liveness_runs_pagination_incomplete")
            return result
        if page == MAX_PAGES:
            raise LivenessAuditError("monitor_liveness_runs_pagination_limit")
        request_path = next_url
    raise LivenessAuditError("monitor_liveness_runs_pagination_limit")


def _run_has_started_monitor_job(
    api_url: str, repository: str, token: str, run_id: int, *, deadline_monotonic: float,
) -> bool:
    path = f"/repos/{repository}/actions/runs/{run_id}/jobs"
    request_path = f"actions/runs/{run_id}/jobs?{urlencode({'per_page': PAGE_SIZE, 'page': 1})}"
    jobs: list[dict[str, Any]] = []
    for page in range(1, MAX_PAGES + 1):
        headers: dict[str, str] = {}
        payload = _request_json(
            api_url, repository, token, "GET", request_path,
            response_headers=headers, deadline_monotonic=deadline_monotonic,
        )
        rows = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise LivenessAuditError("monitor_liveness_jobs_response_incomplete")
        jobs.extend(rows)
        total = payload.get("total_count", len(rows))
        if not isinstance(total, int) or total < len(jobs):
            raise LivenessAuditError("monitor_liveness_jobs_response_incomplete")
        next_url = _next_link(
            headers.get("link", ""), api_url=api_url, expected_path=path,
            expected_page=page + 1,
        )
        if next_url is None:
            if len(jobs) != total:
                raise LivenessAuditError("monitor_liveness_jobs_response_incomplete")
            break
        if page == MAX_PAGES:
            raise LivenessAuditError("monitor_liveness_jobs_pagination_limit")
        request_path = next_url
    else:
        raise LivenessAuditError("monitor_liveness_jobs_pagination_limit")
    matched = [job for job in jobs if job.get("name") == "monitor-send-deploy"]
    if len(matched) > 1:
        raise LivenessAuditError("monitor_liveness_job_identity_ambiguous")
    if not matched:
        # The run may be newly created and its job list has not propagated yet.
        return False
    job = matched[0]
    steps = job.get("steps")
    if not isinstance(steps, list):
        raise LivenessAuditError("monitor_liveness_job_steps_missing")
    # GitHub can fill run_started_at/job.started_at while the job is still
    # waiting for a runner. Only a started workflow step proves execution.
    return any(isinstance(step, dict) and _parse_time(step.get("started_at")) for step in steps)


def _issue_marker(body: object) -> str:
    for line in str(body or "").splitlines():
        for marker in (INCIDENT_MARKER, AUDIT_INCIDENT_MARKER):
            if line.startswith(marker):
                return line[len(marker):].strip()[:160]
    return ""


def _issue_timestamp(body: object, label: str) -> datetime | None:
    prefix = f"{label}:"
    for line in str(body or "").splitlines():
        if line.startswith(prefix):
            return _parse_time(line[len(prefix):].strip())
    return None


def _issue_field(body: object, label: str) -> str:
    prefix = f"{label}:"
    for line in str(body or "").splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def _updated_incident_body(
    issue: dict[str, Any], *, observed_at: datetime, next_reminder_at: datetime | None,
    recovered_at: datetime | None = None,
) -> str:
    dynamic = ("Last reminder at:", "Next reminder at:", "Recovered at:")
    lines = [
        line for line in str(issue.get("body") or "").splitlines()
        if not line.startswith(dynamic)
    ]
    if recovered_at is not None:
        lines.append(f"Recovered at: {recovered_at.isoformat()}")
    else:
        lines.append(f"Last reminder at: {observed_at.isoformat()}")
        if next_reminder_at is not None:
            lines.append(f"Next reminder at: {next_reminder_at.isoformat()}")
    return "\n".join(lines)[:12000]


def _pending_alert_consumer() -> str:
    run_id = str(os.environ.get("GITHUB_RUN_ID") or "").strip()
    attempt = str(os.environ.get("GITHUB_RUN_ATTEMPT") or "").strip()
    return f"{run_id}/{attempt}" if run_id and attempt else "local"


def _mark_alert_pending(body: str, consumer: str, now: datetime) -> str:
    return mark_pending_alert(body, consumer, now)


def _open_incidents(api_url: str, repository: str, token: str, *, deadline_monotonic: float) -> list[dict[str, Any]]:
    try:
        rows = read_open_issues(
            api_url=api_url,
            repository=repository,
            token=token,
            fetch_json=_request_json,
            deadline_monotonic=deadline_monotonic,
            repository_id=_positive_repo_id(os.environ.get("GITHUB_REPOSITORY_ID")),
        )
    except IssuePaginationError as exc:
        raise LivenessAuditError(
            f"monitor_liveness_{str(exc).replace('issues_', 'issues_')}"
        ) from exc
    result = []
    for row in rows:
        if row.get("pull_request"):
            continue
        if str(row.get("title") or "").startswith((
            ISSUE_TITLE_PREFIX, AUDIT_ISSUE_TITLE_PREFIX, EVENT_ISSUE_TITLE_PREFIX,
            "Scheduled market brief delivery degraded",
            "Unified research report degraded",
            "Central incident reconciliation degraded",
        )):
            if not isinstance(row.get("number"), int):
                raise LivenessAuditError("monitor_liveness_issue_identity_invalid")
            result.append(row)
    return result


def _positive_repo_id(value: object) -> int | None:
    try:
        parsed = int(str(value or ""))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def audit_liveness(
    *, api_url: str, repository: str, token: str, now: datetime | None = None,
    defer_notification_cadence: bool = False, deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    if not REPOSITORY_RE.fullmatch(repository) or not token:
        raise LivenessAuditError("monitor_liveness_configuration_invalid")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    deadline_monotonic = deadline_monotonic or time.monotonic() + MAX_AUDIT_SECONDS
    runs = _get_runs(
        api_url, repository, token,
        deadline_monotonic=deadline_monotonic, now=current,
    )
    inspected: list[tuple[dict[str, Any], datetime]] = []
    # _get_runs already restricts this complete, bounded collection to the
    # fixed twenty-minute window. Do not silently drop page three onward.
    for run in runs:
        created = _parse_time(run.get("created_at"))
        if created is None:
            raise LivenessAuditError("monitor_liveness_run_created_at_invalid")
        if current - created > LOOKBACK:
            continue
        inspected.append((run, created))
    if not inspected:
        raise LivenessAuditError("monitor_liveness_no_recent_runs")

    started_rows: list[tuple[dict[str, Any], datetime]] = []
    not_started_rows: list[tuple[dict[str, Any], datetime]] = []
    for run, created in inspected:
        if _run_has_started_monitor_job(
            api_url, repository, token, int(run["id"]), deadline_monotonic=deadline_monotonic,
        ):
            started_rows.append((run, created))
        else:
            not_started_rows.append((run, created))
    latest_started_at = max((created for _, created in started_rows), default=None)
    stale_rows = [
        (run, created) for run, created in not_started_rows
        if current - created >= STALE_AFTER
        and (latest_started_at is None or created > latest_started_at)
    ]
    incidents = _open_incidents(api_url, repository, token, deadline_monotonic=deadline_monotonic)
    stall_incidents = [
        issue for issue in incidents
        if str(issue.get("title") or "").startswith(ISSUE_TITLE_PREFIX)
    ]
    audit_incidents = [
        issue for issue in incidents
        if str(issue.get("title") or "").startswith(AUDIT_ISSUE_TITLE_PREFIX)
    ]
    recovered_audit_incidents: list[int] = []
    for issue in audit_incidents:
        number = int(issue["number"])
        _request_json(
            api_url, repository, token, "POST", f"issues/{number}/comments",
            {"body": f"Liveness audit recovered at {current.isoformat()}; a complete identity-verified audit succeeded."},
            deadline_monotonic=deadline_monotonic,
        )
        body = _updated_incident_body(issue, observed_at=current, next_reminder_at=None, recovered_at=current)
        _request_json(
            api_url, repository, token, "PATCH", f"issues/{number}",
            {"state": "closed", "state_reason": "completed", "body": body},
            deadline_monotonic=deadline_monotonic,
        )
        recovered_audit_incidents.append(number)
    if not stale_rows:
        closed: list[int] = []
        for issue in stall_incidents:
            number = int(issue["number"])
            _request_json(
                api_url, repository, token, "POST", f"issues/{number}/comments",
                {"body": f"Monitor recovery verified at {current.isoformat()}; a real monitor step has started."},
                deadline_monotonic=deadline_monotonic,
            )
            body = _updated_incident_body(issue, observed_at=current, next_reminder_at=None, recovered_at=current)
            _request_json(
                api_url, repository, token, "PATCH", f"issues/{number}",
                {"state": "closed", "state_reason": "completed", "body": body},
                deadline_monotonic=deadline_monotonic,
            )
            closed.append(number)
        return {
            "status": "healthy", "incident_opened": False,
            "incident_active": False, "incident_recovered": bool(closed), "closed_issue_numbers": closed,
            "audit_incident_recovered": recovered_audit_incidents,
            "notification_cadence_confirmations": [],
            "latest_started_at": latest_started_at.isoformat() if latest_started_at else "",
            "inspected_run_count": len(inspected),
        }

    oldest_run, oldest_created = min(stale_rows, key=lambda pair: pair[1])
    # One stable key represents a continuous no-start outage, even as GitHub
    # creates or replaces individual queued runs every few minutes.
    incident_key = INCIDENT_KEY
    pending_consumer = _pending_alert_consumer()
    matching = [issue for issue in stall_incidents if _issue_marker(issue.get("body")) == incident_key]
    if len(matching) > 1:
        raise LivenessAuditError("monitor_liveness_duplicate_incidents")
    incident_opened = not matching
    cadence_confirmations: list[dict[str, str | int]] = []
    if incident_opened:
        body = "\n".join((
            f"{INCIDENT_MARKER}{incident_key}",
            "The Gmail sync completed, but no step started in the official event monitor within 10 minutes.",
            f"Stalled run: {int(oldest_run['id'])}",
            f"Run created at: {oldest_created.isoformat()}",
            f"Observed at: {current.isoformat()}",
            f"Next reminder at: {(current if defer_notification_cadence else current + REMINDER_INTERVAL).isoformat()}",
            "This issue is automatically closed after a monitor step starts again.",
        ))
        if defer_notification_cadence:
            body = _mark_alert_pending(body, pending_consumer, current)
        created_issue = _request_json(
            api_url, repository, token, "POST", "issues",
            {"title": f"{ISSUE_TITLE_PREFIX} / main", "body": body},
            deadline_monotonic=deadline_monotonic,
        )
        if not isinstance(created_issue, dict) or not isinstance(created_issue.get("number"), int):
            raise LivenessAuditError("monitor_liveness_issue_create_invalid")
        matching = [created_issue]
        reminder_sent = False
        if defer_notification_cadence:
            cadence_confirmations.append({
                "issue_number": created_issue["number"],
                "marker": f"{INCIDENT_MARKER}{incident_key}",
                "next_reminder_at": (current + REMINDER_INTERVAL).isoformat(),
            })
    else:
        issue = matching[0]
        next_reminder_at = _issue_timestamp(issue.get("body"), "Next reminder at")
        reminder_sent = next_reminder_at is None or current >= next_reminder_at
        pending_current = (
            defer_notification_cadence
            and _issue_field(issue.get("body"), "Alert pending consumer") == pending_consumer
        )
        notify_due = reminder_sent and (
            not defer_notification_cadence
            or can_emit_pending_alert(issue.get("body"), pending_consumer, current)
        )
        if notify_due and not pending_current:
            scheduled_next = (
                (next_reminder_at or current)
                if defer_notification_cadence
                else current + REMINDER_INTERVAL
            )
            updated_body = _updated_incident_body(
                issue, observed_at=current, next_reminder_at=scheduled_next,
            )
            if defer_notification_cadence:
                updated_body = _mark_alert_pending(updated_body, pending_consumer, current)
            _request_json(
                api_url, repository, token, "PATCH", f"issues/{int(issue['number'])}",
                {"body": updated_body}, deadline_monotonic=deadline_monotonic,
            )
            _request_json(
                api_url, repository, token, "POST", f"issues/{int(issue['number'])}/comments",
                {"body": (
                    f"Still stalled: run {int(oldest_run['id'])} was created at "
                    f"{oldest_created.isoformat()}; no official monitor step has started. "
                    f"Checked at {current.isoformat()}. Next reminder is scheduled in 30 minutes."
                )},
                deadline_monotonic=deadline_monotonic,
            )
            if defer_notification_cadence:
                cadence_confirmations.append({
                    "issue_number": int(issue["number"]),
                    "marker": f"{INCIDENT_MARKER}{incident_key}",
                    "next_reminder_at": (current + REMINDER_INTERVAL).isoformat(),
                })
        elif defer_notification_cadence:
            reminder_sent = False
    return {
        "status": "stalled", "incident_opened": incident_opened,
        "incident_active": True, "incident_key": incident_key, "reminder_sent": reminder_sent,
        "issue_number": int(matching[0]["number"]),
        "stalled_run_id": int(oldest_run["id"]),
        "stalled_run_created_at": oldest_created.isoformat(),
        "audit_incident_recovered": recovered_audit_incidents,
        "notification_cadence_confirmations": cadence_confirmations,
        "latest_started_at": latest_started_at.isoformat() if latest_started_at else "",
        "inspected_run_count": len(inspected),
    }


def reconcile_audit_failure_incident(
    *, api_url: str, repository: str, token: str, reason: str,
    now: datetime | None = None, defer_notification_cadence: bool = False,
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    if not REPOSITORY_RE.fullmatch(repository) or not token:
        raise LivenessAuditError("monitor_liveness_configuration_invalid")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    deadline = deadline_monotonic or time.monotonic() + MAX_AUDIT_SECONDS
    incidents = _open_incidents(
        api_url, repository, token, deadline_monotonic=deadline,
    )
    incident_key = f"official-monitor-audit:{reason[:100]}"
    matching = [
        issue for issue in incidents
        if str(issue.get("title") or "").startswith(AUDIT_ISSUE_TITLE_PREFIX)
        and _issue_marker(issue.get("body")) == incident_key
    ]
    if len(matching) > 1:
        raise LivenessAuditError("monitor_liveness_duplicate_audit_incidents")
    cadence_confirmations: list[dict[str, str | int]] = []
    if not matching:
        issue_body = "\n".join((
            f"{AUDIT_INCIDENT_MARKER}{incident_key}",
            "The monitor liveness audit could not complete a trustworthy read.",
            f"Failure class: {reason[:160]}",
            f"Observed at: {current.isoformat()}",
            f"Next reminder at: {(current if defer_notification_cadence else current + REMINDER_INTERVAL).isoformat()}",
            "This incident is closed automatically after a complete audit succeeds.",
        ))
        pending_consumer = _pending_alert_consumer()
        if defer_notification_cadence:
            issue_body = _mark_alert_pending(issue_body, pending_consumer, current)
        issue = _request_json(
            api_url, repository, token, "POST", "issues",
            {"title": f"{AUDIT_ISSUE_TITLE_PREFIX} / main", "body": issue_body},
            deadline_monotonic=deadline,
        )
        if not isinstance(issue, dict) or not isinstance(issue.get("number"), int):
            raise LivenessAuditError("monitor_liveness_audit_issue_create_invalid")
        if defer_notification_cadence:
            cadence_confirmations.append({
                "issue_number": issue["number"],
                "marker": f"{AUDIT_INCIDENT_MARKER}{incident_key}",
                "next_reminder_at": (current + REMINDER_INTERVAL).isoformat(),
            })
        return {
            "status": "degraded", "diagnostic_complete": False,
            "incident_active": True, "incident_opened": True,
            "incident_key": incident_key, "issue_number": issue["number"],
            "reason": reason[:160], "observed_at": current.isoformat(),
            "reminder_sent": False,
            "notification_cadence_confirmations": cadence_confirmations,
        }

    issue = matching[0]
    number = issue.get("number")
    if not isinstance(number, int):
        raise LivenessAuditError("monitor_liveness_audit_issue_identity_invalid")
    due = _issue_timestamp(issue.get("body"), "Next reminder at")
    reminder_sent = due is None or current >= due
    pending_consumer = _pending_alert_consumer()
    pending_current = (
        defer_notification_cadence
        and _issue_field(issue.get("body"), "Alert pending consumer") == pending_consumer
    )
    notify_due = reminder_sent and (
        not defer_notification_cadence
        or can_emit_pending_alert(issue.get("body"), pending_consumer, current)
    )
    if notify_due and not pending_current:
        next_reminder = (
            (due or current) if defer_notification_cadence
            else current + REMINDER_INTERVAL
        )
        body = _updated_incident_body(
            issue, observed_at=current, next_reminder_at=next_reminder,
        )
        if defer_notification_cadence:
            body = _mark_alert_pending(body, pending_consumer, current)
        _request_json(
            api_url, repository, token, "PATCH", f"issues/{number}",
            {"body": body}, deadline_monotonic=deadline,
        )
        _request_json(
            api_url, repository, token, "POST", f"issues/{number}/comments",
            {"body": f"The liveness audit remains incomplete ({reason[:120]}). Checked at {current.isoformat()}; next reminder in 30 minutes."},
            deadline_monotonic=deadline,
        )
        if defer_notification_cadence:
            cadence_confirmations.append({
                "issue_number": number,
                "marker": f"{AUDIT_INCIDENT_MARKER}{incident_key}",
                "next_reminder_at": (current + REMINDER_INTERVAL).isoformat(),
            })
    elif defer_notification_cadence:
        reminder_sent = False
    return {
        "status": "degraded", "diagnostic_complete": False,
        "incident_active": True, "incident_opened": False,
        "incident_key": incident_key, "issue_number": number,
        "reason": reason[:160], "observed_at": current.isoformat(),
        "reminder_sent": reminder_sent,
        "notification_cadence_confirmations": cadence_confirmations,
    }


def main() -> int:
    destination = os.environ.get("MONITOR_LIVENESS_RESULT_PATH", "official-monitor-liveness.json").strip()

    def save_result(result: dict[str, Any]) -> bool:
        if not destination:
            return False
        try:
            output_path = os.path.abspath(destination)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            temporary = output_path + ".tmp"
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(result, handle, separators=(",", ":"), sort_keys=True)
                handle.write("\n")
            os.replace(temporary, output_path)
            return True
        except OSError as exc:
            print(f"monitor_liveness_result_write_failed:{type(exc).__name__}", file=sys.stderr)
            return False

    def publish_result(result: dict[str, Any]) -> bool:
        print(json.dumps(result, separators=(",", ":"), sort_keys=True))
        output_path = os.environ.get("GITHUB_OUTPUT", "").strip()
        if output_path:
            with open(output_path, "a", encoding="utf-8") as handle:
                for key, value in result.items():
                    if isinstance(value, (dict, list)):
                        value = json.dumps(value, separators=(",", ":"), sort_keys=True)
                    handle.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
        if summary_path:
            incident_state = "DEGRADED INCIDENT" if result.get("incident_active") else "healthy"
            with open(summary_path, "a", encoding="utf-8") as handle:
                handle.write(f"\n## Official monitor liveness: {incident_state}\n")
                if result.get("incident_active"):
                    handle.write(f"- Issue: #{result.get('issue_number')}\n")
                    handle.write(f"- Incident opened this run: {str(bool(result.get('incident_opened'))).lower()}\n")
                    if result.get("stalled_run_id"):
                        handle.write(f"- Stalled run: {result.get('stalled_run_id')}\n")
                    if result.get("reason"):
                        handle.write(f"- Diagnostic reason: {result.get('reason')}\n")
                else:
                    handle.write("- Monitor execution state was audited successfully.\n")
        return True

    def record_audit_failure(reason: str) -> dict[str, Any]:
        return reconcile_audit_failure_incident(
            api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
            repository=os.environ.get("GITHUB_REPOSITORY", ""),
            token=os.environ.get("GITHUB_TOKEN", ""),
            reason=reason,
        )

    try:
        result = audit_liveness(
            api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
            repository=os.environ.get("GITHUB_REPOSITORY", ""),
            token=os.environ.get("GITHUB_TOKEN", ""),
        )
        result = {"schema_version": "official-monitor-liveness-v1", **result}
        if not save_result(result):
            return 1
        publish_result(result)
        return 0
    except LivenessAuditError as exc:
        try:
            result = record_audit_failure(str(exc))
        except LivenessAuditError as incident_exc:
            result = {
                "schema_version": "official-monitor-liveness-v1",
                "status": "error", "reason": str(exc)[:160],
                "incident_persistence_reason": str(incident_exc)[:160],
                "evidence_complete": False, "observed_at": datetime.now(UTC).isoformat(),
            }
            save_result(result)
            print(f"monitor_liveness_audit_failed:{exc}; incident_persistence_failed:{incident_exc}", file=sys.stderr)
            return 1
        result = {"schema_version": "official-monitor-liveness-v1", **result}
        if not save_result(result):
            return 1
        publish_result(result)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
