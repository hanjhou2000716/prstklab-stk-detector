from src.paper_portfolio import build_paper_portfolio_snapshot


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
