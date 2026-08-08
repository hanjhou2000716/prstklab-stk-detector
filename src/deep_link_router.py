"""Fail-closed routing for Telegram Mini App alert deep links."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

VIEWS = {"event", "market", "briefing", "research", "resolved", "source-health"}

@dataclass(frozen=True)
class DeepLink:
    alert: str = ""
    release: str = ""
    view: str = "event"

def parse_deep_link(url: str) -> DeepLink:
    query = parse_qs(urlparse(url).query)
    view = (query.get("view", ["event"])[0] or "event").strip()
    if view not in VIEWS:
        view = "event"
    return DeepLink((query.get("alert", [""])[0]), (query.get("release", [""])[0]), view)

def resolve_deep_link(link: DeepLink, *, manifest: dict[str, Any], alerts: list[dict[str, Any]]) -> dict[str, Any]:
    if not link.release or link.release != str(manifest.get("release_id") or ""):
        return {"status": "archived", "message": "該訊息版本已歸檔或不可用", "view": link.view}
    match = next((item for item in alerts if str(item.get("alert_id") or "") == link.alert), None)
    if not match:
        return {"status": "missing", "message": "找不到對應事件", "view": link.view}
    return {"status": "ok", "view": link.view, "alert": match, "release_id": link.release}
