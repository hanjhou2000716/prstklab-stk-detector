import sys

import pytest

from src.writer_queue import WriterQueueError, blocking_runs, evaluate_production_revision, main, wait_for_slot


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


def test_writer_queue_cli_stops_before_publication_when_main_moves(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_SHA", "old-sha")
    monkeypatch.setattr("src.writer_queue.wait_for_slot", lambda **_kwargs: None)
    monkeypatch.setattr("src.writer_queue._fetch_main_revision", lambda **_kwargs: "new-sha")
    monkeypatch.setattr(sys, "argv", ["writer_queue", "--run-id", "11", "--settle-seconds", "0"])

    assert main() == 1
    assert "stale_workflow_revision" in capsys.readouterr().out
