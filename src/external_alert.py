"""Validate and publish signed external market alerts without exposing secrets."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunsplit

from src.emergency_alert import CATEGORY_LABELS, build_emergency_brief


ALLOWED_SOURCES = {"jin10", "gdelt"}
EVENT_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
STRICT_HIGH_RISK_CATEGORIES = {"black_swan", "conflict"}


def high_risk_confirmation_ready(category: str) -> bool:
    """Require explicit official and market-sync confirmations for disasters."""
    if category not in STRICT_HIGH_RISK_CATEGORIES:
        return True
    return (
        str(os.environ.get("EXTERNAL_OFFICIAL_CONFIRMED", "")).lower() == "true"
        and str(os.environ.get("EXTERNAL_MARKET_SYNC_CONFIRMED", "")).lower() == "true"
    )


@dataclass(frozen=True)
class ExternalAlert:
    category: str
    summary: str
    source: str
    event_id: str
    occurred_at: str
    evidence: tuple[tuple[str, str, str], ...] = ()

    @property
    def evidence_payload(self) -> list[dict[str, str]]:
        return [
            {"domain": domain, "url": url, "seen_at": seen_at}
            for domain, url, seen_at in self.evidence
        ]

    @property
    def canonical(self) -> str:
        trace = json.dumps(self.evidence_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return "\n".join((self.source, self.event_id, self.category, self.summary, self.occurred_at, trace))

    @property
    def cache_key(self) -> str:
        return hashlib.sha256(self.event_id.encode("utf-8")).hexdigest()

    @property
    def canonical_key(self) -> str:
        urls = "|".join(sorted(_normalize_url(item[1]) for item in self.evidence))
        material = "|".join((self.category, self.summary.casefold(), self.occurred_at[:13], urls))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _normalize_url(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if not host:
        return ""
    path = (parsed.path or "/").rstrip("/") or "/"
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid", "ref"}]
    return urlunsplit((parsed.scheme.lower(), host, path, urlencode(sorted(query)), ""))


def _normalize_evidence(value: str | list[dict[str, str]] | None) -> tuple[tuple[str, str, str], ...]:
    if isinstance(value, str):
        try:
            value = json.loads(value or "[]")
        except json.JSONDecodeError as exc:
            raise ValueError("來源佐證格式必須是 JSON 陣列") from exc
    if value is None:
        value = []
    if not isinstance(value, list) or len(value) > 4:
        raise ValueError("來源佐證最多四筆，且必須是陣列")

    normalized: list[tuple[str, str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("來源佐證內容格式不正確")
        url = str(item.get("url") or "").strip()
        domain = str(item.get("domain") or "").strip().lower().removeprefix("www.")
        seen_at = str(item.get("seen_at") or "").strip()
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if parsed.scheme != "https" or not host or not domain or (host != domain and not host.endswith(f".{domain}")):
            raise ValueError("來源佐證僅接受 HTTPS 且網域必須相符")
        try:
            datetime.fromisoformat(seen_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("來源佐證時間必須是 ISO 8601") from exc
        normalized.append((domain, url, seen_at))
    return tuple(sorted(set(normalized), key=lambda item: (item[0], item[1], item[2])))


def normalize_alert(*, category: str, summary: str, source: str, event_id: str, occurred_at: str, evidence: str | list[dict[str, str]] | None = None) -> ExternalAlert:
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
    normalized_evidence = _normalize_evidence(evidence)
    if normalized_source == "gdelt" and len({domain for domain, _, _ in normalized_evidence}) < 2:
        raise ValueError("GDELT 快訊必須附兩個獨立網域的交叉佐證")
    build_emergency_brief(category, normalized_summary)
    return ExternalAlert(category, normalized_summary, normalized_source, normalized_event_id, normalized_time, normalized_evidence)


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
        "canonical_key": alert.canonical_key,
        "occurred_at": alert.occurred_at,
        "source_url": alert.evidence_payload[0]["url"] if alert.evidence_payload else ("https://www.jin10.com/" if alert.source == "jin10" else ""),
        "verified_domains": [item["domain"] for item in alert.evidence_payload],
        "evidence": alert.evidence_payload,
        "received_at": received_at.isoformat(),
        "first_discovered_at": received_at.isoformat(),
        "last_reminded_at": received_at.isoformat(),
        "escalated": alert.category in {"black_swan", "market"} and high_risk_confirmation_ready(alert.category),
        "high_risk_eligible": high_risk_confirmation_ready(alert.category),
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
    parser.add_argument("--evidence", default="[]", help="signed JSON source evidence")
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
        evidence=args.evidence,
    )
    verify_signature(alert, args.signature, args.shared_secret)
    if args.snapshot:
        stamp_snapshot(alert, Path(args.snapshot))
    print(f"event_key={alert.cache_key}")


if __name__ == "__main__":
    main()
