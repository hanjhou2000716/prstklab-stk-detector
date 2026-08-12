from src.production_integration import (
    annotate_instruments,
    bind_intelligence,
    bind_strategy_provenance,
    summarize_observations,
)


def test_unknown_instrument_is_not_guessed():
    rows = annotate_instruments([{"ticker": "NOT-A-REAL-SYMBOL", "price": 1}])
    assert rows[0]["instrument_resolution"] == "unknown"
    assert "instrument_id" not in rows[0]


def test_quality_summary_distinguishes_mixed_and_degraded():
    mixed = summarize_observations([
        {"ticker": "TAIEX", "freshness": "live"},
        {"ticker": "NASDAQ", "freshness": "recent_close"},
    ])
    assert mixed["overall_state"] == "mixed"
    degraded = summarize_observations([{"ticker": "TPEx", "freshness": "stale"}])
    assert degraded["overall_state"] == "degraded"


def test_strategy_without_backtest_remains_observation_only():
    binding = bind_strategy_provenance({"strategy": "momentum", "strategy_version": "1"})
    assert binding["state"] == "observation_only"
    assert "backtest_release" in binding["missing"]


def test_strategy_registry_mismatch_remains_observation_only():
    binding = bind_strategy_provenance({
        "strategy": "momentum", "strategy_version": "2", "data_version": "d1", "backtest_release": "bt1",
        "strategy_registry": {
            "strategy_id": "value", "strategy_version": "2", "data_version": "d1", "backtest_release": "bt1",
            "parameter_hash": "abc", "universe_version": "u1", "code_commit": "deadbeef",
        },
    })
    assert binding["state"] == "observation_only"
    assert binding["registry_state"] == "unverified"
    assert "strategy_registry" in binding["missing"]


def test_strategy_registry_complete_binding_is_verified():
    binding = bind_strategy_provenance({
        "strategy": "momentum", "strategy_version": "2", "data_version": "d1", "backtest_release": "bt1",
        "strategy_registry": {
            "strategy_id": "momentum", "strategy_version": "2", "data_version": "d1", "backtest_release": "bt1",
            "parameter_hash": "abc", "universe_version": "u1", "code_commit": "deadbeef",
        },
    })
    assert binding["state"] == "production"
    assert binding["registry_state"] == "verified"


def test_non_publishable_backtest_contract_remains_observation_only():
    binding = bind_strategy_provenance({
        "strategy": "momentum", "strategy_version": "2", "data_version": "d1", "backtest_release": "bt1",
        "backtest_release_contract": {
            "backtest_release": "bt1", "publication_state": "blocked", "publish_eligible": False,
        },
    })
    assert binding["state"] == "observation_only"
    assert binding["contract_state"] == "unverified"
    assert "backtest_release_contract" in binding["missing"]


def test_backtest_contract_must_match_candidate_release():
    binding = bind_strategy_provenance({
        "strategy": "momentum", "strategy_version": "2", "data_version": "d1", "backtest_release": "bt1",
        "backtest_release_contract": {
            "backtest_release": "bt-other", "publication_state": "ready", "publish_eligible": True,
        },
    })
    assert binding["state"] == "observation_only"
    assert "backtest_release does not match research contract" in binding["contract_errors"]


def test_intelligence_binding_fails_closed_when_release_ids_missing():
    result = bind_intelligence(
        {"advice_gate": "research_only"},
        snapshot={"generated_at": "2026-08-09T09:00:00+08:00"},
        observations=[{"ticker": "TAIEX", "freshness": "live"}],
    )
    binding = result["production_binding"]
    assert binding["state"] == "observation_only"
    assert binding["fail_closed"] is True
    assert result["advice_gate"] == "observation_only"


def test_intelligence_binding_preserves_valid_provenance():
    result = bind_intelligence(
        {"advice_gate": "research_only"},
        snapshot={
            "release_id": "r1", "snapshot_id": "s1", "observation_id": "o1",
            "source_tier": "official", "source_url": "https://example.test",
            "fetched_at": "2026-08-09T09:00:00+08:00", "published_at": "2026-08-09T08:59:00+08:00",
            "freshness": "live", "policy_version": "p1",
        },
        observations=[{"ticker": "TAIEX", "freshness": "live"}],
        candidate={"strategy": "momentum", "strategy_version": "1", "data_version": "d1", "backtest_release": "bt1"},
    )
    assert result["production_binding"]["state"] == "production"
    assert result["production_binding"]["strategy"]["state"] == "production"
