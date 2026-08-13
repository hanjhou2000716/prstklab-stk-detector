"""Private, bounded Creator delivery receipt persistence."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import requests

MAX_RECEIPTS = 2000


def _safe_path(path: Path) -> bool:
    try:
        return not path.resolve().is_relative_to((Path.cwd() / "site").resolve())
    except OSError:
        return False


def load_creator_delivery_history(path: Path | str | None) -> list[dict[str, Any]]:
    """Load only receipt metadata; absent or malformed stores are empty."""
    if not path:
        return []
    target = Path(path).resolve()
    if not _safe_path(target) or not target.is_file():
        return []
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    rows = payload.get("receipts") if isinstance(payload, dict) else payload
    return [dict(row) for row in rows[-MAX_RECEIPTS:] if isinstance(row, dict)] if isinstance(rows, list) else []


def append_creator_delivery_receipts(
    path: Path | str | None,
    receipts: list[dict[str, Any]],
) -> bool:
    """Atomically append privacy-safe receipts to a private path."""
    if not path or not receipts:
        return False
    target = Path(path).resolve()
    if not _safe_path(target):
        return False
    history = load_creator_delivery_history(target)
    history.extend(dict(item) for item in receipts if isinstance(item, dict))
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"schema_version": 1, "receipts": history[-MAX_RECEIPTS:]}, handle, ensure_ascii=False, indent=2)
        temporary.replace(target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return True


def load_remote_creator_delivery_history(
    base_url: str | None,
    shared_secret: str | None,
    *,
    timeout: float = 10,
) -> tuple[list[dict[str, Any]], str]:
    """Read bounded Creator notification keys from Railway.

    A remote outage is explicitly fail-soft: the caller keeps local history
    and records ``unavailable`` rather than treating the outage as proof that
    no episode has previously been delivered.
    """
    url = str(base_url or "").strip().rstrip("/")
    secret = str(shared_secret or "")
    if not url:
        return [], "not_configured"
    if not secret:
        return [], "secret_missing"
    payload = {"receipt_kind": "creator", "limit": 200}
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    try:
        response = requests.post(
            url + "/creator-delivery-history",
            data=body,
            headers={"Content-Type": "application/json", "X-PRSTK-Signature": signature},
            timeout=timeout,
        )
        response.raise_for_status()
        result = response.json()
    except (requests.RequestException, ValueError, TypeError):
        return [], "unavailable"
    keys = result.get("notification_keys") if isinstance(result, dict) else None
    if not isinstance(keys, list):
        return [], "invalid_response"
    return [
        {"notification_key": str(item)[:160], "delivery_status": "delivered", "source": "railway"}
        for item in dict.fromkeys(str(item).strip() for item in keys if str(item).strip())
    ][:MAX_RECEIPTS], "healthy"


__all__ = [
    "append_creator_delivery_receipts",
    "load_creator_delivery_history",
    "load_remote_creator_delivery_history",
]
