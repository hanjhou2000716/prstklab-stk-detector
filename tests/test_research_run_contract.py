from datetime import UTC, datetime

from src.research_run_contract import attach_research_run, build_research_run


def test_run_contract_is_traceable_and_normalizes_times():
    result = build_research_run(
        scan_mode="production",
        scan_scope="full",
        started_at="2026-08-11T01:00:00+08:00",
        finished_at="2026-08-11T01:02:00+08:00",
        run_id="github-123-1",
        source_commit_sha="a" * 40,
    )
    assert result["run_id"] == "github-123-1"
    assert result["source_commit_sha"] == "a" * 40
    assert result["run_started_at"].endswith("+00:00")
    assert result["scan_scope"] == "full"


def test_attach_stamps_candidates_without_changing_values():
    report = {"candidates": [{"ticker": "2330", "score": 9}], "sources": []}
    attach_research_run(
        report,
        scan_mode="smoke",
        scan_scope="bounded",
        started_at=datetime(2026, 8, 11, tzinfo=UTC),
        finished_at=datetime(2026, 8, 11, 0, 1, tzinfo=UTC),
        run_id="local-test",
        source_commit_sha=None,
    )
    assert report["candidates"][0]["ticker"] == "2330"
    assert report["candidates"][0]["research_run_id"] == "local-test"
    assert report["run_id"] == "local-test"

