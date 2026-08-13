"""P0-25/P0-27 strategy provenance and paper-observation contracts."""

from src.paper_portfolio import build_paper_portfolio_snapshot, update_paper_observations
from src.strategy_registry import validate_strategy_release


def test_p0_25_partial_strategy_registry_stays_invalid() -> None:
    errors = validate_strategy_release({"strategy_id": "value", "strategy_version": "1"})
    assert "strategy_registry.parameter_hash is missing" in errors
    assert "strategy_registry.backtest_release is missing" in errors


def test_p0_25_complete_registry_metadata_is_accepted() -> None:
    assert validate_strategy_release({
        "strategy_id": "value", "strategy_version": "1", "parameter_hash": "p",
        "universe_version": "u", "data_version": "d", "code_commit": "c",
        "backtest_release": "bt",
    }) == []


def test_p0_27_paper_portfolio_blocks_unverified_candidates() -> None:
    result = build_paper_portfolio_snapshot(
        [{"ticker": "2330", "strategy": "value"}],
        [{"ticker": "2330", "price": 100, "freshness": "live"}],
    )
    assert result["state"] == "observation_only"
    assert result["records"] == []
    assert result["blocked_candidate_count"] == 1


def test_p0_27_paper_results_wait_for_later_public_closes() -> None:
    updated = update_paper_observations(
        [{"ticker": "2330", "observed_at": "2026-08-01", "simulated_entry_price": 100}],
        {"2330": [{"date": "2026-07-31", "close": 99}]},
    )[0]
    assert updated["tracking_state"] == "pending"
    assert updated["not_a_trade"] is True
    assert all(value is None for value in updated["horizons"].values())
