"""Default source registry; credentials stay in the process environment."""

from __future__ import annotations

from typing import Any

from .base import MarketDataAdapter, Transport
from .sources import (
    BinanceAdapter,
    EiaAdapter,
    FredAdapter,
    GdeltAdapter,
    SecAdapter,
    TaifexAdapter,
    TpexAdapter,
    TwseAdapter,
    YahooAdapter,
)

ADAPTER_TYPES = {
    "twse": TwseAdapter,
    "taifex": TaifexAdapter,
    "tpex": TpexAdapter,
    "yahoo": YahooAdapter,
    "sec": SecAdapter,
    "fred": FredAdapter,
    "eia": EiaAdapter,
    "binance": BinanceAdapter,
    "gdelt": GdeltAdapter,
}


def build_default_adapters(*, transport: Transport | None = None, timeout: float = 15.0) -> dict[str, MarketDataAdapter]:
    """Create fresh adapters so health counters never leak between jobs."""
    return {
        provider: adapter_type(transport=transport, timeout=timeout)
        for provider, adapter_type in ADAPTER_TYPES.items()
    }


def adapter_health_snapshot(adapters: dict[str, MarketDataAdapter]) -> list[dict[str, Any]]:
    """Return deterministic health records for the Mini App/source-health layer."""
    return [adapters[name].health().as_dict() for name in sorted(adapters)]