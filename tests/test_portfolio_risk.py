from src.portfolio_risk import Position, exposure_report, stress_position_values


def test_exposure_report_is_in_memory_and_explainable():
    report = exposure_report([Position("A", 60, "tech", "TW", "TWD"), Position("B", 40, "energy", "US", "USD")], total_cash=100)
    assert report["total_value"] == 200
    assert report["cash_weight"] == 0.5
    assert report["sector_weights"]["tech"] == 0.3
    assert report["research_only"]


def test_stress_is_hypothetical_only():
    values = stress_position_values([Position("A", 100)], {"A": -0.1})
    assert values == {"A": 90.0}
