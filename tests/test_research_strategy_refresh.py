from datetime import UTC, date, datetime

from src.research_report import merge_previous_strategy_versions
from src.research_schedule import due_slot, slot_for
from src.run_research_report import attach_scan_contract


def _full_source(**overrides):
    value = {
        "market": "taiwan",
        "strategy": "momentum",
        "universe_mode": "full",
        "universe_expected": 2,
        "universe_scanned": 2,
        "universe_completed": 2,
        "universe_failed": 0,
        "scan_state": "complete",
    }
    value.update(overrides)
    return value


def test_partial_matrix_can_publish_successful_strategy_only():
    report = {"sources": [
        _full_source(),
        _full_source(market="us", strategy="value", universe_completed=1, universe_scanned=2, universe_failed=1, scan_state="building"),
    ]}
    result = attach_scan_contract(report, "production")
    assert result["publication_state"] == "mixed_strategy"
    assert result["publish_eligible"] is True
    assert result["production_eligible"] is False
    assert result["strategy_publication"][0]["eligible"] is True
    assert result["strategy_publication"][1]["eligible"] is False


def test_failed_strategy_keeps_last_successful_rows_as_historical():
    report = {
        "generated_at": "2026-09-05T16:00:00+08:00",
        "sources": [{
            "market": "taiwan", "strategy": "value", "scan_state": "failed",
            "failed_records": 1, "blocking_reason": "deadline_exceeded",
        }],
        "candidates": [],
    }
    previous = {
        "generated_at": "2026-08-31T16:00:00+08:00",
        "sources": [{"market": "taiwan", "strategy": "value", "scan_state": "complete"}],
        "candidates": [{"market": "taiwan", "strategy": "value", "ticker": "2330", "list_type": "formal"}],
    }
    result = merge_previous_strategy_versions(report, previous)
    assert result["sources"][0]["historical_fallback"] is True
    assert result["sources"][0]["candidate_state"] == "historical"
    assert result["candidates"][0]["research_version_state"] == "historical"


def test_exchange_slot_uses_close_identity_and_actual_session():
    assert slot_for("us", date(2026, 9, 4)) == "us:2026-09-04:close-research"
    before_close_plus_hour = datetime(2026, 9, 4, 20, 59, tzinfo=UTC)
    after_close_plus_hour = datetime(2026, 9, 4, 21, 1, tzinfo=UTC)
    assert due_slot("us", now=before_close_plus_hour) is None
    assert due_slot("us", now=after_close_plus_hour)["trading_date"] == "2026-09-04"


def test_exchange_slot_is_not_due_on_weekend():
    assert due_slot("taiwan", now=datetime(2026, 9, 5, 10, tzinfo=UTC)) is None


def test_delayed_us_slot_keeps_friday_identity_on_taipei_weekend():
    result = due_slot("us", now=datetime(2026, 9, 5, 10, tzinfo=UTC))
    assert result["trading_date"] == "2026-09-04"
    assert result["slot_key"] == "us:2026-09-04:close-research"


def test_single_market_run_keeps_other_market_as_historical_without_attempt():
    report = {
        "generated_at": "2026-09-05T16:00:00+08:00",
        "sources": [
            _full_source(market="taiwan", scan_state="complete"),
            _full_source(market="us", scan_state="failed", failed_records=1),
        ],
        "candidates": [],
    }
    previous = {
        "generated_at": "2026-09-04T16:00:00+08:00",
        "sources": [{
            "market": "us", "strategy": "momentum", "scan_state": "complete",
            "last_successful_generated_at": "2026-09-04T16:00:00+08:00",
            "scan_trading_date": "2026-09-03",
        }],
        "candidates": [{"market": "us", "strategy": "momentum", "ticker": "NVDA", "list_type": "formal"}],
    }
    result = merge_previous_strategy_versions(report, previous, target_market="taiwan")
    source = next(item for item in result["sources"] if item["market"] == "us")
    assert source["unscanned_in_run"] is True
    assert source["historical_fallback"] is True
    assert source["scan_attempted_at"] is None
    assert source["scan_trading_date"] == "2026-09-03"
    assert result["candidates"][0]["research_version_state"] == "historical"
