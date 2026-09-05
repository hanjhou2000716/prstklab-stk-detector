"""Generate the dashboard's public market-data JSON file."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from src.atomic_file import replace_with_retry
from src.market_data import build_market_snapshot
from src.production_evidence import record_market_snapshot_observation


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
    _attach_observation_provenance(payload)
    payload["snapshot_published_at"] = datetime.now(UTC).isoformat()
    # Keep the public artifact linked to the immutable normalized observation
    # when the append-only store is configured. Only safe metadata is exposed.
    payload["raw_observation"] = record_market_snapshot_observation(payload)
    return payload


def _observation_id(snapshot_id: str, item: dict, *, kind: str, ordinal: int) -> str:
    """Create a stable ID for one quote/event within a published snapshot."""
    identity = {
        "kind": kind,
        "ordinal": ordinal,
        "ticker": item.get("ticker"),
        "name": item.get("name"),
        "price": item.get("price"),
        "change": item.get("change"),
        "change_percent": item.get("change_percent"),
        "quote_time": item.get("quote_time"),
        "quote_date": item.get("quote_date"),
        "source_url": item.get("source_url") or item.get("url"),
        "fetched_at": item.get("fetched_at"),
    }
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{snapshot_id}:{encoded}".encode()).hexdigest()[:16]


def _attach_observation_provenance(payload: dict) -> None:
    """Bind every published quote and event to the exact snapshot observed."""
    snapshot_id = str(payload["snapshot_id"])
    collections = ("quotes", "indices", "macro_quotes")
    for collection in collections:
        for ordinal, item in enumerate(payload.get(collection) or []):
            if not isinstance(item, dict):
                continue
            item["snapshot_id"] = snapshot_id
            item["observation_id"] = _observation_id(snapshot_id, item, kind=collection, ordinal=ordinal)

    for event_collection in ("events", "official_events"):
        event_block = payload.get(event_collection) or {}
        for ordinal, event in enumerate(event_block.get("items") or []):
            if not isinstance(event, dict):
                continue
            instrument = event.get("instrument") if isinstance(event.get("instrument"), dict) else None
            source_item = instrument or event
            if not event.get("source_url") and not event.get("url") and instrument:
                promoted_url = instrument.get("source_url") or instrument.get("url")
                if promoted_url:
                    event["source_url"] = promoted_url
            observation_id = str(source_item.get("observation_id") or "").strip()
            if not observation_id:
                observation_id = _observation_id(snapshot_id, source_item, kind=f"event:{event_collection}", ordinal=ordinal)
            event["snapshot_id"] = snapshot_id
            event["observation_id"] = observation_id
            if instrument is not None:
                instrument["snapshot_id"] = snapshot_id
                instrument["observation_id"] = observation_id
            trace = dict(event.get("source_trace") or {})
            trace["snapshot_id"] = snapshot_id
            trace["observation_id"] = observation_id
            event["source_trace"] = trace


def write_snapshot(snapshot: dict, destination: Path | str | None = None) -> bool:
    """Atomically publish a versioned snapshot, refusing stale overwrites."""
    destination = Path(destination or "site/data/market.json")
    if _existing_is_newer(destination, snapshot):
        print("Skip stale snapshot publish: an equal or newer snapshot already exists")
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = _prepare_snapshot(snapshot)
    snapshot.clear()
    snapshot.update(payload)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    replace_with_retry(temporary, destination)
    return True


def merge_published_metadata(
    metadata: dict[str, object], destination: Path | str | None = None,
    *, expected_snapshot_id: str,
) -> bool:
    """Atomically merge post-publish correlation metadata.

    Some fields (for example a Telegram trace ID) are only known after
    ``write_snapshot`` has assigned the immutable snapshot/observation IDs.
    This guarded merge refuses to touch a newer writer's snapshot.
    """
    destination = Path(destination or "site/data/market.json")
    try:
        current = json.loads(destination.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    if not isinstance(current, dict) or str(current.get("snapshot_id") or "") != str(expected_snapshot_id):
        return False
    briefing = dict(current.get("briefing") or {})
    briefing.update({key: value for key, value in metadata.items() if value is not None})
    current["briefing"] = briefing
    temporary = destination.with_name(f".{destination.name}.meta.tmp")
    try:
        temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        replace_with_retry(temporary, destination)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False
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
