from src.production_acceptance import validate_production_bundle


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

