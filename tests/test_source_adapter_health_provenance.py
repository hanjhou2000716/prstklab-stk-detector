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
