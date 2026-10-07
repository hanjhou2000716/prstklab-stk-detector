"""Serialize production data writers without GitHub's one-pending-run trap.

GitHub Actions concurrency keeps one running and one pending run per group;
when a third run arrives it replaces the pending run.  Production refreshes
therefore use a unique concurrency key and this bounded GitHub-run queue to
wait for older writer runs before touching ``data-release``.  The queue is
fail-closed: an unavailable Actions API never permits a concurrent publish.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

# The run name is user-configurable (`run-name:`) and scheduled-brief uses it
# to include the slot. Identify writers by the immutable workflow path and ID
# returned by GitHub's Actions API instead.
WRITER_WORKFLOW_IDENTITIES = {
    ".github/workflows/scheduled-brief.yml": 318853044,
    ".github/workflows/emergency-alert.yml": 319337480,
    ".github/workflows/refresh-dashboard.yml": 318848659,
    ".github/workflows/monitor-health.yml": 326066489,
    ".github/workflows/official-event-monitor.yml": 320209983,
    ".github/workflows/unified-research-report.yml": 319283753,
    # Static Pages publishers share the same fence because they can replace
    # the public site while a release gate is reading it.
    ".github/workflows/deploy-pages.yml": 318841880,
}
# A run holds the shared publication queue only after this exact job reaches
# its publication gate. Keep job and step names beside the immutable workflow
# identity so a newly added publisher cannot silently escape serialization.
WRITER_QUEUE_GATES = {
    ".github/workflows/scheduled-brief.yml": {
        "workflow_id": 318853044,
        "job_name": "refresh-notify-deploy",
        "step_name": "Wait for production writer queue",
    },
    ".github/workflows/emergency-alert.yml": {
        "workflow_id": 319337480,
        "job_name": "send-emergency-alert",
        "step_name": "Wait for production writer queue",
    },
    ".github/workflows/refresh-dashboard.yml": {
        "workflow_id": 318848659,
        "job_name": "refresh-and-deploy",
        "step_name": "Wait for production writer queue",
    },
    ".github/workflows/monitor-health.yml": {
        "workflow_id": 326066489,
        "job_name": "publish-monitor-health",
        "step_name": "Wait for production writer queue",
    },
    ".github/workflows/official-event-monitor.yml": {
        "workflow_id": 320209983,
        "job_name": "monitor-send-deploy",
        "step_name": "Wait for production writer queue",
    },
    ".github/workflows/unified-research-report.yml": {
        "workflow_id": 319283753,
        "job_name": "build-and-deploy",
        "step_name": "Recheck production revision before persistence",
    },
    ".github/workflows/deploy-pages.yml": {
        "workflow_id": 318841880,
        "job_name": "deploy",
        "step_name": "Wait for the production writer queue",
    },
}


def publication_gate_contract_fingerprint(path: str, gate: Mapping[str, object]) -> str:
    """Fingerprint the immutable gate identity; the run SHA identifies its workflow revision."""
    canonical = "\n".join((
        "writer-publication-gate-v1",
        path,
        str(gate.get("workflow_id") or ""),
        str(gate.get("job_name") or ""),
        str(gate.get("step_name") or ""),
    ))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_WRITER_WORKFLOW_PATH_BY_ID = {value: key for key, value in WRITER_WORKFLOW_IDENTITIES.items()}
ACTIVE_STATUSES = frozenset({"queued", "in_progress", "waiting", "pending", "requested"})
_RUNS_PER_PAGE = 100
_MAX_RUN_PAGES_PER_STATUS = 100


def _next_jobs_page_url(
    link_header: str | None,
    *,
    api_url: str,
    repository: str,
    run_id: int,
    attempt: int,
    current_page: int,
) -> str | None:
    """Validate a jobs endpoint pagination link before following it."""
    next_links = _extract_next_links(link_header, error_prefix="writer_queue_jobs_pagination")
    if not next_links:
        return None
    if len(next_links) != 1:
        raise WriterQueueError("writer_queue_jobs_pagination_ambiguous")
    next_url = next_links[0]
    parsed = urlsplit(next_url)
    api = urlsplit(api_url)
    expected_path = (
        f"{api.path.rstrip('/')}/repos/{repository}/actions/runs/"
        f"{run_id}/attempts/{attempt}/jobs"
    )
    if (
        parsed.scheme.casefold() != api.scheme.casefold()
        or parsed.netloc.casefold() != api.netloc.casefold()
        or parsed.path != expected_path
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise WriterQueueError("writer_queue_jobs_pagination_identity_invalid")
    try:
        query = parse_qs(parsed.query, strict_parsing=True, keep_blank_values=True)
        if (
            set(query) != {"per_page", "page"}
            or query["per_page"] != [str(_RUNS_PER_PAGE)]
            or query["page"] != [str(current_page + 1)]
        ):
            raise ValueError("unexpected jobs page query")
    except ValueError:
        raise WriterQueueError("writer_queue_jobs_pagination_query_invalid") from None
    return next_url


def _next_page_url(
    link_header: str | None,
    *,
    api_url: str,
    repository: str,
    status: str,
    current_page: int,
) -> str | None:
    """Return GitHub's next-page URL after validating its API identity."""
    next_links = _extract_next_links(link_header, error_prefix="writer_queue_pagination")
    if not next_links:
        return None
    if len(next_links) != 1:
        raise WriterQueueError("GitHub Actions queue pagination link is ambiguous")

    next_url = next_links[0]
    parsed = urlsplit(next_url)
    api = urlsplit(api_url)
    expected_path = f"{api.path.rstrip('/')}/repos/{repository}/actions/runs"
    if (
        parsed.scheme.casefold() != api.scheme.casefold()
        or parsed.netloc.casefold() != api.netloc.casefold()
        or parsed.path != expected_path
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise WriterQueueError("GitHub Actions queue pagination link identity invalid")

    try:
        query = parse_qs(parsed.query, strict_parsing=True, keep_blank_values=True)
        if (
            set(query) != {"per_page", "status", "page"}
            or query["per_page"] != [str(_RUNS_PER_PAGE)]
            or query["status"] != [status]
            or query["page"] != [str(current_page + 1)]
        ):
            raise ValueError("unexpected page query")
    except ValueError:
        raise WriterQueueError("GitHub Actions queue pagination link query invalid") from None
    return next_url


def _extract_next_links(link_header: str | None, *, error_prefix: str) -> list[str]:
    """Parse every Link entry strictly so malformed pagination cannot look complete."""
    if not link_header:
        return []
    next_links: list[str] = []
    for entry in link_header.split(","):
        match = re.fullmatch(
            r'\s*<([^<>]+)>\s*;\s*rel="([^"]+)"(?:\s*;\s*[A-Za-z0-9_-]+="[^"]*")*\s*',
            entry,
        )
        if not match:
            raise WriterQueueError(f"{error_prefix}_link_invalid")
        if "next" in match.group(2).split():
            next_links.append(match.group(1))
    if len(next_links) > 1:
        raise WriterQueueError(f"{error_prefix}_link_ambiguous")
    return next_links


class WriterQueueError(RuntimeError):
    """Raised when the production writer queue cannot be established."""


class WriterQueueTimeout(WriterQueueError):
    """A bounded queue wait ended while verified publication blockers remained."""

    def __init__(
        self,
        blockers: Iterable[int],
        waited_seconds: int,
        complete_snapshots: int,
        *,
        recovery_rounds: int = 0,
        deferred_candidates: Iterable[Mapping[str, object]] = (),
        blocker_details: Iterable[Mapping[str, object]] = (),
    ) -> None:
        self.blockers = tuple(sorted({int(value) for value in blockers}))
        self.waited_seconds = max(0, int(waited_seconds))
        self.complete_snapshots = max(0, int(complete_snapshots))
        self.recovery_rounds = max(0, int(recovery_rounds))
        self.deferred_candidates = tuple(dict(row) for row in deferred_candidates)
        self.blocker_details = tuple(dict(row) for row in blocker_details)
        super().__init__(
            "writer queue timed out; active blockers="
            f"{','.join(map(str, self.blockers))}; waited_seconds={self.waited_seconds}; "
            f"complete_snapshots={self.complete_snapshots}; recovery_rounds={self.recovery_rounds}; "
            f"deferred_candidates={len(self.deferred_candidates)}; reason=writer_queue_timeout"
        )


class RetryableQueueSnapshotError(WriterQueueError):
    """A complete queue snapshot could not be read consistently; restart at page one."""


class QueueRuns(list[dict[str, object]]):
    """A complete queue snapshot with bounded recovery diagnostics."""

    def __init__(
        self,
        values: Iterable[dict[str, object]] = (),
        *,
        recovery_rounds: int = 0,
        deferred_candidates: Iterable[dict[str, object]] = (),
    ) -> None:
        super().__init__(values)
        self.recovery_rounds = recovery_rounds
        self.deferred_candidates = tuple(dict(row) for row in deferred_candidates)


@dataclass(frozen=True)
class QueueResult:
    waited_seconds: int
    checks: int
    blockers: tuple[int, ...]
    status: str = "acquired"
    reason: str = "queue_acquired"
    run_sha: str = ""
    main_sha: str = ""
    recovery_rounds: int = 0
    complete_snapshots: int = 0
    verified_blockers: tuple[int, ...] = ()
    deferred_candidates: tuple[int, ...] = ()
    admission_at: str = ""
    deferred_candidate_reasons: tuple[str, ...] = ()
    deferred_candidate_details: tuple[dict[str, object], ...] = ()
    queue_budget_seconds: int = 0
    remaining_seconds: int = 0


def _timestamp(run: Mapping[str, object], field: str) -> datetime | None:
    value = run.get(field)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _attempt_started(run: Mapping[str, object]) -> datetime | None:
    """Return the actual publication-gate entry time when available."""
    return _timestamp(run, "queue_gate_started_at") or _timestamp(run, "run_started_at") or _timestamp(run, "created_at")


def _run_id(run: Mapping[str, object]) -> int | None:
    try:
        return int(str(run.get("id") or ""))
    except (TypeError, ValueError):
        return None


def _workflow_identity(run: Mapping[str, object]) -> bool:
    """Validate a GitHub run's immutable workflow path/ID pair."""
    path = str(run.get("path") or "").strip()
    raw_id = run.get("workflow_id")
    try:
        workflow_id = int(str(raw_id))
    except (TypeError, ValueError):
        workflow_id = None
    expected_id = WRITER_WORKFLOW_IDENTITIES.get(path)
    expected_path = _WRITER_WORKFLOW_PATH_BY_ID.get(workflow_id) if workflow_id is not None else None
    if expected_id is not None and workflow_id != expected_id:
        raise WriterQueueError("writer_workflow_identity_mismatch")
    if expected_path is not None and path != expected_path:
        raise WriterQueueError("writer_workflow_identity_mismatch")
    return expected_id is not None and workflow_id == expected_id


def blocking_runs(
    runs: Iterable[Mapping[str, object]],
    *,
    current_run_id: int,
    current_created_at: datetime | None = None,
    current_attempt_started_at: datetime | None = None,
    ignored_run_ids: Iterable[int] = (),
) -> list[dict[str, object]]:
    """Return older active production writers in publication-gate FIFO order."""
    ignored = {int(value) for value in ignored_run_ids}
    blockers: list[dict[str, object]] = []
    current_rows: list[Mapping[str, object]] = []
    candidates: list[Mapping[str, object]] = []
    for run in runs:
        if not isinstance(run, Mapping):
            continue
        run_id = _run_id(run)
        if run_id is None:
            continue
        if not _workflow_identity(run):
            continue
        if str(run.get("status") or "").casefold() not in ACTIVE_STATUSES:
            continue
        if run_id == current_run_id:
            current_rows.append(run)
            continue
        if run_id in ignored:
            continue
        candidates.append(run)

    if len(current_rows) > 1:
        attempts = {str(row.get("run_attempt") or "") for row in current_rows}
        if len(attempts) > 1:
            raise WriterQueueError("current_run_attempt_identity_ambiguous")
    if current_rows and str(current_rows[0].get("queue_gate_state") or "") != "admitted":
        raise WriterQueueError("current_publication_gate_not_verified")
    current_started = (
        _timestamp(current_rows[0], "queue_gate_started_at") if current_rows else None
    ) or current_attempt_started_at or current_created_at
    if current_started is None:
        raise WriterQueueError("current_run_attempt_start_unavailable")
    current_job_id = _positive_int(current_rows[0].get("queue_gate_job_id")) if current_rows else None
    if current_rows and current_job_id is None:
        raise WriterQueueError("current_publication_gate_job_id_unavailable")
    for run in candidates:
        gate_state = str(run.get("queue_gate_state") or "unknown")
        if gate_state == "deferred":
            continue
        if gate_state != "admitted":
            raise WriterQueueError("writer_publication_gate_state_unknown")
        started = _timestamp(run, "queue_gate_started_at")
        if started is None:
            raise WriterQueueError("writer_publication_gate_start_unavailable")
        if started > current_started:
            continue
        if started == current_started:
            candidate_job_id = _positive_int(run.get("queue_gate_job_id"))
            if candidate_job_id is None or current_job_id is None:
                raise WriterQueueError("writer_publication_gate_order_ambiguous")
            if candidate_job_id == current_job_id:
                continue
            if candidate_job_id > current_job_id:
                continue
        blockers.append(dict(run))

    def queue_order(run: Mapping[str, object]) -> tuple[datetime, int, int]:
        started = _timestamp(run, "queue_gate_started_at")
        if started is None:
            raise WriterQueueError("writer_publication_gate_start_unavailable")
        job_id = _positive_int(run.get("queue_gate_job_id"))
        if job_id is None:
            raise WriterQueueError("writer_publication_gate_job_id_unavailable")
        return started, job_id, _run_id(run) or 0

    return sorted(blockers, key=queue_order)


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(str(value or ""))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _request_json(
    url: str,
    *,
    token: str,
    deadline_monotonic: float | None,
) -> tuple[object, str | None]:
    request = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "prstk-production-writer-queue",
    })
    timeout = 15.0
    if deadline_monotonic is not None:
        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 0:
            raise RetryableQueueSnapshotError("writer_queue_snapshot_deadline_exhausted")
        timeout = min(timeout, remaining)
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            headers = getattr(response, "headers", None)
            header_getter = getattr(headers, "get", None) if headers is not None else None
            link = header_getter("Link") if callable(header_getter) else None
            if link is None and callable(getattr(response, "getheader", None)):
                link = response.getheader("Link")
            return payload, str(link) if link is not None else None
    except HTTPError as exc:
        if exc.code == 429 or 500 <= exc.code <= 599:
            raise RetryableQueueSnapshotError(f"writer_queue_transient_http_{exc.code}") from exc
        raise WriterQueueError(f"writer_queue_api_http_{exc.code}") from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise RetryableQueueSnapshotError(
            f"writer_queue_api_temporary_error:{type(exc).__name__}"
        ) from exc


