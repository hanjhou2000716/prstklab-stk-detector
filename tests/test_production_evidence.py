from datetime import UTC, datetime

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
    assert "raw_payload" not in summary


def test_raw_observation_store_summary_is_disabled_without_configuration(monkeypatch) -> None:
    monkeypatch.delenv("RAW_OBSERVATION_ROOT", raising=False)
    summary = raw_observation_store_summary()
    assert summary == {
        "enabled": False,
        "schema_version": None,
        "observation_count": 0,
        "latest_fetched_at": None,
        "error": None,
    }


def test_market_snapshot_observation_is_disabled_without_configuration(monkeypatch) -> None:
    monkeypatch.delenv("RAW_OBSERVATION_ROOT", raising=False)
    assert record_market_snapshot_observation({"snapshot_id": "snap-12345678"}) == {
        "enabled": False,
        "recorded": False,
        "reason": "not_configured",
    }


def test_market_snapshot_observation_requires_snapshot_id(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("RAW_OBSERVATION_ROOT", str(tmp_path / "raw"))
    assert record_market_snapshot_observation({}) == {
        "enabled": True,
        "recorded": False,
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
