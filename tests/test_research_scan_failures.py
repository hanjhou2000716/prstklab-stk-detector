from src.research_scan_failures import apply_scan_failures, load_scan_failures


def test_load_scan_failures_ignores_malformed_lines(tmp_path):
    path = tmp_path / "failures.ndjson"
    path.write_text('{"market":"us","strategy":"momentum","exit_code":1}\nnot-json\n', encoding="utf-8")
    assert load_scan_failures(path) == [{"market": "us", "strategy": "momentum", "exit_code": 1}]


def test_apply_scan_failures_blocks_publication_without_fabricating_candidates():
    report = {"sources": [{"market": "us", "strategy": "momentum", "scan_state": "complete", "failed_records": 0}], "production_eligible": True, "publish_eligible": True, "publication_state": "production"}
    result = apply_scan_failures(report, [{"market": "us", "strategy": "momentum", "exit_code": 1}])
    assert result["sources"][0]["scan_state"] == "failed"
    assert result["sources"][0]["candidate_state"] == "data_gap"
    assert result["production_eligible"] is False
    assert result["publish_eligible"] is False
    assert result["scan_failure_count"] == 1


def test_apply_scan_failures_exposes_bounded_failure_evidence():
    report = {"sources": [{"market": "us", "strategy": "value"}]}
    failures = [{
        "market": "us", "strategy": "value", "attempts": 2,
        "exit_code": 3, "started_at": "2026-08-11T00:00:00+00:00",
        "finished_at": "2026-08-11T00:01:00+00:00", "error": "provider unavailable",
    }]
    apply_scan_failures(report, failures)
    evidence = report["sources"][0]["failure_evidence"]
    assert evidence["attempts"] == 2
    assert evidence["exit_code"] == 3
    assert evidence["error"] == "provider unavailable"
