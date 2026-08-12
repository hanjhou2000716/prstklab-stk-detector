"""Allow-listed public source catalog.

The catalog contains transport policy only.  Fetching remains explicit at the
caller, so listing a provider never silently starts a network request.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any

from src.raw_observation_store import RawObservationStore
from src.source_adapter import AdapterConfig, JsonSourceAdapter

DEFAULT_REPOSITORY_URL = "https://github.com/hanjhou2000716/prstklab-stk-detector"
ADAPTER_CONTRACT_VERSION = 1
PROVENANCE_FIELDS = (
    "provider", "source_tier", "source_url", "request_id", "fetched_at",
    "published_at", "observation_id", "payload_hash", "parser_version",
    "stale_used", "freshness", "data_quality_score", "alert_eligible",
)
HEALTH_FIELDS = (
    "status", "last_success_at", "last_failure_at", "consecutive_failures",
    "error_class", "freshness", "data_quality_score", "display_eligible",
    "alert_eligible", "quality_reasons",
)


@dataclass(frozen=True)
class AdapterSpec:
    provider: str
    endpoint: str
    source_tier: str
    can_trigger_alert: bool
    update_frequency: str
    requires_key: bool = False
    user_agent: str = "PRStK-public-readonly/1.0"


ADAPTER_CATALOG: tuple[AdapterSpec, ...] = (
    AdapterSpec("TWSE", "https://mis.twse.com.tw/stock/api/getStockInfo.jsp", "official", True, "intraday"),
    AdapterSpec("TAIFEX", "https://openapi.taifex.com.tw", "official", True, "intraday"),
    AdapterSpec("TPEx", "https://www.tpex.org.tw", "official", True, "daily"),
    AdapterSpec("Yahoo", "https://query1.finance.yahoo.com/v8/finance/chart", "public-market", False, "delayed"),
    AdapterSpec("SEC", "https://www.sec.gov/cgi-bin/browse-edgar", "official", True, "event-driven"),
    AdapterSpec("FRED", "https://api.stlouisfed.org/fred", "official", True, "daily", True),
    AdapterSpec("EIA", "https://api.eia.gov/v2", "official", True, "daily", True),
    AdapterSpec("Binance", "https://api.binance.com/api/v3", "public-market", False, "intraday"),
    AdapterSpec("CoinGecko", "https://api.coingecko.com/api/v3", "public-market", False, "intraday"),
    AdapterSpec("Binance.US", "https://api.binance.us/api/v3", "public-market", False, "intraday"),
    AdapterSpec("Stooq", "https://stooq.com/q/d/l/", "public-market", False, "daily"),
    AdapterSpec("Nasdaq", "https://api.nasdaq.com/api", "public-market", False, "daily"),
    AdapterSpec("KOFIA", "https://freesis.kofia.or.kr/stat/FreeSIS.do", "official", False, "daily"),
    AdapterSpec("GDELT", "https://api.gdeltproject.org/api/v2/doc/doc", "discovery", False, "15-minute"),
    AdapterSpec("ECB", "https://www.ecb.europa.eu/rss/press.html", "official", True, "event-driven"),
)


def _spec(provider: str) -> AdapterSpec:
    for item in ADAPTER_CATALOG:
        if item.provider.casefold() == provider.casefold():
            return item
    raise KeyError(f"unknown public provider: {provider}")


def build_adapter(provider: str, *, parser=lambda payload: payload, transport=None, raw_store=None) -> JsonSourceAdapter:
    """Build one configured adapter; credentials are supplied by the caller.

    When ``RAW_OBSERVATION_ROOT`` is configured, the adapter automatically
    persists the provider response before parsing.  The environment variable
    is intentionally opt-in so local smoke tests and read-only development
    runs do not create an implicit data directory.
    """
    spec = _spec(provider)
    user_agent = spec.user_agent
    if spec.provider == "SEC":
        user_agent = os.getenv("SEC_USER_AGENT") or f"PRStK ({os.getenv('GITHUB_REPOSITORY_URL', DEFAULT_REPOSITORY_URL)})"
    config = AdapterConfig(
        provider=spec.provider,
        endpoint=spec.endpoint,
        source_tier=spec.source_tier,
        user_agent=user_agent,
    )
    effective_store = raw_store
    if effective_store is None:
        root = os.getenv("RAW_OBSERVATION_ROOT", "").strip()
        if root:
            effective_store = RawObservationStore(root)
    return JsonSourceAdapter(config=config, parser=parser, transport=transport, raw_store=effective_store)


def build_adapter_catalog() -> list[dict[str, Any]]:
    """Return a JSON-safe adapter contract catalog for health and audit pages.

    The catalog is declarative: it describes the allow-listed transport and
    the fields every adapter must expose.  It never performs a network call.
    This makes the market artifact self-describing while keeping collection
    and source health decisions in the explicit pipeline.
    """
    return [
        {
            **asdict(item),
            "adapter_contract_version": ADAPTER_CONTRACT_VERSION,
            "provenance_fields": list(PROVENANCE_FIELDS),
            "health_fields": list(HEALTH_FIELDS),
            "alert_policy": "crosscheck_required" if item.can_trigger_alert else "display_only",
        }
        for item in ADAPTER_CATALOG
    ]
