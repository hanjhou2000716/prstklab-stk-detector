"""Typed runtime settings contract with secret-safe validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class RuntimeSettings:
    environment: str
    dashboard_url: str
    storage_backend: str
    freshness_minutes: int = 30
    request_timeout_seconds: int = 20
    retry_limit: int = 2


def load_runtime_settings(env: Mapping[str, str]) -> RuntimeSettings:
    url = str(env.get("DASHBOARD_URL") or "")
    if not url.startswith("https://"):
        raise ValueError("DASHBOARD_URL must use https")
    freshness = int(env.get("FRESHNESS_MINUTES", "30"))
    timeout = int(env.get("REQUEST_TIMEOUT_SECONDS", "20"))
    retry = int(env.get("RETRY_LIMIT", "2"))
    if min(freshness, timeout, retry) < 0:
        raise ValueError("runtime limits must be non-negative")
    return RuntimeSettings(str(env.get("ENVIRONMENT", "production")), url, str(env.get("STORAGE_BACKEND", "railway")), freshness, timeout, retry)
