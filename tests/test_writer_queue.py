import hashlib
import io
import json
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

import src.writer_queue as writer_queue
from src.writer_queue import (
    QueueResult,
    WriterQueueError,
    WriterQueueTimeout,
    blocking_runs,
    evaluate_production_revision,
    main,
    wait_for_slot,
)

_read_publication_admission = writer_queue._read_publication_admission
_verified_workflow_contract = writer_queue._verified_workflow_contract


@pytest.fixture(autouse=True)
def no_remote_admission_artifact_by_default(monkeypatch):
    """Keep queue state-machine tests offline; admission is covered explicitly below."""
    monkeypatch.setattr(writer_queue, "_read_publication_admission", lambda **_kwargs: None)
    contracts = writer_queue._known_workflow_contracts()["writer_workflows"]

    def verified_contract(run, **_kwargs):
        path = str(run.get("path") or "")
        return {
            **contracts[path],
            "source_commit_sha": str(run.get("head_sha") or ""),
        }

    monkeypatch.setattr(writer_queue, "_verified_workflow_contract", verified_contract)


def _run(
    run_id: int,
    status: str = "in_progress",
    name: str = "Refresh market dashboard",
    *,
    path: str = ".github/workflows/refresh-dashboard.yml",
    workflow_id: int = 318848659,
    created_at: str | None = None,
    run_attempt: int = 1,
    queue_gate_state: str | None = None,
    queue_gate_started_at: str | None = None,
    queue_gate_job_id: int | None = None,
) -> dict[str, object]:
    created = created_at or f"2026-08-31T08:00:{run_id % 60:02d}Z"
    admitted = queue_gate_state or ("deferred" if status == "queued" else "admitted")
    return {
        "id": run_id,
        "name": name,
        "path": path,
        "workflow_id": workflow_id,
        "status": status,
        "created_at": created,
        "run_started_at": None if status == "queued" else created,
        "run_attempt": run_attempt,
        "queue_gate_state": admitted,
        "queue_gate_started_at": queue_gate_started_at or (created if admitted == "admitted" else ""),
        "queue_gate_job_id": queue_gate_job_id or (run_id + 10000 if admitted == "admitted" else 0),
    }


def test_blocking_runs_only_returns_older_active_production_writers():
    rows = blocking_runs(
        [
            _run(10), _run(11, "queued"), _run(12, "completed"),
            _run(13, name="Quality and delivery", path=".github/workflows/quality.yml", workflow_id=999),
        ],
        current_run_id=12,
        current_created_at=datetime(2026, 8, 31, 8, 1, tzinfo=UTC),
    )
    assert [row["id"] for row in rows] == [10]


def test_pages_deployment_is_serialized_with_data_release_writers():
    rows = blocking_runs(
        [_run(
            10, name="Deploy dashboard to GitHub Pages",
            path=".github/workflows/deploy-pages.yml", workflow_id=318841880,
        )],
        current_run_id=11,
        current_created_at=datetime(2026, 8, 31, 8, 1, tzinfo=UTC),
    )
    assert [row["name"] for row in rows] == ["Deploy dashboard to GitHub Pages"]


def test_unstarted_queued_writer_is_deferred_instead_of_blocking():
    queued = _run(10, status="queued")
    assert blocking_runs(
        [queued], current_run_id=11,
        current_created_at=datetime(2026, 8, 31, 8, 1, tzinfo=UTC),
    ) == []


def test_gate_fifo_uses_gate_start_and_job_id_for_same_second():
    start = "2026-08-31T08:01:00Z"
    earlier = _run(99, created_at="2026-08-31T07:00:00Z", queue_gate_started_at=start, queue_gate_job_id=100)
    later = _run(1, created_at="2026-08-31T07:00:00Z", queue_gate_started_at=start, queue_gate_job_id=300)
    current = _run(11, created_at="2026-08-31T07:00:00Z", queue_gate_started_at=start, queue_gate_job_id=200)
    assert blocking_runs(
        [later, current, earlier], current_run_id=11,
    ) == [earlier]


def test_wait_for_slot_waits_until_older_writer_finishes():
    responses = [[_run(10)], [], []]
    sleeps: list[int] = []

    def fetcher(**_kwargs):
        return responses.pop(0)

    result = wait_for_slot(
        current_run_id=11,
        current_created_at=datetime(2026, 8, 31, 8, 1, tzinfo=UTC),
        api_url="https://api.github.test",
        repository="owner/repo",
        token="token",
        timeout_seconds=30,
        poll_seconds=2,
        settle_seconds=0,
        fetcher=fetcher,
        sleeper=sleeps.append,
    )

    assert result.checks == 3
    assert result.complete_snapshots == 3
    assert sleeps == [2, 2]


def test_wait_for_slot_fails_closed_when_lookup_fails():
    def fetcher(**_kwargs):
        raise WriterQueueError("lookup failed")

    with pytest.raises(WriterQueueError, match="lookup failed"):
        wait_for_slot(
            current_run_id=11,
            current_created_at=datetime(2026, 8, 31, 8, 1, tzinfo=UTC),
            api_url="https://api.github.test",
            repository="owner/repo",
            token="token",
            timeout_seconds=5,
            poll_seconds=1,
            settle_seconds=0,
            fetcher=fetcher,
            sleeper=lambda _seconds: None,
        )


def test_wait_for_slot_supersedes_as_soon_as_main_moves():
    responses = [[_run(10)], [_run(10)]]
    revisions = iter(["same-sha", "same-sha", "new-sha"])
    sleeps: list[int] = []

    def fetcher(**_kwargs):
        return responses.pop(0)

    def revision_fetcher(**_kwargs):
        return next(revisions)

    result = wait_for_slot(
        current_run_id=11,
        current_created_at=datetime(2026, 8, 31, 8, 1, tzinfo=UTC),
        api_url="https://api.github.test",
        repository="owner/repo",
        token="token",
        timeout_seconds=30,
        poll_seconds=2,
        settle_seconds=0,
        fetcher=fetcher,
        sleeper=sleeps.append,
        run_sha="same-sha",
        revision_fetcher=revision_fetcher,
    )

    assert result.status == "superseded"
    assert result.reason == "stale_workflow_revision"
    assert result.blockers == (10,)
    assert result.main_sha == "new-sha"
    assert sleeps == [2]


