from dataclasses import dataclass

from src.source_adapter import AdapterConfig, JsonSourceAdapter


@dataclass
class Response:
    status_code: int = 200

    def json(self):
        return {"value": 1}


def test_health_keeps_last_success_observation_provenance() -> None:
    adapter = JsonSourceAdapter(
        config=AdapterConfig(provider="fixture", endpoint="https://example.test"),
        transport=lambda *args, **kwargs: Response(),
    )
    observation = adapter.fetch()
    health = adapter.health()
    assert health["last_success_observation_id"] == observation.observation_id
    assert health["last_success_payload_hash"] == observation.payload_hash
    assert health["last_success_http_status"] == 200
    assert health["last_observation_id"] == observation.observation_id
    assert health["data_quality_score"] == 85.0


def test_display_only_adapter_policy_cannot_restore_alert_eligibility() -> None:
    from src.production_evidence import bind_quote_evidence

    quote = bind_quote_evidence({
        "ticker": "NASDAQ", "price": 100.0, "quote_date": "2026-08-12",
        "source_label": "Yahoo", "quote_source": "Yahoo public quote",
        "source_url": "https://finance.yahoo.com/quote/%5EIXIC",
        "fetched_at": "2026-08-12T08:00:00+00:00", "freshness": "live",
        "cross_checked": True, "adapter_alert_policy": "display_only",
    })
    assert quote["alert_eligible"] is False
    assert "adapter_policy_display_only" in quote["quality_reasons"]
