from src.contagion_monitor import active_contagion, detect_contagion


def test_detects_joint_equity_bond_selloff():
    signals = detect_contagion({"equity_return": -0.02, "bond_return": -0.01,
                                "usd_return": 0.0, "gold_return": 0.0,
                                "vix_return": 0.0, "asia_return": 0.0,
                                "semiconductor_return": 0.0, "crypto_return": 0.0})
    assert any(item.name == "equity_bond_selloff" for item in active_contagion(signals))


def test_missing_observation_is_not_calm():
    signals = detect_contagion({"equity_return": -0.02})
    item = next(item for item in signals if item.name == "equity_bond_selloff")
    assert item.quality == "partial"
    assert not item.active


def test_correlation_break_is_high_severity():
    signals = detect_contagion({}, correlations={"equity_bond": -0.8})
    item = next(item for item in signals if item.name == "correlation_break:equity_bond")
    assert item.severity == "high"
