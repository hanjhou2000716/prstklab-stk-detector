"""Production evidence binding for published market observations.

The collector may show a labelled recent close, but the alert path must be
fail-closed.  This module is the single bridge between quote normalization,
quality scoring and raw observation provenance so every published quote has a
stable observation id and an explicit alert decision.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from src.data_quality import score_quote
from src.instrument_master import InstrumentMaster
from src.intel_contract import normalize_quote_record
from src.raw_observation_store import RawObservationStore


def _raw_observation_required() -> bool:
    """Return whether a release requires durable raw observations.

    The default remains optional for backwards compatibility with local and
    legacy jobs. Production workers can opt into the fail-closed contract by
    setting ``RAW_OBSERVATION_REQUIRED=true`` together with a writable root.
    """
    return str(os.getenv("RAW_OBSERVATION_REQUIRED") or "").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _store_from_env() -> RawObservationStore | None:
    root = str(os.getenv("RAW_OBSERVATION_ROOT") or "").strip()
    return RawObservationStore(root) if root else None


def raw_observation_store_summary(
    store: RawObservationStore | None = None,
) -> dict[str, Any]:
    """Expose safe store health metadata without publishing raw payloads."""
    active = store if store is not None else _store_from_env()
    if active is None:
        return {
            "enabled": False,
            "required": _raw_observation_required(),
            "state": "disabled",
            "schema_version": None,
            "observation_count": 0,
            "latest_fetched_at": None,
            "error": None,
        }
    try:
        latest = active.list_recent(limit=1)
        return {
            "enabled": True,
            "required": _raw_observation_required(),
            "state": "recorded",
            "schema_version": 1,
            "observation_count": active.count(),
            "latest_fetched_at": latest[0].fetched_at if latest else None,
            "error": None,
        }
    except (OSError, RuntimeError, ValueError):
        return {
            "enabled": True,
            "required": _raw_observation_required(),
            "state": "unavailable",
            "schema_version": 1,
            "observation_count": 0,
            "latest_fetched_at": None,
            "error": "store_unavailable",
        }


def record_market_snapshot_observation(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Persist one immutable normalized snapshot when configured."""
    import os
    from datetime import UTC, datetime

    root = os.getenv("RAW_OBSERVATION_ROOT", "").strip()
    required = _raw_observation_required()
    if not root:
        return {
            "enabled": False,
            "required": required,
            "recorded": False,
            "state": "unavailable" if required else "disabled",
            "reason": "required_not_configured" if required else "not_configured",
        }
    snapshot_id = str(snapshot.get("snapshot_id") or "")
    if not snapshot_id:
        return {
            "enabled": True,
            "required": required,
            "recorded": False,
            "state": "unavailable",
            "reason": "snapshot_id_missing",
        }
    try:
        observation = RawObservationStore(root).record(
            provider="prstk-pipeline",
            endpoint="market_snapshot",
            fetched_at=str(snapshot.get("generated_at") or datetime.now(UTC).isoformat()),
            request_id=snapshot_id,
            payload=snapshot,
            http_status=200,
            parser_version="market_snapshot-v1",
            parsing_status="normalized",
        )
        return {
            "enabled": True,
            "required": required,
            "recorded": True,
            "state": "recorded",
            "observation_id": observation.observation_id,
        }
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        return {
            "enabled": True,
            "required": required,
            "recorded": False,
            "state": "unavailable",
            "reason": type(exc).__name__,
        }


def bind_quote_evidence(
    quote: dict[str, Any],
    *,
    now: datetime | None = None,
    raw_store: RawObservationStore | None = None,
) -> dict[str, Any]:
    """Return one quote with quality, provenance and alert eligibility bound."""
    item = normalize_quote_record(quote)
    # Identity is resolved at the evidence boundary so every production quote
    # carries the same cross-market semantics.  Unknown symbols are explicit;
    # this must never guess a ticker mapping.
    master = InstrumentMaster()
    try:
        instrument = master.resolve(
            str(item.get("ticker") or item.get("symbol") or ""),
            market=item.get("market"),
        )
    except (KeyError, ValueError):
        item["instrument_resolution"] = "unknown"
    else:
        item["instrument_id"] = instrument.instrument_id
        item["asset_type"] = instrument.asset_type
        item["instrument_timezone"] = instrument.timezone
        item["instrument_resolution"] = "resolved"
    # Bind the exact public symbol registry used for resolution.  Unknown
    # tickers still carry the registry ID but remain explicitly unresolved.
    registry_artifact = master.artifact()
    item["instrument_master_id"] = registry_artifact["registry_id"]
    item["instrument_master_version"] = registry_artifact["schema_version"]
    quality = score_quote(item, now=now)
    item["data_quality_score"] = quality["data_quality_score"]
    item["quality_freshness"] = quality["freshness"]
    item["quality_reasons"] = quality["reasons"]
    item["alert_eligible"] = quality["alert_eligible"]
    item["quality_checked_at"] = (now or datetime.now().astimezone()).isoformat()

    if raw_store is not None:
        provider = str(item.get("source_domain") or item.get("quote_source") or "public-market")
        endpoint = str(item.get("source_url") or provider)
        fetched_at = str(item.get("fetched_at") or item.get("quote_time") or item.get("quote_date") or "")
        if fetched_at:
            observation = raw_store.record(
                provider=provider,
                endpoint=endpoint,
                fetched_at=fetched_at,
                request_id=f"quote-{item.get('ticker') or item.get('symbol') or 'unknown'}-{fetched_at}",
                payload=item,
                http_status=200 if item.get("price") is not None else None,
                parser_version="quote-contract-v1",
                parsing_status="normalized",
            )
            item["observation_id"] = observation.observation_id
            item["raw_payload_location"] = observation.raw_payload_location
    return item


def bind_market_evidence(
    items: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    raw_store: RawObservationStore | None = None,
) -> list[dict[str, Any]]:
    """Bind evidence to a collection while isolating one malformed quote."""
    store = raw_store if raw_store is not None else _store_from_env()
    bound: list[dict[str, Any]] = []
    for item in items:
        try:
            bound.append(bind_quote_evidence(item, now=now, raw_store=store))
        except (TypeError, ValueError, OSError):
            # Keep the card visible, but never make an unscored quote alertable.
            fallback = dict(item)
            fallback["data_quality_score"] = 0.0
            fallback["alert_eligible"] = False
            fallback["quality_freshness"] = "unknown"
            fallback["quality_reasons"] = ["evidence_binding_failed"]
            bound.append(fallback)
    return bound


def quality_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize evidence for source-health and release diagnostics."""
    scores = [float(item["data_quality_score"]) for item in items if item.get("data_quality_score") is not None]
    return {
        "count": len(items),
        "alert_eligible_count": sum(bool(item.get("alert_eligible")) for item in items),
        "stale_count": sum(item.get("quality_freshness") in {"stale", "unavailable", "unknown"} for item in items),
        "cross_checked_count": sum(item.get("cross_checked") is True for item in items),
        "data_quality_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
    }