def test_dynamic_scheduled_run_name_is_identified_by_exact_workflow_identity():
    scheduled = _run(
        36530546203,
        name="Scheduled market brief / post_close",
        path=".github/workflows/scheduled-brief.yml",
        workflow_id=318853044,
        created_at="2026-09-29T06:20:00Z",
    )
    result = blocking_runs(
        [scheduled],
        current_run_id=36530546204,
        current_created_at=datetime(2026, 9, 29, 6, 21, tzinfo=UTC),
    )
    assert [row["id"] for row in result] == [36530546203]


def test_known_workflow_id_with_wrong_path_fails_closed():
    with pytest.raises(WriterQueueError, match="writer_workflow_identity_mismatch"):
        blocking_runs(
            [_run(10, path=".github/workflows/other.yml", workflow_id=318853044)],
            current_run_id=11,
            current_created_at=datetime(2026, 8, 31, 8, 1, tzinfo=UTC),
        )


def test_old_run_id_rerun_does_not_jump_ahead_of_earlier_attempt_start():
    older_attempt = _run(
        10, created_at="2026-08-31T08:00:00Z", run_attempt=2,
    )
    current = datetime(2026, 8, 31, 8, 1, tzinfo=UTC)
    assert blocking_runs(
        [older_attempt], current_run_id=11, current_created_at=current,
    ) == [older_attempt]
    later_rerun = _run(
        9, created_at="2026-08-31T08:02:00Z", run_attempt=3,
    )
    assert blocking_runs(
        [later_rerun], current_run_id=11, current_created_at=current,
    ) == []


def test_queue_api_reads_all_pages_and_active_statuses(monkeypatch):
    requests: list[str] = []

    class Response:
        def __init__(self, payload, link=None):
            self.payload = payload
            self.headers = {"Link": link} if link else {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.payload).encode()

    def open_request(request, timeout):
        assert timeout == 15
        requests.append(request.full_url)
        if "/runs/101/attempts/1/jobs?" in request.full_url:
            return Response({"total_count": 0, "jobs": []})
        query = request.full_url.split("?", 1)[1]
        params = dict(item.split("=") for item in query.split("&"))
        if params["status"] != "queued":
            return Response({"total_count": 0, "workflow_runs": []})
        if params["page"] == "1":
            rows = [
                {"id": index + 1, "run_attempt": 1, "path": ".github/workflows/quality.yml", "workflow_id": 999}
                for index in range(40)
            ]
            return Response(
                {"total_count": 101, "workflow_runs": rows},
                ' <https://api.github.test/repos/owner/repo/actions/runs?per_page=100&status=queued&page=2>; rel="next", '
                '<https://api.github.test/repos/owner/repo/actions/runs?per_page=100&status=queued&page=2>; rel="last"',
            )
        return Response({"total_count": 101, "workflow_runs": [{
            "id": index + 41, "run_attempt": 1, "path": ".github/workflows/quality.yml",
            "workflow_id": 999,
        } for index in range(60)] + [{
            "id": 101, "run_attempt": 1, "path": ".github/workflows/scheduled-brief.yml",
            "workflow_id": 318853044, "status": "queued",
        }]})

    monkeypatch.setattr(writer_queue, "urlopen", open_request)
    runs = writer_queue._fetch_runs(
        api_url="https://api.github.test", repository="owner/repo", token="token",
    )
    assert len(requests) == 7
    assert any("status=waiting" in url for url in requests)
    assert any("status=requested" in url for url in requests)
    assert any("status=queued&page=2" in url for url in requests)
    assert any(run["id"] == 101 for run in runs)


def test_queue_api_rejects_untrusted_next_page_url_before_request(monkeypatch):
    requests: list[str] = []

    class Response:
        headers = {
            "Link": '<https://evil.example/repos/owner/repo/actions/runs?per_page=100&status=queued&page=2>; rel="next"',
        }

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"total_count": 2, "workflow_runs": [{"id": 1}]}).encode()

    def open_request(request, timeout):
        requests.append(request.full_url)
        return Response()

    monkeypatch.setattr(writer_queue, "urlopen", open_request)
    with pytest.raises(writer_queue.WriterQueueError, match="pagination link identity invalid"):
        writer_queue._fetch_runs(
            api_url="https://api.github.test", repository="owner/repo", token="token",
        )
    assert len(requests) == 1


def test_queue_api_fails_closed_when_count_requires_page_but_link_is_missing(monkeypatch):
    monkeypatch.setattr(writer_queue.time, "sleep", lambda _seconds: None)

    class Response:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"total_count": 2, "workflow_runs": [{"id": 1}]}).encode()

    monkeypatch.setattr(writer_queue, "urlopen", lambda *_args, **_kwargs: Response())
    with pytest.raises(writer_queue.WriterQueueError, match="pagination incomplete"):
        writer_queue._fetch_runs(
            api_url="https://api.github.test", repository="owner/repo", token="token",
        )


