from datetime import UTC, datetime, timedelta

from src.source_priority import cross_check_market, policy_for, source_health_summary


NOW = datetime(2026, 8, 4, 2, 0, tzinfo=UTC)


def quote(source, price=100, minutes=5):
    return {
        "price": price,
        "quote_time": (NOW - timedelta(minutes=minutes)).isoformat(),
        "source_label": source,
        "source_url": f"https://{source.lower().replace(' ', '')}.example/quote",
        "quote_basis": "盤中",
    }


def test_policy_prioritizes_official_taiwan_sources():
    assert policy_for("TAIEX").primary == "TWSE"
    assert policy_for("TAIEX").secondary == "TAIFEX"
    assert policy_for("TPEx").secondary == "TWSE MIS"


def test_confirmed_pair_is_alert_eligible():
    result = cross_check_market("TAIEX", quote("TWSE", 100), quote("TAIFEX", 100.2), now=NOW)
    assert result["cross_checked"] is True
    assert result["alert_allowed"] is True
    assert result["status"] == "confirmed"
    assert result["expected_sources"] == ["TWSE", "TAIFEX"]


def test_missing_secondary_is_visible_but_not_alert_eligible():
    result = cross_check_market("NASDAQ", quote("Yahoo", 100), None, now=NOW)
    assert result["cross_checked"] is False
    assert result["alert_allowed"] is False
    assert result["status"] == "secondary_unavailable"


def test_stale_primary_cannot_trigger_even_when_prices_match():
    result = cross_check_market("BTC", quote("Binance", 100, minutes=30), quote("CoinGecko", 100), now=NOW)
    assert result["freshness"] == "stale_or_unknown"
    assert result["alert_allowed"] is False
    assert result["cross_checked"] is False


def test_price_discrepancy_is_not_confirmed():
    result = cross_check_market("SOX", quote("Yahoo", 100), quote("secondary", 104), now=NOW)
    assert result["cross_checked"] is False
    assert result["status"] == "discrepancy"


def test_health_summary_counts_unconfirmed_records():
    summary = source_health_summary([{"cross_checked": True}, {"cross_checked": False}])
    assert summary == {"total": 2, "confirmed": 1, "unconfirmed": 1, "status": "partial"}