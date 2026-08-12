from src.production_acceptance import _parse_time, production_research_contract_errors, production_strategy_matrix_errors, validate_production_bundle


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


def test_strict_delivery_requires_all_market_strategy_sources():
    bundle = _bundle()
    bundle["research"].update(
        scan_mode="production", scan_scope="full", publish_eligible=True,
        production_eligible=True, universe_expected=1,
        universe_scanned=1, universe_completed=1, universe_failed=0,
        research_run={"run_id": "r", "source_commit_sha": "a" * 40,
                      "scan_mode": "production", "scan_scope": "full",
                      "run_finished_at": "2026-08-04T10:00:00+00:00"},
        run_id="r", generated_at="2026-08-04T10:00:00+00:00",
    )
    result = validate_production_bundle(**bundle, require_production_research=True)
    assert not result.allowed
    assert any("source matrix missing" in error for error in result.errors)


def test_strategy_matrix_rejects_duplicate_and_unknown_sources():
    research = {"sources": [
        {"market": "taiwan", "strategy": "momentum"},
        {"market": "taiwan", "strategy": "momentum"},
        {"market": "mars", "strategy": "momentum"},
    ]}
    errors = production_strategy_matrix_errors(research)
    assert any("duplicate taiwan/momentum" in error for error in errors)
    assert any("unknown entries" in error for error in errors)


def test_explicit_stale_fallback_is_blocked_from_production_delivery():
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
    assert not result.allowed
    assert "production release cannot use stale research fallback" in result.errors


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


def _complete_production_research():
    return {
        "scan_mode": "production",
        "scan_scope": "full",
        "publish_eligible": True,
        "production_eligible": True,
        "generated_at": "2026-08-12T10:00:00+00:00",
        "run_id": "run-1",
        "universe_expected": 2,
        "universe_scanned": 2,
        "universe_completed": 2,
        "universe_failed": 0,
        "research_run": {
            "run_id": "run-1",
            "source_commit_sha": "a" * 40,
            "scan_mode": "production",
            "scan_scope": "full",
            "run_finished_at": "2026-08-12T10:00:00+00:00",
        },
        "sources": [{
            "scan_state": "complete", "requested": 2, "universe_scanned": 2,
            "complete_records": 2, "failed": 0, "candidate_state": "no_candidates",
        }],
    }


def test_complete_production_research_requires_and_accepts_lineage():
    assert production_research_contract_errors(_complete_production_research()) == []


def test_production_research_rejects_mismatched_run_provenance():
    research = _complete_production_research()
    research["run_id"] = "different-run"
    errors = production_research_contract_errors(research)
    assert "research run_id does not match research_run provenance" in errors


def test_production_research_rejects_inconsistent_universe_counts():
    research = _complete_production_research()
    research["universe_scanned"] = 3
    errors = production_research_contract_errors(research)
    assert "production research universe counts are inconsistent" in errors


def test_available_source_requires_visible_candidates():
    research = _complete_production_research()
    research["sources"][0]["candidate_state"] = "available"
    research["sources"][0]["candidates"] = 0
    errors = production_research_contract_errors(research)
    assert "available state has no visible candidates" in errors[0]


def test_acceptance_time_parser_is_fail_closed_for_naive_and_invalid_values():
    assert _parse_time("2026-08-09T10:00:00") is not None
    assert _parse_time("not-a-time") is None


def test_production_research_rejects_generated_time_after_run_finish():
    research = _complete_production_research()
    research["generated_at"] = "2026-08-12T10:06:00+00:00"
    errors = production_research_contract_errors(research)
    assert "production research generated_at is after run_finished_at" in errors


def test_complete_source_cannot_claim_unavailable_provider():
    research = _complete_production_research()
    research["sources"][0]["source_unavailable"] = True
    errors = production_research_contract_errors(research)
    assert "complete state contradicts unavailable source" in " ".join(errors)


def test_candidate_state_cannot_contradict_scan_state():
    research = _complete_production_research()
    research["sources"][0]["candidate_state"] = "data_unavailable"
    errors = production_research_contract_errors(research)
    assert any("complete state contradicts candidate state data_unavailable" in error for error in errors)


def test_no_candidates_state_cannot_have_visible_rows():
    research = _complete_production_research()
    research["sources"][0].update(candidate_state="no_candidates", visible_candidates=1)
    errors = production_research_contract_errors(research)
    assert any("no_candidates state has visible candidates" in error for error in errors)

