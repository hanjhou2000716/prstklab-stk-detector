from src.strategy_registry import validate_strategy_release


def test_registry_validation_rejects_partial_row():
    errors = validate_strategy_release({"strategy_id": "momentum", "strategy_version": "1"})
    assert "strategy_registry.parameter_hash is missing" in errors
    assert "strategy_registry.backtest_release is missing" in errors


def test_registry_validation_rejects_non_string_identity():
    errors = validate_strategy_release({
        "strategy_id": "momentum", "strategy_version": 1,
        "parameter_hash": "p", "universe_version": "u", "data_version": "d",
        "code_commit": "c", "backtest_release": "b",
    })
    assert "strategy_registry.strategy_version must be a string" in errors


def test_registry_validation_accepts_complete_row():
    assert validate_strategy_release({
        "strategy_id": "momentum", "strategy_version": "1", "parameter_hash": "p",
        "universe_version": "u", "data_version": "d", "code_commit": "c",
        "backtest_release": "b",
    }) == []
