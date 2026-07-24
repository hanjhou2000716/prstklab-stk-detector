from src.market_data import build_market_snapshot


def test_risk_source_failure_is_not_labeled_as_a_market_quote_failure(monkeypatch):
    monkeypatch.setattr("src.market_data.get_quote", lambda item: {**item, "price": 1})
    monkeypatch.setattr("src.market_data.get_market_status", lambda market: {"label": market})
    monkeypatch.setattr("src.risk_news.build_risk_snapshot", lambda: {
        "taiwan": {"label": "台股", "errors": ["台指波動率資料暫時無法取得"]},
        "us": {"label": "美股", "errors": []},
    })
    monkeypatch.setattr("src.risk_news.build_news_snapshot", lambda: {"errors": [], "taiwan": [], "us": []})
    monkeypatch.setattr("src.event_alerts.build_event_snapshot", lambda news, quotes: {})
    monkeypatch.setattr("src.macro_summary.build_macro_summary", lambda events, risk, program=None: {})
    monkeypatch.setattr("src.market_history.load_watchlist_history", lambda watchlist: ({}, []))
    monkeypatch.setattr("src.research_scan.build_price_action_snapshot", lambda watchlist, histories: {
        "candidates": [{
            "ticker": "2330", "name": "台積電", "market": "taiwan", "funnel_labels": ["訂單塊回踩"],
            "reference_close": 100, "reference_stop": 90, "reference_risk": 10, "atr": 2,
        }],
        "errors": [],
    })
    monkeypatch.setattr("src.momentum_research.build_momentum_snapshot", lambda watchlist, histories: {"errors": []})
    monkeypatch.setattr("src.resonance_scan.build_resonance_snapshot", lambda watchlist, histories: {"errors": []})
    monkeypatch.setattr("src.value_quality.build_value_snapshot", lambda watchlist: {"errors": []})

    snapshot = build_market_snapshot()

    assert snapshot["data_status"] == "即時"
    assert snapshot["errors"] == [{
        "ticker": "台股風險指標",
        "message": "台指波動率資料暫時無法取得",
        "scope": "risk",
    }]
    assert "allocation" not in snapshot
    candidate = snapshot["research"]["candidates"][0]
    assert candidate["ticker"] == "2330"
    assert {"reference_close", "reference_stop", "reference_risk"}.isdisjoint(candidate)
