"""Standalone environment/configuration projection for the Railway poll loop."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class PollSettings:
    jin10_token: str
    github_token: str
    repository: str
    shared_secret: str
    interval: int
    limit: int
    cooldown: int
    bootstrap: bool
    gdelt_interval: int
    gdelt_enabled: bool


def _bounded_int(environ: Mapping[str, str], name: str, default: str, low: int, high: int) -> int:
    try:
        value = int(environ.get(name, default))
    except (TypeError, ValueError):
        value = int(default)
    return min(high, max(low, value))


def load_poll_settings(
    *,
    configured: Callable[[str], str],
    environ: Mapping[str, str] | None = None,
    cooldown_seconds: int = 30 * 60,
) -> PollSettings:
    """Read poll-loop settings without importing the Railway application."""
    values = environ or os.environ
    return PollSettings(
        jin10_token=configured("JIN10_MCP_TOKEN"),
        github_token=configured("GITHUB_DISPATCH_TOKEN"),
        repository=configured("GITHUB_REPOSITORY"),
        shared_secret=configured("EXTERNAL_ALERT_SHARED_SECRET"),
        interval=_bounded_int(values, "JIN10_POLL_SECONDS", "120", 60, 24 * 60 * 60),
        limit=_bounded_int(values, "JIN10_FLASH_LIMIT", "30", 1, 100),
        cooldown=max(0, int(cooldown_seconds)),
        bootstrap=values.get("JIN10_INITIAL_BACKFILL", "false").lower() == "true",
        gdelt_interval=_bounded_int(values, "GDELT_POLL_SECONDS", "900", 900, 7 * 24 * 60 * 60),
        gdelt_enabled=values.get("GDELT_DISCOVERY_ENABLED", "true").lower() == "true",
    )


__all__ = ["PollSettings", "load_poll_settings"]
