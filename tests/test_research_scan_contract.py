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
    assert result["publish_eligible"] is True
    assert result["production_eligible"] is False
    assert result["universe_completed"] == 29
