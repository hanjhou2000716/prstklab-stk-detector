"""Send a signed, non-secret Telegram delivery receipt to the configured backend.

The Cloudflare Worker/Supabase endpoint is preferred; Railway remains an
optional rollback. The callback is optional so GitHub Actions remains usable
while the backend is being configured. It contains counts and recipient
hashes only; bot tokens and raw chat IDs never leave the runner.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from datetime import UTC, datetime

import requests

from src.railway_secret import delivery_shared_secret


def _callback_target() -> tuple[str, str] | None:
    """Return the preferred zero-cost endpoint and its backend label.

    Railway remains a rollback target for existing deployments.  When the
    Cloudflare Worker URL is configured it is always preferred, so a Railway
    outage cannot prevent the durable receipt path from being attempted.
    """
    worker_url = os.environ.get("RECEIPT_CALLBACK_URL", "").strip().rstrip("/")
    if worker_url:
        return worker_url, "cloudflare_worker"
    railway_url = os.environ.get("RAILWAY_STATUS_URL", "").strip().rstrip("/")
    if railway_url:
        return railway_url + "/delivery-status", "railway"
    return None


def _callback_secret() -> str:
    return os.environ.get("DELIVERY_RECEIPT_SHARED_SECRET", "").strip() or delivery_shared_secret()


def _financialjuice_trace() -> dict[str, object] | None:
    """Return only the release-bound FJ trace fields safe for Railway storage."""
    raw = os.environ.get("FINANCIALJUICE_TRACE", "").strip()
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as err:
        raise ValueError("invalid FinancialJuice delivery trace") from err
    if not isinstance(value, dict):
        raise ValueError("invalid FinancialJuice delivery trace")
    allowed = {
        "observation_id_hash", "item_id", "event_cluster_key", "vendor_importance",
        "prstk_risk", "notification_reason", "release_id", "snapshot_id", "delivery_status",
    }
    trace = {key: value[key] for key in allowed if key in value}
    digest = str(trace.get("observation_id_hash") or "")
    if digest and (len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower())):
        raise ValueError("invalid FinancialJuice observation hash")
    for field in ("release_id", "snapshot_id", "delivery_status"):
        if field in trace and not str(trace[field]).strip():
            raise ValueError(f"invalid FinancialJuice {field}")
    if not trace:
        raise ValueError("empty FinancialJuice delivery trace")
    return trace


def build_payload() -> dict[str, object]:
    hashes = [
        item.strip()
        for item in os.environ.get("FAILED_RECIPIENT_HASHES", "").split(",")
        if item.strip()
    ]
    notification_keys = list(dict.fromkeys(
        item.strip()
        for item in os.environ.get("NOTIFICATION_KEYS", "").split(",")
        if item.strip()
    ))[:200]
    payload: dict[str, object] = {
        "receipt_origin": "github_actions",
        "trace_id": os.environ.get("TRACE_ID", "").strip(),
        "receipt_kind": os.environ.get("DELIVERY_RECEIPT_KIND", "production").strip() or "production",
        "release_id": os.environ.get("RELEASE_ID", "").strip(),
        "snapshot_id": os.environ.get("SNAPSHOT_ID", "").strip(),
        "alert_id": os.environ.get("ALERT_ID", "").strip() or None,
        "delivery_mode": os.environ.get("DELIVERY_MODE", "text").strip(),
        "delivery_status": os.environ.get("DELIVERY_STATUS", "unknown").strip(),
        "delivered_count": int(os.environ.get("DELIVERED_COUNT", "0") or 0),
        "failed_count": int(os.environ.get("FAILED_COUNT", "0") or 0),
        "failed_recipient_hashes": hashes,
        "notification_keys": notification_keys,
        "renderer_error_type": os.environ.get("RENDERER_ERROR_TYPE", "").strip() or None,
        "reported_at": datetime.now(UTC).isoformat(),
    }
    trace = _financialjuice_trace()
    if trace is not None:
        # A delivery callback is the final durable link in the FJ chain.  The
        # trace is allow-listed and contains only hashed observation identity;
        # raw Gmail/message identifiers never cross the runner boundary.
        if str(trace.get("release_id") or "") not in {"", str(payload["release_id"])}:
            raise ValueError("FinancialJuice release_id does not match receipt")
        if str(trace.get("snapshot_id") or "") not in {"", str(payload["snapshot_id"])}:
            raise ValueError("FinancialJuice snapshot_id does not match receipt")
        trace["release_id"] = payload["release_id"]
        trace["snapshot_id"] = payload["snapshot_id"]
        trace["delivery_status"] = payload["delivery_status"]
        payload["financialjuice_delivery_trace"] = trace
    return payload


def send_callback() -> bool:
    target = _callback_target()
    if not target:
        print("Delivery receipt callback skipped: no receipt endpoint is configured")
        return False
    url, backend = target
    secret = _callback_secret()
    payload = build_payload()
    if not payload["trace_id"] or not secret:
        raise RuntimeError("TRACE_ID and delivery receipt secret are required for the callback")
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    response = requests.post(
        url,
        data=body,
        headers={"Content-Type": "application/json", "X-PRSTK-Signature": signature},
        timeout=15,
    )
    response.raise_for_status()
    print(f"{backend} delivery callback accepted trace_id={payload['trace_id']}")
    return True


if __name__ == "__main__":
    try:
        send_callback()
    except Exception as error:
        print(f"Railway delivery callback failed: {type(error).__name__}", file=sys.stderr)
        raise