def test_queue_api_accepts_a_valid_run_transition_between_status_reads(monkeypatch):
    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.payload).encode()

    run = _run(42, "queued", created_at="2026-08-31T08:00:01Z")
    run["updated_at"] = "2026-08-31T08:00:02Z"

    def open_request(request, timeout):
        if "/runs/42/attempts/1/jobs?" in request.full_url:
            return Response({"total_count": 1, "jobs": [{
                "id": 4200,
                "name": "refresh-and-deploy",
                "status": "in_progress",
                "steps": [{
                    "name": "Wait for production writer queue",
                    "status": "in_progress",
                    "started_at": "2026-08-31T08:00:04Z",
                }],
            }]})
        status = request.full_url.split("status=", 1)[1].split("&", 1)[0]
        if status == "queued":
            return Response({"total_count": 1, "workflow_runs": [run]})
        if status == "in_progress":
            advanced = {**run, "status": "in_progress", "updated_at": "2026-08-31T08:00:03Z"}
            return Response({"total_count": 1, "workflow_runs": [advanced]})
        return Response({"total_count": 0, "workflow_runs": []})

    monkeypatch.setattr(writer_queue, "urlopen", open_request)
    rows = writer_queue._fetch_runs(
        api_url="https://api.github.test", repository="owner/repo", token="token",
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "in_progress"


def test_queued_writer_without_runner_does_not_hold_live_publication_gate(monkeypatch):
    class Response:
        def __init__(self, payload):
            self.payload = payload
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.payload).encode()

    blocker = {
        "id": 90, "run_attempt": 1, "path": ".github/workflows/official-event-monitor.yml",
        "workflow_id": 320209983, "status": "queued", "created_at": "2026-10-06T00:00:00Z",
        "run_started_at": None, "head_sha": "main-sha", "updated_at": "2026-10-06T00:00:00Z",
    }
    current = {
        "id": 100, "run_attempt": 1, "path": ".github/workflows/scheduled-brief.yml",
        "workflow_id": 318853044, "status": "in_progress", "created_at": "2026-10-06T00:05:00Z",
        "run_started_at": "2026-10-06T00:05:00Z", "head_sha": "main-sha",
        "updated_at": "2026-10-06T00:05:01Z",
    }

    def open_request(request, timeout):
        assert timeout > 0
        url = request.full_url
        if "/runs/90/attempts/1/jobs?" in url:
            return Response({"total_count": 1, "jobs": [{
                "id": 900, "name": "monitor-send-deploy", "status": "queued",
                "runner_id": 0, "started_at": None, "steps": [],
            }]})
        if "/runs/100/attempts/1/jobs?" in url:
            return Response({"total_count": 1, "jobs": [{
                "id": 1000, "name": "refresh-notify-deploy", "status": "in_progress",
                "runner_id": 77, "started_at": "2026-10-06T00:05:00Z", "steps": [{
                    "name": "Wait for production writer queue", "status": "in_progress",
                    "started_at": "2026-10-06T00:05:01Z",
                }],
            }]})
        status = url.split("status=", 1)[1].split("&", 1)[0]
        rows = {"queued": [blocker], "in_progress": [current]}.get(status, [])
        return Response({"total_count": len(rows), "workflow_runs": rows})

    monkeypatch.setattr(writer_queue, "urlopen", open_request)
    result = wait_for_slot(
        current_run_id=100, current_attempt=1, require_current_attempt=True,
        api_url="https://api.github.test", repository="owner/repo", token="token",
        timeout_seconds=60, settle_seconds=0, poll_seconds=1,
        sleeper=lambda _seconds: None,
    )

    assert result.status == "acquired"
    assert result.complete_snapshots == 2
    assert result.deferred_candidates == (90,)
    assert result.deferred_candidate_reasons == ("writer_job_not_started",)


def test_queued_writer_with_unavailable_steps_is_not_assumed_unstarted(monkeypatch):
    from src.writer_queue import RetryableQueueSnapshotError

    run = {
        "id": 90, "run_attempt": 1, "path": ".github/workflows/official-event-monitor.yml",
        "workflow_id": 320209983, "status": "queued", "created_at": "2026-10-06T00:00:00Z",
        "run_started_at": None,
    }

    class Response:
        headers = {}

        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.payload).encode()

    def open_request(request, timeout):
        if "/attempts/1/jobs?" in request.full_url:
            return Response({"total_count": 1, "jobs": [{
                "id": 900, "name": "monitor-send-deploy", "status": "queued",
                "runner_id": 0, "started_at": None, "steps": None,
            }]})
        return Response({"total_count": 1, "workflow_runs": [run]})

    monkeypatch.setattr(writer_queue, "urlopen", open_request)
    with pytest.raises(RetryableQueueSnapshotError, match="writer_publication_gate_steps_unavailable"):
        writer_queue._fetch_runs_once(
            api_url="https://api.github.test", repository="owner/repo", token="token",
        )


def test_real_github_queued_writer_timestamps_do_not_prove_runner_or_gate(monkeypatch):
    run = {
        "id": 37349718666,
        "run_attempt": 1,
        "path": ".github/workflows/official-event-monitor.yml",
        "workflow_id": 320209983,
        "status": "queued",
        "created_at": "2026-10-05T17:36:42Z",
        # GitHub returned these non-empty placeholders for an unstarted run.
        "run_started_at": "2026-10-05T17:36:42Z",
    }
    job = {
        "id": 111897193426,
        "name": "monitor-send-deploy",
        "status": "queued",
        "runner_id": None,
        "started_at": "2026-10-05T17:36:43Z",
        "steps": [],
    }
    monkeypatch.setattr(
        writer_queue,
        "_fetch_attempt_jobs",
        lambda **_kwargs: [job],
    )

    candidate = dict(run)
    deferred = writer_queue._annotate_publication_gate(
        candidate,
        api_url="https://api.github.test",
        repository="owner/repo",
        token="token",
        deadline_monotonic=None,
    )

    assert deferred["run_id"] == 37349718666
    assert deferred["attempt"] == 1
    assert deferred["reason"] == "writer_job_not_started"
    assert candidate["queue_gate_state"] == "deferred"


def test_github_waiting_environment_job_with_started_timestamps_and_empty_steps_is_deferred(monkeypatch):
    run = {
        "id": 37518565189,
        "run_attempt": 1,
        "path": ".github/workflows/scheduled-brief.yml",
        "workflow_id": 318853044,
        "status": "waiting",
        "created_at": "2026-10-06T19:23:11Z",
        "run_started_at": "2026-10-06T19:23:11Z",
        "head_sha": "ce7f0ec273014dd173c4928feebb31c70280b266",
    }
    job = {
        "id": 112457723411,
        "name": "refresh-notify-deploy",
        "status": "waiting",
        "runner_id": None,
        "started_at": "2026-10-06T19:23:12Z",
        "steps": [],
    }
    monkeypatch.setattr(writer_queue, "_fetch_attempt_jobs", lambda **_kwargs: [job])

    candidate = dict(run)
    deferred = writer_queue._annotate_publication_gate(
        candidate,
        api_url="https://api.github.test",
        repository="owner/repo",
        token="token",
        deadline_monotonic=None,
    )

    assert deferred["run_id"] == 37518565189
    assert deferred["attempt"] == 1
    assert deferred["reason"] == "writer_job_not_started"
    assert deferred["observed_status"] == "waiting"
    assert deferred["job_status"] == "waiting"
    assert deferred["runner_assigned"] is False
    assert deferred["observed_steps"] == 0
    assert candidate["queue_gate_state"] == "deferred"
    assert candidate["queue_gate_observed_steps"] == 0
    assert candidate["queue_gate_runner_assigned"] is False


