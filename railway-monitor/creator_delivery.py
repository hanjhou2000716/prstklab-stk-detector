"""Creator notification receipt projection for the Railway health API."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def notification_keys(history: Iterable[dict[str, Any]], limit: int = 200) -> list[str]:
    """Return bounded, non-secret creator notification keys from receipts."""
    bounded = max(1, min(200, int(limit)))
    return list(dict.fromkeys(
        str(item)[:160]
        for row in history
        if row.get("category") == "creator_receipt"
        for item in (row.get("notification_keys") or [])
        if isinstance(item, str) and item.strip()
    ))[:bounded]
