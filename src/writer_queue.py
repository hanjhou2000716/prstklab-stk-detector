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
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

WRITER_WORKFLOW_NAMES = frozenset(
    {
        "Scheduled market brief",
        "Emergency market alert",
        "Refresh market dashboard",
        "Railway monitor health",
        "Official macro and price monitor",
        "Unified Taiwan-US research report",
    }
)
ACTIVE_STATUSES = frozenset({"queued", "in_progress", "waiting", "pending"})


class WriterQueueError(RuntimeError):
    """Raised when the production writer queue cannot be established."""


@dataclass(frozen=True)
class QueueResult:
    waited_seconds: int
    checks: int
    blockers: tuple[int, ...]


def _created_at(run: Mapping[str, object]) -> datetime | None:
    value = run.get("created_at")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _run_id(run: Mapping[str, object]) -> int | None:
    try:
        return int(str(run.get("id") or ""))
    except (TypeError, ValueError):
        return None


def blocking_runs(
    runs: Iterable[Mapping[str, object]],
    *,
    current_run_id: int,
    current_created_at: datetime | None = None,
) -> list[dict[str, object]]:
    """Return older active production writers in deterministic order."""
    blockers: list[dict[str, object]] = []
    for run in runs:
        if not isinstance(run, Mapping):
            continue
        run_id = _run_id(run)
        if run_id is None or run_id == current_run_id:
            continue
        if run.get("name") not in WRITER_WORKFLOW_NAMES:
            continue
        if str(run.get("status") or "").casefold() not in ACTIVE_STATUSES:
            continue
        created = _created_at(run)
        # Run IDs are monotonically increasing within a repository.  The
        # timestamp guard handles mocked/non-GitHub IDs without allowing a
        # newer run to block an older one indefinitely.
        if run_id > current_run_id:
            continue
        if current_created_at is not None and created is not None and created > current_created_at:
            continue
        blockers.append(dict(run))
    return sorted(blockers, key=lambda item: _run_id(item) or 0)


def _fetch_runs(*, api_url: str, repository: str, token: str) -> list[dict[str, object]]:
    if not repository or not token:
        raise WriterQueueError("GITHUB_REPOSITORY and GITHUB_TOKEN are required for the writer queue")
    url = f"{api_url.rstrip('/')}/repos/{repository}/actions/runs?per_page=100&status=queued"
    rows: list[dict[str, object]] = []
    for status in ("queued", "in_progress"):
        request = Request(
            url.replace("status=queued", f"status={status}"),
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
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            raise WriterQueueError(f"GitHub Actions queue lookup failed: {type(exc).__name__}") from exc
        values = payload.get("workflow_runs") if isinstance(payload, Mapping) else None
        if isinstance(values, list):
            rows.extend(item for item in values if isinstance(item, dict))
    return rows


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


def wait_for_slot(
    *,
    current_run_id: int,
    current_created_at: datetime | None = None,
    api_url: str | None = None,
    repository: str | None = None,
    token: str | None = None,
    timeout_seconds: int = 3300,
    poll_seconds: int = 20,
    settle_seconds: int = 10,
    fetcher=_fetch_runs,
    sleeper=time.sleep,
) -> QueueResult:
    """Wait until all older production writer runs have left active states."""
    api_url = api_url or os.getenv("GITHUB_API_URL", "https://api.github.com")
    repository = repository or os.getenv("GITHUB_REPOSITORY", "")
    token = token or os.getenv("GITHUB_TOKEN", "")
    started = time.monotonic()
    checks = 0
    if settle_seconds > 0:
        sleeper(min(settle_seconds, max(timeout_seconds, 0)))
    while True:
        checks += 1
        blockers = blocking_runs(
            fetcher(api_url=api_url, repository=repository, token=token),
            current_run_id=current_run_id,
            current_created_at=current_created_at,
        )
        elapsed = int(max(0, time.monotonic() - started))
        if not blockers:
            print(json.dumps({"writer_queue": "acquired", "waited_seconds": elapsed, "checks": checks}))
            return QueueResult(elapsed, checks, ())
        remaining = timeout_seconds - elapsed
        if remaining <= 0:
            ids = tuple(_run_id(item) for item in blockers if _run_id(item) is not None)
            raise WriterQueueError(f"writer queue timed out; active blockers={','.join(map(str, ids))}")
        ids = tuple(_run_id(item) for item in blockers if _run_id(item) is not None)
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
    created = _created_at({"created_at": created_raw}) if created_raw else None
    try:
        wait_for_slot(
            current_run_id=args.run_id,
            current_created_at=created,
            timeout_seconds=max(0, args.timeout_seconds),
            poll_seconds=max(1, args.poll_seconds),
            settle_seconds=max(0, args.settle_seconds),
        )
        main_revision = _fetch_main_revision(
            api_url=os.getenv("GITHUB_API_URL", "https://api.github.com"),
            repository=os.getenv("GITHUB_REPOSITORY", ""),
            token=os.getenv("GITHUB_TOKEN", ""),
        )
        revision = evaluate_production_revision(
            run_sha=os.getenv("GITHUB_SHA"),
            main_sha=main_revision,
        )
        if not revision["allowed"]:
            print(f"::error::{revision['reason']}; Telegram and data publication are blocked")
            return 1
        print(json.dumps({"production_revision": revision["reason"]}))
    except WriterQueueError as exc:
        print(f"::error::{exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
