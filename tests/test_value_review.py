from src.value_review import metrics_from_info, quote_from_info, review_candidates, score_metrics


def test_value_review_scores_only_reproducible_public_metrics():
    metrics = metrics_from_info({"netIncomeToCommon": 600_000_000, "marketCap": 20_000_000_000, "returnOnEquity": .2, "payoutRatio": .5})
    assert score_metrics(metrics) == 4


def test_value_review_keeps_public_price_change_separate_from_fundamental_score():
    quote = quote_from_info({"currentPrice": 110, "previousClose": 100})
    assert quote == {"close": 110.0, "change_percent": 10.0}


def test_value_review_is_bounded_to_upstream_candidates_and_discloses_errors():
    rows, errors = review_candidates(
        [{"ticker": "A", "name": "A", "symbol": "A"}, {"ticker": "B", "name": "B", "symbol": "B"}],
        lambda symbol: {"returnOnEquity": .2} if symbol == "A" else (_ for _ in ()).throw(RuntimeError()),
    )
    assert rows[0]["ticker"] == "A"
    assert rows[0]["moat_review"] == "需人工檢視"
    assert errors == ["B"]