def _fetch_attempt_jobs(
    *,
    run_id: int,
    attempt: int,
    api_url: str,
    repository: str,
    token: str,
    deadline_monotonic: float | None = None,
) -> list[dict[str, object]]:
    """Read all jobs for one immutable attempt, restarting is handled by the caller."""
    expected_total: int | None = None
    rows: dict[int, dict[str, object]] = {}
    page = 1
    url = (
        f"{api_url.rstrip('/')}/repos/{repository}/actions/runs/{run_id}"
        f"/attempts/{attempt}/jobs?per_page={_RUNS_PER_PAGE}&page={page}"
    )
    seen_urls: set[str] = set()
    while page <= _MAX_RUN_PAGES_PER_STATUS:
        if url in seen_urls:
            raise WriterQueueError("writer_queue_jobs_pagination_cycle")
        seen_urls.add(url)
        payload, link = _request_json(
            url, token=token, deadline_monotonic=deadline_monotonic,
        )
        values = payload.get("jobs") if isinstance(payload, Mapping) else None
        count = payload.get("total_count") if isinstance(payload, Mapping) else None
        if not isinstance(values, list) or not isinstance(count, int) or count < 0:
            raise WriterQueueError("writer_queue_jobs_response_contract_invalid")
        if expected_total is None:
            expected_total = count
        elif expected_total != count:
            raise RetryableQueueSnapshotError("writer_queue_jobs_total_changed_during_read")
        for item in values:
            if not isinstance(item, dict):
                raise WriterQueueError("writer_queue_job_contract_invalid")
            job_id = _positive_int(item.get("id"))
            if job_id is None:
                raise WriterQueueError("writer_queue_job_id_invalid")
            previous = rows.get(job_id)
            if previous is not None and previous != item:
                raise RetryableQueueSnapshotError("writer_queue_job_changed_during_read")
            rows[job_id] = item
        next_url = _next_jobs_page_url(
            link,
            api_url=api_url,
            repository=repository,
            run_id=run_id,
            attempt=attempt,
            current_page=page,
        )
        if next_url is None:
            if len(rows) < expected_total:
                raise RetryableQueueSnapshotError("writer_queue_jobs_pagination_incomplete")
            break
        url = next_url
        page += 1
    else:
        raise WriterQueueError("writer_queue_jobs_pagination_limit_exceeded")
    return list(rows.values())


