from src.paper_portfolio import build_paper_portfolio_snapshot, update_paper_observations


def test_paper_portfolio_blocks_candidate_without_backtest():
    result = build_paper_portfolio_snapshot(
        [{"ticker": "2330", "market": "taiwan", "strategy": "value"}],
        [{"ticker": "2330", "price": 100, "freshness": "live"}],
    )
    assert result["state"] == "observation_only"
    assert result["records"] == []
    assert result["blocked_candidate_count"] == 1


def test_paper_portfolio_records_only_valid_research_observation():
    result = build_paper_portfolio_snapshot(
        [{
            "ticker": "2330", "market": "taiwan", "strategy": "momentum",
            "strategy_version": "1", "data_version": "d1", "backtest_release": "bt1",
        }],
        [{"ticker": "2330", "price": 100, "quote_time": "2026-08-09T09:00:00+08:00"}],
        release_id="r1",
    )
    assert result["state"] == "available"
    assert result["records"][0]["simulated_entry_price"] == 100.0
    assert result["records"][0]["not_a_trade"] is True


def test_paper_observation_tracks_only_completed_trading_day_horizons():
    record = {
        "ticker": "2330",
        "observed_at": "2026-08-01T09:00:00+08:00",
        "simulated_entry_price": 100.0,
        "not_a_trade": True,
    }
    history = {
        "2330": [
            {"date": f"2026-08-{day:02d}", "close": 100 + day}
            for day in range(2, 8)
        ]
    }

    updated = update_paper_observations([record], history)[0]

    assert updated["horizons"]["5d"] == 6.0
    assert updated["horizons"]["20d"] is None
    assert updated["tracking_state"] == "partial"
    assert updated["completed_horizons"] == ["5d"]
    assert updated["max_favorable_excursion"] == 7.0
    assert updated["max_adverse_excursion"] == 2.0
    assert updated["not_a_trade"] is True


def test_paper_observation_does_not_fill_missing_history():
    record = {"ticker": "2330", "observed_at": "2026-08-01", "simulated_entry_price": 100}
    updated = update_paper_observations([record], {"2330": [{"date": "2026-07-31", "close": 99}]})[0]

    assert updated["tracking_state"] == "pending"
    assert updated["horizons"] == {"5d": None, "20d": None, "60d": None}
    assert updated["max_favorable_excursion"] is None
    assert updated["not_a_trade"] is True