def test_active_runner_with_unavailable_steps_is_retried_not_misclassified(monkeypatch):
    from src.writer_queue import RetryableQueueSnapshotError

    run = {
        "id": 37518565189,
        "run_attempt": 1,
        "path": ".github/workflows/scheduled-brief.yml",
        "workflow_id": 318853044,
        "status": "in_progress",
    }
    job = {
        "id": 112457723411,
        "name": "refresh-notify-deploy",
        "status": "in_progress",
        "runner_id": 741,
        "started_at": "2026-10-06T19:23:12Z",
        "steps": None,
    }
    monkeypatch.setattr(writer_queue, "_fetch_attempt_jobs", lambda **_kwargs: [job])

    with pytest.raises(RetryableQueueSnapshotError, match="writer_publication_gate_steps_unavailable"):
        writer_queue._annotate_publication_gate(
            run,
            api_url="https://api.github.test",
            repository="owner/repo",
            token="token",
            deadline_monotonic=None,
        )

    assert run["queue_gate_job_id"] == 112457723411


def test_active_gate_job_with_runner_but_missing_step_is_recovered_not_deferred(monkeypatch):
    from src.writer_queue import RetryableQueueSnapshotError

    candidate = {
        "id": 92,
        "run_attempt": 1,
        "path": ".github/workflows/scheduled-brief.yml",
        "workflow_id": 318853044,
        "status": "in_progress",
    }
    monkeypatch.setattr(writer_queue, "_fetch_attempt_jobs", lambda **_kwargs: [{
        "id": 920,
        "name": "refresh-notify-deploy",
        "status": "in_progress",
        "runner_id": 77,
        "steps": [],
    }])

    with pytest.raises(RetryableQueueSnapshotError, match="writer_publication_gate_step_not_visible"):
        writer_queue._annotate_publication_gate(
            candidate,
            api_url="https://api.github.test",
            repository="owner/repo",
            token="token",
            deadline_monotonic=None,
        )


def test_current_registered_gate_invocation_survives_delayed_empty_steps(monkeypatch):
    candidate = {
        "id": 1048,
        "run_attempt": 1,
        "path": ".github/workflows/official-event-monitor.yml",
        "workflow_id": 320209983,
        "status": "in_progress",
        "head_sha": "a" * 40,
    }
    job = {
        "id": 123456,
        "name": "monitor-send-deploy",
        "status": "in_progress",
        "runner_id": 42,
        "started_at": "2026-10-14T01:00:00Z",
        "steps": [],
    }
    monkeypatch.setenv("GITHUB_RUN_ID", "1048")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_JOB", "monitor-send-deploy")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setattr(writer_queue, "_fetch_attempt_jobs", lambda **_kwargs: [job])

    deferred = writer_queue._annotate_publication_gate(
        candidate,
        api_url="https://api.github.test",
        repository="owner/repo",
        token="token",
        deadline_monotonic=None,
    )

    assert deferred is None
    assert candidate["queue_gate_state"] == "admitted"
    assert candidate["queue_gate_evidence"] == "current_registered_gate_invocation"
    assert candidate["queue_gate_step_status"] == "in_progress_api_steps_delayed"


def test_current_gate_invocation_with_wrong_sha_does_not_bypass_missing_step(monkeypatch):
    from src.writer_queue import RetryableQueueSnapshotError

    candidate = {
        "id": 1048, "run_attempt": 1,
        "path": ".github/workflows/official-event-monitor.yml",
        "workflow_id": 320209983, "status": "in_progress", "head_sha": "a" * 40,
    }
    monkeypatch.setenv("GITHUB_RUN_ID", "1048")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_JOB", "monitor-send-deploy")
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    monkeypatch.setattr(writer_queue, "_fetch_attempt_jobs", lambda **_kwargs: [{
        "id": 123456, "name": "monitor-send-deploy", "status": "in_progress",
        "runner_id": 42, "steps": [],
    }])

    with pytest.raises(RetryableQueueSnapshotError, match="writer_publication_gate_step_not_visible"):
        writer_queue._annotate_publication_gate(
            candidate, api_url="https://api.github.test", repository="owner/repo",
            token="token", deadline_monotonic=None,
        )


def test_started_collection_before_pending_gate_is_deferred_but_later_step_is_not():
    from src.writer_queue import RetryableQueueSnapshotError

    candidate = {
        "id": 90,
        "run_attempt": 1,
        "path": ".github/workflows/official-event-monitor.yml",
        "workflow_id": 320209983,
        "status": "in_progress",
    }
    prior_step = {
        "name": "Collect official observations",
        "status": "completed",
        "started_at": "2026-10-06T00:00:01Z",
    }
    pending_gate = {
        "name": "Wait for production writer queue",
        "status": "queued",
        "started_at": None,
    }
    steps = [prior_step, pending_gate]

    def fetch(**_kwargs):
        return [{"id": 900, "name": "monitor-send-deploy", "status": "in_progress",
                 "runner_id": 77, "started_at": "2026-10-06T00:00:00Z", "steps": steps}]

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(writer_queue, "_fetch_attempt_jobs", lambda **_kwargs: fetch())
    try:
        assert writer_queue._annotate_publication_gate(
            candidate,
            api_url="https://api.github.test",
            repository="owner/repo",
            token="token",
            deadline_monotonic=None,
        )["reason"] == "publication_gate_not_reached"
        candidate["id"] = 91
        steps.append({"name": "Publish data-release", "status": "in_progress",
                      "started_at": "2026-10-06T00:00:02Z"})
        with pytest.raises(RetryableQueueSnapshotError):
            writer_queue._annotate_publication_gate(
                candidate,
                api_url="https://api.github.test",
                repository="owner/repo",
                token="token",
                deadline_monotonic=None,
            )
    finally:
        monkeypatch.undo()




