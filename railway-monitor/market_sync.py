"""Read-only market-snapshot retrieval used as event-confirmation evidence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx


class MarketSyncObservation:
    """A bounded health envelope for the public market-sync snapshot.

    ``snapshot`` is deliberately retained as the legacy raw dictionary so the
    existing confirmation gate can continue to consume the same payload.  The
    status makes an unavailable/invalid read distinguishable from a valid
    snapshot that simply contains no confirming move.
    """

    __slots__ = ("status", "snapshot", "source_url", "fetched_at", "error")

    def __init__(
        self,
        status: str,
        snapshot: dict[str, Any],
        source_url: str | None,
        fetched_at: str | None,
        error: str | None = None,
    ) -> None:
        self.status = status
        self.snapshot = snapshot
        self.source_url = source_url
        self.fetched_at = fetched_at
        self.error = error

    def health(self) -> dict[str, Any]:
        records = list(self.snapshot.get("indices") or []) + list(self.snapshot.get("quotes") or [])
        return {
            "status": self.status,
            "source_url": self.source_url,
            "fetched_at": self.fetched_at,
            "record_count": len([record for record in records if isinstance(record, dict)]),
            "error": self.error,
        }


def snapshot_url(environ: dict[str, str] | None = None) -> str:
    values = environ if environ is not None else {}
    base = values.get("MARKET_SNAPSHOT_URL", "").strip()
    if base:
        return base
    dashboard = values.get("DASHBOARD_URL", "").strip().rstrip("/")
    return f"{dashboard}/data/market.json" if dashboard else ""


async def fetch_market_sync_snapshot(
    *,
    environ: dict[str, str] | None = None,
    client_factory: Callable[..., Any] = httpx.AsyncClient,
) -> dict[str, Any]:
    """Fetch a public snapshot; failures are an explicit no-confirmation result."""
    return (await fetch_market_sync_observation(environ=environ, client_factory=client_factory)).snapshot


async def fetch_market_sync_observation(
    *,
    environ: dict[str, str] | None = None,
    client_factory: Callable[..., Any] = httpx.AsyncClient,
) -> MarketSyncObservation:
    """Fetch a snapshot with explicit source-health semantics.

    ``no_event`` is intentionally not inferred here: an empty but valid JSON
    object is an available snapshot and downstream event logic decides whether
    a market move is present.  Transport/configuration/parser failures remain
    separate states so the health page cannot call a failed scan "no event".
    """
    url = snapshot_url(environ)
    if not url:
        return MarketSyncObservation(
            status="configuration_missing",
            snapshot={},
            source_url=None,
            fetched_at=None,
            error="market_snapshot_url_missing",
        )
    fetched_at = datetime.now(UTC).isoformat()
    try:
        async with client_factory(timeout=15, follow_redirects=True) as client:
            response = await client.get(url)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return MarketSyncObservation(
                status="invalid_payload",
                snapshot={},
                source_url=url,
                fetched_at=fetched_at,
                error="payload_not_object",
            )
        return MarketSyncObservation(
            status="available",
            snapshot=payload,
            source_url=url,
            fetched_at=fetched_at,
        )
    except httpx.HTTPError as error:
        status = "rate_limited" if isinstance(error, httpx.HTTPStatusError) and error.response is not None and error.response.status_code == 429 else "http_error"
        logging_error = type(error).__name__
    except (ValueError, TypeError) as error:
        status = "invalid_payload"
        logging_error = type(error).__name__
    except Exception as error:  # pragma: no cover - defensive boundary
        status = "failed"
        logging_error = type(error).__name__
    else:  # pragma: no cover - return paths above are exhaustive
        return MarketSyncObservation("failed", {}, url, fetched_at, "unknown")
    import logging

    logging.warning("market sync snapshot unavailable status=%s error=%s", status, logging_error)
    return MarketSyncObservation(
        status=status,
        snapshot={},
        source_url=url,
        fetched_at=fetched_at,
        error=logging_error,
    )
