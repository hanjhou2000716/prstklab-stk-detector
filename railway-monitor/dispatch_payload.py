"""Canonical signed repository-dispatch payload construction."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable
from typing import Any


def sign(alert: Any, shared_secret: str) -> str:
    digest = hmac.new(
        shared_secret.encode("utf-8"),
        str(alert.canonical).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def build_dispatch_payload(
    alert: Any,
    trace_id: str | None,
    *,
    alert_trace_id: Callable[[Any], str],
    alert_canonical_key: Callable[[Any], str],
    normalize_source_url: Callable[[str], str],
) -> dict[str, Any]:
    """Build the exact durable repository-dispatch body."""
    stable_trace_id = trace_id or alert_trace_id(alert)
    evidence = list(alert.evidence_payload)
    return {
        "event_type": "external-market-alert",
        "client_payload": {
            "source": alert.source,
            "event_id": alert.event_id,
            "category": alert.category,
            "summary": alert.summary,
            "risk_level": alert.risk_level,
            "official_confirmed": alert.official_confirmed,
            "market_sync_confirmed": alert.market_sync_confirmed,
            "market_sync": list(alert.market_sync),
            "occurred_at": alert.occurred_at,
            "evidence": evidence,
            "canonical_key": alert_canonical_key(alert),
            "source_url": normalize_source_url(evidence[0]["url"] if evidence else ""),
            "verified_sources": [normalize_source_url(item["url"]) for item in evidence],
            "event_ledger_retention_days": 30,
            "trace_id": stable_trace_id,
        },
    }


def sign_dispatch_payload(payload: dict[str, Any], alert: Any, shared_secret: str) -> dict[str, Any]:
    """Attach the HMAC after restoring a serialized outbox payload."""
    client_payload = payload.setdefault("client_payload", {})
    client_payload["signature"] = sign(alert, shared_secret)
    return payload
