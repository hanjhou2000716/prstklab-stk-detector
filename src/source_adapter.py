"""Common adapter contract for public market and event sources.

Adapters keep transport concerns (timeouts, retries, rate limits and an
optional stale cache) separate from provider-specific parsing.  The returned
observation always carries provenance and a health state so callers can fail
closed for alerts while still showing a labelled stale value in the UI.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

TRANSIENT_HTTP_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


class AdapterError(RuntimeError):
    """A normalized provider/transport error with a stable error code."""

    def __init__(self, message: str, *, code: str, retryable: bool = False, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


class ResponseLike(Protocol):
    status_code: int

    def json(self) -> Any: ...


Transport = Callable[..., ResponseLike]
Parser = Callable[[Any], Any]


@dataclass(frozen=True)
class AdapterConfig:
    provider: str
    endpoint: str
    source_tier: str = "public-market"
    timeout_seconds: float = 10.0
    max_retries: int = 2
    min_interval_seconds: float = 0.0
    cache_ttl_seconds: float = 900.0
    max_stale_seconds: float = 7200.0
    parser_version: str = "1"
    user_agent: str = "PRStK-public-readonly/1.0"


@dataclass
class SourceObservation:
    """Normalized result of one provider request."""

    provider: str
    endpoint: str
    request_id: str
    fetched_at: str
    payload: Any = None
    raw_payload: Any = None
    http_status: int | None = None
    latency_ms: float | None = None
    parsing_status: str = "parsed"
    stale_used: bool = False
    source_tier: str = "public-market"
    source_url: str = ""
    parser_version: str = "1"
    observation_id: str | None = None
    raw_payload_location: str | None = None
    error: dict[str, Any] | None = None

    @property
    def payload_hash(self) -> str:
        serialized = json.dumps(
            self.raw_payload if self.raw_payload is not None else self.payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(serialized).hexdigest()

    @property
    def freshness(self) -> str:
        if self.error and self.stale_used:
            return "stale"
        return "unknown" if self.stale_used else "fresh"

    def provenance(self) -> dict[str, Any]:
        quality = self.quality()
        return {
            "provider": self.provider,
            "endpoint": self.endpoint,
            "source_tier": self.source_tier,
            "source_url": self.source_url or self.endpoint,
            "request_id": self.request_id,
            "fetched_at": self.fetched_at,
            "http_status": self.http_status,
            "latency_ms": self.latency_ms,
            "payload_hash": self.payload_hash,
            "parser_version": self.parser_version,
            "observation_id": self.observation_id,
            "raw_payload_location": self.raw_payload_location,
            "parsing_status": self.parsing_status,
            "stale_used": self.stale_used,
            "freshness": self.freshness,
            "data_quality_score": quality["data_quality_score"],
            "quality_freshness": quality["freshness"],
            "quality_reasons": quality["reasons"],
            "display_eligible": quality["display_eligible"],
            "alert_eligible": quality["alert_eligible"],
        }

    def quality(self, *, now: datetime | None = None) -> dict[str, Any]:
        """Score this observation without treating it as cross-checked.

        An adapter can prove availability, parsing and freshness, but it cannot
        claim independent market confirmation by itself.  The shared quality
        scorer therefore keeps ``crosscheck_missing`` and ``alert_eligible``
        false until a caller supplies a second-source reconciliation.
        """
        from src.data_quality import score_source

        status = "failed" if self.error else "healthy"
        result = score_source(
            {
                "provider": self.provider,
                "status": status,
                "fetched_at": self.fetched_at,
                "cross_checked": False,
                "completeness": 100 if self.payload is not None and not self.error else 0,
                "parsing_confidence": 100 if self.parsing_status == "parsed" and not self.error else 0,
                "stale_used": self.stale_used,
                "consecutive_failures": 1 if self.error else 0,
            },
            now=now,
        )
        # ``fetched_at`` records when the fallback was read, not when the
        # provider produced the cached payload.  Never let a freshly fetched
        # stale fallback score as live or become alert eligible.
        if self.stale_used:
            result["freshness"] = "stale"
            result["data_quality_score"] = 0.0
            result["alert_eligible"] = False
            result["display_eligible"] = False
            if "stale_used" not in result["reasons"]:
                result["reasons"].append("stale_used")
        return result


@dataclass
class _CacheEntry:
    observation: SourceObservation
    stored_monotonic: float


@dataclass
class JsonSourceAdapter:
    """Transport and health wrapper for a JSON public endpoint.

    ``transport`` is injectable for tests.  Production callers can leave it
    unset and the adapter uses ``requests.get``.  The adapter never turns a
    stale cache into a fresh observation; callers must explicitly pass
    ``allow_stale=True`` and inspect ``stale_used`` before using it for alerts.
    """

    config: AdapterConfig
    parser: Parser = lambda payload: payload
    transport: Transport | None = None
    raw_store: Any | None = None
    clock: Callable[[], float] = time.monotonic
    _last_request_at: float | None = field(default=None, init=False, repr=False)
    _cache: _CacheEntry | None = field(default=None, init=False, repr=False)
    _last_observation: SourceObservation | None = field(default=None, init=False, repr=False)
    _health: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.config.provider.strip():
            raise ValueError("provider is required")
        if not self.config.endpoint.strip():
            raise ValueError("endpoint is required")
        if self.config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.config.max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        self._health = {
            "provider": self.config.provider,
            "endpoint": self.config.endpoint,
            "status": "warming",
            "last_success_at": None,
            "last_failure_at": None,
            "consecutive_failures": 0,
            "request_count": 0,
            "error_class": None,
            "last_success_observation_id": None,
            "last_success_payload_hash": None,
            "last_success_http_status": None,
        }

    def normalize(self, payload: Any) -> Any:
        """Normalize a provider payload through the configured parser.

        Keeping this as a public operation lets callers validate or replay a
        raw observation without performing another network request.
        """
        try:
            return self.parser(payload)
        except Exception as exc:
            raise AdapterError(str(exc), code="parse_error", retryable=False) from exc

    def _sleep_for_rate_limit(self) -> None:
        if self._last_request_at is None:
            return
        remaining = self.config.min_interval_seconds - (self.clock() - self._last_request_at)
        if remaining > 0:
            time.sleep(remaining)

    def _request(self, *, params: Mapping[str, Any] | None, request_id: str) -> ResponseLike:
        if self.transport is None:
            import requests

            def call(url: str, **kwargs: Any) -> ResponseLike:
                return requests.get(url, **kwargs)
        else:
            call = self.transport
        self._sleep_for_rate_limit()
        self._last_request_at = self.clock()
        headers = {"User-Agent": self.config.user_agent, "Accept": "application/json"}
        try:
            response = call(
                self.config.endpoint,
                params=dict(params or {}),
                headers=headers,
                timeout=self.config.timeout_seconds,
            )
        except Exception as exc:  # pragma: no cover - transport-specific
            raise AdapterError(str(exc), code="network_error", retryable=True) from exc
        status = int(getattr(response, "status_code", 0) or 0)
        if status >= 400:
            retry_after: float | None = None
            if status == 429:
                raw_retry_after = getattr(response, "headers", {}).get("Retry-After")
                try:
                    retry_after = max(0.0, float(raw_retry_after)) if raw_retry_after is not None else None
                except (TypeError, ValueError):
                    retry_after = None
            raise AdapterError(
                f"HTTP {status} from {self.config.provider}",
                code="rate_limited" if status == 429 else "http_error",
                retryable=status in TRANSIENT_HTTP_STATUSES,
                retry_after_seconds=retry_after,
            )
        return response

    def _failed_observation(self, exc: AdapterError, *, request_id: str, started: float) -> SourceObservation | None:
        entry = self._cache
        age = self.clock() - entry.stored_monotonic if entry else None
        if entry and age is not None and age <= self.config.max_stale_seconds:
            cached = entry.observation
            return SourceObservation(
                provider=self.config.provider,
                endpoint=self.config.endpoint,
                request_id=request_id,
                fetched_at=datetime.now(UTC).isoformat(),
                payload=cached.payload,
                raw_payload=cached.raw_payload,
                http_status=cached.http_status,
                latency_ms=round((self.clock() - started) * 1000, 1),
                parsing_status=cached.parsing_status,
                stale_used=True,
                source_tier=self.config.source_tier,
                source_url=self.config.endpoint,
                parser_version=self.config.parser_version,
                error={"code": exc.code, "message": str(exc), "retryable": exc.retryable},
            )
        return None

    def fetch(self, *, params: Mapping[str, Any] | None = None, allow_stale: bool = False) -> SourceObservation:
        request_id = uuid4().hex
        started = self.clock()
        last_error: AdapterError | None = None
        for attempt in range(self.config.max_retries + 1):
            self._health["request_count"] += 1
            try:
                response = self._request(params=params, request_id=request_id)
                raw = response.json()
                raw_record = None
                if self.raw_store is not None:
                    raw_record = self.raw_store.record(
                        provider=self.config.provider,
                        endpoint=self.config.endpoint,
                        fetched_at=datetime.now(UTC).isoformat(),
                        request_id=request_id,
                        payload=raw,
                        http_status=int(response.status_code),
                        parser_version=self.config.parser_version,
                        parsing_status="raw_received",
                    )
                payload = self.normalize(raw)
                observation = SourceObservation(
                    provider=self.config.provider,
                    endpoint=self.config.endpoint,
                    request_id=request_id,
                    fetched_at=datetime.now(UTC).isoformat(),
                    payload=payload,
                    raw_payload=raw,
                    http_status=int(response.status_code),
                    latency_ms=round((self.clock() - started) * 1000, 1),
                    source_tier=self.config.source_tier,
                    source_url=self.config.endpoint,
                    parser_version=self.config.parser_version,
                    observation_id=getattr(raw_record, "observation_id", None),
                    raw_payload_location=getattr(raw_record, "raw_payload_location", None),
                )
                self._cache = _CacheEntry(observation, self.clock())
                self._last_observation = observation
                self._health.update({
                    "status": "healthy",
                    "last_success_at": observation.fetched_at,
                    "last_failure_at": None,
                    "consecutive_failures": 0,
                    "error_class": None,
                    "last_latency_ms": observation.latency_ms,
                    "last_success_observation_id": observation.observation_id,
                    "last_success_payload_hash": observation.payload_hash,
                    "last_success_http_status": observation.http_status,
                })
                return observation
            except AdapterError as exc:
                last_error = exc
                if not exc.retryable or attempt >= self.config.max_retries:
                    break
                delay = last_error.retry_after_seconds
                if delay is None:
                    delay = min(2**attempt, 4)
                # A provider-controlled header must not turn one failed call
                # into an unbounded workflow hang.
                time.sleep(min(max(delay, 0.0), 30.0))
        assert last_error is not None
        failed_at = datetime.now(UTC).isoformat()
        self._health.update({
            "status": "failed",
            "last_failure_at": failed_at,
            "consecutive_failures": int(self._health.get("consecutive_failures") or 0) + 1,
            "error_class": last_error.code,
        })
        if allow_stale:
            stale = self._failed_observation(last_error, request_id=request_id, started=started)
            if stale is not None:
                self._health["status"] = "stale"
                self._last_observation = stale
                return stale
        raise last_error

    def health(self) -> dict[str, Any]:
        """Return a copy suitable for source-health snapshots."""
        health = dict(self._health)
        observation = self._last_observation
        if observation is None:
            health.update({
                "source_tier": self.config.source_tier,
                "source_url": self.config.endpoint,
                "freshness": "unavailable" if health.get("status") == "failed" else "unknown",
                "data_quality_score": 0.0,
                "display_eligible": False,
                "alert_eligible": False,
                "quality_reasons": ["no_observation"],
            })
            return health
        quality = observation.quality()
        # A failed request with an old successful observation is still a
        # runtime failure; it must not inherit the previous observation's
        # freshness or alert eligibility.
        if health.get("status") == "failed":
            quality = {
                **quality,
                "freshness": "unavailable",
                "data_quality_score": 0.0,
                "display_eligible": False,
                "alert_eligible": False,
                "reasons": [*quality.get("reasons", []), "latest_request_failed"],
            }
        health.update({
            "source_tier": observation.source_tier,
            "source_url": observation.source_url or self.config.endpoint,
            "freshness": quality["freshness"],
            "data_quality_score": quality["data_quality_score"],
            "display_eligible": quality["display_eligible"],
            "alert_eligible": quality["alert_eligible"],
            "quality_reasons": quality["reasons"],
            "last_observation_id": observation.observation_id,
            "last_payload_hash": observation.payload_hash,
        })
        return health

    def provenance(self, observation: SourceObservation) -> dict[str, Any]:
        data = observation.provenance()
        data["parser_version"] = self.config.parser_version
        data["cache_ttl_seconds"] = self.config.cache_ttl_seconds
        return data
