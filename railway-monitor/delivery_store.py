"""SQLite delivery outbox and receipt persistence for the Railway monitor.

The monitor keeps its public ``SeenStore`` API for compatibility, while this
module owns the durable outbox/receipt queries.  It has no Telegram or GitHub
transport logic: callers decide when a release is eligible and only persist
the resulting status here.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

try:
    from health_contract import age_seconds, non_negative_int
except ModuleNotFoundError:  # pragma: no cover - direct file loading
    import importlib.util
    from pathlib import Path

    _health_spec = importlib.util.spec_from_file_location(
        "railway_delivery_health_contract",
        Path(__file__).with_name("health_contract.py"),
    )
    if _health_spec is None or _health_spec.loader is None:
        raise ImportError("cannot load railway-monitor/health_contract.py") from None
    _health_module = importlib.util.module_from_spec(_health_spec)
    _health_spec.loader.exec_module(_health_module)
    age_seconds = _health_module.age_seconds
    non_negative_int = _health_module.non_negative_int


def record_outbox(
    connection: sqlite3.Connection,
    *,
    trace_id: str,
    canonical_key: str,
    source: str,
    event_id: str,
    category: str,
    payload: dict[str, Any],
) -> None:
    now = datetime.now(UTC).isoformat()
    connection.execute(
        """INSERT INTO delivery_outbox(trace_id,canonical_key,source,event_id,category,payload_json,status,created_at,updated_at)
           VALUES(?,?,?,?,?,?,'pending',?,?)
           ON CONFLICT(trace_id) DO UPDATE SET category=excluded.category, payload_json=excluded.payload_json, updated_at=excluded.updated_at""",
        (trace_id, canonical_key, source, event_id, category, json.dumps(payload, ensure_ascii=False), now, now),
    )
    connection.commit()


def mark_outbox(
    connection: sqlite3.Connection,
    trace_id: str,
    status: str,
    error: str | None = None,
) -> None:
    if status not in {"pending", "sent", "partial", "failed"}:
        raise ValueError(f"unsupported outbox status: {status}")
    now = datetime.now(UTC)
    retry_at: str | None = None
    if status == "failed":
        row = connection.execute(
            "SELECT attempts FROM delivery_outbox WHERE trace_id = ?", (trace_id,)
        ).fetchone()
        attempts = int(row[0]) if row else 0
        delay_seconds = min(15 * 60, 30 * (2 ** min(attempts, 5)))
        retry_at = (now + timedelta(seconds=delay_seconds)).isoformat()
    connection.execute(
        """UPDATE delivery_outbox
           SET status=?, attempts=attempts+1, last_error=?, next_retry_at=?, updated_at=?
           WHERE trace_id=?""",
        (status, error, retry_at, now.isoformat(), trace_id),
    )
    connection.commit()


def _safe_financialjuice_trace(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Keep the FJ release trace while excluding transport/private identifiers."""
    value = payload.get("financialjuice_delivery_trace")
    if not isinstance(value, dict):
        return None
    allowed = {
        "observation_id_hash", "item_id", "event_cluster_key", "vendor_importance",
        "prstk_risk", "notification_reason", "release_id", "snapshot_id", "delivery_status",
    }
    trace = {key: value[key] for key in allowed if key in value}
    digest = str(trace.get("observation_id_hash") or "")
    if digest and (len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower())):
        raise ValueError("invalid FinancialJuice observation hash")
    if trace and str(trace.get("release_id") or "") != str(payload.get("release_id") or ""):
        raise ValueError("FinancialJuice release trace does not match receipt")
    if trace and str(trace.get("snapshot_id") or "") != str(payload.get("snapshot_id") or ""):
        raise ValueError("FinancialJuice snapshot trace does not match receipt")
    return trace or None


