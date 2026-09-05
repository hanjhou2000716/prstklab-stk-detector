"""Reconcile an already-delivered Telegram receipt without sending again.

This module is deliberately a persistence-only path.  It accepts a redacted
receipt exported by the existing workflow/Worker, verifies the release-bound
identifiers and HTTPS report URL, and appends an idempotent delivery row to the
existing EventLedger.  It never claims a notification and never calls the
Telegram client.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from src.event_ledger import EventLedger, event_source_url


def _text(payload: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def _evidence_layers(receipt: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return the redacted receipt and any embedded Worker receipt views.

    Worker and Railway exports have used both a flat shape and a nested
    ``worker_receipt``/``delivery_receipt`` shape.  Reading both keeps this
    persistence-only repair path compatible without accepting arbitrary
    nested payloads or logging their contents.
    """
    layers: list[Mapping[str, Any]] = [receipt]
    for key in ("worker_receipt", "delivery_receipt", "receipt"):
        nested = receipt.get(key)
        if isinstance(nested, Mapping):
            layers.append(nested)
    return layers


def _layered_text(layers: list[Mapping[str, Any]], *keys: str) -> tuple[str, bool]:
    """Read one value and flag conflicting identity evidence."""
    values: list[str] = []
    for layer in layers:
        value = _text(layer, *keys)
        if value and value not in values:
            values.append(value)
    return (values[0] if values else "", len(values) > 1)


def _layered_preferred_text(layers: list[Mapping[str, Any]], *keys: str) -> tuple[str, bool]:
    """Prefer semantic aliases without comparing different timestamp fields."""
    for key in keys:
        values = [str(layer.get(key) or "").strip() for layer in layers]
        values = [value for value in values if value]
        unique = list(dict.fromkeys(values))
        if unique:
            return unique[0], len(unique) > 1
    return "", False


def _timestamp(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC)


def _already_recorded(ledger: EventLedger, trace_id: str) -> bool:
    return any(
        isinstance(row, dict) and str(row.get("trace_id") or "") == trace_id
        for record in ledger.records.values()
        if isinstance(record, dict)
        for row in (record.get("delivery_history") or [])
    )


def _uncertain(reason: str) -> dict[str, Any]:
    # Keep this result intentionally free of message bodies, recipient IDs and
    # transport tokens.  The workflow can publish the reason to its summary.
    return {
        "reconciled": False,
        "delivery_status": "delivery_uncertain",
        "notification_status": "delivery_uncertain",
        "notification_reason": reason,
        "sender_attempts": 0,
    }