def _annotate_publication_gate(
    run: dict[str, object],
    *,
    api_url: str,
    repository: str,
    token: str,
    deadline_monotonic: float | None,
) -> dict[str, object] | None:
    """Attach verified gate evidence; return a safe deferred-candidate record."""
    path = str(run.get("path") or "")
    gate = WRITER_QUEUE_GATES.get(path)
    if gate is None:
        return None
    if _positive_int(run.get("workflow_id")) != gate["workflow_id"]:
        raise WriterQueueError("writer_publication_gate_workflow_identity_mismatch")
    contract_fingerprint = publication_gate_contract_fingerprint(path, gate)
    run["queue_gate_contract_fingerprint"] = contract_fingerprint
    run["queue_gate_workflow_sha"] = str(run.get("head_sha") or "")
    run_id = _run_id(run)
    try:
        attempt = int(str(run.get("run_attempt") or "1"))
    except (TypeError, ValueError):
        attempt = 0
    if run_id is None or attempt <= 0:
        raise WriterQueueError("writer_publication_gate_attempt_identity_invalid")
    jobs = _fetch_attempt_jobs(
        run_id=run_id,
        attempt=attempt,
        api_url=api_url,
        repository=repository,
        token=token,
        deadline_monotonic=deadline_monotonic,
    )
    gate_jobs = [job for job in jobs if str(job.get("name") or "") == gate["job_name"]]
    if len(gate_jobs) > 1:
        raise WriterQueueError("writer_publication_gate_job_ambiguous")
    status = str(run.get("status") or "").casefold()
    # GitHub may populate run/job started_at before a runner is assigned.
    # Those timestamps are diagnostic only; the runner and step state are the
    # evidence for whether this writer reached its publication gate.
    # `waiting` can mean that GitHub has not assigned a runner yet.  A
    # non-empty started_at is not evidence of execution: the complete,
    # attempt-scoped runner and step fields are authoritative.
    run_active = status in ACTIVE_STATUSES
    if not gate_jobs:
        if run_active and not jobs:
            run.update({"queue_gate_state": "deferred", "queue_gate_reason": "workflow_not_started"})
            return {
                "run_id": run_id, "attempt": attempt, "reason": "workflow_not_started",
                "workflow_sha": str(run.get("head_sha") or ""),
                "contract_fingerprint": contract_fingerprint,
                "observed_status": status,
                "runner_assigned": False,
                "observed_steps": 0,
            }
        if status in {"in_progress", "waiting"}:
            raise RetryableQueueSnapshotError("writer_publication_gate_job_not_visible")
        raise WriterQueueError("writer_publication_gate_job_missing")
    job = gate_jobs[0]
    job_id = _positive_int(job.get("id"))
    steps = job.get("steps")
    job_status = str(job.get("status") or "").casefold()
    runner_id = job.get("runner_id")
    if runner_id not in (None, "", 0, "0") and _positive_int(runner_id) is None:
        raise WriterQueueError("writer_publication_gate_runner_identity_invalid")
    no_runner = runner_id in (None, "", 0, "0")
    if job_id is None:
        raise WriterQueueError("writer_publication_gate_job_contract_invalid")
    run["queue_gate_job_id"] = job_id
    run.update({
        "queue_gate_observed_status": status,
        "queue_gate_job_status": job_status,
        "queue_gate_runner_assigned": not no_runner,
        "queue_gate_observed_steps": len(steps) if isinstance(steps, list) else "unknown",
    })
    if not isinstance(steps, list):
        if run_active or job_status in ACTIVE_STATUSES:
            raise RetryableQueueSnapshotError("writer_publication_gate_steps_unavailable")
        raise WriterQueueError("writer_publication_gate_steps_unavailable")
    steps_started = any(
        _timestamp(step, "started_at") is not None
        for step in steps
        if isinstance(step, Mapping)
    )
    if run_active and job_status in ACTIVE_STATUSES and no_runner and not steps_started:
        run.update({
            "queue_gate_state": "deferred",
            "queue_gate_reason": "writer_job_not_started",
            "queue_gate_observed_status": status,
            "queue_gate_job_status": job_status,
            "queue_gate_runner_assigned": False,
            "queue_gate_observed_steps": len(steps),
        })
        return {
            "run_id": run_id,
            "attempt": attempt,
            "reason": "writer_job_not_started",
            "workflow_sha": str(run.get("head_sha") or ""),
            "contract_fingerprint": contract_fingerprint,
            "observed_status": status,
            "job_status": job_status,
            "runner_assigned": False,
            "observed_steps": len(steps),
        }
    gate_steps = [step for step in steps if isinstance(step, Mapping) and str(step.get("name") or "") == gate["step_name"]]
    if len(gate_steps) > 1:
        raise WriterQueueError("writer_publication_gate_step_ambiguous")
    if not gate_steps:
        if run_active or job_status in ACTIVE_STATUSES:
            raise RetryableQueueSnapshotError("writer_publication_gate_step_not_visible")
        raise WriterQueueError("writer_publication_gate_step_missing")
    step = gate_steps[0]
    gate_started = _timestamp(step, "started_at")
    if gate_started is None:
        step_status = str(step.get("status") or "").casefold()
        if step_status == "completed" and str(step.get("conclusion") or "").casefold() == "skipped":
            run.update({"queue_gate_state": "deferred", "queue_gate_reason": "publication_gate_skipped"})
            return {"run_id": run_id, "attempt": attempt, "reason": "publication_gate_skipped"}
        gate_index = steps.index(step)
        later_steps_started = any(
            _timestamp(item, "started_at") is not None
            for item in steps[gate_index + 1:]
            if isinstance(item, Mapping)
        )
        if step_status in {"queued", "pending", ""} and not later_steps_started:
            run.update({"queue_gate_state": "deferred", "queue_gate_reason": "publication_gate_not_reached"})
            return {"run_id": run_id, "attempt": attempt, "reason": "publication_gate_not_reached"}
        if step_status in {"queued", "pending", ""}:
            raise RetryableQueueSnapshotError("writer_publication_gate_state_conflicts_with_later_step")
        raise WriterQueueError("writer_publication_gate_started_at_unavailable")
    run.update({
        "queue_gate_state": "admitted",
        "queue_gate_started_at": gate_started.isoformat(),
        "queue_gate_job_id": job_id,
        "queue_gate_step_status": str(step.get("status") or "unknown"),
    })
    return None


