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


def test_completed_empty_scan_is_not_reported_as_a_source_failure(tmp_path):
    scan = tmp_path / "scan.csv"
    scan.write_text("", encoding="utf-8")
    summary = tmp_path / "summary.json"
    summary.write_text('{"requested": 503, "data_complete": 503, "failed": 0, "scan_state": "complete"}', encoding="utf-8")

    report = build_research_report([{
        "path": str(scan), "summary_path": str(summary), "market": "us", "strategy": "value"
    }])

    assert report["sources"][0]["status"] == "本次無研究候選"
