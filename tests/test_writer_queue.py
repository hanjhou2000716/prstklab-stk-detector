import pytest

from src.writer_queue import WriterQueueError, blocking_runs, wait_for_slot


def _run(run_id: int, status: str = "in_progress", name: str = "Refresh market dashboard") -> dict[str, object]:
    return {
        "id": run_id,
        "name": name,
        "status": status,
        "created_at": "2026-08-31T08:00:00Z",
    }


def test_blocking_runs_only_returns_older_active_production_writers():
    rows = blocking_runs(
        [_run(10), _run(11, "queued"), _run(12, "completed"), _run(13, name="Quality and delivery")],
        current_run_id=12,
    )
    assert [row["id"] for row in rows] == [10, 11]


def test_wait_for_slot_waits_until_older_writer_finishes():
    responses = [[_run(10)], []]
    sleeps: list[int] = []

    def fetcher(**_kwargs):
        return responses.pop(0)

    result = wait_for_slot(
        current_run_id=11,
        api_url="https://api.github.test",
        repository="owner/repo",
        token="token",
        timeout_seconds=30,
        poll_seconds=2,
        settle_seconds=0,
        fetcher=fetcher,
        sleeper=sleeps.append,
    )

    assert result.checks == 2
    assert sleeps == [2]


def test_wait_for_slot_fails_closed_when_lookup_fails():
    def fetcher(**_kwargs):
        raise WriterQueueError("lookup failed")

    with pytest.raises(WriterQueueError, match="lookup failed"):
        wait_for_slot(
            current_run_id=11,
            api_url="https://api.github.test",
            repository="owner/repo",
            token="token",
            timeout_seconds=5,
            poll_seconds=1,
            settle_seconds=0,
            fetcher=fetcher,
            sleeper=lambda _seconds: None,
        )
