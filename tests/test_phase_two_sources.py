from src.phase_two_sources import (
    _macd_state,
    _record_phase_two_observation,
    build_phase_two_snapshot,
    classify_provider_health,
    fetch_eia_snapshot,
    fetch_fred_snapshot,
    fetch_kofia_credit_margin,
)
from src.raw_observation_store import RawObservationStore


def test_provider_health_classification_separates_config_and_fallback_states():
    assert classify_provider_health("missing_api_key", required_for="research") == "configuration_required"
    assert classify_provider_health("failed", required_for="alert", fallback_available=True) == "degraded_with_fallback"
    assert classify_provider_health("failed", required_for="alert") == "critical_gap"
    assert classify_provider_health("failed", required_for="optional") == "failed"


def test_macd_detects_bearish_cross():
    # A falling tail after a long rising series produces a deterministic cross.
    state = _macd_state([float(i) for i in range(60)] + [60.0, 55.0])
    assert state["bearish_cross"] is True
    assert state["label"] == "死叉"


def test_fred_never_calls_without_key(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    result = fetch_fred_snapshot()
    assert result["status"] == "missing_api_key"
    assert result["data"] == {}
    assert result["health"]["health_class"] == "configuration_required"
    assert result["health"]["required_for"] == "research"


def test_eia_never_calls_without_key(monkeypatch):
    monkeypatch.delenv("EIA_API_KEY", raising=False)
    result = fetch_eia_snapshot()
    assert result["status"] == "missing_api_key"
    assert result["data"] == {}
    assert result["health"]["health_class"] == "configuration_required"
    assert result["health"]["required_for"] == "alert"


def test_kofia_reports_unambiguous_gap(monkeypatch):
    class Response:
        text = "<html>public page without a data table</html>"
        def raise_for_status(self):
            return None

    monkeypatch.setattr("src.phase_two_sources.requests.get", lambda *args, **kwargs: Response())
    result = fetch_kofia_credit_margin()
    assert result["status"] == "data_gap"
    assert result["health"]["status"] == "partial"
    assert result["health"]["health_class"] == "optional_degraded"


def test_phase_two_observation_store_binds_immutable_provenance(tmp_path):
    store = RawObservationStore(tmp_path / "raw")
    result = {
        "status": "ok",
        "data": {"value": 1},
        "fetched_at": "2026-08-08T09:00:00+00:00",
        "health": {"source_url": "https://example.test/feed", "checked_at": "2026-08-08T09:00:00+00:00"},
    }

    _record_phase_two_observation(store, "example", result)

    health = result["health"]
    assert health["observation_id"]
    assert health["raw_payload_location"]
    assert store.count(provider="example") == 1


def test_phase_two_snapshot_records_each_configured_result(monkeypatch, tmp_path):
    def result(key):
        return {
            "status": "ok",
            "data": {"key": key},
            "fetched_at": "2026-08-08T09:00:00+00:00",
            "health": {"key": key, "source_url": f"https://example.test/{key}", "checked_at": "2026-08-08T09:00:00+00:00"},
        }

    monkeypatch.setattr("src.phase_two_sources.fetch_kofia_credit_margin", lambda: result("kofia"))
    monkeypatch.setattr("src.phase_two_sources.fetch_crypto_macd", lambda: result("crypto_macd"))
    monkeypatch.setattr("src.phase_two_sources.fetch_fred_snapshot", lambda: result("fred"))
    monkeypatch.setattr("src.phase_two_sources.fetch_eia_snapshot", lambda: result("eia"))
    monkeypatch.setattr("src.crypto_spot_sources.fetch_crypto_spot_snapshot", lambda: result("crypto_spot"))
    monkeypatch.setattr("src.public_market_secondary.fetch_public_market_secondary", lambda: result("secondary"))
    store = RawObservationStore(tmp_path / "raw")

    snapshot = build_phase_two_snapshot(raw_store=store)

    assert store.count() == 6
    assert all(item.get("observation_id") for item in snapshot["sources"])
