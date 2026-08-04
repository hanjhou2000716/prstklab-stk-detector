"""Generate the dashboard's public market-data JSON file."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
from datetime import datetime, UTC

from src.market_data import build_market_snapshot


def _iso(value: object) -> str:
    return str(value or "").strip()


def _started_at(snapshot: dict) -> str:
    return _iso((snapshot.get("scan") or {}).get("started_at"))


def _existing_is_newer(destination: Path, snapshot: dict) -> bool:
    """Prevent an older, slower run from overwriting a newer snapshot."""
    try:
        current = json.loads(destination.read_text(encoding="utf-8"))
        current_generated = _iso(current.get("generated_at"))
        incoming_started = _started_at(snapshot)
        return bool(current_generated and incoming_started and current_generated >= incoming_started)
    except (OSError, ValueError, TypeError):
        return False


def _prepare_snapshot(snapshot: dict) -> dict:
    payload = dict(snapshot)
    payload.setdefault("snapshot_schema_version", "3.0")
    digest_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["snapshot_id"] = hashlib.sha256(digest_payload.encode("utf-8")).hexdigest()[:16]
    payload["snapshot_published_at"] = datetime.now(UTC).isoformat()
    return payload


def write_snapshot(snapshot: dict, destination: Path | str | None = None) -> bool:
    """Atomically publish a versioned snapshot, refusing stale overwrites."""
    destination = Path(destination or "site/data/market.json")
    if _existing_is_newer(destination, snapshot):
        print("Skip stale snapshot publish: an equal or newer snapshot already exists")
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = _prepare_snapshot(snapshot)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, destination)
    return True


def main() -> None:
    snapshot = build_market_snapshot()
    write_snapshot(snapshot)
    print(
        f"已產生 {len(snapshot['quotes'])} 筆報價；"
        f"資料狀態：{snapshot['data_status']}。"
    )


if __name__ == "__main__":
    main()
