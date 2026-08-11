from src.research_report import build_research_report


def test_report_exposes_public_scan_coverage_when_summary_exists(tmp_path):
    scan = tmp_path / "scan.csv"
    scan.write_text("ticker,name\nNVDA,NVIDIA\n", encoding="utf-8")
    summary = tmp_path / "summary.json"
    summary.write_text('{"requested": 519, "data_complete": 510, "failed": 9}', encoding="utf-8")

    report = build_research_report([{
        "path": str(scan), "summary_path": str(summary), "market": "us", "strategy": "momentum"
    }])

    assert report["sources"][0]["requested"] == 519
    assert report["sources"][0]["data_complete"] == 510


def test_report_normalizes_missing_candidate_counts_and_structured_gaps(tmp_path):
    """Generated research never publishes null counts or drops gap detail."""
    scan = tmp_path / "scan.csv"
    scan.write_text("ticker,name\nNVDA,NVIDIA\n", encoding="utf-8")
    summary = tmp_path / "summary.json"
    summary.write_text(
        '{"requested": 10, "data_complete": 8, "failed": 0, '
        '"scan_state": "building", "partial_candidates_allowed": true, '
        '"data_gap_counts": '
        '{"history": 2, "quotes": 0}}',
        encoding="utf-8",
    )

    report = build_research_report([{
        "path": str(scan), "summary_path": str(summary),
        "market": "us", "strategy": "momentum",
    }])

    source = report["sources"][0]
    assert source["candidate_state"] == "available_from_completed_records"
    assert source["formal_candidates"] == 0
    assert source["observation_candidates"] == 0
    assert source["formal_candidate_count"] == 0
    assert source["observation_candidate_count"] == 0
    assert source["data_gap_counts"] == 2



def test_failed_scan_does_not_reuse_candidates_from_previous_csv(tmp_path):
    scan = tmp_path / "scan.csv"
    scan.write_text("ticker,name\n2330,Example\n", encoding="utf-8")
    summary = tmp_path / "summary.json"
    summary.write_text(
        '{"requested": 100, "data_complete": 0, "failed": 100, "scan_state": "failed", "status": "掃描失敗"}',
        encoding="utf-8",
    )

    report = build_research_report([{
        "path": str(scan), "summary_path": str(summary), "market": "taiwan", "strategy": "momentum"
    }])

    assert report["candidates"] == []
    assert report["sources"][0]["status"] == "掃描失敗"


def test_completed_empty_scan_is_not_reported_as_a_source_failure(tmp_path):
    scan = tmp_path / "scan.csv"
    scan.write_text("", encoding="utf-8")
    summary = tmp_path / "summary.json"
    summary.write_text('{"requested": 503, "data_complete": 503, "failed": 0, "scan_state": "complete"}', encoding="utf-8")

    report = build_research_report([{
        "path": str(scan), "summary_path": str(summary), "market": "us", "strategy": "value"
    }])

    assert report["sources"][0]["status"] == "本次無研究候選"


def test_verified_value_rows_remain_visible_during_incremental_history_build(tmp_path):
    scan = tmp_path / "scan.csv"
    scan.write_text("ticker,name,score\n2330,Example,88\n", encoding="utf-8")
    summary = tmp_path / "summary.json"
    summary.write_text(
        '{"requested": 150, "data_complete": 20, "failed": 18, '
        '"scan_state": "building", "status": "建檔中", '
        '"partial_candidates_allowed": true, "evaluable_records": 1}',
        encoding="utf-8",
    )

    report = build_research_report([{
        "path": str(scan), "summary_path": str(summary),
        "market": "taiwan", "strategy": "value",
    }])

    assert report["candidates"][0]["ticker"] == "2330"
    assert report["sources"][0]["status"] == "建檔中"


def test_missing_scan_output_suppresses_stale_formal_counts(tmp_path):
    """A summary must not make an unavailable CSV look like published rows."""
    summary = tmp_path / "summary.json"
    summary.write_text(
        '{"requested": 105, "data_complete": 97, "failed": 1, '
        '"scan_state": "failed", "formal_candidates": 5, '
        '"observation_candidates": 0}',
        encoding="utf-8",
    )

    report = build_research_report([{
        "path": str(tmp_path / "missing.csv"),
        "summary_path": str(summary),
        "market": "us",
        "strategy": "value",
    }])

    source = report["sources"][0]
    assert source["candidates"] == 0
    assert source["formal_candidates"] == 0
    assert source["observation_candidates"] == 0
    assert source["candidate_state"] == "data_gap"
