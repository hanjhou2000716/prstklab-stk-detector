"""Shared, redacted lookup for the Railway delivery HMAC secret.

Railway deployments may still expose the historical variable name while
GitHub Actions uses the canonical name.  Callers must use this helper instead
of reading either name directly; it never returns a value in health metadata.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

CANONICAL_ENV = "RAILWAY_STATUS_SHARED_SECRET"
LEGACY_ENV = "DELIVERY_STATUS_SHARED_SECRET"


def delivery_shared_secret(environ: Mapping[str, str] | None = None) -> str:
    """Return the configured secret, preferring canonical then legacy name."""
    values = environ if environ is not None else os.environ
    canonical = str(values.get(CANONICAL_ENV, "")).strip()
    if canonical:
        return canonical
    return str(values.get(LEGACY_ENV, "")).strip()


def delivery_secret_health(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Return non-secret configuration metadata for diagnostics."""
    values = environ if environ is not None else os.environ
    canonical = bool(str(values.get(CANONICAL_ENV, "")).strip())
    legacy = bool(str(values.get(LEGACY_ENV, "")).strip())
    active_name = CANONICAL_ENV if canonical else LEGACY_ENV if legacy else None
    return {
        "configured": bool(canonical or legacy),
        "canonical_name_present": canonical,
        "legacy_name_present": legacy,
        "active_name": active_name,
        "migration_required": bool(legacy and not canonical),
    }


__all__ = ["CANONICAL_ENV", "LEGACY_ENV", "delivery_shared_secret", "delivery_secret_health"]
