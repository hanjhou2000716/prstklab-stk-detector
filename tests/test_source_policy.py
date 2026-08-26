from src.source_policy import evaluate_crosscheck, source_policy_for


def test_policy_uses_official_taiwan_pair():
    policy = source_policy_for("TAIEX")
    assert policy.primary == ("TWSE",)
    assert policy.secondary == ("TAIFEX",)
    assert policy.official_required is True


def test_crosscheck_requires_aligned_quotes():
    result = evaluate_crosscheck(
        "BTC",
        {"price": 100, "quote_time": "2026-08-05T01:00:00+00:00"},
        {"price": 100.5, "quote_time": "2026-08-05T01:03:00+00:00"},
    )
    assert result["cross_checked"] is True


def test_taiex_crosscheck_compares_direction_not_unlike_contract_prices():
    result = evaluate_crosscheck(
        "TAIEX",
        {"price": 20_000, "change_percent": 2.4, "quote_time": "2026-08-05T01:00:00+00:00"},
        {"price": 20_250, "change_percent": 1.1, "quote_time": "2026-08-05T01:03:00+00:00"},
    )
    assert result["cross_checked"] is True
    assert result["comparison_basis"] == "direction_only"
    assert result["price_comparable"] is False


def test_taiex_crosscheck_blocks_opposite_direction():
    result = evaluate_crosscheck(
        "TAIEX",
        {"price": 20_000, "change_percent": 2.4, "quote_time": "2026-08-05T01:00:00+00:00"},
        {"price": 20_250, "change_percent": -1.1, "quote_time": "2026-08-05T01:03:00+00:00"},
    )
    assert result["cross_checked"] is False
    assert result["status"] == "direction_mismatch"

