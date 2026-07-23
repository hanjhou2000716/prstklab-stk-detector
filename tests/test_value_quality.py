from src.value_quality import normalize, quality_score


def test_normalize_keeps_missing_public_fields_explicit():
    metrics = normalize({"returnOnEquity": .2, "trailingPE": 15})
    assert metrics == {"roe": .2, "pe": 15.0, "dividend_yield": None, "net_income": None}


def test_quality_score_uses_available_fundamental_thresholds():
    assert quality_score({"roe": .2, "pe": None, "dividend_yield": .03, "net_income": 600_000_000}) == 3
    assert quality_score({"roe": None, "pe": None, "dividend_yield": None, "net_income": None}) == 0
