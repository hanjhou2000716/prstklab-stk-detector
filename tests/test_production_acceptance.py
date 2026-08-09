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