def test_queue_api_restarts_from_first_page_after_transient_count_mismatch(monkeypatch):
    sleeps = []
    monkeypatch.setattr(writer_queue.time, "sleep", sleeps.append)
    calls = {"count": 0}

    class Response:
        headers = {}

        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.payload).encode()

    def open_request(request, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            return Response({"total_count": 2, "workflow_runs": [{"id": 1}]})
        return Response({"total_count": 0, "workflow_runs": []})

    monkeypatch.setattr(writer_queue, "urlopen", open_request)
    result = writer_queue._fetch_runs(
        api_url="https://api.github.test", repository="owner/repo", token="token",
    )
    assert result == []
    assert result.recovery_rounds == 1
    assert calls["count"] == 6
    assert sleeps == [2]


def test_wait_for_slot_requires_two_complete_empty_snapshots():
    calls = 0
    sleeps = []

    def fetcher(**_kwargs):
        nonlocal calls
        calls += 1
        return []

    result = wait_for_slot(
        current_run_id=11,
        current_created_at=datetime(2026, 8, 31, 8, 1, tzinfo=UTC),
        timeout_seconds=30,
        settle_seconds=0,
        fetcher=fetcher,
        sleeper=sleeps.append,
    )
    assert result.status == "acquired"
    assert result.complete_snapshots == 2
    assert calls == 2
    assert sleeps == [2]


def test_disappeared_blocker_requires_authoritative_terminal_verification():
    rows = [[_run(10)], [], []]
    verified = []

    def fetcher(**_kwargs):
        return rows.pop(0)

    def verify(run, **_kwargs):
        verified.append(run["id"])
        return False

    result = wait_for_slot(
        current_run_id=11,
        current_created_at=datetime(2026, 8, 31, 8, 1, tzinfo=UTC),
        timeout_seconds=30,
        poll_seconds=1,
        settle_seconds=0,
        fetcher=fetcher,
        blocker_verifier=verify,
        sleeper=lambda _seconds: None,
    )
    assert result.status == "acquired"
    assert verified == [10]
    assert result.verified_blockers == ()


def test_previously_admitted_blocker_cannot_disappear_while_attempt_is_active(monkeypatch):
    rows = [[_run(10)], [], []]
    now = [0.0]
    monkeypatch.setattr(writer_queue.time, "monotonic", lambda: now[0])

    def fetcher(**_kwargs):
        return rows.pop(0)

    def verify(_run_row, **_kwargs):
        return True

    def sleep(seconds):
        now[0] += seconds

    with pytest.raises(WriterQueueTimeout) as raised:
        wait_for_slot(
            current_run_id=11,
            current_created_at=datetime(2026, 8, 31, 8, 1, tzinfo=UTC),
            timeout_seconds=2,
            poll_seconds=1,
            settle_seconds=0,
            fetcher=fetcher,
            blocker_verifier=verify,
            sleeper=sleep,
        )
    assert raised.value.blockers == (10,)





def test_scheduled_queue_wait_preserves_slot_delivery_reserve():
    anchor = "2026-09-29T14:20:00+08:00"
    context = {
        "scheduled_slot": "post_close",
        "scheduled_for_at": anchor,
        "delivery_intent": "notify_candidate",
    }
    budget, deadline = writer_queue._scheduled_queue_budget(
        context,
        requested_seconds=3300,
        now=datetime.fromisoformat("2026-09-29T14:25:00+08:00"),
    )
    assert budget == 12 * 60
    assert deadline == "2026-09-29T06:50:00+00:00"

    expired = writer_queue._scheduled_queue_budget(
        context,
        requested_seconds=3300,
        now=datetime.fromisoformat("2026-09-29T14:45:00+08:00"),
    )
    assert expired[0] == 0


def test_scheduled_notification_queue_requires_immutable_anchor():
    with pytest.raises(writer_queue.WriterQueueError, match="scheduled_queue_anchor_missing"):
        writer_queue._scheduled_queue_budget(
            {"scheduled_slot": "morning", "delivery_intent": "notify_candidate"},
            requested_seconds=3300,
            now=datetime.fromisoformat("2026-10-06T06:00:00+08:00"),
        )


def test_scheduled_notification_queue_rejects_unknown_slot_deadline():
    with pytest.raises(writer_queue.WriterQueueError, match="scheduled_queue_slot_invalid"):
        writer_queue._scheduled_queue_budget(
            {
                "scheduled_slot": "unrecognized",
                "scheduled_for_at": "2026-10-06T06:00:00+08:00",
                "delivery_intent": "notify_candidate",
            },
            requested_seconds=3300,
            now=datetime.fromisoformat("2026-10-06T06:00:00+08:00"),
        )


def test_us_queue_wait_stops_before_exchange_open_reserve():
    context = {
        "scheduled_slot": "us_premarket",
        "scheduled_for_at": "2026-09-29T21:00:00+08:00",
        "delivery_intent": "notify_candidate",
    }
    budget, deadline = writer_queue._scheduled_queue_budget(
        context,
        requested_seconds=3300,
        now=datetime.fromisoformat("2026-09-29T09:15:00-04:00"),
    )
    assert budget == 2 * 60
    assert deadline == "2026-09-29T13:30:00+00:00"


def test_morning_queue_cutoff_preserves_prepare_and_delivery_windows():
    context = {
        "scheduled_slot": "morning",
        "scheduled_for_at": "2026-10-06T06:00:00+08:00",
        "delivery_intent": "notify_candidate",
    }
    budget, deadline = writer_queue._scheduled_queue_budget(
        context,
        requested_seconds=3300,
        now=datetime.fromisoformat("2026-10-06T06:00:00+08:00"),
    )
    assert budget == 17 * 60
    assert deadline == "2026-10-05T22:30:00+00:00"


def test_production_revision_fence_allows_current_main():
    assert evaluate_production_revision(run_sha="abc123", main_sha="ABC123") == {
        "allowed": True,
        "reason": "current_production_revision",
    }


def test_production_revision_fence_blocks_stale_workflow():
    assert evaluate_production_revision(run_sha="old-sha", main_sha="new-sha") == {
        "allowed": False,
        "reason": "stale_workflow_revision",
    }


def test_production_revision_fence_blocks_missing_revision():
    assert evaluate_production_revision(run_sha="", main_sha="main-sha") == {
        "allowed": False,
        "reason": "production_revision_unavailable",
    }


def test_only_bounded_queue_observation_failures_are_incident_degradations():
    assert writer_queue.queue_error_is_degraded(WriterQueueTimeout((), 90, 1))
    assert writer_queue.queue_error_is_degraded(
        writer_queue.RetryableQueueSnapshotError("writer_publication_gate_step_not_visible")
    )
    assert not writer_queue.queue_error_is_degraded(
        WriterQueueError("writer_publication_gate_workflow_identity_mismatch")
    )


@pytest.mark.parametrize(
    ("error", "expected_code", "expected_exit", "expected_business"),
    [
        (
            writer_queue.RetryableQueueSnapshotError("writer_publication_gate_step_not_visible"),
            "writer_publication_gate_step_not_visible", 0, "degraded",
        ),
        (
            WriterQueueError("writer_publication_gate_workflow_identity_mismatch"),
            "writer_publication_gate_workflow_identity_mismatch", 1, "blocked",
        ),
    ],
)
def test_writer_queue_cli_hands_off_bounded_observation_failures_but_fails_contract_errors(
    monkeypatch, capsys, tmp_path, error, expected_code, expected_exit, expected_business,
):
    sha = "a" * 40
    monkeypatch.setenv("GITHUB_RUN_ID", "77")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_SHA", sha)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "github-output"))
    monkeypatch.setattr(sys, "argv", ["writer_queue", "--run-id", "77"])
    monkeypatch.setattr(
        writer_queue, "wait_for_slot",
        lambda **_kwargs: (_ for _ in ()).throw(error),
    )
    monkeypatch.setattr(writer_queue, "_fetch_main_revision", lambda **_kwargs: sha)

    assert main() == expected_exit
    output = (tmp_path / "github-output").read_text(encoding="utf-8")
    assert f"queue_error_code={expected_code}" in output
    assert f"business_status={expected_business}" in output
    assert "should_continue=false" in output
    message = capsys.readouterr().out
    assert ("::warning::" if expected_exit == 0 else "::error::") in message


def test_writer_queue_cli_stops_before_publication_when_main_moves(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_SHA", "old-sha")
    monkeypatch.setattr("src.writer_queue.wait_for_slot", lambda **_kwargs: None)
    monkeypatch.setattr("src.writer_queue._fetch_main_revision", lambda **_kwargs: "new-sha")
    monkeypatch.setattr(sys, "argv", ["writer_queue", "--run-id", "11", "--settle-seconds", "0"])

    output_path = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))

    assert main() == 0
    output = capsys.readouterr().out
    assert "stale_workflow_superseded" in output
    assert "queue_status=superseded" in output_path.read_text(encoding="utf-8")
    assert "should_continue=false" in output_path.read_text(encoding="utf-8")


