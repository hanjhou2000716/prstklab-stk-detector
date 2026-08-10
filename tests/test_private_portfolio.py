from src.private_portfolio import build_private_portfolio_view


def test_private_portfolio_view_is_never_publishable_or_deliverable():
    result = build_private_portfolio_view([
        {"ticker": "AAA", "value": 100, "sector": "tech", "country": "US", "currency": "USD"},
    ])
    assert result["visibility"] == "private_local_only"
    assert result["storage"] == "caller_memory_only"
    assert result["public_release_eligible"] is False
    assert result["telegram_delivery_allowed"] is False
    assert result["account_access"] is False
    assert result["trading_enabled"] is False