def _fetch_runs_once(
    *, api_url: str, repository: str, token: str,
    deadline_monotonic: float | None = None,
) -> QueueRuns:
    if not repository or not token:
        raise WriterQueueError("GITHUB_REPOSITORY and GITHUB_TOKEN are required for the writer queue")
    rows_by_attempt: dict[tuple[int, str], dict[str, object]] = {}
    for status in ("queued", "in_progress", "waiting", "pending", "requested"):
        page = 1
        fetched = 0
        total_count: int | None = None
        url = (
            f"{api_url.rstrip('/')}/repos/{repository}/actions/runs"
            f"?per_page={_RUNS_PER_PAGE}&status={status}&page={page}"
        )
        requested_urls: set[str] = set()
        while page <= _MAX_RUN_PAGES_PER_STATUS:
            if url in requested_urls:
                raise WriterQueueError("GitHub Actions queue pagination link cycle")
            requested_urls.add(url)
            request = Request(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "User-Agent": "prstk-production-writer-queue",
                },
            )
            try:
                request_timeout = 15.0
                if deadline_monotonic is not None:
                    remaining = deadline_monotonic - time.monotonic()
                    if remaining <= 0:
                        raise RetryableQueueSnapshotError("writer_queue_recovery_deadline_exhausted")
                    request_timeout = min(request_timeout, remaining)
                with urlopen(request, timeout=request_timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    response_headers = getattr(response, "headers", None)
                    header_get = getattr(response_headers, "get", None)
                    link_header = header_get("Link") if callable(header_get) else None
                    if link_header is None:
                        getheader = getattr(response, "getheader", None)
                        if callable(getheader):
                            link_header = getheader("Link")
            except HTTPError as exc:
                if exc.code == 429 or 500 <= exc.code <= 599:
                    raise RetryableQueueSnapshotError(
                        f"writer_queue_transient_http_{exc.code}"
                    ) from exc
                raise WriterQueueError(
                    f"GitHub Actions queue lookup failed: HTTPError_{exc.code}"
                ) from exc
            except (URLError, TimeoutError, OSError, ValueError) as exc:
                raise RetryableQueueSnapshotError(
                    f"GitHub Actions queue lookup failed: {type(exc).__name__}"
                ) from exc
            values = payload.get("workflow_runs") if isinstance(payload, Mapping) else None
            count = payload.get("total_count") if isinstance(payload, Mapping) else None
            if not isinstance(values, list) or not isinstance(count, int) or count < 0:
                raise WriterQueueError("GitHub Actions queue response contract invalid")
            if total_count is None:
                total_count = count
            elif total_count != count:
                raise RetryableQueueSnapshotError(
                    "GitHub Actions queue pagination changed during read: "
                    f"status={status} page={page}"
                )
            fetched += len(values)
            for item in values:
                if not isinstance(item, dict):
                    raise WriterQueueError("GitHub Actions queue row contract invalid")
                run_id = _run_id(item)
                if run_id is None:
                    raise WriterQueueError("GitHub Actions queue row has no run ID")
                attempt = str(item.get("run_attempt") or "1")
                key = (run_id, attempt)
                previous = rows_by_attempt.get(key)
                if previous is None:
                    rows_by_attempt[key] = item
                    continue
                immutable_fields = (
                    "path", "workflow_id", "head_sha", "run_attempt",
                    "created_at", "run_started_at",
                )
                if any(previous.get(field) != item.get(field) for field in immutable_fields):
                    raise WriterQueueError("GitHub Actions queue row identity changed during read")
                previous_updated = _timestamp(previous, "updated_at")
                item_updated = _timestamp(item, "updated_at")
                if item_updated is not None and (previous_updated is None or item_updated > previous_updated):
                    rows_by_attempt[key] = item
                elif item_updated == previous_updated and previous.get("status") != item.get("status"):
                    raise RetryableQueueSnapshotError("GitHub Actions queue state ambiguous during read")
            next_url = _next_page_url(
                str(link_header) if link_header is not None else None,
                api_url=api_url,
                repository=repository,
                status=status,
                current_page=page,
            )
            if next_url is None:
                if fetched < total_count:
                    raise RetryableQueueSnapshotError(
                        "GitHub Actions queue pagination incomplete: "
                        f"status={status} page={page} fetched={fetched} total_count={total_count}"
                    )
                break
            url = next_url
            page += 1
        else:
            raise WriterQueueError("GitHub Actions queue pagination limit exceeded")
    deferred: list[dict[str, object]] = []
    for run in rows_by_attempt.values():
        if not _workflow_identity(run):
            continue
        try:
            reason = _annotate_publication_gate(
                run,
                api_url=api_url,
                repository=repository,
                token=token,
                deadline_monotonic=deadline_monotonic,
            )
        except WriterQueueError as exc:
            run_id = _run_id(run)
            try:
                diagnostic_attempt = int(str(run.get("run_attempt") or "1"))
            except (TypeError, ValueError):
                diagnostic_attempt = 0
            job_id = _positive_int(run.get("queue_gate_job_id"))
            identity = (
                f"run_id={run_id or 'unknown'};attempt={diagnostic_attempt or 'unknown'};"
                f"job_id={job_id or 'unknown'};workflow_sha={str(run.get('head_sha') or 'unknown')};"
                f"status={str(run.get('status') or 'unknown')};"
                f"job_status={str(run.get('queue_gate_job_status') or '')};"
                f"runner_assigned={str(bool(run.get('queue_gate_runner_assigned'))).lower()};"
                f"observed_steps={str(run.get('queue_gate_observed_steps') or '')};"
                    f"contract_fingerprint={str(run.get('queue_gate_contract_fingerprint') or '')}"
            )
            raise type(exc)(f"{str(exc).split(':', 1)[0]}:{identity}") from exc
        if reason is not None:
            deferred.append(reason)
    return QueueRuns(rows_by_attempt.values(), deferred_candidates=deferred)


def _fetch_runs(
    *, api_url: str, repository: str, token: str,
    deadline_monotonic: float | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> QueueRuns:
    """Read a complete queue snapshot, restarting from page one on transient inconsistency."""
    if not repository or not token:
        raise WriterQueueError("GITHUB_REPOSITORY and GITHUB_TOKEN are required for the writer queue")
    sleep = sleeper or time.sleep
    started = time.monotonic()
    deadline = min(started + 90.0, deadline_monotonic) if deadline_monotonic is not None else started + 90.0
    delays = (2.0, 5.0)
    last_error: RetryableQueueSnapshotError | None = None
    attempts = 0
    for round_index in range(3):
        attempts = round_index + 1
        try:
            rows = _fetch_runs_once(
                api_url=api_url,
                repository=repository,
                token=token,
                deadline_monotonic=deadline,
            )
            return QueueRuns(
                rows,
                recovery_rounds=round_index,
                deferred_candidates=getattr(rows, "deferred_candidates", ()),
            )
        except RetryableQueueSnapshotError as exc:
            last_error = exc
            if round_index >= 2:
                break
            delay = delays[round_index]
            remaining = deadline - time.monotonic()
            if remaining <= delay:
                break
            print(json.dumps({
                "writer_queue": "snapshot_recovering",
                "recovery_round": round_index + 1,
                "error_code": str(exc).split(":", 1)[0][:80],
                "remaining_seconds": max(0, int(remaining)),
            }, sort_keys=True))
            sleep(delay)
    reason = str(last_error or "writer_queue_snapshot_unavailable")
    raise WriterQueueError(
        f"{reason}; writer_queue_recovery_exhausted; recovery_rounds={attempts}"
    ) from last_error


def _fetch_run_attempt(
    run: Mapping[str, object], *, api_url: str, repository: str, token: str,
    deadline_monotonic: float | None = None,
) -> bool:
    """Return whether a previously observed writer attempt is still active."""
    run_id = _run_id(run)
    try:
        attempt = int(str(run.get("run_attempt") or "1"))
    except (TypeError, ValueError):
        attempt = 0
    if run_id is None or attempt <= 0 or not repository or not token:
        raise WriterQueueError("writer_queue_blocker_identity_invalid")
    url = (
        f"{api_url.rstrip('/')}/repos/{repository}/actions/runs/"
        f"{run_id}/attempts/{attempt}"
    )
    request = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "prstk-production-writer-queue",
    })
    timeout = 15.0
    if deadline_monotonic is not None:
        timeout = min(timeout, deadline_monotonic - time.monotonic())
    if timeout <= 0:
        raise WriterQueueError("writer_queue_blocker_verification_deadline_exhausted")
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise WriterQueueError(
            f"writer_queue_blocker_verification_failed:{type(exc).__name__}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise WriterQueueError("writer_queue_blocker_response_invalid")
    if (
        _run_id(payload) != run_id
        or str(payload.get("run_attempt") or "") != str(attempt)
        or not _workflow_identity(payload)
    ):
        raise WriterQueueError("writer_queue_blocker_identity_mismatch")
    status = str(payload.get("status") or "").casefold()
    if status in ACTIVE_STATUSES:
        # Once an attempt was observed inside the gate, it remains a blocker
        # until GitHub confirms that exact attempt is terminal. API snapshots
        # may temporarily regress to queued or omit the job/step.
        return True
    if status != "completed":
        raise WriterQueueError("writer_queue_blocker_terminal_state_unknown")
    return False


def _scheduled_queue_budget(
    slot_context: Mapping[str, object],
    *,
    requested_seconds: int,
    now: datetime | None = None,
) -> tuple[int, str]:
    """Keep scheduled queue waiting inside the original slot's delivery reserve."""
    slot = str(slot_context.get("scheduled_slot") or slot_context.get("effective_slot") or "")
    if str(slot_context.get("delivery_intent") or "") != "notify_candidate":
        return max(0, requested_seconds), ""
    raw_anchor = str(slot_context.get("scheduled_for_at") or "").strip()
    if not raw_anchor:
        raise WriterQueueError("scheduled_queue_anchor_missing")
    if slot not in {"morning", "pre_open", "post_close", "us_premarket"}:
        raise WriterQueueError("scheduled_queue_slot_invalid")
    try:
        anchor = datetime.fromisoformat(raw_anchor.replace("Z", "+00:00"))
    except ValueError:
        raise WriterQueueError("scheduled_queue_anchor_invalid") from None
    if anchor.tzinfo is None or anchor.utcoffset() is None:
        raise WriterQueueError("scheduled_queue_anchor_invalid")
    if slot == "us_premarket":
        try:
            from src.schedule_contract import NEW_YORK, us_session_bounds
            open_at, _close_at = us_session_bounds(anchor.astimezone(NEW_YORK).date())
            deadline = open_at.astimezone(UTC)
        except (ImportError, OSError, ValueError) as exc:
            raise WriterQueueError("scheduled_queue_market_deadline_unavailable") from exc
    else:
        deadline = anchor.astimezone(UTC) + timedelta(minutes=30)
    current = (now or datetime.now(UTC)).astimezone(UTC)
    # Preserve up to eight minutes for bounded preparation plus the final
    # five-minute publish/public-gate/delivery window.
    available = int((deadline - current).total_seconds()) - 13 * 60
    return max(0, min(max(0, requested_seconds), available)), deadline.isoformat()


def _fetch_main_revision(*, api_url: str, repository: str, token: str) -> str:
    """Return the current production ``main`` SHA from GitHub."""
    if not repository or not token:
        raise WriterQueueError("GITHUB_REPOSITORY and GITHUB_TOKEN are required for the revision fence")
    url = f"{api_url.rstrip('/')}/repos/{repository}/commits/main"
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "prstk-production-revision-fence",
        },
    )
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise WriterQueueError(f"GitHub production revision lookup failed: {type(exc).__name__}") from exc
    revision = str(payload.get("sha") or "").strip().lower() if isinstance(payload, Mapping) else ""
    if not revision:
        raise WriterQueueError("GitHub production revision lookup returned no SHA")
    return revision


