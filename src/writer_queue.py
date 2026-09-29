"""Serialize production data writers without GitHub's one-pending-run trap.

GitHub Actions concurrency keeps one running and one pending run per group;
when a third run arrives it replaces the pending run.  Production refreshes
therefore use a unique concurrency key and this bounded GitHub-run queue to
wait for older writer runs before touching ``data-release``.  The queue is
fail-closed: an unavailable Actions API never permits a concurrent publish.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
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
_WRITER_WORKFLOW_PATH_BY_ID = {value: key for key, value in WRITER_WORKFLOW_IDENTITIES.items()}
ACTIVE_STATUSES = frozenset({"queued", "in_progress", "waiting", "pending", "requested"})
_RUNS_PER_PAGE = 100
_MAX_RUN_PAGES_PER_STATUS = 100


def _next_page_url(
    link_header: str | None,
    *,
    api_url: str,
    repository: str,
    status: str,
    current_page: int,
) -> str | None:
    """Return GitHub's next-page URL after validating its API identity."""
    if not link_header:
        return None
    next_links: list[str] = []
    for entry in link_header.split(","):
        match = re.search(r"<([^<>]+)>\s*;\s*rel=\"([^\"]+)\"", entry)
        if match and "next" in match.group(2).split():
            next_links.append(match.group(1))
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


class WriterQueueError(RuntimeError):
    """Raised when the production writer queue cannot be established."""


@dataclass(frozen=True)
class QueueResult:
    waited_seconds: int
    checks: int
    blockers: tuple[int, ...]
    status: str = "acquired"
    reason: str = "queue_acquired"
    run_sha: str = ""
    main_sha: str = ""


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
    """Use this run's current attempt start, not the original run creation."""
    return _timestamp(run, "run_started_at") or _timestamp(run, "created_at")


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
    """Return older active production writers in attempt-start FIFO order."""
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
    current_started = (
        _attempt_started(current_rows[0]) if current_rows else None
    ) or current_attempt_started_at or current_created_at
    if current_started is None:
        raise WriterQueueError("current_run_attempt_start_unavailable")
    current_attempt = str(current_rows[0].get("run_attempt") or "1") if current_rows else "1"

    for run in candidates:
        started = _attempt_started(run)
        if started is None:
            raise WriterQueueError("writer_attempt_start_unavailable")
        if started > current_started:
            continue
        if started == current_started:
            # GitHub timestamps are second precision. Do not use the old run
            # ID to order a re-run against another attempt that started in the
            # same second; the attempt order cannot be established safely.
            candidate_attempt = str(run.get("run_attempt") or "1")
            if candidate_attempt == current_attempt and _run_id(run) == current_run_id:
                continue
            raise WriterQueueError("writer_attempt_order_ambiguous")
        blockers.append(dict(run))

    def queue_order(run: Mapping[str, object]) -> tuple[datetime, int, int]:
        started = _attempt_started(run)
        if started is None:
            raise WriterQueueError("writer_attempt_start_unavailable")
        try:
            attempt = int(str(run.get("run_attempt") or "1"))
        except ValueError:
            raise WriterQueueError("writer_attempt_identity_invalid") from None
        return started, _run_id(run) or 0, attempt

    return sorted(blockers, key=queue_order)


def _fetch_runs(*, api_url: str, repository: str, token: str) -> list[dict[str, object]]:
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
                with urlopen(request, timeout=15) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    response_headers = getattr(response, "headers", None)
                    header_get = getattr(response_headers, "get", None)
                    link_header = header_get("Link") if callable(header_get) else None
                    if link_header is None:
                        getheader = getattr(response, "getheader", None)
                        if callable(getheader):
                            link_header = getheader("Link")
            except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
                raise WriterQueueError(f"GitHub Actions queue lookup failed: {type(exc).__name__}") from exc
            values = payload.get("workflow_runs") if isinstance(payload, Mapping) else None
            count = payload.get("total_count") if isinstance(payload, Mapping) else None
            if not isinstance(values, list) or not isinstance(count, int) or count < 0:
                raise WriterQueueError("GitHub Actions queue response contract invalid")
            if total_count is None:
                total_count = count
            elif total_count != count:
                raise WriterQueueError(
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
                    raise WriterQueueError("GitHub Actions queue state ambiguous during read")
            next_url = _next_page_url(
                str(link_header) if link_header is not None else None,
                api_url=api_url,
                repository=repository,
                status=status,
                current_page=page,
            )
            if next_url is None:
                if fetched < total_count:
                    raise WriterQueueError(
                        "GitHub Actions queue pagination incomplete: "
                        f"status={status} page={page} fetched={fetched} total_count={total_count}"
                    )
                break
            url = next_url
            page += 1
        else:
            raise WriterQueueError("GitHub Actions queue pagination limit exceeded")
    return list(rows_by_attempt.values())


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
) -> QueueResult:
    """Wait until all older production writer runs have left active states."""
    resolved_api_url: str = api_url or os.getenv("GITHUB_API_URL") or "https://api.github.com"
    resolved_repository: str = repository or os.getenv("GITHUB_REPOSITORY") or ""
    resolved_token: str = token or os.getenv("GITHUB_TOKEN") or ""
    started = time.monotonic()
    checks = 0
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
        checks += 1
        blockers = blocking_runs(
            fetcher(api_url=resolved_api_url, repository=resolved_repository, token=resolved_token),
            current_run_id=current_run_id,
            current_created_at=current_created_at,
            current_attempt_started_at=current_attempt_started_at,
            ignored_run_ids=ignored_run_ids,
        )
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
            print(json.dumps({"writer_queue": "acquired", "waited_seconds": elapsed, "checks": checks}))
            return QueueResult(
                elapsed,
                checks,
                (),
                status="acquired",
                reason="queue_acquired",
                run_sha=run_sha,
            )
        remaining = timeout_seconds - elapsed
        if remaining <= 0:
            ids = _run_ids(blockers)
            raise WriterQueueError(f"writer queue timed out; active blockers={','.join(map(str, ids))}")
        ids = _run_ids(blockers)
        print(json.dumps({"writer_queue": "waiting", "blockers": ids, "waited_seconds": elapsed}))
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
        with open(destination, "a", encoding="utf-8") as handle:
            for key, value in values.items():
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
        result = wait_for_slot(
            current_run_id=args.run_id,
            current_created_at=created,
            current_attempt_started_at=attempt_started,
            timeout_seconds=max(0, args.timeout_seconds),
            poll_seconds=max(1, args.poll_seconds),
            settle_seconds=max(0, args.settle_seconds),
            run_sha=run_sha,
            revision_fetcher=_fetch_main_revision,
            ignored_run_ids=ignored_parent,
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
            "blocker_run_ids": "",
            "run_sha": run_sha,
            "main_sha": main_revision,
        })
        print(json.dumps({"production_revision": revision["reason"]}))
    except WriterQueueError as exc:
        write_outputs({
            "queue_status": "failed",
            "should_continue": "false",
            "reason": str(exc).replace("\n", " "),
            "waited_seconds": "",
            "blocker_run_ids": "",
            "run_sha": run_sha,
            "main_sha": "",
        })
        print(f"::error::{exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