def reconcile_delivery(
    receipt: Mapping[str, Any],
    ledger: EventLedger,
    *,
    report_url: str | None = None,
) -> dict[str, Any]:
    """Persist one proven delivery, preserving its original identity/time.

    A receipt is considered sufficient only when it says ``delivered`` (or an
    accepted Worker receipt), has the immutable alert lineage, an HTTPS report
    URL, and the original send timestamp.  Missing or conflicting evidence is
    explicitly marked uncertain and leaves the ledger unchanged.
    """
    if not isinstance(receipt, Mapping):
        return _uncertain("receipt_invalid_shape")

    layers = _evidence_layers(receipt)
    trace_id, trace_conflict = _layered_text(layers, "trace_id", "delivery_trace_id")
    release_id, release_conflict = _layered_text(layers, "release_id")
    snapshot_id, snapshot_conflict = _layered_text(layers, "snapshot_id")
    alert_id, alert_conflict = _layered_text(layers, "alert_id", "notification_id")
    observation_id, observation_conflict = _layered_text(layers, "observation_id")
    if any((trace_conflict, release_conflict, snapshot_conflict, alert_conflict, observation_conflict)):
        return _uncertain("receipt_lineage_conflict")
    sent_at_raw, sent_at_conflict = _layered_preferred_text(
        layers, "sent_at", "delivered_at", "telegram_attempted_at"
    )
    if sent_at_conflict:
        return _uncertain("delivery_time_conflict")
    sent_at = _timestamp(sent_at_raw)
    delivery_status, _ = _layered_preferred_text(layers, "delivery_status", "status")
    delivery_status = delivery_status.casefold()
    worker_status, _ = _layered_preferred_text(
        layers, "worker_receipt_status", "receipt_status", "worker_status"
    )
    if not worker_status:
        # Some Worker exports only expose ``status=accepted`` inside the
        # nested receipt.  A top-level delivery status remains authoritative;
        # this fallback only fills the explicit Worker-receipt lane.
        for layer in layers[1:]:
            worker_status = _text(layer, "status").casefold()
            if worker_status:
                break
    worker_status = worker_status.casefold()
    if not trace_id or not release_id or not snapshot_id or not alert_id or not observation_id:
        return _uncertain("release_lineage_incomplete")
    if sent_at is None:
        return _uncertain("original_delivery_time_missing")
    delivery_proven = delivery_status == "delivered" or worker_status in {"accepted", "delivered"}
    if not delivery_proven or (worker_status and worker_status not in {"accepted", "delivered"}):
        return _uncertain("delivery_not_proven")

    source_url, source_conflict = _layered_text(layers, "source_url", "target_url", "report_url")
    if source_conflict:
        return _uncertain("source_url_conflict")
    source_url = source_url or str(report_url or "").strip()
    parsed = urlsplit(source_url)
    if parsed.scheme != "https" or not parsed.hostname:
        return _uncertain("ledger_source_url_invalid")

    if _already_recorded(ledger, trace_id):
        return {
            "reconciled": True,
            "delivery_status": "already_recorded",
            "notification_status": "accepted",
            "notification_reason": "delivery_already_recorded",
            "trace_id": trace_id,
            "release_id": release_id,
            "snapshot_id": snapshot_id,
            "alert_id": alert_id,
            "sender_attempts": 0,
        }

    body, _ = _layered_text(layers, "public_short_message", "brief_title", "title")
    workflow_run_id, workflow_run_conflict = _layered_text(
        layers, "workflow_run_id", "run_id", "github_run_id"
    )
    if workflow_run_conflict:
        return _uncertain("workflow_run_conflict")
    event: dict[str, Any] = {
        "kind": "market_briefing",
        "source_key": "scheduled_brief",
        "source": "PRStK 多來源市場判讀",
        "notification_id": alert_id,
        "alert_id": alert_id,
        "event_cluster_key": alert_id,
        "release_id": release_id,
        "snapshot_id": snapshot_id,
        "observation_id": observation_id,
        "source_url": source_url,
        "source_domain": parsed.hostname.lower().removeprefix("www."),
        "public_short_message": body,
        "title": body or "市場簡報",
        "brief_title": body or "市場簡報",
        "trace_id": trace_id,
        "workflow_run_id": workflow_run_id,
        "delivery_status": "delivered",
    }
    if event_source_url(event) == "":
        return _uncertain("ledger_source_url_invalid")
    try:
        ledger.record_delivery(event, sent_at=sent_at, trace_id=trace_id, reason="reconcile_delivery")
        ledger.save()
    except (OSError, TimeoutError, ValueError):
        return _uncertain("ledger_persist_failed")
    return {
        "reconciled": True,
        "delivery_status": "reconciled",
        "notification_status": "accepted",
        "notification_reason": "delivery_reconciled_without_resend",
        "trace_id": trace_id,
        "release_id": release_id,
        "snapshot_id": snapshot_id,
        "alert_id": alert_id,
        "sender_attempts": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile an existing delivered Telegram receipt")
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, default=Path("site/data/event-ledger.json"))
    parser.add_argument("--report-url", default="")
    args = parser.parse_args()
    try:
        payload = json.loads(args.receipt.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        result = _uncertain("receipt_unreadable")
    else:
        result = reconcile_delivery(payload, EventLedger(args.ledger), report_url=args.report_url)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("reconciled") else 2


if __name__ == "__main__":
    raise SystemExit(main())
