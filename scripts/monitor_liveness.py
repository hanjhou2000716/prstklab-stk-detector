"""Detect a stalled official-event monitor and keep one issue per incident."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
INCIDENT_MARKER = "official-monitor-incident="
ISSUE_TITLE_PREFIX = "Official event monitor stalled"
INCIDENT_KEY = "official-monitor-stalled:main"
STALE_AFTER = timedelta(minutes=10)
LOOKBACK = timedelta(hours=6)


class LivenessAuditError(RuntimeError):
    """A required GitHub API response could not be trusted."""


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
) -> Any:
    body = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else None
    request = Request(
        f"{api_url.rstrip('/')}/repos/{repository}/{path.lstrip('/')}",
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
        with urlopen(request, timeout=15) as response:
            raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise LivenessAuditError("monitor_liveness_response_too_large")
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"))
    except HTTPError as exc:
        raise LivenessAuditError(f"monitor_liveness_api_http_{exc.code}") from exc
    except (URLError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
        raise LivenessAuditError(f"monitor_liveness_api_{type(exc).__name__}") from exc


def _get_runs(api_url: str, repository: str, token: str) -> list[dict[str, Any]]:
    # The newest 100 runs are a deliberately bounded liveness window. A full
    # history walk is both unnecessary for a ten-minute detector and can turn
    # a high-frequency schedule into an unbounded API audit.
    query = urlencode({"per_page": 100, "branch": "main", "page": 1})
    payload = _request_json(
        api_url, repository, token, "GET",
        f"actions/workflows/official-event-monitor.yml/runs?{query}",
    )
    rows = payload.get("workflow_runs") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise LivenessAuditError("monitor_liveness_runs_response_invalid")
    if any(not isinstance(row, dict) for row in rows):
        raise LivenessAuditError("monitor_liveness_run_row_invalid")
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise LivenessAuditError("monitor_liveness_run_row_invalid")
        run_id = row.get("id")
        if not isinstance(run_id, int) or run_id <= 0:
            raise LivenessAuditError("monitor_liveness_run_identity_invalid")
        if str(row.get("head_branch") or "") == "main":
            result.append(row)
    return result


def _run_has_started_monitor_job(
    api_url: str, repository: str, token: str, run_id: int,
) -> bool:
    payload = _request_json(
        api_url, repository, token, "GET",
        f"actions/runs/{run_id}/jobs?per_page=100",
    )
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list) or payload.get("total_count", len(jobs)) != len(jobs):
        raise LivenessAuditError("monitor_liveness_jobs_response_incomplete")
    matched = [job for job in jobs if isinstance(job, dict) and job.get("name") == "monitor-send-deploy"]
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
        if line.startswith(INCIDENT_MARKER):
            return line[len(INCIDENT_MARKER):].strip()[:80]
    return ""


def _open_incidents(api_url: str, repository: str, token: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in range(1, 11):
        query = urlencode({"state": "open", "per_page": 100, "sort": "created", "direction": "desc", "page": page})
        payload = _request_json(api_url, repository, token, "GET", f"issues?{query}")
        if not isinstance(payload, list):
            raise LivenessAuditError("monitor_liveness_issues_response_invalid")
        if any(not isinstance(row, dict) for row in payload):
            raise LivenessAuditError("monitor_liveness_issue_row_invalid")
        rows.extend(payload)
        if len(payload) < 100:
            break
    else:
        raise LivenessAuditError("monitor_liveness_issues_pagination_limit")
    result = []
    for row in rows:
        if row.get("pull_request"):
            continue
        if str(row.get("title") or "").startswith(ISSUE_TITLE_PREFIX):
            if not isinstance(row.get("number"), int):
                raise LivenessAuditError("monitor_liveness_issue_identity_invalid")
            result.append(row)
    return result


def audit_liveness(
    *, api_url: str, repository: str, token: str, now: datetime | None = None,
) -> dict[str, Any]:
    if not REPOSITORY_RE.fullmatch(repository) or not token:
        raise LivenessAuditError("monitor_liveness_configuration_invalid")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    runs = _get_runs(api_url, repository, token)
    inspected: list[tuple[dict[str, Any], datetime]] = []
    for run in runs[:20]:
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
        if _run_has_started_monitor_job(api_url, repository, token, int(run["id"])):
            started_rows.append((run, created))
        else:
            not_started_rows.append((run, created))
    latest_started_at = max((created for _, created in started_rows), default=None)
    stale_rows = [
        (run, created) for run, created in not_started_rows
        if current - created >= STALE_AFTER
        and (latest_started_at is None or created > latest_started_at)
    ]
    incidents = _open_incidents(api_url, repository, token)
    if not stale_rows:
        closed: list[int] = []
        for issue in incidents:
            number = int(issue["number"])
            _request_json(
                api_url, repository, token, "PATCH", f"issues/{number}",
                {"state": "closed", "state_reason": "completed"},
            )
            closed.append(number)
        return {
            "status": "healthy", "incident_opened": False,
            "incident_active": False, "closed_issue_numbers": closed,
            "latest_started_at": latest_started_at.isoformat() if latest_started_at else "",
            "inspected_run_count": len(inspected),
        }

    oldest_run, oldest_created = min(stale_rows, key=lambda pair: pair[1])
    # One stable key represents a continuous no-start outage, even as GitHub
    # creates or replaces individual queued runs every few minutes.
    incident_key = INCIDENT_KEY
    matching = [issue for issue in incidents if _issue_marker(issue.get("body")) == incident_key]
    if len(matching) > 1:
        raise LivenessAuditError("monitor_liveness_duplicate_incidents")
    incident_opened = not matching
    if incident_opened:
        body = "\n".join((
            f"{INCIDENT_MARKER}{incident_key}",
            "The Gmail sync completed, but no step started in the official event monitor within 10 minutes.",
            f"Stalled run: {int(oldest_run['id'])}",
            f"Run created at: {oldest_created.isoformat()}",
            f"Observed at: {current.isoformat()}",
            "This issue is automatically closed after a monitor step starts again.",
        ))
        created_issue = _request_json(
            api_url, repository, token, "POST", "issues",
            {"title": f"{ISSUE_TITLE_PREFIX} / main", "body": body},
        )
        if not isinstance(created_issue, dict) or not isinstance(created_issue.get("number"), int):
            raise LivenessAuditError("monitor_liveness_issue_create_invalid")
        matching = [created_issue]
    return {
        "status": "stalled", "incident_opened": incident_opened,
        "incident_active": True, "incident_key": incident_key,
        "issue_number": int(matching[0]["number"]),
        "stalled_run_id": int(oldest_run["id"]),
        "stalled_run_created_at": oldest_created.isoformat(),
        "latest_started_at": latest_started_at.isoformat() if latest_started_at else "",
        "inspected_run_count": len(inspected),
    }


def main() -> int:
    try:
        result = audit_liveness(
            api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
            repository=os.environ.get("GITHUB_REPOSITORY", ""),
            token=os.environ.get("GITHUB_TOKEN", ""),
        )
        print(json.dumps(result, separators=(",", ":"), sort_keys=True))
        destination = os.environ.get("GITHUB_OUTPUT", "").strip()
        if destination:
            with open(destination, "a", encoding="utf-8") as handle:
                for key, value in result.items():
                    if isinstance(value, (dict, list)):
                        value = json.dumps(value, separators=(",", ":"), sort_keys=True)
                    handle.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")
        summary = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
        if summary:
            status = "ACTIVE INCIDENT" if result.get("incident_active") else "healthy"
            with open(summary, "a", encoding="utf-8") as handle:
                handle.write(f"\n## Official monitor liveness: {status}\n")
                if result.get("incident_active"):
                    handle.write(
                        f"- Issue: #{result.get('issue_number')}\n"
                        f"- Stalled run: {result.get('stalled_run_id')}\n"
                        f"- Incident opened this run: {str(bool(result.get('incident_opened'))).lower()}\n"
                    )
                else:
                    handle.write("- A monitor step started within the liveness window.\n")
        return 0
    except LivenessAuditError as exc:
        print(f"monitor_liveness_audit_failed:{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
