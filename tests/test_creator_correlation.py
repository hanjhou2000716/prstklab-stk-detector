from src.creator_correlation import correlate_creator_insight


def _insight(**overrides):
    result = {"tickers": ["2330"], "sectors": ["semiconductor"], "topics": ["ai"]}
    result.update(overrides)
    return result


def test_missing_snapshots_is_not_comparable_and_never_an_investment_signal():
    result = correlate_creator_insight(_insight())
    assert result["correlation_state"] == "not_comparable"
    assert result["is_investment_signal"] is False


def test_explicit_ticker_match_is_aligned():
    result = correlate_creator_insight(
        _insight(),
        market_snapshot={
            "snapshot_id": "m-1",
            "as_of": "2026-08-13T04:00:00+00:00",
            "quotes": [{"ticker": "2330", "price": 1000}],
        },
        as_of="2026-08-13T05:00:00+00:00",
    )
    assert result["correlation_state"] == "aligned"
    assert result["matched_tickers"] == ["2330"]
    assert result["market_snapshot_id"] == "m-1"


def test_no_entity_match_waits_for_market_evidence():
    result = correlate_creator_insight(
        _insight(),
        market_snapshot={
            "snapshot_id": "m-2",
            "as_of": "2026-08-13T04:00:00+00:00",
            "quotes": [{"ticker": "^TWII", "price": 20000}],
        },
        as_of="2026-08-13T05:00:00+00:00",
    )
    assert result["correlation_state"] == "awaiting_market"
    assert result["reason"] == "no_explicit_entity_match"


def test_stale_market_snapshot_is_not_used_as_current_evidence():
    result = correlate_creator_insight(
        _insight(),
        market_snapshot={
            "snapshot_id": "m-old",
            "as_of": "2026-08-10T04:00:00+00:00",
            "quotes": [{"ticker": "2330"}],
        },
        as_of="2026-08-13T05:00:00+00:00",
    )
    assert result["correlation_state"] == "stale"
    assert result["matched_tickers"] == ["2330"]

