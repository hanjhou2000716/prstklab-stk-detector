from src.run_research_report import attach_scan_contract


def test_smoke_scan_is_never_publishable():
    report = {"sources": [{"requested": 30, "complete_records": 30, "failed": 0, "scan_state": "complete"}]}
    result = attach_scan_contract(report, "smoke")
    assert result["scan_scope"] == "bounded"
    assert result["publish_eligible"] is False
    assert result["production_eligible"] is False
    assert "isolated" in result["blocking_reason"]


def test_production_requires_full_scope_and_no_failures():
    report = {"sources": [{"requested": 30, "complete_records": 29, "failed": 1, "scan_state": "building"}]}
    result = attach_scan_contract(report, "production")
    assert result["publish_eligible"] is False
    assert result["production_eligible"] is False
    assert result["universe_completed"] == 29
    assert result["strategy_publication"][0]["eligible"] is False


def test_production_tracks_each_strategy_without_hiding_partial_scope():
    report = {"sources": [
        {"market": "taiwan", "strategy": "momentum", "requested": 2, "complete_records": 2, "failed": 0, "scan_state": "complete"},
        {"market": "us", "strategy": "value", "requested": 2, "complete_records": 1, "failed": 1, "scan_state": "building"},
    ]}
    result = attach_scan_contract(report, "production")
    assert result["strategy_publication"][0]["eligible"] is True
    assert result["strategy_publication"][1]["eligible"] is False
