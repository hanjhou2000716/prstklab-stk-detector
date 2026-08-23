"""Railway runtime configuration boundary.

The monitor is deployed as a standalone service, so this module deliberately
has no dependency on the repository's ``src`` package.  It exposes only
privacy-safe configuration metadata to health endpoints and keeps secret
lookup in one place during the environment-name migration.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any


def delivery_shared_secret(environ: Mapping[str, str] | None = None) -> str:
    """Return the delivery HMAC secret without exposing its value.

    ``RAILWAY_STATUS_SHARED_SECRET`` is the canonical name.  The historical
    ``DELIVERY_STATUS_SHARED_SECRET`` name remains a compatibility fallback
    while Railway is migrated, but it must never win when both are present.
    """

    values = environ if environ is not None else os.environ
    return (
        str(values.get("RAILWAY_STATUS_SHARED_SECRET", "")).strip()
        or str(values.get("DELIVERY_STATUS_SHARED_SECRET", "")).strip()
    )


def configuration_health(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Return a redacted, deterministic runtime configuration health record."""

    values = environ if environ is not None else os.environ
    secret = delivery_shared_secret(values)
    canonical_present = bool(str(values.get("RAILWAY_STATUS_SHARED_SECRET", "")).strip())
    legacy_present = bool(str(values.get("DELIVERY_STATUS_SHARED_SECRET", "")).strip())
    return {
        "status": "healthy" if secret else "configuration_missing",
        "delivery_secret_configured": bool(secret),
        "canonical_name_present": canonical_present,
        "legacy_name_present": legacy_present,
        "active_name": "RAILWAY_STATUS_SHARED_SECRET" if canonical_present else "DELIVERY_STATUS_SHARED_SECRET" if legacy_present else None,
        "migration_required": legacy_present and not canonical_present,
        "secret_values_exposed": False,
    }


__all__ = ["configuration_health", "delivery_shared_secret"]
