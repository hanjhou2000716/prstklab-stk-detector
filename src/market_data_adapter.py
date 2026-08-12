"""Shared structural contract for public market and event adapters."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, TypeVar, runtime_checkable

from src.source_adapter import SourceObservation

PayloadT_co = TypeVar("PayloadT_co", covariant=True)


@runtime_checkable
class MarketDataAdapter(Protocol[PayloadT_co]):
    """Provider adapter boundary used by production callers and replays.

    Implementations must keep transport, normalization, health and
    provenance separate.  The protocol is structural, so the existing
    ``JsonSourceAdapter`` and future provider-specific adapters can adopt it
    without a parallel inheritance hierarchy.
    """

    def fetch(
        self,
        *,
        params: Mapping[str, Any] | None = None,
        allow_stale: bool = False,
    ) -> SourceObservation: ...

    def normalize(self, payload: Any) -> PayloadT_co: ...

    def health(self) -> dict[str, Any]: ...

    def provenance(self, observation: SourceObservation) -> dict[str, Any]: ...


def bind_adapter_contract(
    observations: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach the declared adapter policy to published observations.

    Matching uses the explicit source label/domain, never a ticker guess. An
    unknown provider remains visible but is marked unavailable and cannot be
    promoted to an alert by this binding step.
    """
    by_provider = {
        str(item.get("provider") or "").casefold(): item
        for item in catalog
        if isinstance(item, dict) and str(item.get("provider") or "").strip()
    }
    bound: list[dict[str, Any]] = []
    for observation in observations:
        item = dict(observation)
        label = str(item.get("source_label") or item.get("quote_source") or "").casefold()
        domain = str(item.get("source_domain") or item.get("source_url") or "").casefold()
        provider = next(
            (name for name in by_provider if name in label or name in domain),
            None,
        )
        spec = by_provider.get(provider or "")
        if spec is None:
            item.update({
                "adapter_contract_state": "unavailable",
                "adapter_provider": None,
                "adapter_alert_policy": "display_only",
            })
            item["alert_eligible"] = False
        else:
            item.update({
                "adapter_contract_state": "declared",
                "adapter_provider": spec["provider"],
                "adapter_contract_version": spec.get("adapter_contract_version"),
                "adapter_alert_policy": spec.get("alert_policy"),
                "adapter_provenance_fields": list(spec.get("provenance_fields") or []),
                "adapter_health_fields": list(spec.get("health_fields") or []),
            })
            if spec.get("alert_policy") != "crosscheck_required":
                item["alert_eligible"] = False
        bound.append(item)
    return bound


__all__ = ["MarketDataAdapter", "bind_adapter_contract"]