def evaluate_production_revision(*, run_sha: str | None, main_sha: str | None) -> dict[str, object]:
    """Fail closed when a workflow is no longer running current production code."""
    run_revision = str(run_sha or "").strip().lower()
    main_revision = str(main_sha or "").strip().lower()
    if not run_revision or not main_revision:
        return {"allowed": False, "reason": "production_revision_unavailable"}
    if run_revision != main_revision:
        return {"allowed": False, "reason": "stale_workflow_revision"}
    return {"allowed": True, "reason": "current_production_revision"}


def _run_ids(runs: Iterable[Mapping[str, object]]) -> tuple[int, ...]:
    ids: list[int] = []
    for run in runs:
        run_id = _run_id(run)
        if run_id is not None:
            ids.append(run_id)
    return tuple(ids)


def _blocker_details(runs: Iterable[Mapping[str, object]]) -> tuple[dict[str, object], ...]:
    """Keep bounded, non-secret identity for each actual queue blocker."""
    details = []
    for row in runs:
        run_id = _run_id(row)
        if run_id is None:
            continue
        details.append({
            "run_id": run_id,
            "attempt": str(row.get("run_attempt") or "1"),
            "job_id": _positive_int(row.get("queue_gate_job_id")),
            "workflow_id": _positive_int(row.get("workflow_id")),
            "workflow_path": str(row.get("path") or ""),
            "workflow_sha": str(row.get("queue_gate_workflow_sha") or row.get("head_sha") or ""),
            "contract_fingerprint": str(row.get("queue_gate_contract_fingerprint") or ""),
            "observed_status": str(row.get("status") or "unknown"),
            "job_status": str(row.get("queue_gate_job_status") or "unknown"),
            "runner_assigned": bool(row.get("queue_gate_runner_assigned")),
            "observed_steps": row.get("queue_gate_observed_steps", "unknown"),
            "gate_state": str(row.get("queue_gate_state") or "unknown"),
            "gate_reason": str(row.get("queue_gate_reason") or ""),
            "publication_gate_started_at": str(row.get("queue_gate_started_at") or ""),
        })
    return tuple(details)