def test_us_premarket_superseded_run_dispatches_one_fixed_slot_successor(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        "src.writer_queue._scheduled_queue_budget",
        lambda _context, *, requested_seconds: (requested_seconds, ""),
    )
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_SHA", "old-sha")
    monkeypatch.setenv("HANDOFF_PARENT_RUN_ID", "")
    monkeypatch.setenv("SLOT_CONTEXT", json.dumps({
        "scheduled_slot": "us_premarket",
        "scheduled_for_at": "2026-09-25T09:00:00-04:00",
        "contract_status": "valid",
        "delivery_intent": "notify_candidate",
        "dispatch_trace_id": "same-slot-trace",
    }))
    monkeypatch.setattr("src.writer_queue._fetch_main_revision", lambda **_kwargs: "new-main-sha")
    monkeypatch.setattr("src.writer_queue.wait_for_slot", lambda **_kwargs: None)
    monkeypatch.setattr("src.scheduled_handoff._utc_now", lambda: datetime.fromisoformat("2026-09-25T13:05:00+00:00"))
    calls = []

    def dispatch(*args, **kwargs):
        calls.append((args, kwargs))
        return {"status": "delivered", "reason": "handoff_child_completed", "handoff_id": "us_premarket-2026-09-25-11", "child_run_id": 12, "request_outcome": "accepted"}

    monkeypatch.setattr("src.scheduled_handoff.dispatch_and_wait", dispatch)
    monkeypatch.setattr(sys, "argv", ["writer_queue", "--run-id", "11", "--settle-seconds", "0"])
    output_path = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))

    assert main() == 0
    output = output_path.read_text(encoding="utf-8")
    assert "queue_status=handoff_completed" in output
    assert "handoff_status=delivered" in output
    assert "handoff_run_id=12" in output
    assert len(calls) == 1
    assert "stale_workflow_superseded" not in capsys.readouterr().out


def test_handoff_child_cannot_start_a_second_successor(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        "src.writer_queue._scheduled_queue_budget",
        lambda _context, *, requested_seconds: (requested_seconds, ""),
    )
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_SHA", "old-sha")
    monkeypatch.setenv("HANDOFF_PARENT_RUN_ID", "10")
    monkeypatch.setenv("HANDOFF_PARENT_VERIFIED", "true")
    monkeypatch.setenv("SLOT_CONTEXT", json.dumps({
        "scheduled_slot": "us_premarket", "scheduled_for_at": "2026-09-25T09:00:00-04:00",
        "contract_status": "valid", "delivery_intent": "notify_candidate",
    }))
    observed = {}

    def superseded(**kwargs):
        observed.update(kwargs)
        return QueueResult(12, 3, (), status="superseded", reason="stale_workflow_revision", run_sha="old-sha", main_sha="new-main-sha")

    monkeypatch.setattr("src.writer_queue.wait_for_slot", superseded)
    monkeypatch.setattr(
        "src.scheduled_handoff.dispatch_and_wait",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("a handoff child must never re-dispatch")),
    )
    monkeypatch.setattr(sys, "argv", ["writer_queue", "--run-id", "20", "--settle-seconds", "0"])
    output_path = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))

    assert main() == 0
    output = output_path.read_text(encoding="utf-8")
    assert observed["ignored_run_ids"] == (10,)
    assert "queue_status=superseded" in output
    assert "handoff_status=not_attempted" in output
    assert "handoff_status=delivered" not in output


def test_unverified_handoff_parent_is_never_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_SHA", "current-sha")
    monkeypatch.setenv("HANDOFF_PARENT_RUN_ID", "10")
    monkeypatch.setenv("HANDOFF_PARENT_VERIFIED", "false")
    monkeypatch.setattr(sys, "argv", ["writer_queue", "--run-id", "20", "--settle-seconds", "0"])
    output_path = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    assert main() == 1
    assert "handoff_parent_not_verified" in output_path.read_text(encoding="utf-8")


