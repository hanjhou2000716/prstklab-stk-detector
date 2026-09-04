from datetime import UTC, datetime

from src.adapters.catalog import build_adapter_catalog
from src.market_data_adapter import bind_adapter_contract
from src.production_evidence import (
    bind_market_evidence,
    quality_summary,
    raw_observation_store_summary,
    record_market_snapshot_observation,
)
from src.raw_observation_store import RawObservationStore


def test_stale_quote_remains_visible_but_is_not_alert_eligible() -> None:
    items = bind_market_evidence(
        [
            {
                "ticker": "TAIEX",
                "price": 43119,
                "previous_close": 40000,
                "change_percent": 7.8,
                "quote_date": "2026-07-31",
                "freshness": "stale",
                "cross_checked": True,
                "quote_source": "TWSE official close",
            }
        ],
        now=datetime(2026, 8, 5, tzinfo=UTC),
    )
    assert len(items) == 1
    assert items[0]["price"] == 43119
    assert items[0]["alert_eligible"] is False
    assert items[0]["data_quality_score"] == 0.0
    assert items[0]["instrument_master_id"].startswith("instrument-")
    assert items[0]["instrument_master_version"] == 1


def test_fresh_cross_checked_quote_is_alert_eligible() -> None:
    items = bind_market_evidence(
        [
            {
                "ticker": "TAIEX",
                "price": 43119,
                "previous_close": 40000,
                "change_percent": 7.8,
                "quote_time": "2026-08-05T09:05:00+08:00",
                "freshness": "live",
                "cross_checked": True,
                "quote_source": "TWSE official MIS",
            }
        ],
        now=datetime(2026, 8, 5, 1, 10, tzinfo=UTC),
    )
    assert items[0]["alert_eligible"] is True
    assert items[0]["data_quality_score"] == 100


def test_cross_checked_us_index_can_alert_through_display_only_yahoo() -> None:
    quote = {
        "ticker": "SOX",
        "name": "費城半導體指數",
        "market": "us",
        "price": 12000,
        "previous_close": 11700,
        "change_percent": 2.56,
        "quote_time": "2026-08-05T01:05:00+00:00",
        "fetched_at": "2026-08-05T01:06:00+00:00",
        "freshness": "live",
        "cross_checked": True,
        "quote_source": "Yahoo Finance public 5-minute quote",
        "source_label": "Yahoo",
        "source_url": "https://finance.yahoo.com/quote/%5ESOX",
        "source_domain": "finance.yahoo.com",
    }
    first = bind_market_evidence([quote], now=datetime(2026, 8, 5, 1, 10, tzinfo=UTC))[0]
    bound = bind_adapter_contract([first], build_adapter_catalog())[0]
    final = bind_market_evidence([bound], now=datetime(2026, 8, 5, 1, 10, tzinfo=UTC))[0]
    assert final["adapter_alert_policy"] == "display_only"
    assert final["adapter_policy_exception"] == "crosschecked_market_index"
    assert final["alert_eligible"] is True


def test_uncross_checked_yahoo_index_remains_closed() -> None:
    quote = {
        "ticker": "DJIA",
        "name": "道瓊工業指數",
        "market": "us",
        "price": 40000,
        "previous_close": 39200,
        "change_percent": 2.04,
        "quote_time": "2026-08-05T01:05:00+00:00",
        "fetched_at": "2026-08-05T01:06:00+00:00",
        "freshness": "live",
        "cross_checked": False,
        "quote_source": "Yahoo Finance public 5-minute quote",
        "source_label": "Yahoo",
        "source_url": "https://finance.yahoo.com/quote/%5EDJI",
        "source_domain": "finance.yahoo.com",
    }
    first = bind_market_evidence([quote], now=datetime(2026, 8, 5, 1, 10, tzinfo=UTC))[0]
    bound = bind_adapter_contract([first], build_adapter_catalog())[0]
    final = bind_market_evidence([bound], now=datetime(2026, 8, 5, 1, 10, tzinfo=UTC))[0]
    assert final["alert_eligible"] is False
    assert "adapter_policy_display_only" in final["quality_reasons"]


def test_quality_summary_counts_stale_and_verified_quotes() -> None:
    summary = quality_summary(
        [
            {"data_quality_score": 100, "alert_eligible": True, "quality_freshness": "live", "cross_checked": True},
            {"data_quality_score": 0, "alert_eligible": False, "quality_freshness": "stale", "cross_checked": False},
        ]
    )
    assert summary == {
        "count": 2,
        "alert_eligible_count": 1,
        "stale_count": 1,
        "cross_checked_count": 1,
        "data_quality_score": 50.0,
    }


def test_raw_observation_store_summary_is_safe_and_tracks_latest(tmp_path) -> None:
    store = RawObservationStore(tmp_path / "raw")
    assert raw_observation_store_summary(store)["enabled"] is True
    store.record(
        provider="twse",
        endpoint="https://example.invalid/quote",
        fetched_at="2026-08-09T01:00:00+00:00",
        request_id="req-1",
        payload={"ticker": "TAIEX", "price": 1},
        http_status=200,
        parser_version="test",
        parsing_status="normalized",
    )
    summary = raw_observation_store_summary(store)
    assert summary["observation_count"] == 1
    assert summary["latest_fetched_at"] == "2026-08-09T01:00:00+00:00"
    assert summary["state"] == "recorded"
    assert "raw_payload" not in summary


def test_raw_observation_store_summary_is_disabled_without_configuration(monkeypatch) -> None:
    monkeypatch.delenv("RAW_OBSERVATION_ROOT", raising=False)
    summary = raw_observation_store_summary()
    assert summary == {
        "enabled": False,
        "required": False,
        "state": "disabled",
        "schema_version": None,
        "observation_count": 0,
        "latest_fetched_at": None,
        "error": None,
    }


def test_market_snapshot_observation_is_disabled_without_configuration(monkeypatch) -> None:
    monkeypatch.delenv("RAW_OBSERVATION_ROOT", raising=False)
    assert record_market_snapshot_observation({"snapshot_id": "snap-12345678"}) == {
        "enabled": False,
        "required": False,
        "recorded": False,
        "state": "disabled",
        "reason": "not_configured",
    }


def test_market_snapshot_observation_requires_snapshot_id(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("RAW_OBSERVATION_ROOT", str(tmp_path / "raw"))
    assert record_market_snapshot_observation({}) == {
        "enabled": True,
        "required": False,
        "recorded": False,
        "state": "unavailable",
        "reason": "snapshot_id_missing",
    }


def test_market_snapshot_observation_persists_normalized_snapshot(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("RAW_OBSERVATION_ROOT", str(tmp_path / "raw"))
    result = record_market_snapshot_observation(
        {
            "snapshot_id": "snap-12345678",
            "generated_at": "2026-08-09T00:00:00+00:00",
            "primary": {"TAIEX": {"price": 43119}},
        }
    )
    assert result["enabled"] is True
    assert result["recorded"] is True
    summary = raw_observation_store_summary()
    assert summary["observation_count"] == 1
    assert summary["latest_fetched_at"] == "2026-08-09T00:00:00+00:00"


def test_required_raw_observation_fails_closed_when_root_is_missing(monkeypatch) -> None:
    monkeypatch.delenv("RAW_OBSERVATION_ROOT", raising=False)
    monkeypatch.setenv("RAW_OBSERVATION_REQUIRED", "true")
    result = record_market_snapshot_observation({"snapshot_id": "snap-12345678"})
    assert result == {
        "enabled": False,
        "required": True,
        "recorded": False,
        "state": "unavailable",
        "reason": "required_not_configured",
    }
