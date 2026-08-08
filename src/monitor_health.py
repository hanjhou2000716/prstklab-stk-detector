"""Merge non-secret Railway monitor diagnostics into the public Mini App snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REASON_LABELS = {
    "waiting_second_trusted_source": "等待第二來源：尚未有第二個可信新聞網域核對",
    "waiting_shared_entity_action": "等待共同實體／動作：來源尚未指向同一事件",
    "waiting_market_sync_for_warning": "等待市場同步：相關價格或波動尚未確認",
}


def _as_count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _pending_issues(payload: dict[str, Any]) -> list[str]:
    reasons = payload.get("pending_reasons") or {}
    if not isinstance(reasons, dict):
        return []
    issues: list[str] = []
    for reason, count in reasons.items():
        amount = _as_count(count)
        if amount <= 0:
            continue
        label = REASON_LABELS.get(str(reason), f"待核對：{reason}")
        issues.append(f"{label}（{amount} 個候選）")
    pending_count = _as_count(payload.get("pending_count"))
    if pending_count and not issues:
        if str(payload.get("market_sync_status") or "not_confirmed") != "confirmed":
            issues.append(f"{REASON_LABELS['waiting_market_sync_for_warning']}（{pending_count} 個候選）")
        else:
            issues.append(f"{REASON_LABELS['waiting_second_trusted_source']}（{pending_count} 個候選）")
    return issues[:3]


def apply_monitor_health(snapshot: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Return a snapshot with a bounded GDELT health entry.

    Pending evidence is an expected intermediate state, not a provider
    outage. It therefore uses ``status=pending`` and does not inflate the
    top-level missing-source count; the Mini App can still explain why an
    alert has not been promoted.
    """
    if str(payload.get("component") or "").lower() != "gdelt":
        raise ValueError("unsupported monitor health component")
    health = snapshot.setdefault("source_health", {})
    if not isinstance(health, dict):
        raise ValueError("snapshot.source_health must be an object")
    sources = health.setdefault("sources", [])
    if not isinstance(sources, list):
        raise ValueError("snapshot.source_health.sources must be a list")

    status = str(payload.get("status") or "unknown")
    pending_count = _as_count(payload.get("pending_count"))
    error = str(payload.get("error") or "").strip()
    source_status = "partial" if status == "failed" else "pending" if pending_count else "healthy"
    issues = _pending_issues(payload)
    if status == "failed":
        issues = [f"GDELT 掃描失敗：{error or '等待下一輪重試'}"]
    entry: dict[str, Any] = {
        "key": "gdelt_crosscheck",
        "label": "GDELT 事件交叉核對",
        "status": source_status,
        "checked_at": payload.get("checked_at"),
        "source_url": "https://api.gdeltproject.org/api/v2/doc/doc",
        "issues": issues,
        "pending_count": pending_count,
        "pending_reasons": payload.get("pending_reasons") if isinstance(payload.get("pending_reasons"), dict) else {},
        "market_sync_status": payload.get("market_sync_status") or "not_confirmed",
    }
    existing = next((item for item in sources if isinstance(item, dict) and item.get("key") == entry["key"]), None)
    if existing is None:
        sources.append(entry)
    else:
        existing.clear()
        existing.update(entry)

    health["monitor_health"] = {
        "component": "gdelt",
        "checked_at": entry["checked_at"],
        "status": source_status,
        "pending_count": pending_count,
        "pending_reasons": entry["pending_reasons"],
    }
    partial = sum(
        1 for item in sources
        if isinstance(item, dict) and item.get("status") in {"partial", "failed", "missing_api_key", "data_gap"}
    )
    pending = sum(
        _as_count(item.get("pending_count"))
        for item in sources if isinstance(item, dict) and item.get("status") == "pending"
    )
    health["missing_source_count"] = partial
    health["pending_event_count"] = pending
    health["status"] = "partial" if partial else "healthy"
    health["summary"] = (
        f"{partial} 個來源有資料缺口" if partial else "所有資料來源目前可用"
    ) + (f"｜{pending} 個事件待核對" if pending else "")
    return snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge Railway monitor health into market snapshot")
    parser.add_argument("--payload", required=True)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--state", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = json.loads(args.payload)
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    updated = apply_monitor_health(snapshot, payload)
    args.snapshot.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.state:
        state = {
            "component": "gdelt",
            "checked_at": payload.get("checked_at"),
            "status": payload.get("status"),
            "pending_count": payload.get("pending_count", 0),
            "pending_reasons": payload.get("pending_reasons") if isinstance(payload.get("pending_reasons"), dict) else {},
            "market_sync_status": payload.get("market_sync_status") or "not_confirmed",
        }
        args.state.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
