"""Validate and publish signed external market alerts without exposing secrets."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.emergency_alert import CATEGORY_LABELS, build_emergency_brief


ALLOWED_SOURCES = {"jin10", "gdelt"}
EVENT_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@dataclass(frozen=True)
class ExternalAlert:
    category: str
    summary: str
    source: str
    event_id: str
    occurred_at: str

    @property
    def canonical(self) -> str:
        return "\n".join((self.source, self.event_id, self.category, self.summary, self.occurred_at))

    @property
    def cache_key(self) -> str:
        return hashlib.sha256(self.event_id.encode("utf-8")).hexdigest()


def normalize_alert(*, category: str, summary: str, source: str, event_id: str, occurred_at: str) -> ExternalAlert:
    normalized_summary = " ".join(summary.split())
    normalized_source = source.strip().lower()
    normalized_event_id = event_id.strip()
    normalized_time = occurred_at.strip()
    if normalized_source not in ALLOWED_SOURCES:
        raise ValueError("外部來源不在允許清單內")
    if not EVENT_ID_RE.fullmatch(normalized_event_id):
        raise ValueError("外部事件識別碼格式不正確")
    if category not in CATEGORY_LABELS:
        raise ValueError("外部事件分類不在允許清單內")
    if not normalized_time:
        raise ValueError("外部事件缺少發生時間")
    try:
        datetime.fromisoformat(normalized_time.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("外部事件時間必須為 ISO 8601 格式") from exc
    build_emergency_brief(category, normalized_summary)
    return ExternalAlert(category, normalized_summary, normalized_source, normalized_event_id, normalized_time)


def verify_signature(alert: ExternalAlert, signature: str, shared_secret: str) -> None:
    if not shared_secret:
        raise ValueError("缺少外部快訊共用密鑰")
    provided = signature.removeprefix("sha256=").strip().lower()
    expected = hmac.new(shared_secret.encode("utf-8"), alert.canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(provided, expected):
        raise ValueError("外部快訊簽章驗證失敗")


def stamp_snapshot(alert: ExternalAlert, snapshot_path: Path) -> None:
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("無法讀取市場快照") from exc
    received_at = datetime.now(timezone.utc)
    snapshot["external_alert"] = {
        "category": alert.category,
        "summary": alert.summary,
        "source": alert.source,
        "event_id": alert.event_id,
        "occurred_at": alert.occurred_at,
        "received_at": received_at.isoformat(),
        "expires_at": (received_at + timedelta(hours=6)).isoformat(),
    }
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="驗證外部市場快訊")
    parser.add_argument("--category", required=True, choices=CATEGORY_LABELS)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--occurred-at", required=True)
    parser.add_argument("--signature", required=True)
    parser.add_argument("--shared-secret", required=True)
    parser.add_argument("--snapshot", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    alert = normalize_alert(
        category=args.category,
        summary=args.summary,
        source=args.source,
        event_id=args.event_id,
        occurred_at=args.occurred_at,
    )
    verify_signature(alert, args.signature, args.shared_secret)
    if args.snapshot:
        stamp_snapshot(alert, Path(args.snapshot))
    print(f"event_key={alert.cache_key}")


if __name__ == "__main__":
    main()
