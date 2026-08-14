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


def test_event_and_research_snapshots_are_retained_as_evidence_lineage():
    result = correlate_creator_insight(
        _insight(),
        market_snapshot={
            "snapshot_id": "m-3",
            "as_of": "2026-08-13T04:00:00+00:00",
            "quotes": [{"ticker": "2330"}],
        },
        research_snapshot={
            "snapshot_id": "r-3",
            "as_of": "2026-08-13T04:00:00+00:00",
            "candidates": [{"ticker": "2330", "sector": "semiconductor"}],
        },
        event_snapshot={
            "snapshot_id": "e-3",
            "as_of": "2026-08-13T04:00:00+00:00",
            "events": [{"affected_instruments": ["2330"]}],
        },
        as_of="2026-08-13T05:00:00+00:00",
    )
    assert result["evidence_alignment"] == "aligned"
    assert result["snapshot_ids"] == {"market": "m-3", "research": "r-3", "event": "e-3"}
    assert result["event_snapshot_id"] == "e-3"
    assert result["matched_event_entities"] == ["2330"]


def test_stale_event_snapshot_is_explicitly_marked():
    result = correlate_creator_insight(
        _insight(),
        event_snapshot={
            "snapshot_id": "e-old",
            "as_of": "2026-08-10T04:00:00+00:00",
            "events": [{"affected_instruments": ["2330"]}],
        },
        as_of="2026-08-13T05:00:00+00:00",
    )
    assert result["evidence_alignment"] == "stale"
    assert result["stale_contexts"] == ["event"]