def test_publication_admission_artifact_is_verified_against_run_attempt_and_job(monkeypatch):
    run = _run(420, run_attempt=2)
    run["head_sha"] = "a" * 40
    gate = writer_queue.WRITER_QUEUE_GATES[str(run["path"])]
    workflow_hash = "b" * 64
    record = {
        "schema_version": "writer-publication-admission-v1",
        "run_id": 420, "attempt": 2, "job_id": 4200,
        "job_name": gate["job_name"], "workflow_id": gate["workflow_id"],
        "workflow_path": run["path"], "workflow_sha": "a" * 40,
        "workflow_content_sha256": workflow_hash,
        "contract_fingerprint": writer_queue.publication_gate_contract_fingerprint(
            str(run["path"]), gate, workflow_hash,
        ),
    }
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("writer-publication-admission.json", json.dumps(record))
    monkeypatch.setattr(writer_queue, "_request_json", lambda *_args, **_kwargs: ({
        "total_count": 1,
        "artifacts": [{
            "id": 55, "name": "writer-publication-admission-420-2",
            "expired": False, "created_at": "2026-10-16T02:00:00Z",
            "workflow_run": {"id": 420, "head_sha": "a" * 40},
        }],
    }, None))
    monkeypatch.setattr(writer_queue, "_open_artifact_url", lambda *_args, **_kwargs: io.BytesIO(archive_buffer.getvalue()))

    evidence = _read_publication_admission(
        run=run, gate=gate, job_id=4200,
        api_url="https://api.github.com", repository="owner/repo", token="token",
        deadline_monotonic=writer_queue.time.monotonic() + 10,
        trusted_contract={
            "workflow_content_sha256": workflow_hash,
            "source_commit_sha": "a" * 40,
        },
    )
    assert evidence is not None
    assert evidence["artifact_id"] == 55
    assert evidence["created_at"] == "2026-10-16T02:00:00+00:00"
    assert evidence["contract_fingerprint"] == record["contract_fingerprint"]


def test_verified_workflow_contract_matches_exact_sha_source_bytes(monkeypatch):
    path = ".github/workflows/official-event-monitor.yml"
    revision = "d" * 40
    source = (writer_queue.Path(__file__).parents[1] / path).read_bytes().replace(b"\r\n", b"\n")
    git_blob_sha = hashlib.sha1(
        b"blob " + str(len(source)).encode("ascii") + b"\0" + source,
    ).hexdigest()
    requests = []

    def fake_request(url, **_kwargs):
        requests.append(url)
        return ({
            "path": path,
            "type": "file",
            "encoding": "base64",
            "size": len(source),
            "sha": git_blob_sha,
            "content": __import__("base64").b64encode(source).decode("ascii"),
        }, None)

    monkeypatch.setattr(writer_queue, "_request_json", fake_request)
    writer_queue._WORKFLOW_CONTENT_HASH_CACHE.pop((revision, path), None)
    contract = _verified_workflow_contract({
        "path": path,
        "head_sha": revision,
        "workflow_id": writer_queue.WRITER_WORKFLOW_IDENTITIES[path],
    }, api_url="https://api.github.com", repository="owner/repo", token="token",
       deadline_monotonic=writer_queue.time.monotonic() + 10)

    assert requests == [
        f"https://api.github.com/repos/owner/repo/contents/{path}?ref={revision}"
    ]
    assert contract["workflow_content_sha256"] == hashlib.sha256(source).hexdigest()
    assert contract["gate_step"] == writer_queue.WRITER_QUEUE_GATES[path]["step_name"]


def test_workflow_content_hash_is_stable_across_checkout_line_endings(tmp_path, monkeypatch):
    path = ".github/workflows/official-event-monitor.yml"
    source = b"name: test workflow\njobs:\n  check:\n    runs-on: ubuntu-latest\n"
    target = tmp_path / path
    target.parent.mkdir(parents=True)
    target.write_bytes(source.replace(b"\n", b"\r\n"))
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))

    assert writer_queue._workflow_content_hash(path) == hashlib.sha256(source).hexdigest()


def test_verified_workflow_contract_rejects_unknown_source(monkeypatch):
    path = ".github/workflows/official-event-monitor.yml"
    revision = "e" * 40
    source = b"name: changed without an approved writer gate\n"
    git_blob_sha = hashlib.sha1(
        b"blob " + str(len(source)).encode("ascii") + b"\0" + source,
    ).hexdigest()
    monkeypatch.setattr(writer_queue, "_request_json", lambda *_a, **_k: ({
        "path": path,
        "type": "file",
        "encoding": "base64",
        "size": len(source),
        "sha": git_blob_sha,
        "content": __import__("base64").b64encode(source).decode("ascii"),
    }, None))
    writer_queue._WORKFLOW_CONTENT_HASH_CACHE.pop((revision, path), None)

    with pytest.raises(WriterQueueError, match="workflow_contract_sha_unknown"):
        _verified_workflow_contract({
            "path": path,
            "head_sha": revision,
            "workflow_id": writer_queue.WRITER_WORKFLOW_IDENTITIES[path],
        }, api_url="https://api.github.com", repository="owner/repo", token="token",
           deadline_monotonic=writer_queue.time.monotonic() + 10)


def test_skipped_gate_with_started_at_is_not_admitted(monkeypatch):
    path = ".github/workflows/official-event-monitor.yml"
    gate = writer_queue.WRITER_QUEUE_GATES[path]
    run = {
        "id": 39698088993, "run_attempt": 1, "workflow_id": gate["workflow_id"],
        "path": path, "head_sha": "c" * 40, "status": "in_progress",
    }
    monkeypatch.setattr(writer_queue, "_fetch_attempt_jobs", lambda **_kwargs: [{
        "id": 1200001, "name": gate["job_name"], "status": "completed",
        "conclusion": "success", "runner_id": 21,
        "steps": [{
            "name": gate["step_name"], "status": "completed", "conclusion": "skipped",
            "started_at": "2026-10-22T00:14:46Z", "completed_at": "2026-10-22T00:14:46Z",
        }],
    }])

    deferred = writer_queue._annotate_publication_gate(
        run, api_url="https://api.github.com", repository="owner/repo", token="token",
        deadline_monotonic=writer_queue.time.monotonic() + 10,
    )

    assert deferred is not None
    assert deferred["reason"] == "publication_gate_skipped"
    assert run["queue_gate_state"] == "deferred"
    assert run["queue_gate_step_conclusion"] == "skipped"


