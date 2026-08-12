"""Shared structural contract for public market and event adapters."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, TypeVar, runtime_checkable

from src.source_adapter import SourceObservation

PayloadT = TypeVar("PayloadT")


@runtime_checkable
class MarketDataAdapter(Protocol[PayloadT]):
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

    def normalize(self, payload: Any) -> PayloadT: ...

    def health(self) -> dict[str, Any]: ...

    def provenance(self, observation: SourceObservation) -> dict[str, Any]: ...


__all__ = ["MarketDataAdapter"]