def due_outbox(connection: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    now = datetime.now(UTC).isoformat()
    rows = connection.execute(
        """SELECT trace_id, payload_json, status, attempts, updated_at
           FROM delivery_outbox
           WHERE status IN ('pending', 'failed')
             AND (next_retry_at IS NULL OR next_retry_at <= ?)
           ORDER BY updated_at ASC LIMIT ?""",
        (now, max(1, min(100, int(limit)))),
    ).fetchall()
    due: list[dict[str, Any]] = []
    for trace_id, payload_json, status, attempts, updated_at in rows:
        try:
            payload = json.loads(payload_json)
        except (TypeError, json.JSONDecodeError):
            continue
        dispatch_payload = payload.get("dispatch_payload") if isinstance(payload, dict) else None
        if not isinstance(dispatch_payload, dict):
            continue
        due.append({
            "trace_id": str(trace_id),
            "dispatch_payload": dispatch_payload,
            "status": str(status),
            "attempts": int(attempts),
            "updated_at": str(updated_at),
        })
    return due


def outbox_state(connection: sqlite3.Connection, trace_id: str) -> tuple[str, bool] | None:
    row = connection.execute(
        "SELECT status, payload_json FROM delivery_outbox WHERE trace_id = ?", (trace_id,)
    ).fetchone()
    if row is None:
        return None
    try:
        payload = json.loads(row[1])
    except (TypeError, json.JSONDecodeError):
        payload = None
    has_payload = isinstance(payload, dict) and isinstance(payload.get("dispatch_payload"), dict)
    return str(row[0]), has_payload


def delivery_history(
    connection: sqlite3.Connection,
    *,
    limit: int = 10,
    age_seconds_fn: Callable[..., int | None] = age_seconds,
) -> list[dict[str, Any]]:
    """Return bounded, non-secret delivery history for health checks."""
    rows = connection.execute(
        """SELECT trace_id, source, event_id, category, status, attempts, last_error, updated_at
           FROM delivery_outbox ORDER BY updated_at DESC LIMIT ?""",
        (max(1, min(20, int(limit))),),
    ).fetchall()
    history: list[dict[str, Any]] = []
    for trace_id, source, event_id, category, outbox_status, attempts, last_error, updated_at in rows:
        notification_keys: list[str] = []
        payload_row = connection.execute(
            "SELECT payload_json FROM delivery_outbox WHERE trace_id=?", (trace_id,)
        ).fetchone()
        if payload_row:
            try:
                stored_payload = json.loads(payload_row[0] or "{}")
            except (TypeError, json.JSONDecodeError):
                stored_payload = {}
            if isinstance(stored_payload, dict):
                notification_keys = [
                    str(item)[:160] for item in (stored_payload.get("notification_keys") or [])
                    if isinstance(item, str) and item.strip()
                ][:200]
        receipt = connection.execute(
            """SELECT status, delivered_count, failed_count, reported_at, error, updated_at
               FROM delivery_receipts
               WHERE trace_id=? AND recipient_hash='__aggregate__'
               ORDER BY updated_at DESC LIMIT 1""",
            (trace_id,),
        ).fetchone()
        delivered_count = int(receipt[1]) if receipt and receipt[1] is not None else None
        failed_count = int(receipt[2]) if receipt and receipt[2] is not None else None
        reported_at = str(receipt[3]) if receipt and receipt[3] else None
        receipt_updated_at = str(receipt[5]) if receipt else None
        if receipt and (delivered_count is None or failed_count is None):
            try:
                legacy_counts = json.loads(receipt[4] or "{}")
            except (TypeError, json.JSONDecodeError):
                legacy_counts = {}
            if isinstance(legacy_counts, dict):
                delivered_count = delivered_count if delivered_count is not None else non_negative_int(legacy_counts.get("delivered_count"))
                failed_count = failed_count if failed_count is not None else non_negative_int(legacy_counts.get("failed_count"))
                reported_at = reported_at or (str(legacy_counts.get("reported_at")) if legacy_counts.get("reported_at") else None)
        failed_hash_count = int(connection.execute(
            """SELECT COUNT(*) FROM delivery_receipts
               WHERE trace_id=? AND recipient_hash <> '__aggregate__' AND status='failed'""",
            (trace_id,),
        ).fetchone()[0])
        history.append({
            "trace_id": str(trace_id),
            "source": str(source),
            "event_id": str(event_id),
            "category": str(category) if category else None,
            "outbox_status": str(outbox_status),
            "attempts": int(attempts),
            "last_error": str(last_error) if last_error else None,
            "updated_at": str(updated_at),
            "receipt_status": str(receipt[0]) if receipt else None,
            "delivered_count": delivered_count,
            "failed_count": failed_count,
            "recipient_count": (delivered_count + failed_count) if delivered_count is not None and failed_count is not None else None,
            "reported_at": reported_at,
            "receipt_age_seconds": age_seconds_fn(receipt_updated_at),
            "failed_recipient_hash_count": failed_hash_count,
            "notification_keys": notification_keys,
        })
    return history


def delivery_diagnostics(
    connection: sqlite3.Connection,
    *,
    age_seconds_fn: Callable[..., int | None] = age_seconds,
) -> dict[str, Any]:
    rows = connection.execute("SELECT status, COUNT(*) FROM delivery_outbox GROUP BY status").fetchall()
    counts = {str(status): int(count) for status, count in rows}
    now = datetime.now(UTC).isoformat()
    retryable_count = 0
    due_retry_count = 0
    retry_rows = connection.execute(
        """SELECT payload_json, next_retry_at FROM delivery_outbox
           WHERE status IN ('pending', 'failed')"""
    ).fetchall()
    for payload_json, next_retry_at in retry_rows:
        try:
            stored_payload = json.loads(payload_json)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(stored_payload, dict) or not isinstance(stored_payload.get("dispatch_payload"), dict):
            continue
        retryable_count += 1
        if not next_retry_at or str(next_retry_at) <= now:
            due_retry_count += 1
    latest = connection.execute(
        """SELECT trace_id, status, last_error, updated_at
           FROM delivery_outbox ORDER BY updated_at DESC LIMIT 1"""
    ).fetchone()
    latest_receipt = connection.execute(
        """SELECT trace_id, status, delivered_count, failed_count, reported_at, error, updated_at
           FROM delivery_receipts
           WHERE recipient_hash='__aggregate__' ORDER BY updated_at DESC LIMIT 1"""
    ).fetchone()
    receipt = connection.execute(
        """SELECT trace_id, status, delivered_count, failed_count, reported_at, error, updated_at
           FROM delivery_receipts
           WHERE recipient_hash='__aggregate__' AND trace_id=?
           ORDER BY updated_at DESC LIMIT 1""",
        (latest[0],),
    ).fetchone() if latest else latest_receipt
    delivered_count = int(receipt[2]) if receipt and receipt[2] is not None else None
    failed_count = int(receipt[3]) if receipt and receipt[3] is not None else None
    reported_at = str(receipt[4]) if receipt and receipt[4] else None
    receipt_updated_at = str(receipt[6]) if receipt else None
    if receipt and (delivered_count is None or failed_count is None):
        try:
            legacy_counts = json.loads(receipt[5] or "{}")
        except (TypeError, json.JSONDecodeError):
            legacy_counts = {}
        if isinstance(legacy_counts, dict):
            delivered_count = delivered_count if delivered_count is not None else non_negative_int(legacy_counts.get("delivered_count"))
            failed_count = failed_count if failed_count is not None else non_negative_int(legacy_counts.get("failed_count"))
            reported_at = reported_at or (str(legacy_counts.get("reported_at")) if legacy_counts.get("reported_at") else None)
    recent = delivery_history(connection, limit=10, age_seconds_fn=age_seconds_fn)
    outbox_status = str(latest[1]) if latest else None
    receipt_trace_id = str(receipt[0]) if receipt else None
    receipt_status = str(receipt[1]) if receipt else None
    return {
        "status": receipt_status or outbox_status or "not_checked",
        "last_trace_id": str(latest[0]) if latest else None,
        "last_outbox_status": outbox_status,
        "last_receipt_status": receipt_status,
        "last_receipt_trace_id": receipt_trace_id,
        "receipt_matches_last_outbox": (receipt_trace_id == str(latest[0])) if latest and receipt_trace_id else (False if latest else None),
        "stale_receipt_status": str(latest_receipt[1]) if latest_receipt and receipt_trace_id != str(latest_receipt[0]) else None,
        "counts": counts,
        "retryable_count": retryable_count,
        "due_retry_count": due_retry_count,
        "last_updated_at": receipt_updated_at if receipt else (latest[3] if latest else None),
        "last_error": str(latest[2]) if latest and latest[2] else None,
        "last_delivered_count": delivered_count,
        "last_failed_count": failed_count,
        "last_recipient_count": (delivered_count + failed_count) if delivered_count is not None and failed_count is not None else None,
        "last_reported_at": reported_at,
        "last_receipt_age_seconds": age_seconds_fn(receipt_updated_at),
        "last_failed_recipient_hash_count": int(connection.execute(
            """SELECT COUNT(*) FROM delivery_receipts
               WHERE trace_id=? AND recipient_hash <> '__aggregate__' AND status='failed'""",
            (receipt_trace_id,),
        ).fetchone()[0]) if receipt_trace_id else 0,
        "recent": recent,
    }


def prune_delivery_history(connection: sqlite3.Connection, retention_days: int = 30, limit: int = 500) -> int:
    days = max(30, int(retention_days))
    batch_size = max(1, min(5000, int(limit)))
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    rows = connection.execute(
        """SELECT trace_id FROM delivery_outbox
           WHERE status IN ('sent', 'partial') AND updated_at < ?
           ORDER BY updated_at ASC LIMIT ?""",
        (cutoff, batch_size),
    ).fetchall()
    trace_ids = [str(row[0]) for row in rows]
    if not trace_ids:
        return 0
    placeholders = ",".join("?" for _ in trace_ids)
    connection.execute(f"DELETE FROM delivery_receipts WHERE trace_id IN ({placeholders})", trace_ids)
    connection.execute(f"DELETE FROM delivery_outbox WHERE trace_id IN ({placeholders})", trace_ids)
    connection.commit()
    return len(trace_ids)


def record_delivery_status(connection: sqlite3.Connection, payload: dict[str, Any]) -> bool:
    """Persist an authenticated delivery receipt; reject unknown origins."""
    trace_id = str(payload.get("trace_id") or "").strip()
    receipt_kind = str(payload.get("receipt_kind") or "production").strip()
    status = str(payload.get("delivery_status") or "unknown").strip()
    if receipt_kind not in {"production", "photo_smoke", "creator"}:
        raise ValueError("invalid delivery receipt kind")
    if not trace_id or status not in {"delivered", "partial", "failed"}:
        raise ValueError("invalid delivery receipt")
    failed_hashes = payload.get("failed_recipient_hashes") or []
    if not isinstance(failed_hashes, list) or any(not isinstance(item, str) for item in failed_hashes):
        raise ValueError("invalid failed recipient hashes")
    delivered_count = non_negative_int(payload.get("delivered_count", 0))
    failed_count = non_negative_int(payload.get("failed_count", 0))
    if delivered_count is None or failed_count is None:
        raise ValueError("invalid delivery counts")
    reported_at = str(payload.get("reported_at") or "")[:80] or None
    now = datetime.now(UTC).isoformat()
    exists = connection.execute(
        "SELECT 1 FROM delivery_outbox WHERE trace_id = ?", (trace_id,)
    ).fetchone()
    if exists is None:
        photo_smoke = (
            receipt_kind == "photo_smoke"
            and payload.get("release_id") == "photo-smoke-test"
            and payload.get("snapshot_id") == "photo-smoke-test"
            and payload.get("alert_id") == "photo-smoke-test"
            and payload.get("delivery_mode") == "photo"
        )
        creator_receipt = (
            receipt_kind == "creator"
            and payload.get("receipt_origin") == "github_actions"
            and bool(payload.get("release_id"))
            and bool(payload.get("snapshot_id"))
            and bool(payload.get("alert_id"))
            and payload.get("delivery_mode") in {"photo", "text"}
        )
        production_receipt = (
            receipt_kind == "production"
            and payload.get("receipt_origin") == "github_actions"
            and bool(payload.get("release_id"))
            and bool(payload.get("snapshot_id"))
            and bool(payload.get("alert_id"))
            and payload.get("delivery_mode") in {"text", "photo"}
        )
        if not (photo_smoke or creator_receipt or production_receipt):
            logging.warning("delivery receipt for unknown trace_id=%s", trace_id)
            return False
        smoke_payload = {
            "receipt_kind": receipt_kind,
            "receipt_origin": payload.get("receipt_origin"),
            "release_id": payload.get("release_id"),
            "snapshot_id": payload.get("snapshot_id"),
            "alert_id": payload.get("alert_id"),
            "delivery_mode": payload.get("delivery_mode"),
            "notification_keys": [
                str(item)[:160] for item in (payload.get("notification_keys") or [])
                if isinstance(item, str) and item.strip()
            ][:200],
        }
        financialjuice_trace = _safe_financialjuice_trace(payload)
        if financialjuice_trace is not None:
            smoke_payload["financialjuice_delivery_trace"] = financialjuice_trace
        connection.execute(
            """INSERT INTO delivery_outbox(
                trace_id,canonical_key,source,event_id,category,payload_json,
                status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?, ?, ?)""",
            (
                trace_id,
                f"photo-smoke:{trace_id}" if photo_smoke else f"github-actions:{payload.get('alert_id')}",
                "github_actions",
                payload.get("alert_id") or "photo-smoke-test",
                "photo_smoke" if photo_smoke else "creator_receipt" if creator_receipt else "production_receipt",
                json.dumps(smoke_payload, ensure_ascii=False, sort_keys=True),
                status,
                now,
                now,
            ),
        )
    connection.execute(
        "UPDATE delivery_outbox SET status=?, last_error=?, updated_at=? WHERE trace_id=?",
        (status, None if status == "delivered" else "recipient delivery incomplete", now, trace_id),
    )
    for recipient_hash in failed_hashes:
        connection.execute(
            "INSERT OR REPLACE INTO delivery_receipts(trace_id,recipient_hash,status,error,updated_at) VALUES(?,?,?,?,?)",
            (trace_id, recipient_hash[:128], "failed", "recipient delivery failed", now),
        )
    connection.execute(
        """INSERT OR REPLACE INTO delivery_receipts(
            trace_id,recipient_hash,status,error,delivered_count,failed_count,reported_at,updated_at
        ) VALUES(?,?,?,?,?,?,?,?)""",
        (trace_id, "__aggregate__", status, None, delivered_count, failed_count, reported_at, now),
    )
    connection.commit()
    return True
