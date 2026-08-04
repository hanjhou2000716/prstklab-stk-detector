"""Stable contract shared by all public read-only data sources.

Adapters deliberately expose raw observations before normalisation. This keeps
provenance and failure state auditable and prevents a parser from silently
turning a missing quote into a valid-looking value.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

Transport = Callable[..., Any]


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


@dataclass(frozen=True)
class AdapterError(Exception):
    """Safe, machine-readable adapter error; never contains credentials."""

    code: str
    message: str
    transient: bool = True
    http_status: int | None = None

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


@dataclass(frozen=True)
class AdapterObservation:
    provider: str
    endpoint: str
    source_tier: str
    fetched_at: datetime
    payload: Any
    source_url: str
    request_id: str | None = None
    published_at: datetime | None = None
    http_status: int | None = None
    parse_status: str = "ok"
    payload_hash: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["fetched_at"] = iso(self.fetched_at)
        data["published_at"] = iso(self.published_at)
        return data


@dataclass(frozen=True)
class AdapterHealth:
    provider: str
    source_tier: str
    source_url: str
    status: str
    checked_at: datetime
    latency_ms: float | None = None
    consecutive_failures: int = 0
    last_success_at: datetime | None = None
    error_code: str | None = None
    message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["checked_at"] = iso(self.checked_at)
        data["last_success_at"] = iso(self.last_success_at)
        return data


class MarketDataAdapter(ABC):
    """Source adapter contract used by market, event and research jobs.

    ``fetch`` is the only method allowed to perform I/O. ``normalize`` remains
    deterministic and can be tested with stored fixtures. ``health`` and
    ``provenance`` never infer success when a request failed.
    """

    provider: str
    source_tier: str
    endpoint: str
    source_url: str

    @abstractmethod
    def fetch(self) -> AdapterObservation:
        """Fetch one raw observation from the public endpoint."""

    @abstractmethod
    def normalize(self, observation: AdapterObservation) -> Any:
        """Convert a successful raw observation into domain data."""

    @abstractmethod
    def health(self) -> AdapterHealth:
        """Return the latest source health without making a new request."""

    @abstractmethod
    def provenance(self, observation: AdapterObservation | None = None) -> dict[str, Any]:
        """Return source and timing fields suitable for release artifacts."""


def payload_hash(payload: Any) -> str:
    """Hash a payload deterministically without retaining sensitive headers."""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class HttpSourceAdapter(MarketDataAdapter):
    """Small transport wrapper for JSON, RSS and text public endpoints."""

    response_format = "auto"
    default_headers: Mapping[str, str] = {"Accept": "application/json, application/xml, text/plain"}
    required_env: str | None = None
    credential_param: str | None = None

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        timeout: float = 15.0,
        request_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._transport = transport or self._requests_transport
        self.timeout = timeout
        self._request_id_factory = request_id_factory
        self._health = AdapterHealth(
            provider=self.provider,
            source_tier=self.source_tier,
            source_url=self.source_url,
            status="unknown",
            checked_at=utc_now(),
        )

    @staticmethod
    def _requests_transport(url: str, *, params: Mapping[str, str], headers: Mapping[str, str], timeout: float) -> Any:
        import requests

        return requests.get(url, params=params, headers=headers, timeout=timeout)

    def _decode(self, response: Any) -> tuple[Any, int | None]:
        status = getattr(response, "status_code", None)
        if status is not None and not 200 <= int(status) < 300:
            raise AdapterError("http_error", f"HTTP status {int(status)}", transient=int(status) in {408, 425, 429} or int(status) >= 500, http_status=int(status))
        if self.response_format == "json" or (self.response_format == "auto" and hasattr(response, "json")):
            try:
                return response.json(), int(status) if status is not None else None
            except Exception as err:
                if self.response_format == "json":
                    raise AdapterError("parse_error", "response is not valid JSON", transient=False, http_status=status) from err
        return getattr(response, "text", response), int(status) if status is not None else None

    def _params(self) -> dict[str, str]:
        if not self.required_env:
            return {}
        import os

        value = os.getenv(self.required_env)
        if not value:
            raise AdapterError("missing_credential", f"required environment variable {self.required_env} is not configured", transient=False)
        return {self.credential_param or "api_key": value}

    def fetch(self) -> AdapterObservation:
        started = utc_now()
        request_id = self._request_id_factory() if self._request_id_factory else None
        try:
            response = self._transport(self.endpoint, params=self._params(), headers=self.default_headers, timeout=self.timeout)
            payload, status = self._decode(response)
            observed = AdapterObservation(
                provider=self.provider,
                endpoint=self.endpoint,
                source_tier=self.source_tier,
                fetched_at=utc_now(),
                payload=payload,
                source_url=self.source_url,
                request_id=request_id,
                http_status=status,
                payload_hash=payload_hash(payload),
            )
            self._health = AdapterHealth(
                provider=self.provider,
                source_tier=self.source_tier,
                source_url=self.source_url,
                status="healthy",
                checked_at=observed.fetched_at,
                latency_ms=(observed.fetched_at - started).total_seconds() * 1000,
                consecutive_failures=0,
                last_success_at=observed.fetched_at,
            )
            return observed
        except AdapterError as exc:
            self._record_failure(exc, started)
            raise
        except Exception as exc:
            error = AdapterError("transport_error", type(exc).__name__, transient=True)
            self._record_failure(error, started)
            raise error from exc

    def _record_failure(self, error: AdapterError, started: datetime) -> None:
        self._health = AdapterHealth(
            provider=self.provider,
            source_tier=self.source_tier,
            source_url=self.source_url,
            status="failed",
            checked_at=utc_now(),
            latency_ms=(utc_now() - started).total_seconds() * 1000,
            consecutive_failures=self._health.consecutive_failures + 1,
            last_success_at=self._health.last_success_at,
            error_code=error.code,
            message=error.message,
        )

    def normalize(self, observation: AdapterObservation) -> Any:
        if observation.parse_status != "ok":
            raise AdapterError("parse_error", "observation is not parseable", transient=False)
        return observation.payload

    def health(self) -> AdapterHealth:
        return self._health

    def provenance(self, observation: AdapterObservation | None = None) -> dict[str, Any]:
        item = observation
        return {
            "provider": self.provider,
            "source_tier": self.source_tier,
            "source_url": self.source_url,
            "endpoint": self.endpoint,
            "fetched_at": iso(item.fetched_at) if item else None,
            "published_at": iso(item.published_at) if item else None,
            "request_id": item.request_id if item else None,
            "http_status": item.http_status if item else None,
            "payload_hash": item.payload_hash if item else None,
            "health": self._health.as_dict(),
        }