def _queue_revision(
    *,
    run_sha: str | None,
    api_url: str,
    repository: str,
    token: str,
    revision_fetcher: Callable[..., str] | None,
    waited_seconds: int,
    checks: int,
    blockers: tuple[int, ...] = (),
) -> QueueResult | None:
    """Return a terminal superseded result when main moved during the wait.

    A workflow that no longer runs the current production revision must never
    publish.  It is nevertheless a normal, successful no-op: treating this
    expected race as a failed job produces misleading GitHub failure alerts.
    Infrastructure failures remain exceptions and therefore keep the
    fail-closed behavior.
    """
    if not run_sha or revision_fetcher is None:
        return None
    main_sha = revision_fetcher(api_url=api_url, repository=repository, token=token)
    verdict = evaluate_production_revision(run_sha=run_sha, main_sha=main_sha)
    if verdict["allowed"]:
        return None
    reason = str(verdict["reason"])
    if reason != "stale_workflow_revision":
        raise WriterQueueError(reason)
    result = QueueResult(
        waited_seconds,
        checks,
        blockers,
        status="superseded",
        reason=reason,
        run_sha=str(run_sha),
        main_sha=str(main_sha),
    )
    print(json.dumps({
        "writer_queue": result.status,
        "reason": result.reason,
        "should_continue": False,
        "waited_seconds": result.waited_seconds,
        "checks": result.checks,
        "blockers": list(result.blockers),
        "run_sha": result.run_sha,
        "main_sha": result.main_sha,
    }))
    return result


def wait_for_slot(
    *,
    current_run_id: int,
    current_created_at: datetime | None = None,
    current_attempt_started_at: datetime | None = None,
    api_url: str | None = None,
    repository: str | None = None,
    token: str | None = None,
    timeout_seconds: int = 3300,
    poll_seconds: int = 20,
    settle_seconds: int = 10,
    fetcher=_fetch_runs,
    sleeper=time.sleep,
    run_sha: str | None = None,
    revision_fetcher: Callable[..., str] | None = None,
    ignored_run_ids: Iterable[int] = (),
    blocker_verifier: Callable[..., bool] | None = None,
    stable_empty_snapshots: int = 2,
    current_attempt: int | None = None,
    require_current_attempt: bool = False,
) -> QueueResult:
    """Wait for two complete queue snapshots and verify disappeared blockers."""
    resolved_api_url: str = api_url or os.getenv("GITHUB_API_URL") or "https://api.github.com"
    resolved_repository: str = repository or os.getenv("GITHUB_REPOSITORY") or ""
    resolved_token: str = token or os.getenv("GITHUB_TOKEN") or ""
    started = time.monotonic()
    checks = 0
    complete_snapshots = 0
    recovery_rounds = 0
    stable_empty = 0
    known_blockers: dict[tuple[int, str], dict[str, object]] = {}
    deferred_candidates: dict[tuple[int, str], dict[str, object]] = {}
    run_sha = str(run_sha or "").strip().lower()
    if revision_fetcher is not None:
        early_revision = _queue_revision(
            run_sha=run_sha,
            api_url=resolved_api_url,
            repository=resolved_repository,
            token=resolved_token,
            revision_fetcher=revision_fetcher,
            waited_seconds=0,
            checks=0,
        )
        if early_revision is not None:
            return early_revision
    if settle_seconds > 0:
        sleeper(min(settle_seconds, max(timeout_seconds, 0)))
    while True:
        elapsed = int(max(0, time.monotonic() - started))
        remaining = timeout_seconds - elapsed
        if remaining <= 0:
            ids = tuple(sorted({key[0] for key in known_blockers}))
            raise WriterQueueTimeout(
                ids, elapsed, complete_snapshots,
                recovery_rounds=recovery_rounds,
                blocker_details=_blocker_details(known_blockers.values()),
                deferred_candidates=(
                    {"run_id": run_id, "attempt": attempt, **details}
                    for (run_id, attempt), details in deferred_candidates.items()
                ),
            )
        checks += 1
        rows = fetcher(
            api_url=resolved_api_url,
            repository=resolved_repository,
            token=resolved_token,
            deadline_monotonic=started + timeout_seconds,
        )
        recovery_rounds += int(getattr(rows, "recovery_rounds", 0) or 0)
        complete_snapshots += 1
        for candidate in getattr(rows, "deferred_candidates", ()):
            run_id = _positive_int(candidate.get("run_id"))
            attempt = str(candidate.get("attempt") or "1")
            if run_id is not None:
                deferred_candidates[(run_id, attempt)] = {
                    **dict(candidate),
                    "run_id": run_id,
                    "attempt": attempt,
                    "reason": str(candidate.get("reason") or "publication_gate_not_reached"),
                }
        current_rows = [
            row for row in rows
            if _run_id(row) == current_run_id
            and (current_attempt is None or str(row.get("run_attempt") or "1") == str(current_attempt))
        ]
        if require_current_attempt:
            if len(current_rows) != 1:
                raise WriterQueueError("current_run_attempt_missing_or_ambiguous_in_queue_snapshot")
            if str(current_rows[0].get("queue_gate_state") or "") != "admitted":
                raise WriterQueueError("current_publication_gate_not_verified")
            if (
                _timestamp(current_rows[0], "queue_gate_started_at") is None
                or _positive_int(current_rows[0].get("queue_gate_job_id")) is None
            ):
                raise WriterQueueError("current_publication_gate_identity_incomplete")
        blockers = blocking_runs(
            rows,
            current_run_id=current_run_id,
            current_created_at=current_created_at,
            current_attempt_started_at=current_attempt_started_at,
            ignored_run_ids=ignored_run_ids,
        )
        present_keys = {
            (_run_id(row) or 0, str(row.get("run_attempt") or "1"))
            for row in blockers
        }
        for key, previous in list(known_blockers.items()):
            if key in present_keys:
                continue
            if blocker_verifier is not None:
                still_active = blocker_verifier(
                    previous,
                    api_url=resolved_api_url,
                    repository=resolved_repository,
                    token=resolved_token,
                    deadline_monotonic=started + timeout_seconds,
                )
            elif fetcher is _fetch_runs:
                still_active = _fetch_run_attempt(
                    previous,
                    api_url=resolved_api_url,
                    repository=resolved_repository,
                    token=resolved_token,
                    deadline_monotonic=started + timeout_seconds,
                )
            else:
                # An injected fetcher is a deterministic test seam; production
                # always uses the authoritative attempt endpoint above.
                still_active = False
            if still_active:
                blockers.append(previous)
                present_keys.add(key)
            else:
                known_blockers.pop(key, None)
        for row in blockers:
            run_id = _run_id(row)
            key = (run_id or 0, str(row.get("run_attempt") or "1"))
            if run_id:
                known_blockers[key] = dict(row)
        blockers.sort(key=lambda row: (
            _timestamp(row, "queue_gate_started_at") or datetime.max.replace(tzinfo=UTC),
            _positive_int(row.get("queue_gate_job_id")) or 0,
            _run_id(row) or 0,
        ))
        elapsed = int(max(0, time.monotonic() - started))
        revision = _queue_revision(
            run_sha=run_sha,
            api_url=resolved_api_url,
            repository=resolved_repository,
            token=resolved_token,
            revision_fetcher=revision_fetcher,
            waited_seconds=elapsed,
            checks=checks,
            blockers=_run_ids(blockers),
        )
        if revision is not None:
            return revision
        if not blockers:
            stable_empty += 1
            if stable_empty >= max(2, stable_empty_snapshots):
                print(json.dumps({
                    "writer_queue": "acquired",
                    "waited_seconds": elapsed,
                    "checks": checks,
                    "complete_snapshots": complete_snapshots,
                    "recovery_rounds": recovery_rounds,
                    "verified_blockers": sorted({key[0] for key in known_blockers}),
                    "deferred_candidates": [
                        details
                        for _key, details in sorted(deferred_candidates.items())
                    ],
                    "queue_budget_seconds": timeout_seconds,
                    "remaining_seconds": max(0, timeout_seconds - elapsed),
                }, sort_keys=True))
                return QueueResult(
                    elapsed,
                    checks,
                    (),
                    status="acquired",
                    reason="queue_acquired",
                    run_sha=run_sha,
                    recovery_rounds=recovery_rounds,
                    complete_snapshots=complete_snapshots,
                    verified_blockers=tuple(sorted({key[0] for key in known_blockers})),
                    deferred_candidates=tuple(sorted({key[0] for key in deferred_candidates})),
                    admission_at=datetime.now(UTC).isoformat(),
                    deferred_candidate_reasons=tuple(sorted({
                        str(details.get("reason") or "unknown")
                        for details in deferred_candidates.values()
                    })),
                    deferred_candidate_details=tuple(
                        details
                        for _key, details in sorted(deferred_candidates.items())
                    ),
                    queue_budget_seconds=timeout_seconds,
                    remaining_seconds=max(0, timeout_seconds - elapsed),
                )
            sleeper(min(2, max(0, timeout_seconds - elapsed)))
            continue
        stable_empty = 0
        remaining = timeout_seconds - elapsed
        if remaining <= 0:
            ids = _run_ids(blockers)
            raise WriterQueueTimeout(
                ids, elapsed, complete_snapshots,
                recovery_rounds=recovery_rounds,
                blocker_details=_blocker_details(blockers),
                deferred_candidates=(
                    {"run_id": run_id, "attempt": attempt, **details}
                    for (run_id, attempt), details in deferred_candidates.items()
                ),
            )
        ids = _run_ids(blockers)
        print(json.dumps({
            "writer_queue": "waiting",
            "blockers": ids,
            "waited_seconds": elapsed,
            "complete_snapshots": complete_snapshots,
            "recovery_rounds": recovery_rounds,
            "deferred_candidate_run_ids": sorted({key[0] for key in deferred_candidates}),
        }, sort_keys=True))
        sleeper(min(max(1, poll_seconds), remaining))