def test_blocker_diagnostics_include_contract_and_terminal_observations():
    details = writer_queue._blocker_details([{
        "id": 123, "run_attempt": 2, "workflow_id": 320209983,
        "path": ".github/workflows/official-event-monitor.yml", "head_sha": "a" * 40,
        "queue_gate_workflow_sha": "a" * 40,
        "queue_gate_contract_fingerprint": "b" * 64,
        "queue_gate_contract_source": "a" * 40,
        "queue_gate_workflow_content_sha256": "c" * 64,
        "queue_gate_jobs_snapshot_complete": True,
        "queue_gate_protected_jobs_complete": True,
        "queue_gate_protected_job_states": [{"job": "monitor-send-deploy", "status": "completed", "conclusion": "success"}],
        "status": "in_progress", "queue_gate_job_status": "completed",
        "queue_gate_job_conclusion": "success", "queue_gate_step_conclusion": "skipped",
        "queue_gate_release_reason": "all_protected_jobs_terminal_after_complete_attempt_read",
        "queue_gate_state": "admitted", "queue_gate_reason": "",
        "queue_gate_runner_assigned": True, "queue_gate_observed_steps": 3,
        "queue_gate_started_at": "2026-10-24T04:00:00Z",
    }])[0]

    assert details["workflow_contract_source"] == "a" * 40
    assert details["workflow_content_sha256"] == "c" * 64
    assert details["protected_jobs_complete"] is True
    assert details["gate_conclusion"] == "skipped"
    assert details["release_reason"] == "all_protected_jobs_terminal_after_complete_attempt_read"


def test_admission_artifact_conflicts_with_skipped_gate(monkeypatch):
    path = ".github/workflows/official-event-monitor.yml"
    gate = writer_queue.WRITER_QUEUE_GATES[path]
    run = {
        "id": 39698088993, "run_attempt": 1, "workflow_id": gate["workflow_id"],
        "path": path, "head_sha": "c" * 40, "status": "in_progress",
    }
    monkeypatch.setattr(writer_queue, "_fetch_attempt_jobs", lambda **_kwargs: [{
        "id": 1200001, "name": gate["job_name"], "status": "completed",
        "conclusion": "success", "runner_id": 21,
        "steps": [{
            "name": gate["step_name"], "status": "completed", "conclusion": "skipped",
            "started_at": "2026-10-22T00:14:46Z",
        }],
    }])
    monkeypatch.setattr(writer_queue, "_read_publication_admission", lambda **_kwargs: {
        "artifact_id": 7, "created_at": "2026-10-22T00:14:00+00:00",
        "contract_fingerprint": "a" * 64,
    })

    with pytest.raises(WriterQueueError, match="admission_skipped_gate_conflict"):
        writer_queue._annotate_publication_gate(
            run, api_url="https://api.github.com", repository="owner/repo", token="token",
            deadline_monotonic=writer_queue.time.monotonic() + 10,
        )


def test_missing_writer_job_after_completed_declared_predecessor_is_deferred(monkeypatch):
    path = ".github/workflows/official-event-monitor.yml"
    gate = writer_queue.WRITER_QUEUE_GATES[path]
    run = {
        "id": 40071138384, "run_attempt": 1, "workflow_id": gate["workflow_id"],
        "path": path, "head_sha": "c" * 40, "status": "queued",
    }
    monkeypatch.setattr(writer_queue, "_fetch_attempt_jobs", lambda **_kwargs: [{
        "id": 1200002, "name": "monitor-admission", "status": "completed",
        "conclusion": "success", "steps": [{"name": "Persist monitor admission", "status": "completed"}],
    }])
    monkeypatch.setattr(writer_queue, "_publication_admission_artifact_exists", lambda **_kwargs: False)

    deferred = writer_queue._annotate_publication_gate(
        run, api_url="https://api.github.com", repository="owner/repo", token="token",
        deadline_monotonic=writer_queue.time.monotonic() + 10,
    )

    assert deferred is not None
    assert deferred["reason"] == "protected_job_handoff_not_visible"
    assert run["queue_gate_state"] == "deferred"


def test_writer_job_terminal_releases_even_when_workflow_run_is_active(monkeypatch):
    path = ".github/workflows/official-event-monitor.yml"
    gate = writer_queue.WRITER_QUEUE_GATES[path]
    run = {
        "id": 39698088993, "run_attempt": 1, "workflow_id": gate["workflow_id"],
        "path": path, "head_sha": "c" * 40, "status": "in_progress",
    }
    monkeypatch.setattr(
        writer_queue, "_fetch_attempt_jobs",
        lambda **_kwargs: [{
            "id": 1200001, "name": gate["job_name"], "status": "completed",
            "conclusion": "success", "steps": [],
        }],
    )
    attempt_payload = json.dumps({
        "id": run["id"], "run_attempt": 1, "workflow_id": gate["workflow_id"],
        "path": path, "status": "in_progress",
    }).encode()
    monkeypatch.setattr(writer_queue, "urlopen", lambda *_args, **_kwargs: io.BytesIO(attempt_payload))

    assert writer_queue._fetch_run_attempt(
        run, api_url="https://api.github.com", repository="owner/repo", token="token",
        deadline_monotonic=writer_queue.time.monotonic() + 10,
    ) is False


def test_create_publication_admission_binds_exact_checked_out_workflow(monkeypatch, tmp_path):
    path = ".github/workflows/refresh-dashboard.yml"
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", f"owner/repo/{path}@main")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(Path(__file__).resolve().parents[1]))
    monkeypatch.setenv("GITHUB_RUN_ID", "777")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "3")
    monkeypatch.setenv("GITHUB_SHA", "c" * 40)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    output = tmp_path / "admission.json"
    monkeypatch.setenv("WRITER_ADMISSION_PATH", str(output))
    gate = writer_queue.WRITER_QUEUE_GATES[path]
    monkeypatch.setattr(writer_queue, "_fetch_attempt_jobs", lambda **_kwargs: [{
        "id": 990, "name": gate["job_name"],
    }])

    record = writer_queue.create_publication_admission()
    assert record["job_id"] == 990
    assert record["attempt"] == 3
    assert record["workflow_content_sha256"] == hashlib.sha256(
        (Path(__file__).resolve().parents[1] / path).read_bytes().replace(b"\r\n", b"\n")
    ).hexdigest()
    assert json.loads(output.read_text(encoding="utf-8")) == record
