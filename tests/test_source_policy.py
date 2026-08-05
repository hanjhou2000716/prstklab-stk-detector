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