def main() -> int:
    parser = argparse.ArgumentParser(description="Wait for the production data-writer queue")
    parser.add_argument("--run-id", type=int, default=int(os.getenv("GITHUB_RUN_ID", "0") or 0))
    parser.add_argument("--timeout-seconds", type=int, default=3300)
    parser.add_argument("--poll-seconds", type=int, default=20)
    parser.add_argument("--settle-seconds", type=int, default=10)
    args = parser.parse_args()
    if args.run_id <= 0:
        raise SystemExit("GITHUB_RUN_ID is required")
    created_raw = os.getenv("GITHUB_RUN_ATTEMPT_CREATED_AT")
    created = _timestamp({"created_at": created_raw}, "created_at") if created_raw else None
    attempt_started_raw = os.getenv("GITHUB_RUN_ATTEMPT_STARTED_AT", "")
    attempt_started = _timestamp({"run_started_at": attempt_started_raw}, "run_started_at") if attempt_started_raw else None
    run_sha = os.getenv("GITHUB_SHA", "").strip().lower()

    def write_outputs(values: Mapping[str, object]) -> None:
        destination = os.getenv("GITHUB_OUTPUT", "").strip()
        if not destination:
            return
        workflow_ref = os.getenv("GITHUB_WORKFLOW_REF", "")
        workflow_match = re.search(r"(\.github/workflows/[^@]+\.ya?ml)@", workflow_ref)
        workflow_path = workflow_match.group(1) if workflow_match else ""
        workflow_gate = WRITER_QUEUE_GATES.get(workflow_path, {})
        outputs: dict[str, object] = {
            "queue_diagnostic_schema_version": "writer-queue-v3",
            "queue_entry_at": queue_entry_at,
            "queue_current_attempt": os.getenv("GITHUB_RUN_ATTEMPT", "1"),
            "queue_workflow_path": workflow_path,
            "queue_workflow_sha": run_sha,
            "queue_gate_contract_fingerprint": (
                publication_gate_contract_fingerprint(workflow_path, workflow_gate)
                if workflow_gate else ""
            ),
        }
        outputs.update(values)
        with open(destination, "a", encoding="utf-8") as handle:
            for key, value in outputs.items():
                handle.write(f"{key}={value}\n")

    def handoff_superseded_run(result: QueueResult, *, eligible: bool) -> bool:
        """Attempt one bounded successor only for an in-window US premarket obligation."""
        if not eligible or result.status != "superseded":
            return False
        if (
            str(slot_context.get("scheduled_slot") or slot_context.get("effective_slot") or "") != "us_premarket"
            or str(slot_context.get("delivery_intent") or "") != "notify_candidate"
        ):
            return False
        from src.scheduled_handoff import HandoffError, build_handoff_payload, dispatch_and_wait, handoff_deadline

        try:
            payload = build_handoff_payload(
                slot_context,
                parent_run_id=args.run_id,
                parent_sha=run_sha,
                target_sha=result.main_sha,
            )
            client_payload = payload["client_payload"]
            assert isinstance(client_payload, Mapping)
            handoff_state = dispatch_and_wait(
                payload,
                repository=os.getenv("GITHUB_REPOSITORY", ""),
                token=os.getenv("GITHUB_TOKEN", ""),
                api_url=os.getenv("GITHUB_API_URL", "https://api.github.com"),
                deadline=handoff_deadline(slot_context),
            )
            handoff_status = str(handoff_state.get("status") or "unconfirmed")
            write_outputs({
                "queue_status": "handoff_completed" if handoff_status == "delivered" else "handoff_failed",
                "should_continue": "false",
                "reason": str(handoff_state.get("reason") or "handoff_unconfirmed"),
                "waited_seconds": result.waited_seconds,
                "blocker_run_ids": ",".join(str(item) for item in result.blockers),
                "run_sha": result.run_sha,
                "main_sha": result.main_sha,
                "handoff_status": handoff_status,
                "handoff_run_id": handoff_state.get("child_run_id", ""),
                "handoff_id": handoff_state.get("handoff_id", client_payload.get("handoff_id", "")),
                "handoff_request_outcome": handoff_state.get("request_outcome", "unknown"),
            })
            print(json.dumps({"writer_queue": "handoff", **handoff_state}, sort_keys=True))
        except HandoffError as exc:
            write_outputs({
                "queue_status": "handoff_failed",
                "should_continue": "false",
                "reason": str(exc),
                "waited_seconds": result.waited_seconds,
                "blocker_run_ids": ",".join(str(item) for item in result.blockers),
                "run_sha": result.run_sha,
                "main_sha": result.main_sha,
                "handoff_status": "failed",
                "handoff_run_id": "",
                "handoff_id": "",
                "handoff_request_outcome": "rejected_or_unknown",
            })
            print(f"::error::scheduled_handoff_failed:{exc}")
        return True

    queue_started = time.monotonic()
    queue_entry_at = datetime.now(UTC).isoformat()
    queue_timeout_seconds = max(0, args.timeout_seconds)
    queue_deadline_at = ""
    try:
        context_raw = os.getenv("SLOT_CONTEXT", "{}")
        try:
            slot_context = json.loads(context_raw)
        except ValueError:
            slot_context = {}
        if not isinstance(slot_context, Mapping):
            slot_context = {}
        ignored_parent: tuple[int, ...] = ()
        raw_parent = os.getenv("HANDOFF_PARENT_RUN_ID", "").strip()
        is_handoff = bool(raw_parent)
        if is_handoff:
            if os.getenv("HANDOFF_PARENT_VERIFIED", "").strip().casefold() != "true":
                raise WriterQueueError("handoff_parent_not_verified")
            try:
                ignored_parent = (int(raw_parent),)
            except ValueError as exc:
                raise WriterQueueError("handoff_parent_id_invalid") from exc
        queue_timeout_seconds, queue_deadline_at = _scheduled_queue_budget(
            slot_context,
            requested_seconds=max(0, args.timeout_seconds),
        )
        if queue_timeout_seconds <= 0 and str(slot_context.get("delivery_intent") or "") == "notify_candidate":
            raise WriterQueueError("scheduled_queue_delivery_reserve_exhausted")
        result = wait_for_slot(
            current_run_id=args.run_id,
            current_attempt=_positive_int(os.getenv("GITHUB_RUN_ATTEMPT", "1")),
            current_created_at=created,
            current_attempt_started_at=attempt_started,
            timeout_seconds=queue_timeout_seconds,
            poll_seconds=max(1, args.poll_seconds),
            settle_seconds=max(0, args.settle_seconds),
            run_sha=run_sha,
            revision_fetcher=_fetch_main_revision,
            ignored_run_ids=ignored_parent,
            require_current_attempt=True,
        )
        if result is not None and result.status == "superseded":
            if handoff_superseded_run(result, eligible=not is_handoff):
                return 0
            write_outputs({
                "queue_status": result.status,
                "should_continue": "false",
                "reason": result.reason,
                "waited_seconds": result.waited_seconds,
                "blocker_run_ids": ",".join(str(item) for item in result.blockers),
                "run_sha": result.run_sha,
                "main_sha": result.main_sha,
                "handoff_status": "not_attempted",
            })
            print("::notice::stale_workflow_superseded; Telegram and data publication skipped")
            return 0
        waited_seconds = result.waited_seconds if result is not None else 0
        main_revision = (result.main_sha if result is not None else "") or _fetch_main_revision(
            api_url=os.getenv("GITHUB_API_URL", "https://api.github.com"),
            repository=os.getenv("GITHUB_REPOSITORY", ""),
            token=os.getenv("GITHUB_TOKEN", ""),
        )
        revision = evaluate_production_revision(
            run_sha=run_sha,
            main_sha=main_revision,
        )
        if not revision["allowed"]:
            reason = str(revision["reason"])
            if reason == "stale_workflow_revision":
                late_result = QueueResult(
                    waited_seconds, result.checks if result is not None else 0, (),
                    status="superseded", reason=reason, run_sha=run_sha, main_sha=main_revision,
                )
                if handoff_superseded_run(late_result, eligible=not is_handoff):
                    return 0
                write_outputs({
                    "queue_status": "superseded",
                    "should_continue": "false",
                    "reason": reason,
                    "waited_seconds": waited_seconds,
                    "blocker_run_ids": "",
                    "run_sha": run_sha,
                    "main_sha": main_revision,
                })
                print("::notice::stale_workflow_superseded; Telegram and data publication skipped")
                return 0
            raise WriterQueueError(reason)
        write_outputs({
            "queue_status": "acquired",
            "should_continue": "true",
            "reason": "current_production_revision",
            "waited_seconds": waited_seconds,
            "queue_budget_seconds": queue_timeout_seconds,
            "queue_deadline_at": queue_deadline_at,
            "remaining_seconds": result.remaining_seconds if result is not None else queue_timeout_seconds,
            "complete_snapshots": result.complete_snapshots if result is not None else 0,
            "recovery_rounds": result.recovery_rounds if result is not None else 0,
            "admission_at": result.admission_at if result is not None else datetime.now(UTC).isoformat(),
            "blocker_details": "[]",
            "deferred_candidate_run_ids": ",".join(str(item) for item in (result.deferred_candidates if result is not None else ())),
            "deferred_candidate_reasons": ",".join(result.deferred_candidate_reasons if result is not None else ()),
            "deferred_candidate_details": json.dumps(result.deferred_candidate_details if result is not None else (), sort_keys=True),
            "blocker_run_ids": "",
            "run_sha": run_sha,
            "main_sha": main_revision,
        })
        print(json.dumps({"production_revision": revision["reason"]}))
    except WriterQueueError as exc:
        recovery_match = re.search(r"recovery_rounds=(\d+)", str(exc))
        timeout_error = exc if isinstance(exc, WriterQueueTimeout) else None
        timeout_match = timeout_error is not None
        blockers = timeout_error.blockers if timeout_error is not None else ()
        waited_seconds = (
            timeout_error.waited_seconds
            if timeout_error is not None
            else max(0, int(time.monotonic() - queue_started))
        )
        deferred_details = timeout_error.deferred_candidates if timeout_error is not None else ()
        error_candidate = re.search(r"run_id=(\d+);attempt=(\d+);job_id=(\d+)", str(exc))
        error_text = str(exc)
        error_code = "writer_queue_timeout" if timeout_match else error_text.split(";", 1)[0].split(":", 1)[0][:100]
        def candidate_field(field: str) -> str:
            match = re.search(rf"(?:^|;){field}=([^;]+)", error_text)
            return match.group(1) if match else ""

        write_outputs({
            "queue_status": "failed",
            "should_continue": "false",
            "reason": error_text.replace("\n", " "),
            "queue_error_code": error_code,
            "recovery_rounds": timeout_error.recovery_rounds if timeout_error is not None else (recovery_match.group(1) if recovery_match else ""),
            "complete_snapshots": timeout_error.complete_snapshots if timeout_error is not None else "",
            "queue_budget_seconds": queue_timeout_seconds,
            "queue_deadline_at": queue_deadline_at,
            "remaining_seconds": max(0, queue_timeout_seconds - waited_seconds),
            "waited_seconds": waited_seconds,
            "blocker_run_ids": ",".join(str(item) for item in blockers),
            "queue_error_candidate_run_id": error_candidate.group(1) if error_candidate else "",
            "queue_error_candidate_attempt": error_candidate.group(2) if error_candidate else "",
            "queue_error_candidate_job_id": error_candidate.group(3) if error_candidate else "",
            "queue_error_candidate_status": candidate_field("status"),
            "queue_error_candidate_job_status": candidate_field("job_status"),
            "queue_error_candidate_runner_assigned": candidate_field("runner_assigned"),
            "queue_error_candidate_observed_steps": candidate_field("observed_steps"),
            "queue_error_candidate_workflow_sha": candidate_field("workflow_sha"),
            "queue_error_candidate_contract_fingerprint": candidate_field("contract_fingerprint"),
            "blocker_details": json.dumps(
                timeout_error.blocker_details if timeout_error is not None else (),
                sort_keys=True,
            ),
            "deferred_candidate_run_ids": ",".join(str(item.get("run_id")) for item in deferred_details),
            "deferred_candidate_reasons": ",".join(sorted({str(item.get("reason")) for item in deferred_details})),
            "deferred_candidate_details": json.dumps(deferred_details, sort_keys=True),
            "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT", "1"),
            "run_sha": run_sha,
            "main_sha": "",
        })
        print(f"::error::{exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
