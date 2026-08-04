"""Send a signed, non-secret Telegram delivery receipt to Railway.

The callback is optional so GitHub Actions remains usable while the Railway
variable is being configured.  It contains counts and recipient hashes only;
bot tokens and raw chat IDs never leave the runner.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from datetime import datetime, timezone

import requests


def build_payload() -> dict[str, object]:
    hashes = [
        item.strip()
        for item in os.environ.get("FAILED_RECIPIENT_HASHES", "").split(",")
        if item.strip()
    ]
    return {
        "trace_id": os.environ.get("TRACE_ID", "").strip(),
        "release_id": os.environ.get("RELEASE_ID", "").strip(),
        "snapshot_id": os.environ.get("SNAPSHOT_ID", "").strip(),
        "delivery_status": os.environ.get("DELIVERY_STATUS", "unknown").strip(),
        "delivered_count": int(os.environ.get("DELIVERED_COUNT", "0") or 0),
        "failed_count": int(os.environ.get("FAILED_COUNT", "0") or 0),
        "failed_recipient_hashes": hashes,
        "reported_at": datetime.now(timezone.utc).isoformat(),
    }


def send_callback() -> bool:
    url = os.environ.get("RAILWAY_STATUS_URL", "").strip().rstrip("/")
    if not url:
        print("Railway delivery callback skipped: RAILWAY_STATUS_URL is not configured")
        return False
    secret = os.environ.get("RAILWAY_STATUS_SHARED_SECRET", "")
    payload = build_payload()
    if not payload["trace_id"] or not secret:
        raise RuntimeError("TRACE_ID and RAILWAY_STATUS_SHARED_SECRET are required for the callback")
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    response = requests.post(
        url + "/delivery-status",
        data=body,
        headers={"Content-Type": "application/json", "X-PRSTK-Signature": signature},
        timeout=15,
    )
    response.raise_for_status()
    print(f"Railway delivery callback accepted trace_id={payload['trace_id']}")
    return True


if __name__ == "__main__":
    try:
        send_callback()
    except Exception as error:
        print(f"Railway delivery callback failed: {type(error).__name__}", file=sys.stderr)
        raise
