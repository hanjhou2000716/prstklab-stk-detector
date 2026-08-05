import pytest

from src.portfolio_risk import portfolio_risk_snapshot


POSITIONS = [
    {"ticker": "AAA", "value": 60, "sector": "tech", "country": "US", "currency": "USD", "beta": 1.2},
    {"ticker": "BBB", "value": 40, "sector": "energy", "country": "TW", "currency": "TWD", "beta": 0.8},
]


def test_portfolio_risk_is_ephemeral_and_explains_exposures():
    result = portfolio_risk_snapshot(POSITIONS, [-0.1, 0.02, -0.03, 0.04])
    assert result["largest_position"] == 0.6
    assert result["weighted_beta"] == 1.04
    assert result["sector_exposure"] == {"energy": 0.4, "tech": 0.6}
    assert result["historical_var"] == 0.1
    assert result["persisted"] is False
    assert result["advice_allowed"] is False


def test_portfolio_risk_rejects_negative_value():
    with pytest.raises(ValueError):
        portfolio_risk_snapshot([{"ticker": "BAD", "value": -1}])
