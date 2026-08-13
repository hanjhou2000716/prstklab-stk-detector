"""Private, bounded Creator delivery receipt persistence."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

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


__all__ = ["append_creator_delivery_receipts", "load_creator_delivery_history"]
