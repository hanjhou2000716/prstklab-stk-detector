from src.strategy_registry import parameter_hash, register_strategy


def test_parameter_hash_is_stable_and_registry_is_explicit():
    assert parameter_hash({"b": 2, "a": 1}) == parameter_hash({"a": 1, "b": 2})
    record = register_strategy("momentum", version="1.0", parameters={"threshold": 80}, universe_version="u1", data_version="d1", code_commit="abc")
    assert record.parameter_hash
    assert record.backtest_release is None


def test_registry_requires_identity():
    try:
        register_strategy("", version="1", parameters={}, universe_version="u", data_version="d", code_commit="c")
    except ValueError:
        pass
    else:
        raise AssertionError("missing strategy identity must fail")
