from src.intel_contract import normalize_event_record, normalize_quote_record, source_domain


def test_source_domain_is_stable():
    assert source_domain("https://www.sec.gov/Archives/a") == "sec.gov"


def test_event_contract_preserves_provenance_and_impact_confirmation():
    item = normalize_event_record({
        "kind": "official_event", "relevance": "official", "title": "Fed update",
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "impact_confirmation": {"confirmed": True},
    }, fetched_at="2026-08-01T00:00:00+00:00")
    assert item["source_tier"] == "official"
    assert item["source_domain"] == "federalreserve.gov"
    assert item["fetched_at"].startswith("2026-08-01")
    assert item["cross_checked"] is True
    assert item["event_type"] == "central-bank"


def test_quote_contract_marks_delayed_close():
    item = normalize_quote_record({
        "ticker": "TPEx", "quote_source": "TWSE MIS official OTC index",
        "quote_basis": "最近收盤", "quote_date": "2026-07-31",
    }, fetched_at="2026-08-01T00:00:00+00:00")
    assert item["source_tier"] == "official"
    assert item["stale_used"] is True
    assert item["published_at"] == "2026-07-31"


def test_quote_contract_reconciles_direction_from_price_and_previous_close():
    item = normalize_quote_record({
        "ticker": "TAIEX",
        "price": 110,
        "previous_close": 100,
        "change": -10,
        "change_percent": -10,
    })
    assert item["change"] == 10
    assert item["change_percent"] == 10
    assert item["market_direction"] == "上漲"
    assert item["direction_sign"] == 1
    assert item["change_consistency"] == "reconciled"


def test_quote_contract_reconciles_point_change_sign_without_base_price():
    item = normalize_quote_record({
        "ticker": "NASDAQ",
        "change": 5,
        "change_percent": -2.5,
    })
    assert item["change"] == -5
    assert item["market_direction"] == "下跌"
    assert item["direction_sign"] == -1
    assert item["change_consistency"] == "reconciled"


def test_market_signal_contract_uses_instrument_direction():
    item = normalize_event_record({
        "kind": "market_signal",
        "title": "TAIEX move",
        "instrument": {"ticker": "TAIEX", "change_percent": -1.25},
        "market_direction": "上漲",
        "market_move": "+1.25%",
    })
    assert item["market_direction"] == "下跌"
    assert item["market_move"] == "-1.25%"
