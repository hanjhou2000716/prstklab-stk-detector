from src.production_acceptance import _parse_time, production_research_contract_errors, validate_production_bundle


def _bundle():
    return {
        "manifest": {
            "status": "ready",
            "release_id": "release-1",
            "market_snapshot_id": "market-1",
            "research_snapshot_id": "research-1",
            "event_snapshot_id": "event-1",
        },
        "market": {"snapshot_id": "market-1", "overall_state": "mixed", "stale_count": 1},
        "research": {"snapshot_id": "research-1", "sources": [{"candidate_state": "no_candidates", "candidates": 0}]},
        "events": {"snapshot_id": "event-1", "events": []},
    }


def test_valid_bundle_is_allowed():
    result = validate_production_bundle(**_bundle())
    assert result.allowed


def test_live_market_with_stale_count_fails_closed():
    bundle = _bundle()
    bundle["market"].update(overall_state="live", stale_count=1)
    result = validate_production_bundle(**bundle)
    assert not result.allowed
    assert "overall_state live" in " ".join(result.errors)


def test_formal_candidates_cannot_exceed_visible_rows():
    bundle = _bundle()
    bundle["research"]["sources"][0] = {"candidate_state": "available", "candidates": 2, "formal_candidates": 3}
    result = validate_production_bundle(**bundle)
    assert not result.allowed


def test_high_risk_without_evidence_is_rejected():
    bundle = _bundle()
    bundle["events"]["events"] = [{"severity": "high-risk"}]
    result = validate_production_bundle(**bundle)
    assert not result.allowed


def test_incomplete_production_research_is_rejected():
    bundle = _bundle()
    bundle["research"].update(
        scan_mode="production",
        publish_eligible=False,
        production_eligible=False,
        universe_expected=10,
        universe_scanned=9,
        universe_completed=9,
    )
    result = validate_production_bundle(**bundle)
    assert not result.allowed
    assert "production research" in " ".join(result.errors)


def test_delivery_mode_rejects_legacy_research_snapshot():
    result = validate_production_bundle(**_bundle(), require_production_research=True)
    assert not result.allowed
    assert "not a production scan" in " ".join(result.errors)


def test_explicit_stale_fallback_is_deliverable_but_not_production_research():
    bundle = _bundle()
    bundle["research"].update(
        scan_mode="production",
        publication_state="fallback",
        research_fallback_used=True,
        production_eligible=False,
        publish_eligible=False,
        universe_expected=10,
        universe_scanned=3,
        universe_completed=3,
    )
    result = validate_production_bundle(**bundle, require_production_research=True)
    assert result.allowed


def test_production_contract_rejects_incomplete_source_metadata():
    research = {
        "scan_mode": "production", "scan_scope": "full",
        "publish_eligible": True, "production_eligible": True,
        "universe_expected": 1, "universe_scanned": 1, "universe_completed": 1,
        "sources": [{"scan_state": "building", "requested": 2, "complete_records": 1}],
    }
    errors = production_research_contract_errors(research)
    assert "research source 0 is not complete" in errors
    assert "research source 0 universe is incomplete" in errors


def test_acceptance_time_parser_is_fail_closed_for_naive_and_invalid_values():
    assert _parse_time("2026-08-09T10:00:00") is not None
    assert _parse_time("not-a-time") is None

