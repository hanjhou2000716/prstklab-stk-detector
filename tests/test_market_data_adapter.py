from collections.abc import Mapping
from typing import Any

from src.adapters import MarketDataAdapter, build_adapter
from src.source_adapter import SourceObservation


class Response:
    status_code = 200
    headers: dict[str, str] = {}

    def json(self) -> dict[str, int]:
        return {"value": 1}


def test_catalog_adapter_satisfies_shared_market_data_adapter_contract() -> None:
    adapter = build_adapter(
        "TWSE",
        parser=lambda payload: {"value": int(payload["value"])},
        transport=lambda url, **kwargs: Response(),
    )
    assert isinstance(adapter, MarketDataAdapter)
    assert adapter.normalize({"value": "2"}) == {"value": 2}
    observation = adapter.fetch()
    assert isinstance(observation, SourceObservation)
    assert isinstance(adapter.health(), dict)
    assert adapter.provenance(observation)["provider"] == "TWSE"


def test_contract_shape_is_explicit_for_custom_provider() -> None:
    class Custom:
        def fetch(self, *, params: Mapping[str, Any] | None = None, allow_stale: bool = False) -> SourceObservation:
            raise NotImplementedError

        def normalize(self, payload: Any) -> Any:
            return payload

        def health(self) -> dict[str, Any]:
            return {}

        def provenance(self, observation: SourceObservation) -> dict[str, Any]:
            return {"observation_id": observation.observation_id}

    # Static type checkers and the runtime-checkable protocol both validate
    # this structural implementation without nominal inheritance.
    custom: MarketDataAdapter[Any] = Custom()
    assert isinstance(custom, MarketDataAdapter)
    assert custom.normalize({"ok": True}) == {"ok": True}
