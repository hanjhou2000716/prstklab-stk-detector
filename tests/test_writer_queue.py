import json
import sys
from datetime import UTC, datetime

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
                "runner_id": 0, "started_at": None, "steps": None,
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


def test_queued_writer_with_unavailable_steps_only_defers_without_runner(monkeypatch):
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
    result = writer_queue._fetch_runs_once(
        api_url="https://api.github.test", repository="owner/repo", token="token",
    )
    assert result[0]["queue_gate_state"] == "deferred"
    assert result.deferred_candidates == ({"run_id": 90, "attempt": 1, "reason": "writer_job_not_started"},)


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

    assert deferred == {
        "run_id": 37349718666,
        "attempt": 1,
        "reason": "writer_job_not_started",
    }
    assert candidate["queue_gate_state"] == "deferred"


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
